"""
The profile-subtract UFunc: a standalone Python UFunc (no C# class); its menu button runs this file's main().

Three dialogs (tools\\make-dlx.py, 2026-10-29), all anywhere in the assembly:
  - ProfileSubtractTargets.dlx: the target solid bodies only. Each is blanked as soon as it is picked (so the tool
    faces behind it can be picked next), one taken out of the pick is unblanked, and every one still blanked is
    unblanked when the run ends - cancelled, finished or failed;
  - one target picked: ProfileSubtractTools.dlx - the offset and many planar tool faces;
  - many targets picked: ProfileSubtractTool.dlx - the offset and a single planar tool face.
OK stays greyed out until something is picked.

The offset's units follow the job (tsg_dialog.detect_customer, 2026-10-29): a GM job - or one it cannot tell -
asks for Offset (mm), 20 by default; a TSG job for Offset (in), .5 by default. Either is converted to the target
part's own units.

Each target is built in turn (build, its own undo mark); two picked occurrences of the same part are built once,
since the subtract goes into the shared part. Then, per target and tool face (each in its own try/except, printed,
so one bad face does not drop the rest):
  - the face is wave-linked into the target body's owning part as a single face with its holes removed, from the
    assembly, with the target's component as the work component (Boss._extract_face_without_holes);
  - with the target's part displayed and made the work part, a curve is copied off every edge of the linked face, so
    the curves are in the part's own coordinates (Boss found that taking them from the assembly offsets them by the
    component's position a second time);
  - the linked face is deleted; the edge curves stay in the target's part;
  - the curves are offset outward by the offset (an Offset Curve feature, the edge curves kept; a negative offset
    goes inward, 0 skips it). Which side the builder offsets to follows the loop's direction, so the result is
    measured and redone reversed if its box came out smaller;
  - each 45-degree corner of the offset profile (a line at 45 degrees to the lines either side of it - a chamfer) is
    turned into a 25 mm radius (CornerRadiusMm, 2026-10-29): the two side lines are trimmed back to the arc's
    tangent points and the arc replaces the chamfer. The offset's curves are feature output and cannot be edited, so
    the trimmed lines and the arcs are new dumb curves and the curves they replace are blanked. A chamfer whose side
    lines are too short for the radius is left as it is (noted in the syslog);
  - the offset curves are extruded 10" both ways along the linked face's normal (Boss._snap_extrude) and the
    extrude is subtracted from the target body. The offset, radius and extrude lengths are converted to the target
    part's units.
The starting display and work parts are restored in a finally. The curves, offset and extrude stay as features
behind the subtract, so the profile can be edited.

Two ways in:
  - File -> Execute -> NX Open on this file runs main().
  - build(target, tool_faces, offset, offset_in_mm) with the picked occurrences.
"""

from __future__ import annotations

import math
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, cast

# Session.Execute does not put the script's folder on sys.path, so the shared modules would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# From the source tree (src\UFuncs) the shared modules are in src\python; deployed, they are beside this file.
_shared_python = os.path.join(os.path.dirname(_here), "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.BlockStyler  # noqa: E402
import NXOpen.Features  # noqa: E402
import NXOpen.GeometricUtilities  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
from Boss import (_extract_face_without_holes, _normal_vector, _planar_face_mask, _snap_delete,  # noqa: E402
                    _snap_extrude)
from tsg_dialog import CustomerTsg, Dialog, detect_customer, title_with_version  # noqa: E402

ufunc_name = "profile-subtract"

# UF_UI_SEL_FEATURE_SOLID_BODY - not in every UFConstants build, so the number Perfect.py uses too.
_SolidBodyDetail = 36

# How far the profile is extruded each way along the tool face's normal.
ExtrudeInches = 10.0

# The radius a 45-degree corner (chamfer) of the offset profile becomes.
CornerRadiusMm = 25.0
# How far off 45 degrees a chamfer's angle to each side line may be.
_ChamferAngleTolerance = 2.0


class ProfileSubtract(object):

    @staticmethod
    def execute() -> None:
        """
        The targets dialog, then the tools dialog for one target (many faces) or for many targets (one face), then
        build per target. The targets, blanked once picked, are unblanked at the end - cancelled, finished or failed.
        """
        title = title_with_version("Profile Subtract")
        targets_dialog = _TargetsDialog(title)
        try:
            if not targets_dialog.run() or not targets_dialog.targets:
                return
            targets = targets_dialog.targets
            # One target: many tool faces. Many targets: one tool face.
            tools_dialog = _ToolsDialog(title, many_faces=len(targets) == 1)
            if not tools_dialog.run() or not tools_dialog.tool_faces:
                return

            built: Set[int] = set()
            for target in targets:
                # Two occurrences of one part share its body: subtract into it once.
                owner = cast(NXOpen.Body, target.Prototype) if target.IsOccurrence else target
                if owner.Tag in built:
                    nx.warn("Profile Subtract: {} is already done through another occurrence - skipped.".format(
                        cast(NXOpen.Part, owner.OwningPart).Leaf))
                    continue
                built.add(owner.Tag)
                try:
                    build(target, tools_dialog.tool_faces, tools_dialog.offset, tools_dialog.offset_in_mm)
                except Exception as ex:
                    nx.print_exception(ex)
        finally:
            targets_dialog.unblank_targets()


def build(target: NXOpen.Body, tool_faces: Sequence[NXOpen.Face], offset: float, offset_in_mm: bool = False) -> int:
    """
    Per tool face: links it into the target's owning part without its holes, copies the linked face's edges to curves
    there, deletes the link, offsets the curves outward by offset (millimetres with offset_in_mm, else inches),
    extrudes them ExtrudeInches up and down the face's normal and subtracts that from the target body. Returns how
    many faces were subtracted.
    """
    starting_display = nx.display_part()
    starting_work = nx.work_part()
    target_component = target.OwningComponent if target.IsOccurrence else None
    owner = cast(NXOpen.Body, target.Prototype) if target.IsOccurrence else target
    target_part = cast(NXOpen.Part, owner.OwningPart)
    # The builders take the target part's units.
    per_inch = 25.4 if target_part.PartUnits == NXOpen.BasePart.Units.Millimeters else 1.0
    part_offset = offset * per_inch / 25.4 if offset_in_mm else offset * per_inch
    subtracted = 0
    nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Profile Subtract")

    try:
        for face in tool_faces:
            try:
                curves, normal = _profile_curves(face, starting_display, target_component, target_part)
                profile = _offset_outward(curves, part_offset)
                profile = _round_chamfers(profile, CornerRadiusMm * per_inch / 25.4)
                extrude = _snap_extrude(profile, normal, ExtrudeInches * per_inch, start=-ExtrudeInches * per_inch)
                nx.create_boolean(owner, list(extrude.GetBodies()), NXOpen.Features.Feature.BooleanType.Subtract)
                subtracted += 1
            except Exception as ex:
                nx.print_exception(ex)
    finally:
        nx.set_display_part(starting_display)
        nx.set_work_part(starting_work)

    nx.print_("Profile Subtract: subtracted {} of {} tool face(s) from {}.".format(
        subtracted, len(tool_faces), target_part.Leaf))
    return subtracted


def _profile_curves(face: NXOpen.Face, assembly: NXOpen.Part,
                    target_component: Optional[NXOpen.Assemblies.Component],
                    target_part: NXOpen.Part) -> Tuple[List[NXOpen.Curve], NXOpen.Vector3d]:
    """
    One tool face: linked into target_part without holes, its edges copied to curves there, the link deleted. Returns
    the curves and the linked face's normal. Leaves target_part displayed and the work part.
    """
    # The face is an occurrence picked in the assembly, so the link is made from there.
    nx.set_display_part(assembly)
    if target_component is None:
        nx.set_work_part(assembly)
    else:
        nx.set_work_component(target_component)
    linked = _extract_face_without_holes(face)

    # In the target's part, in its own coordinates.
    nx.set_display_part(target_part)
    nx.set_work_part(target_part)
    try:
        faces = list(linked.GetFaces())
        if len(faces) == 0:
            raise RuntimeError("The linked tool face has no face")
        normal = _normal_vector(faces[0])
        curves = [nx.edge_to_curve(edge) for edge in linked.GetEdges()]
    finally:
        _snap_delete([linked])

    return curves, normal


def _offset_outward(curves: Sequence[NXOpen.Curve], distance: float) -> List[NXOpen.Curve]:
    """
    An Offset Curve (Distance) feature of curves, distance in part units, in the work part, on the outside of the
    loop: a negative distance goes inside. The builder's side depends on the loop's direction, so the result is
    measured - an outward offset of a closed loop has the bigger box - and redone reversed when it went the wrong way.
    The input curves are kept. A zero distance returns curves as they are.
    """
    if abs(distance) < 1e-9:
        return list(curves)

    original = _box_size(curves)
    for reverse in (False, True):
        feature = _offset_curve(curves, abs(distance), reverse)
        offset = [c for c in feature.GetEntities() if isinstance(c, NXOpen.Curve)]
        if offset and (_box_size(offset) > original) == (distance > 0):
            return offset
        _snap_delete([feature])
    raise RuntimeError("Could not offset the profile curves {} {}".format(
        "out" if distance > 0 else "in", nx.cs_double_str(abs(distance))))


def _offset_curve(curves: Sequence[NXOpen.Curve], distance: float, reverse: bool) -> NXOpen.Features.Feature:
    """Part.__CreateOffsetCurve(curves, distance, reverseDirection) - Distance type, input retained, tangents
    extended at the corners."""
    part = nx.work_part()
    modeling: Any = cast(Any, part.Preferences).Modeling
    distance_tolerance = modeling.DistanceToleranceData
    angle_tolerance = modeling.AngleToleranceData

    builder: Any = cast(Any, part.Features).CreateOffsetCurveBuilder(None)
    try:
        features: Any = NXOpen.Features
        geometric: Any = NXOpen.GeometricUtilities
        builder.Type = features.OffsetCurveBuilder.Types.Distance
        builder.InputCurvesOptions.InputCurveOption = geometric.CurveOptions.InputCurve.Retain
        builder.CurveFitData.Tolerance = distance_tolerance
        builder.TrimMethod = features.OffsetCurveBuilder.TrimOption.ExtendTangents
        section = builder.CurvesToOffset
        section.DistanceTolerance = distance_tolerance
        section.AngleTolerance = angle_tolerance
        section.ChainingTolerance = 0.95 * distance_tolerance
        section.SetAllowedEntityTypes(NXOpen.Section.AllowTypes.OnlyCurves)
        section.AllowSelfIntersection(True)
        for curve in curves:
            section.AddToSection([part.ScRuleFactory.CreateRuleCurveDumb([curve])], curve, None, None,
                                 NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Section.Mode.Create, False)
        builder.OffsetDistance.RightHandSide = nx.cs_double_str(distance)
        builder.ReverseDirection = reverse
        return cast(NXOpen.Features.Feature, builder.CommitFeature())
    finally:
        builder.Destroy()


def _round_chamfers(curves: Sequence[NXOpen.Curve], radius: float) -> List[NXOpen.Curve]:
    """
    curves with every 45-degree corner turned into a radius (part units): a line whose two ends each meet another
    line at 45 degrees (+- _ChamferAngleTolerance) is replaced by an arc tangent to those two lines, which are
    trimmed back to its tangent points. Replaced curves are blanked, not deleted (offset curves are feature output);
    the result is the untouched curves plus new dumb lines and arcs in the work part.
    """
    tolerance = max(nx.distance_tolerance() * 10, 1e-6)
    lines = [cast(NXOpen.Line, c) for c in curves if isinstance(c, NXOpen.Line)]

    def touching(line: NXOpen.Line, point: NXOpen.Point3d) -> Optional[NXOpen.Line]:
        for other in lines:
            if other.Tag != line.Tag and (_distance(other.StartPoint, point) < tolerance
                                          or _distance(other.EndPoint, point) < tolerance):
                return other
        return None

    # Each line's ends as they will be: a trimmed side line's end moves to its tangent point.
    ends: Dict[int, List[NXOpen.Point3d]] = {line.Tag: [line.StartPoint, line.EndPoint] for line in lines}
    chamfers: List[NXOpen.Line] = []
    sides: Set[int] = set()
    arcs:List[Tuple[NXOpen.Point3d, NXOpen.Point3d, NXOpen.Point3d]] = []

    for chamfer in lines:
        a = touching(chamfer, chamfer.StartPoint)
        b = touching(chamfer, chamfer.EndPoint)
        # A line is a chamfer or a side, never both (an octagon's lines are all at 45 degrees to each other).
        if a is None or b is None or a.Tag == b.Tag or chamfer.Tag in sides \
                or any(c.Tag in (a.Tag, b.Tag) for c in chamfers):
            continue
        direction = _unit(_sub(chamfer.EndPoint, chamfer.StartPoint))
        if not all(abs(_line_angle(direction, side) - 45.0) <= _ChamferAngleTolerance for side in (a, b)):
            continue
        fillet = _fillet(a, b, chamfer, radius, tolerance)
        if fillet is None:
            nx.warn("Profile Subtract: a 45-degree corner's side lines are too short for a {} radius - left as "
                    "it is.".format(nx.cs_double_str(radius)))
            continue
        for side, near, tangent in ((a, chamfer.StartPoint, fillet[0]), (b, chamfer.EndPoint, fillet[2])):
            side_ends = ends[side.Tag]
            index = 0 if _distance(side_ends[0], near) < _distance(side_ends[1], near) else 1
            side_ends[index] = tangent
        chamfers.append(chamfer)
        sides.update((a.Tag, b.Tag))
        arcs.append(fillet)

    if not chamfers:
        return list(curves)

    part = nx.work_part()
    replaced = {c.Tag for c in chamfers}
    result: List[NXOpen.Curve] = []
    for curve in curves:
        if curve.Tag in replaced:
            curve.Blank()
            continue
        if isinstance(curve, NXOpen.Line):
            start, end = ends[curve.Tag]
            if _distance(start, curve.StartPoint) > 1e-9 or _distance(end, curve.EndPoint) > 1e-9:
                curve.Blank()
                result.append(cast(NXOpen.Curve, part.Curves.CreateLine(start, end)))
                continue
        result.append(curve)
    for start, middle, end in arcs:
        arc: Any = part.Curves.CreateArc(start, middle, end, False)
        # The C# out bool comes back alongside the arc in a tuple.
        if isinstance(arc, (tuple, list)):
            arc = arc[0]
        result.append(cast(NXOpen.Curve, arc))
    nx.syslog("Profile Subtract: {} 45-degree corner(s) rounded to {}".format(len(arcs), nx.cs_double_str(radius)))
    return result


def _fillet(a: NXOpen.Line, b: NXOpen.Line, chamfer: NXOpen.Line, radius: float,
            tolerance: float) -> Optional[Tuple[NXOpen.Point3d, NXOpen.Point3d, NXOpen.Point3d]]:
    """
    The radius arc tangent to line a (at the chamfer's start) and line b (at its end), as (tangent point on a, the
    arc's middle, tangent point on b); None when a tangent point would fall off a or b.
    """
    a_far = a.EndPoint if _distance(a.StartPoint, chamfer.StartPoint) < tolerance else a.StartPoint
    b_far = b.EndPoint if _distance(b.StartPoint, chamfer.EndPoint) < tolerance else b.StartPoint
    # The corner the chamfer cut off: where a and b, extended, meet.
    corner = _intersect(chamfer.StartPoint, _sub(chamfer.StartPoint, a_far),
                        chamfer.EndPoint, _sub(chamfer.EndPoint, b_far))
    if corner is None:
        return None
    to_a = _sub(a_far, corner)
    to_b = _sub(b_far, corner)
    along_a, along_b = _unit(to_a), _unit(to_b)
    angle = math.acos(max(-1.0, min(1.0, _dot(along_a, along_b))))
    if angle < 1e-6 or angle > math.pi - 1e-6:
        return None
    back = radius / math.tan(angle / 2)
    if back >= _length(to_a) - tolerance or back >= _length(to_b) - tolerance:
        return None
    bisector = _unit(_add(along_a, along_b))
    centre = _move(corner, bisector, radius / math.sin(angle / 2))
    return _move(corner, along_a, back), _move(centre, bisector, -radius), _move(corner, along_b, back)


def _intersect(p: NXOpen.Point3d, u: NXOpen.Vector3d, q: NXOpen.Point3d,
               v: NXOpen.Vector3d) -> Optional[NXOpen.Point3d]:
    """Where the coplanar lines p + s u and q + t v meet (the middle of their closest points); None if parallel."""
    w = _sub(p, q)
    a, b, c, d, e = _dot(u, u), _dot(u, v), _dot(v, v), _dot(u, w), _dot(v, w)
    denominator = a * c - b * b
    if abs(denominator) < 1e-12:
        return None
    s = (b * e - c * d) / denominator
    t = (a * e - b * d) / denominator
    on_p, on_q = _move(p, u, s), _move(q, v, t)
    return NXOpen.Point3d((on_p.X + on_q.X) / 2, (on_p.Y + on_q.Y) / 2, (on_p.Z + on_q.Z) / 2)


def _line_angle(direction: NXOpen.Vector3d, line: NXOpen.Line) -> float:
    """The angle in degrees (0-90) between direction and line, either way along it."""
    other = _unit(_sub(line.EndPoint, line.StartPoint))
    return math.degrees(math.acos(min(1.0, abs(_dot(direction, other)))))


def _sub(p: NXOpen.Point3d, q: NXOpen.Point3d) -> NXOpen.Vector3d:
    return NXOpen.Vector3d(p.X - q.X, p.Y - q.Y, p.Z - q.Z)


def _add(u: NXOpen.Vector3d, v: NXOpen.Vector3d) -> NXOpen.Vector3d:
    return NXOpen.Vector3d(u.X + v.X, u.Y + v.Y, u.Z + v.Z)


def _move(p: NXOpen.Point3d, u: NXOpen.Vector3d, distance: float) -> NXOpen.Point3d:
    return NXOpen.Point3d(p.X + u.X * distance, p.Y + u.Y * distance, p.Z + u.Z * distance)


def _dot(u: NXOpen.Vector3d, v: NXOpen.Vector3d) -> float:
    return u.X * v.X + u.Y * v.Y + u.Z * v.Z


def _length(u: NXOpen.Vector3d) -> float:
    return math.sqrt(_dot(u, u))


def _unit(u: NXOpen.Vector3d) -> NXOpen.Vector3d:
    length = _length(u)
    return NXOpen.Vector3d(u.X / length, u.Y / length, u.Z / length) if length > 0 else u


def _distance(p: NXOpen.Point3d, q: NXOpen.Point3d) -> float:
    return _length(_sub(p, q))


def _box_size(curves: Sequence[NXOpen.Curve]) -> float:
    """The sum of the curves' combined box extents. body_box is UF_MODL_ask_bounding_box_exact, which takes any
    object's tag."""
    box = nx.combine_boxes([nx.body_box(cast(Any, c)) for c in curves])
    return (box.MaxX - box.MinX) + (box.MaxY - box.MinY) + (box.MaxZ - box.MinZ)


class _TargetsDialog(Dialog):
    """
    ProfileSubtractTargets.dlx: the target solid bodies, nothing else. Each is blanked as soon as it is picked (so
    the tool faces behind it can be picked in the next dialog); one taken out of the pick is unblanked again. The
    caller unblanks the rest (unblank_targets) when the run ends.
    """

    dlx_name = "ProfileSubtractTargets.dlx"

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__()
        # Captured in ok(): the blocks are gone once Launch returns.
        self.targets: List[NXOpen.Body] = []
        # The target bodies blanked (update) by tag, unblanked by unblank_targets.
        self._blanked: Dict[int, NXOpen.Body] = {}

    def initialize(self) -> None:
        body_mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type, 0, _SolidBodyDetail)
        self.block("targets").SetSelectionFilter(NXOpen.Selection.SelectionAction.ClearAndEnableSpecific,
                                                 [body_mask])
        self.assembly_scope(self.block("targets"))

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        if block == self.block("targets"):
            picked = {b.Tag: b for b in self._picked_targets()}
            # Taken out of the pick: show it again.
            for tag in [t for t in self._blanked if t not in picked]:
                self._unblank(self._blanked.pop(tag))
            for tag, body in picked.items():
                if tag not in self._blanked:
                    try:
                        body.Blank()
                        self._blanked[tag] = body
                    except Exception as ex:
                        nx.print_exception(ex)

    def unblank_targets(self) -> None:
        """Shows every target body this dialog blanked again (no-op when none)."""
        for body in self._blanked.values():
            self._unblank(body)
        self._blanked = {}

    @staticmethod
    def _unblank(body: NXOpen.Body) -> None:
        try:
            body.Unblank()
        except Exception as ex:
            nx.print_exception(ex)

    def enable_ok(self) -> bool:
        return len(self._picked_targets()) > 0

    def ok(self) -> bool:
        self.targets = self._picked_targets()
        # enable_ok greys OK out for this; it is a backstop.
        if not self.targets:
            self.message("Select the target solid bodies.")
            return False
        return True

    def _picked_targets(self) -> List[NXOpen.Body]:
        return [cast(NXOpen.Body, o) for o in self.selected(self.block("targets"))
                if isinstance(o, NXOpen.Body) and cast(NXOpen.Body, o).IsSolidBody]


class _ToolsDialog(Dialog):
    """
    The offset and the planar tool faces: ProfileSubtractTools.dlx (many faces, for one target) or
    ProfileSubtractTool.dlx (one face, for many targets). The offset's units follow the job: Offset (mm) 20 for GM or
    a job detect_customer cannot tell, Offset (in) .5 for TSG.
    """

    def __init__(self, title: str, many_faces: bool) -> None:
        self.title = title
        self.dlx_name = "ProfileSubtractTools.dlx" if many_faces else "ProfileSubtractTool.dlx"
        super().__init__()
        # Captured in ok(): the blocks are gone once Launch returns.
        self.tool_faces: List[NXOpen.Face] = []
        self.offset = 0.0
        # Offset in millimetres (GM job, or one detect_customer cannot tell) or inches (TSG job).
        self.offset_in_mm = True

    def initialize(self) -> None:
        self.block("tool_faces").SetSelectionFilter(NXOpen.Selection.SelectionAction.ClearAndEnableSpecific,
                                                    [_planar_face_mask()])
        self.assembly_scope(self.block("tool_faces"))

    def shown(self) -> None:
        # Value properties: set once the dialog is up. The job decides the units every time.
        self.offset_in_mm = detect_customer() != CustomerTsg
        offset = self.block("offset")
        if self.offset_in_mm:
            offset.Label = "Offset (mm)"
            offset.Value = 20.0
        else:
            offset.Label = "Offset (in)"
            offset.Value = .5

    def enable_ok(self) -> bool:
        return len(self._picked_faces()) > 0

    def ok(self) -> bool:
        self.tool_faces = self._picked_faces()
        # enable_ok greys OK out for this; it is a backstop.
        if not self.tool_faces:
            self.message("Select the tool planar faces.")
            return False
        self.offset = float(self.block("offset").Value)
        return True

    def _picked_faces(self) -> List[NXOpen.Face]:
        return [cast(NXOpen.Face, o) for o in self.selected(self.block("tool_faces")) if isinstance(o, NXOpen.Face)]


def main() -> None:
    """The profile-subtract UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            # No confirm: the dialog is the choice to run.
            ProfileSubtract.execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
