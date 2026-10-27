"""
Python port of the work half of the WireStartHole form (src\\UFuncs\\WireStartHole.cs), from the C# statics in
src\\Static\\WireStartHole.cs: WireStartHoleExecute (split into prepare + one place per pick),
WireStartSelectedHoleDiameter and ImportWireStart.

WIRED (2026-10-21), never run in NX.

Not ported: WireStartTryPickScreenPosition and WireStartPreviewCircleMotionCallback. They are the pick itself
(UF_UI_specify_screen_position with a motion callback drawing the preview circle), and Python cannot host a UF
motion callback, so the pick loop stays C#. Static.WireStartHoleExecute calls
    PythonLibrary.Execute("WireStartHole.py", "WireStartHole", "prepare");
once before its do/while, then for each picked position
    PythonLibrary.Execute("WireStartHole.py", "WireStartHole", "place",
        dynamicBlock, is125, is250, subtract, screenPosition.X, screenPosition.Y, screenPosition.Z);
in place of the loop body after the pick, with no catch of its own: a failure ends the picks and is printed by
BtnSelect_Click, as the C# was. The preview radius/matrix setup and WireStartSelectedHoleDiameter (which sizes the
preview) stay C# with the pick; selected_hole_diameter is not called. The replaced C# (the old loop body,
ImportWireStart and the part paths) sits commented out in src\Static\WireStartHole.cs.

Differences from the C#:
- The subtract goes through tsg_nx.subtract (boolean builder with a tool-body collector); the C# __Subtract
  feeds the obsolete BooleanBuilder.Tools. Both build the boolean in the work part.
- The arc's start point (the extrude direction's origin) is evaluated with Eval.EvaluateUnitVectors, as
  tsg_nx.curve_mid_point does, since the Python UFEval has no Evaluate.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.Features  # noqa: E402
import NXOpen.Layer  # noqa: E402
import NXOpen.Preferences  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402

_WireStartPath125 = "G:\\0Library\\CtsComponents\\-125_START_HOLE.prt"
_WireStartPath250 = "G:\\0Library\\CtsComponents\\-250_START_HOLE.prt"
_WireStartPath375 = "G:\\0Library\\CtsComponents\\-375_START_HOLE.prt"

# Layer the hole's circle is moved to (and which prepare() makes selectable).
_StartHoleLayer = 94


def _selected_hole_diameter(is_125: bool, is_250: bool) -> float:
    """Static.WireStartSelectedHoleDiameter - the start hole's nominal diameter: .125, .250 or .375."""
    if is_125:
        return .125

    return .250 if is_250 else .375


def _import_wire_start(path: str, location: NXOpen.Point3d) -> None:
    """Static.ImportWireStart - imports the start-hole part into the work part at the WCS orientation."""
    work = nx.work_part()
    importer1 = work.ImportManager.CreatePartImporter()
    try:
        part_importer1 = cast(NXOpen.PartImporter, importer1)
        part_importer1.FileName = path
        part_importer1.Scale = 1.0
        part_importer1.CreateNamedGroup = False
        part_importer1.ImportViews = False
        part_importer1.ImportCamObjects = False
        part_importer1.LayerOption = NXOpen.PartImporter.LayerOptionType.Original
        part_importer1.DestinationCoordinateSystemSpecification = \
            NXOpen.PartImporter.DestinationCoordinateSystemSpecificationType.Work
        element1 = work.WCS.CoordinateSystem.Orientation.Element
        nx_matrix1 = work.NXMatrices.Create(element1)
        part_importer1.DestinationCoordinateSystem = nx_matrix1
        part_importer1.DestinationPoint = location
        part_importer1.Commit()
    finally:
        importer1.Destroy()


def _create_circle0(part: NXOpen.BasePart, origin: NXOpen.Point3d, radius: float) -> NXOpen.Arc:
    """BasePart.__CreateCircle0 - a non-associative full circle about origin, in the WCS XY plane."""
    if part.Tag != nx.work_part().Tag:
        # BasePart.__AssertIsWorkPart (compares tags; two Python wrappers of one part need not compare equal)
        raise ValueError("Part {} is not the work part".format(part.Leaf))

    builder = part.BaseFeatures.CreateAssociativeArcBuilder(None)
    try:
        builder.CenterPoint.Value = part.Points.CreatePoint(origin)
        builder.EndPointOptions = NXOpen.Features.AssociativeArcBuilder.EndOption.Radius
        builder.Limits.FullCircle = True
        builder.Type = NXOpen.Features.AssociativeArcBuilder.Types.ArcFromCenter
        # C# writes $"{radius}"; str() gives the same digits for these radii.
        builder.Radius.SetFormula("{}".format(radius))
        builder.Associative = False
        builder.Commit()
        return cast(NXOpen.Arc, builder.GetCommittedObjects()[0])
    finally:
        builder.Destroy()


def _curve_start_point(curve: NXOpen.Curve) -> NXOpen.Point3d:
    """Curve.__StartPoint - the point at the start of the parameter range (__MinU/__Position)."""
    evaluator = nx.ufsession_.Eval.Initialize2(curve.Tag)
    limits = nx.ufsession_.Eval.AskLimits(evaluator)
    point = nx.ufsession_.Eval.EvaluateUnitVectors(evaluator, limits[0])[0]
    return NXOpen.Point3d(point[0], point[1], point[2])


def _create_extrude(part: NXOpen.BasePart, curves: List[NXOpen.Curve], direction: NXOpen.Vector3d,
                    start: float, end: float) -> NXOpen.Features.Extrude:
    """BasePart.__CreateExtrude(Curve[], Vector3d, double, double)."""
    if part.Tag != nx.work_part().Tag:
        # BasePart.__AssertIsWorkPart (compares tags; two Python wrappers of one part need not compare equal)
        raise ValueError("Part {} is not the work part".format(part.Leaf))

    builder = part.Features.CreateExtrudeBuilder(None)
    try:
        rules = [part.ScRuleFactory.CreateRuleCurveDumb(curves)]
        # The C# calls the no-argument CreateSection() overload; the stubs only declare the tolerance overload,
        # and the Python binding's overload resolution for it is not confirmed.
        builder.Section = nx.display_part().Sections.CreateSection()  # type: ignore[call-arg]
        builder.Section.AddToSection(rules, None, None, None, NXOpen.Point3d(0.0, 0.0, 0.0),
                                     NXOpen.Section.Mode.Create, False)
        builder.Limits.StartExtend.Value.Value = start
        builder.Limits.EndExtend.Value.Value = end
        builder.Direction = part.Directions.CreateDirection(_curve_start_point(curves[0]), direction,
                                                            NXOpen.SmartObject.UpdateOption.WithinModeling)
        return cast(NXOpen.Features.Extrude, builder.Commit())
    finally:
        builder.Destroy()


class WireStartHole(object):

    @staticmethod
    def prepare() -> None:
        """
        The setup at the top of Static.WireStartHoleExecute, before its pick loop: undo mark, free placement on
        the display part's work plane, and layer 94 selectable in the work part.
        """
        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Add Wire Start")
        # Free placement: no grid points on screen and no snapping the pick to them.
        work_plane1 = nx.display_part().Preferences.Workplane
        work_plane1.ShowGrid = False
        work_plane1.SnapToGrid = False
        # Obsolete in the C# (warning 618 suppressed); same property here.
        nx.session_.Preferences.WorkPlane.ObjectOffWorkPlane = \
            NXOpen.Preferences.SessionWorkPlane.ObjectDisplay.Normal
        # set layer 94 to selectable
        nx.work_part().Layers.SetState(_StartHoleLayer, NXOpen.Layer.State.Selectable)

    @staticmethod
    def place(dynamic_block: NXOpen.Features.Block, is_125: bool, is_250: bool, subtract: bool,
              x: float, y: float, z: float) -> None:
        """
        One iteration of Static.WireStartHoleExecute's pick loop, after the pick: import the start-hole part
        at (x, y, z), or (subtract) extrude a circle +-10 along the WCS Z, name its cylinder face HOLECHART and
        subtract it from the dynamic block's body.
        """
        screen_position = NXOpen.Point3d(x, y, z)
        radius = 0.0

        if is_125:
            if subtract:
                radius = 0.06250000045
            else:
                _import_wire_start(_WireStartPath125, screen_position)
        elif is_250:
            if subtract:
                radius = 0.12500000045
            else:
                _import_wire_start(_WireStartPath250, screen_position)
        elif subtract:
            radius = 0.18750000045
        else:
            _import_wire_start(_WireStartPath375, screen_position)

        if not subtract:
            return

        work = nx.work_part()
        arc = _create_circle0(work, screen_position, radius)
        curves: List[NXOpen.Curve] = [arc]
        axis_z = nx.axis_z(nx.display_part().WCS.CoordinateSystem.Orientation.Element)
        direction = axis_z
        start = 10.0
        end = -10.0
        extrude = _create_extrude(work, curves, direction, start, end)

        # todo: need to color extrude and set extrude to layer 94
        # extrude.._SetDisplayColor(211);

        arc.Layer = _StartHoleLayer
        arc.RedisplayObject()

        cylinders = [face for face in extrude.GetFaces() if face.SolidFaceType == NXOpen.Face.FaceType.Cylindrical]
        if len(cylinders) > 1:
            # SingleOrDefault
            raise ValueError("Sequence contains more than one matching element")
        cylinder_face: Optional[NXOpen.Face] = cylinders[0] if cylinders else None

        if cylinder_face is None:
            nx.print_("Was unable to find a cylinder face.")
            return

        cylinder_face.SetName("HOLECHART")

        nx.subtract(dynamic_block.GetBodies()[0], extrude.GetBodies())

    @staticmethod
    def selected_hole_diameter(is_125: bool, is_250: bool) -> float:
        """Static.WireStartSelectedHoleDiameter."""
        return _selected_hole_diameter(is_125, is_250)
