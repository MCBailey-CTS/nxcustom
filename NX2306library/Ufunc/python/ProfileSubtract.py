"""
The profile-subtract UFunc: a standalone Python UFunc (no C# class); its menu button runs this file's main().

The dialog (ProfileSubtract.dlx, tools\\make-dlx.py): one target solid body, one or more planar tool faces (both
anywhere in the assembly) and an offset in inches. OK stays greyed out until a target and a tool face are picked.

Then, per tool face (each in its own try/except, printed, so one bad face does not drop the rest):
  - the face is wave-linked into the target body's owning part as a single face with its holes removed, from the
    assembly, with the target's component as the work component (Boss._extract_face_without_holes);
  - with the target's part displayed and made the work part, a curve is copied off every edge of the linked face, so
    the curves are in the part's own coordinates (Boss found that taking them from the assembly offsets them by the
    component's position a second time);
  - the linked face is deleted; the edge curves stay in the target's part;
  - the curves are offset outward by the offset (an Offset Curve feature, the edge curves kept; a negative offset
    goes inward, 0 skips it). Which side the builder offsets to follows the loop's direction, so the result is
    measured and redone reversed if its box came out smaller;
  - the offset curves are extruded 10" both ways along the linked face's normal (Boss._snap_extrude) and the
    extrude is subtracted from the target body. Inches are converted for a metric target part.
The starting display and work parts are restored in a finally. The curves, offset and extrude stay as features
behind the subtract, so the profile can be edited.

Two ways in:
  - File -> Execute -> NX Open on this file runs main().
  - build(target, tool_faces, offset) with the picked occurrences.
"""

from __future__ import annotations

import os
import sys
from typing import Any, List, Optional, Sequence, Tuple, cast

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
from tsg_dialog import Dialog, title_with_version  # noqa: E402

ufunc_name = "profile-subtract"

# UF_UI_SEL_FEATURE_SOLID_BODY - not in every UFConstants build, so the number Perfect.py uses too.
_SolidBodyDetail = 36

# How far the profile is extruded each way along the tool face's normal.
ExtrudeInches = 10.0


class ProfileSubtract(object):

    @staticmethod
    def execute() -> None:
        """The dialog, then build."""
        dialog = _ProfileSubtractDialog(title_with_version("Profile Subtract"))
        if not dialog.run() or dialog.target is None:
            return
        build(dialog.target, dialog.tool_faces, dialog.offset)


def build(target: NXOpen.Body, tool_faces: Sequence[NXOpen.Face], offset: float) -> int:
    """
    Per tool face: links it into the target's owning part without its holes, copies the linked face's edges to curves
    there, deletes the link, offsets the curves outward by offset inches, extrudes them ExtrudeInches up and down the
    face's normal and subtracts that from the target body. Returns how many faces were subtracted.
    """
    starting_display = nx.display_part()
    starting_work = nx.work_part()
    target_component = target.OwningComponent if target.IsOccurrence else None
    owner = cast(NXOpen.Body, target.Prototype) if target.IsOccurrence else target
    target_part = cast(NXOpen.Part, owner.OwningPart)
    # The dialog takes inches; the builders take the target part's units.
    per_inch = 25.4 if target_part.PartUnits == NXOpen.BasePart.Units.Millimeters else 1.0
    subtracted = 0
    nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Profile Subtract")

    try:
        for face in tool_faces:
            try:
                curves, normal = _profile_curves(face, starting_display, target_component, target_part)
                profile = _offset_outward(curves, offset * per_inch)
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


def _box_size(curves: Sequence[NXOpen.Curve]) -> float:
    """The sum of the curves' combined box extents. body_box is UF_MODL_ask_bounding_box_exact, which takes any
    object's tag."""
    box = nx.combine_boxes([nx.body_box(cast(Any, c)) for c in curves])
    return (box.MaxX - box.MinX) + (box.MaxY - box.MinY) + (box.MaxZ - box.MinZ)


class _ProfileSubtractDialog(Dialog):
    """ProfileSubtract.dlx: the target body, the tool faces, the offset."""

    dlx_name = "ProfileSubtract.dlx"

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__()
        # Captured in ok(): the blocks are gone once Launch returns.
        self.target: Optional[NXOpen.Body] = None
        self.tool_faces: List[NXOpen.Face] = []
        self.offset = 0.0

    def initialize(self) -> None:
        body_mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type, 0, _SolidBodyDetail)
        self.block("target").SetSelectionFilter(NXOpen.Selection.SelectionAction.ClearAndEnableSpecific,
                                                [body_mask])
        self.block("tool_faces").SetSelectionFilter(NXOpen.Selection.SelectionAction.ClearAndEnableSpecific,
                                                    [_planar_face_mask()])
        self.assembly_scope(self.block("target"))
        self.assembly_scope(self.block("tool_faces"))

    def enable_ok(self) -> bool:
        return self._picked_target() is not None and len(self._picked_faces()) > 0

    def ok(self) -> bool:
        self.target = self._picked_target()
        self.tool_faces = self._picked_faces()

        # enable_ok greys OK out for both; these are a backstop.
        if self.target is None:
            self.message("Select the target solid body.")
            return False
        if not self.tool_faces:
            self.message("Select the tool planar faces.")
            return False

        self.offset = float(self.block("offset").Value)
        return True

    def _picked_target(self) -> Optional[NXOpen.Body]:
        bodies = [cast(NXOpen.Body, o) for o in self.selected(self.block("target"))
                  if isinstance(o, NXOpen.Body) and cast(NXOpen.Body, o).IsSolidBody]
        return bodies[0] if bodies else None

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
