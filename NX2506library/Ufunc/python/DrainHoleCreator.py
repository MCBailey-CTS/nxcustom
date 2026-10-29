"""
drain-hole-creator (_UFunc.ufunc_drain_hole_creator) - Python port of the DrainHoleCreator WinForms form
(src\\UFuncs\\DrainHoleCreator.cs + .Designer.cs) and its statics (src\\Static\\DrainHoleCreator.cs), finished from
the design its dead code describes. No C# class: the menu button runs this file.

WRITTEN 2026-10-23, never run in NX.

What the C# actually did: nothing. The form had no [UFunc] attribute and no _Runner case; its only constructors
all chain to DrainHoleCreator(object settings), which throws NotImplementedException, so the form never opened.
Its Drain Holes button raised a MainButtonClicked event nobody subscribed to (the presenter that did -
DrainHolePresenter.RunDrainHoleOperation - was [Obsolete], fully commented out and throwing, and was deleted). It
was already dead when it came over from NXJournals (git b5adc6c): SelectSingleFaceWithResult,
CreateExtrusionCurves, CreateExtrusionCore, CornersOnly and OffsetCurves all threw there too. The live statics
(MidPointsOnly, CreateCircle, CreateSubtraction, AddToFeatureGroup, MinBy) were never called.

What this does - the RunDrainHoleOperation loop the commented-out code describes, with the settings of the
commented-out GetSettings (b5adc6c's DrainHoleSettings defaults):
  1. The dialog: diameter (2.0 in / 50.0 mm when the units change, as the radio buttons did), its units, Subtract
     Holes, the Corners / Mid-Points placement (OK greyed out with neither, as ValidateDrainHoles greyed the
     button), and the extrusion start / end limits in inches (the form's "Extrusion Limits (IN)"; .25 and -2.0).
  2. OK closes it and starts the pick loop (the form hid itself the same way): pick a planar face of the work
     part near where the hole goes. Each pick gets a visible undo mark "Drain Hole {n}" and:
       - the pick position is the cursor ray through the face's plane (Compute.ClosestPoints(CursorRay, face));
       - among the face's linear edges, the nearest corner (an end point) and the nearest edge midpoint; with
         both placements on, whichever is nearer the pick wins (CreateExtrusionCurves);
       - Mid-Points: a circle tangent to that edge, on the pick's side of it (MidPointsOnly);
         Corners: a circle tangent to both edges meeting at that corner (CornersOnly - the commented-out offset /
         intersect, done here as the bisector point at radius / sin(half angle));
       - the circle's radius is the diameter / 2, in part units, less .001 (CreateCircle);
       - the circle is extruded along the face's outward normal from the start limit to the end limit
         (CreateExtrusionCore), and with Subtract Holes the extrusion is subtracted from the face's body
         (CreateSubtraction);
       - clean-up (CleanUp + GetSettings): the circle is named DRAIN_HOLE_CURVE, layer 8, color 10; the extrude
         DRAIN_HOLE_EXTRUSION, its bodies layer 1; the subtract DRAIN_HOLE_SUBTRACTION, its bodies layer 1. (Feature
         Navigator still knows those two feature names.)
     A failed pick is printed and the loop goes on. Back reopens the dialog with the values last used (the form
     came back after the loop); Cancel, or OK with nothing picked, ends the UFunc.

Dead and not ported: the feature group (DRAIN_HOLE_FEATURE_GROUP - AddToFeatureGroup's calls were commented out
even in the loop), the settings XML path the parameterless constructor passed (U:\\nxFiles\\UfuncFiles\\
DrainHoleSettings.xml, never read), the Tab-key handler, and the Units/Settings interfaces.

Differences from what the dead C# would have done:
- MidPointsOnly moved the display part's WCS to the edge midpoint to offset the center in WCS Y; the same point is
  computed here without touching the WCS.
- The extrude direction is the face's outward normal (the face sense applied, like __OutwardNormal), so the start
  limit is outside the material and the end limit (negative) inside it. Face.__NormalVector, which the C# used,
  drops the sense; a reversed face would have put the hole above the face.
- The limits are inches whatever the diameter units (the form's group said IN) and are converted for a metric part.
- Only faces in the work part can be picked (the commented-out Snap pick was AnyInAssembly, but the circle,
  extrude and boolean are all built in the work part).
- One failed hole no longer ends the loop.
"""

from __future__ import annotations

import math
import os
import sys
from typing import Any, List, Optional, Tuple, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# From the source tree (src\UFuncs) the shared modules are in src\python; deployed, they are beside this file.
_shared_python = os.path.join(os.path.dirname(_here), "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.BlockStyler  # noqa: E402
import NXOpen.Features  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
import WireStartHole as wirestart  # noqa: E402
from tsg_dialog import Dialog, title_with_version  # noqa: E402

# _UFunc.ufunc_drain_hole_creator
ufunc_name = "drain-hole-creator"

# NX will not build a Block Styler dialog from inside some callbacks (a menu or toolbar launch, it seems).
_ErrorCannotLaunchDialog = 3520048

# UF_UI_SEL_FEATURE_PLANAR_FACE (as Boss.py uses it).
_UF_UI_SEL_FEATURE_PLANAR_FACE = 21

_MillimetersPerInch = 25.4

# The commented-out GetSettings.
_CurveName = "DRAIN_HOLE_CURVE"
_CurveLayer = 8
_CurveColor = 10
_ExtrusionName = "DRAIN_HOLE_EXTRUSION"
_ExtrusionLayer = 1
_SubtractionName = "DRAIN_HOLE_SUBTRACTION"
_SubtractionLayer = 1

# The diameter each units radio button put in the box (RdoMetric/RdoEnglish_CheckedChanged).
_Metric = "Metric"
_English = "English"
_DefaultDiameter = {_Metric: 50.0, _English: 2.0}

# Distinct-point tolerance (EqualityPos / __IsEqualTo).
_Tolerance = .001


class Settings(object):
    """DrainHoleSettings: what the dialog edits. The defaults are the commented-out GetSettings."""

    def __init__(self) -> None:
        self.diameter = 2.0
        self.units = _English
        self.subtract = True
        self.corners = True
        self.midpoints = True
        self.start_limit = .25
        self.end_limit = -2.0


# ---------------------------------------------------------------------------------------------------
# Vector helpers
# ---------------------------------------------------------------------------------------------------

def _sub(p: NXOpen.Point3d, q: NXOpen.Point3d) -> NXOpen.Vector3d:
    return NXOpen.Vector3d(p.X - q.X, p.Y - q.Y, p.Z - q.Z)


def _dot(u: NXOpen.Vector3d, v: NXOpen.Vector3d) -> float:
    return u.X * v.X + u.Y * v.Y + u.Z * v.Z


def _cross(u: NXOpen.Vector3d, v: NXOpen.Vector3d) -> NXOpen.Vector3d:
    return NXOpen.Vector3d(u.Y * v.Z - u.Z * v.Y, u.Z * v.X - u.X * v.Z, u.X * v.Y - u.Y * v.X)


def _length(v: NXOpen.Vector3d) -> float:
    return math.sqrt(_dot(v, v))


def _move(p: NXOpen.Point3d, v: NXOpen.Vector3d, s: float = 1.0) -> NXOpen.Point3d:
    return NXOpen.Point3d(p.X + v.X * s, p.Y + v.Y * s, p.Z + v.Z * s)


def _same(p: NXOpen.Point3d, q: NXOpen.Point3d) -> bool:
    return nx.distance(p, q) < _Tolerance


def _z_matrix(axis_z: NXOpen.Vector3d) -> NXOpen.Matrix3x3:
    """Vector3d.__ToMatrix3x3(axisZ) - an orientation with that Z axis (as __CreateCircle(center, axisZ, r) uses)."""
    u = NXOpen.Vector3d(0.0, 1.0, 0.0) if not abs(axis_z.X) < abs(axis_z.Y) else NXOpen.Vector3d(1.0, 0.0, 0.0)
    z = nx.unit(axis_z)
    x = nx.unit(_cross(u, z))
    y = nx.unit(_cross(z, x))
    return nx.matrix_from_axes(x, y)


# ---------------------------------------------------------------------------------------------------
# The geometry: CreateExtrusionCurves / MidPointsOnly / CornersOnly / CreateCircle
# ---------------------------------------------------------------------------------------------------

def _outward_plane(face: NXOpen.Face) -> Tuple[NXOpen.Point3d, NXOpen.Vector3d]:
    """A point on a planar face and its outward unit normal (Face.__OutwardNormal)."""
    face_type, point, direction, _box, _radius, _rad_data, norm_dir = \
        nx.ufsession_.Modeling.AskFaceData(face.Tag)
    if face_type != nx.UF_MODL_PLANAR_FACE:
        raise RuntimeError("Cannot ask for the normal of a non planar face")
    normal = nx.unit(NXOpen.Vector3d(direction[0], direction[1], direction[2]))
    if norm_dir < 0:
        normal = nx.negate(normal)
    return NXOpen.Point3d(point[0], point[1], point[2]), normal


def _pick_position(cursor: NXOpen.Point3d, plane_point: NXOpen.Point3d,
                   normal: NXOpen.Vector3d) -> NXOpen.Point3d:
    """Compute.ClosestPoints(CursorRay, face).Point1 - the cursor ray (along the work view's Z) through the face's
    plane; the cursor dropped square onto the plane when the view looks along the face."""
    m = nx.display_part().ModelingViews.WorkView.Matrix
    view_z = NXOpen.Vector3d(m.Zx, m.Zy, m.Zz)
    across = _dot(view_z, normal)
    if abs(across) < 1e-9:
        return _move(cursor, normal, _dot(_sub(plane_point, cursor), normal))
    return _move(cursor, view_z, _dot(_sub(plane_point, cursor), normal) / across)


def _to_part_units(part: NXOpen.Part, length: float, inches: bool) -> float:
    """A length given in inches (or millimeters) in the part's units - CreateCircle's three-way branch."""
    part_inches = part.PartUnits == NXOpen.BasePart.Units.Inches
    if part_inches == inches:
        return length
    return length / _MillimetersPerInch if part_inches else length * _MillimetersPerInch


def _midpoint_center(edge: NXOpen.Edge, pick: NXOpen.Point3d, mid: NXOpen.Point3d,
                     radius: float) -> NXOpen.Point3d:
    """MidPointsOnly: the edge midpoint moved radius square to the edge, toward the pick (the C# set the WCS X along
    the edge and Y toward the pick, then added (0, d/2, 0) in WCS)."""
    start, end = edge.GetVertices()
    x_axis = nx.unit(_sub(start, end))
    toward = _sub(pick, mid)
    along = _dot(toward, x_axis)
    y_axis = NXOpen.Vector3d(toward.X - x_axis.X * along, toward.Y - x_axis.Y * along, toward.Z - x_axis.Z * along)
    if _length(y_axis) < 1e-9:
        raise RuntimeError("The pick is on the edge itself - pick inside the face, beside the edge.")
    return _move(mid, nx.unit(y_axis), radius)


def _corner_center(linear_edges: List[NXOpen.Edge], corner: NXOpen.Point3d, pick: NXOpen.Point3d,
                   radius: float) -> NXOpen.Point3d:
    """CornersOnly: the point radius from both edges meeting at the corner (their offsets' intersection)."""
    away: List[NXOpen.Vector3d] = []
    for edge in linear_edges:
        start, end = edge.GetVertices()
        if _same(start, corner):
            away.append(nx.unit(_sub(end, corner)))
        elif _same(end, corner):
            away.append(nx.unit(_sub(start, corner)))

    if len(away) != 2:
        raise RuntimeError("Expecting closest corner to be attached to exactly 2 edges. It was actually attached "
                           "to {} edge(s).".format(len(away)))

    angle = math.acos(max(-1.0, min(1.0, _dot(away[0], away[1]))))
    half_sin = math.sin(angle / 2)
    bisector = NXOpen.Vector3d(away[0].X + away[1].X, away[0].Y + away[1].Y, away[0].Z + away[1].Z)
    if half_sin < 1e-6 or _length(bisector) < 1e-9:
        raise RuntimeError("The resulting offset did not have an intersection.")
    bisector = nx.unit(bisector)
    # The face side of the corner: the pick's side of the bisector.
    if _dot(_sub(pick, corner), bisector) < 0:
        bisector = nx.negate(bisector)
    return _move(corner, bisector, radius / half_sin)


def _create_circle(part: NXOpen.Part, center: NXOpen.Point3d, normal: NXOpen.Vector3d,
                   radius: float) -> NXOpen.Arc:
    """CreateCircle -> BasePart.__CreateCircle(center, axisZ, radius): a full circle (CreateArc 0..2pi)."""
    matrix = part.NXMatrices.Create(_z_matrix(normal))
    curves: Any = part.Curves
    return cast(NXOpen.Arc, curves.CreateArc(center, matrix, radius, 0.0, 2 * math.pi))


def _drain_hole(face: NXOpen.Face, cursor: NXOpen.Point3d, settings: Settings) -> None:
    """One pick of RunDrainHoleOperation's loop: the circle, the extrude, the subtract and the clean-up."""
    part = nx.work_part()
    plane_point, normal = _outward_plane(face)
    pick = _pick_position(cursor, plane_point, normal)

    linear_edges = [e for e in face.GetEdges() if e.SolidEdgeType == NXOpen.Edge.EdgeType.Linear]
    if not linear_edges:
        raise RuntimeError("The selected face has no linear edges.")

    corners: List[NXOpen.Point3d] = []
    for edge in linear_edges:
        for point in edge.GetVertices():
            if not any(_same(point, c) for c in corners):
                corners.append(point)
    # MinBy(..., Distance2)
    nearest_corner = min(corners, key=lambda p: nx.distance(pick, p))
    mids = [(edge, nx.mid_point(*edge.GetVertices())) for edge in linear_edges]
    nearest_edge, nearest_mid = min(mids, key=lambda em: nx.distance(pick, em[1]))

    radius = _to_part_units(part, settings.diameter / 2, settings.units == _English)
    use_corner = settings.corners and (not settings.midpoints
                                       or nx.distance(pick, nearest_corner) < nx.distance(pick, nearest_mid))
    if use_corner:
        center = _corner_center(linear_edges, nearest_corner, pick, radius)
    else:
        center = _midpoint_center(nearest_edge, pick, nearest_mid, radius)

    circle = _create_circle(part, center, normal, radius - .001)

    start = _to_part_units(part, settings.start_limit, True)
    end = _to_part_units(part, settings.end_limit, True)
    curves: List[NXOpen.Curve] = [circle]
    extrude = wirestart._create_extrude(part, curves, normal, start, end)

    subtraction: Optional[NXOpen.Features.BooleanFeature] = None
    if settings.subtract:
        subtraction = nx.subtract(face.GetBody(), extrude.GetBodies())

    # CleanUp
    circle.SetName(_CurveName)
    circle.Layer = _CurveLayer
    nx.set_color(circle, _CurveColor)
    extrude.SetName(_ExtrusionName)
    for body in extrude.GetBodies():
        body.Layer = _ExtrusionLayer
        body.RedisplayObject()
    if subtraction is None:
        return
    for body in subtraction.GetBodies():
        body.Layer = _SubtractionLayer
        body.RedisplayObject()
    subtraction.SetName(_SubtractionName)


# ---------------------------------------------------------------------------------------------------
# The pick loop (RunDrainHoleOperation)
# ---------------------------------------------------------------------------------------------------

def _planar_face_mask() -> NXOpen.Selection.MaskTriple:
    return NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type,
                                       NXOpen.UF.UFConstants.UF_solid_face_subtype,
                                       _UF_UI_SEL_FEATURE_PLANAR_FACE)


def _pick_holes(settings: Settings) -> bool:
    """Picks faces until Back (True: show the dialog again) or Cancel / OK with nothing picked (False)."""
    counter = 1
    while True:
        result: Any = NXOpen.UI.GetUI().SelectionManager.SelectTaggedObject(
            "Select a face near the corner or edge for the drain hole (Back: settings)",
            "Drain Holes",
            NXOpen.Selection.SelectionScope.WorkPart,
            NXOpen.Selection.SelectionAction.ClearAndEnableSpecific,
            False,
            False,
            [_planar_face_mask()])
        response, obj, cursor = result[0], result[1], result[2]

        if response == NXOpen.Selection.Response.Back:
            return True
        if response == NXOpen.Selection.Response.Cancel:
            # Cancel is how the loop ends; only a run that made no hole counts as cancelled.
            if counter == 1:
                nx.mark_cancelled("the face pick")
            return False
        if not isinstance(obj, NXOpen.Face):
            # Middle click / OK with nothing picked.
            return False

        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Drain Hole {}".format(counter))
        counter += 1
        try:
            _drain_hole(obj, cursor, settings)
        except Exception as ex:
            nx.print_exception(ex)


# ---------------------------------------------------------------------------------------------------
# The dialog
# ---------------------------------------------------------------------------------------------------

class _DrainHoleDialog(Dialog):
    dlx_name = "DrainHoleCreator.dlx"

    def __init__(self, title: str, settings: Settings) -> None:
        self.title = title
        super().__init__()
        # Updated in ok(): the blocks are gone once Launch returns.
        self.settings = settings

    def shown(self) -> None:
        s = self.settings
        self.block("units").ValueAsString = s.units
        self.block("diameter").Value = s.diameter
        self.block("subtract").Value = s.subtract
        self.block("corners").Value = s.corners
        self.block("midpoints").Value = s.midpoints
        self.block("start_limit").Value = s.start_limit
        self.block("end_limit").Value = s.end_limit

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        if block == self.block("units"):
            # RdoMetric/RdoEnglish_CheckedChanged: each put its own default diameter in the box.
            units = str(self.block("units").ValueAsString)
            self.block("diameter").Value = _DefaultDiameter.get(units, 2.0)

    def enable_ok(self) -> bool:
        # ValidateDrainHoles (the numbers always parse in a double block).
        return bool(self.block("corners").Value or self.block("midpoints").Value)

    def ok(self) -> bool:
        if float(self.block("diameter").Value) <= 0:
            self.message("The diameter must be more than 0.", error=True)
            return False
        s = self.settings
        s.units = str(self.block("units").ValueAsString)
        s.diameter = float(self.block("diameter").Value)
        s.subtract = bool(self.block("subtract").Value)
        s.corners = bool(self.block("corners").Value)
        s.midpoints = bool(self.block("midpoints").Value)
        s.start_limit = float(self.block("start_limit").Value)
        s.end_limit = float(self.block("end_limit").Value)
        return True


def execute() -> None:
    title = title_with_version("Drain Holes")
    settings = Settings()
    while True:
        try:
            accepted = _DrainHoleDialog(title, settings).run()
        except NXOpen.NXException as ex:
            if ex.ErrorCode != _ErrorCannotLaunchDialog:
                raise
            nx.print_exception(ex)
            nx.show_error("NX would not open the {} dialog (error {} - it will not create a dialog from inside a "
                          "callback).\n\nTry running it from File -> Execute -> NX Open rather than from a menu or "
                          "toolbar button.".format(title, _ErrorCannotLaunchDialog))
            return

        if not accepted or not _pick_holes(settings):
            return


def main() -> None:
    """The drain-hole-creator UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
