"""
Python port of the boss UFunc (Merlin.StaticBoss, src\\UFuncs\\Merlin.cs, region
"Standalone Builders - Boss, Perfect & Backing Plate").
The C# wrapper was deleted 2026-10-22 (in git at 1cb53d8): the UFunc's menu button runs this file's main().

Two picks: a planar target face, then one or more planar tool faces (both any in assembly). The target face's
component is blanked between the picks so the tool faces behind it can be reached, and the target's component is made
the work component. Then, per tool face (each in its own try/except, printed, so one bad face does not drop the rest):
  - the face is wave-linked into the target's part as a single face with its holes removed, from the assembly (the
    tool face is an occurrence picked there; the target's component is the work component);
  - the target's part is then displayed and made the work part, and everything below is built in its own
    coordinates. Built from the assembly, the curves came out offset by the component's position a second time
    (abs - 2 x origin), and the C#'s work part (target_face.OwningPart - the assembly) made the extrude's section
    interpart (674354 "Creating an interpart section is not allowed");
  - a datum axis is made at the linked face's first edge start point along its normal, and its owning part's leaf
    is printed;
  - a curve is copied off every edge of the linked face, checked to lie on those edges (it raises when they are more
    than .001 apart);
  - the curves are extruded from the tool face up to the target face (Until Extended, toward the target whichever
    way the tool face's normal points - the C#'s commented-out "Until Selected"), and the extrude's parameters removed;
  - the side faces of the resulting body (the last unsuppressed feature in the work part) - every face that is not
    planar, or planar but not normal to +/-Z - are offset "10mm";
  - the body takes the target face's color, its end at the tool face (the extrude's start cap) goes 42;
  - it is united into the target face's prototype body; the linked face and the curves are deleted.
The target component is unblanked and the starting display and work parts restored in a finally.

This is the C#'s work-in-progress state, ported as it stands: the datum axis is left in the part, target_z / tool_z
are read and never used. The extrude now ends on the target face (the C#'s commented-out
Merlin.CreateExtrudeUntilSelected, as Until Extended) instead of the C#'s fixed 10.

Two ways in:
  - File -> Execute -> NX Open on this file runs main() with is_gm = True, as the boss UFunc does.
  - Session.Execute("Boss.py", "Boss", "execute", is_gm) from C#, or build_gm_boss(target_face, tool_faces) with
    the picked face occurrences.
is_gm is accepted and unused, as in the C#.

Differences from the C#:
  - The picks are the NXOpen SelectionManager with the same mask SNAP builds for SetFaceFilter(FacePlane)
    ((70, 2, 21) - solid type, face subtype, planar face) instead of Snap.UI.Selection. Response handling is kept:
    the target pick only counts on ObjectSelected; the tool pick returns nothing on Cancel or an empty OK, and raises
    on any other response (the C#'s ArgumentOutOfRangeException), which the outer handler prints.
  - Snap.Create.DatumAxis / Extrude / OffsetFace / Unite, Feature.Orphan and NXObject.Delete are re-implemented with
    the NXOpen builders SNAP itself uses (decompiled from Snap.dll). Unite uses tsg_nx.create_boolean (tool-body
    collector) where SNAP uses the obsolete BooleanBuilder.Tools. SNAP's history-mode check before each feature is not
    ported. AddToSection is the seven-argument overload with chainWithinFeature False.
  - build_gm_boss blanks the target's component itself as well (idempotent), so it works when C# does the picks.

The Merlin helpers DrawDie.py already ports are imported rather than copied. Several NXOpen members used here are not
in python\\stubs (ExtrudeBuilder.DistanceTolerance/Offset/Draft, DatumAxisBuilder, ExtractFaceBuilder.DeleteHoles /
ObjectToExtract, ScRuleFactory.CreateRuleFaceTangent, PartPreferences.Modeling); they are reached through Any.
"""

from __future__ import annotations

import os
import sys
from typing import Any, List, Optional, Sequence, cast

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
import NXOpen.Features  # noqa: E402
import NXOpen.GeometricUtilities  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
import DrawDie as drawdie  # noqa: E402

# Snap MaskTriple.BuildFromTypeCombo(Face, FacePlane): UF_solid_type, UF_solid_face_subtype, 100121 % 1001.
_UF_UI_SEL_FEATURE_PLANAR_FACE = 21

# Snap.Create.Extrude(curves, v, 10) - extents 0 .. 10, part units.
# The extrude's end value; overridden by the Until Extended target face, so only a fallback.
BossExtrudeLength = 10
# Snap.Create.OffsetFace("10mm", false, ...)
BossSideOffset = "10mm"
BossBottomColor = 42

_VectorZ = NXOpen.Vector3d(0.0, 0.0, 1.0)
_VectorZN = NXOpen.Vector3d(0.0, 0.0, -1.0)


class Boss(object):

    @staticmethod
    def execute(is_gm: bool = True) -> None:
        """Merlin.StaticBoss(is_gm) - the boss UFunc passes is_gm = True."""
        static_boss(is_gm)


def static_boss(is_gm: bool) -> None:
    """Merlin.StaticBoss - units gate, the two picks, then build_gm_boss."""
    ok, message = drawdie._check_info_units()
    if not ok:
        nx.show_error(message)
        return

    blanked: List[NXOpen.DisplayableObject] = []
    starting_display = nx.display_part()
    starting_work = nx.work_part()

    try:
        version = nx.assembly_file_version()
        target_face = _select_planar_face("Select target face for Boss: {}".format(version),
                                          "Boss Target: {}".format(version))
        if target_face is None:
            nx.mark_cancelled("the target face pick")
            return
        target_component = target_face.GetBody().OwningComponent
        target_component.Blank()
        blanked.append(target_component)
        tool_faces = _select_planar_faces("Select tool faces for Boss: {}".format(version),
                                          "Boss Tools: {}".format(version))
        if tool_faces is None:
            nx.mark_cancelled("the tool face pick")
            return

        build_gm_boss(target_face, tool_faces)
    except Exception as ex:
        nx.print_exception(ex)
    finally:
        for blanked_component in blanked:
            blanked_component.Unblank()

        nx.set_display_part(starting_display)
        nx.set_work_part(starting_work)


def build_gm_boss(target_face: NXOpen.Face, tool_faces: Sequence[NXOpen.Face]) -> None:
    """
    The build half of Merlin.StaticBoss on picked face occurrences: target_face is the planar target, tool_faces the
    planar tool faces. Blanks the target's component for the run and restores it, and the starting display / work
    parts, in a finally.
    """
    blanked: List[NXOpen.DisplayableObject] = []
    starting_display = nx.display_part()
    starting_work = nx.work_part()

    try:
        target_component = target_face.GetBody().OwningComponent
        target_component.Blank()
        blanked.append(target_component)
        target_color = target_face.Color

        # The wave-linked face and the curves taken off it have to land in the target's part, so the work component
        # is switched before the loop rather than part-way through it.
        nx.set_work_component(target_face.OwningComponent)
        # Read and unused in the C# (target_face / target_z), kept for the same failure modes.
        _target_prototype_face = target_face.Prototype
        _target_z = nx.edge_start_point(target_face.GetEdges()[0]).Z

        for face in tool_faces:
            try:
                _build_one_boss(target_face, face, target_color, starting_display)
            except Exception as ex:
                nx.print_exception(ex)
    except Exception as ex:
        nx.print_exception(ex)
    finally:
        for blanked_component in blanked:
            blanked_component.Unblank()

        nx.set_display_part(starting_display)
        nx.set_work_part(starting_work)


def _build_one_boss(target_face: NXOpen.Face, face: NXOpen.Face, target_color: int,
                    assembly: Optional[NXOpen.BasePart] = None) -> None:
    """
    The body of StaticBoss's per-tool-face loop. The tool face is wave-linked into the target's part from the
    assembly (assembly, with the target's component as work component - the face is an occurrence picked there);
    everything after that - curves, extrude, offset, unite - is built with the target's part displayed, so nothing is
    mapped through the component's position. Built from the assembly, the curves taken off the linked face's edges
    came out offset by the component's position a second time (abs - 2 x origin on 006066-010's cast trim pad).
    """
    target_prototype = cast(Optional[NXOpen.Face], target_face.Prototype)
    if target_prototype is None:
        raise RuntimeError("The target face is not an occurrence")
    target_part = cast(NXOpen.Part, target_prototype.OwningPart)

    if assembly is not None:
        nx.set_display_part(assembly)
    nx.set_work_component(target_face.OwningComponent)
    extracted_face = _extract_face_without_holes(face)

    # From here on in the target's part, in its own coordinates.
    nx.set_display_part(target_part)
    nx.set_work_part(target_part)
    linked_faces = list(extracted_face.GetFaces())
    if len(linked_faces) == 0:
        raise RuntimeError("The linked tool face has no face")
    linked_face = linked_faces[0]
    v = _normal_vector(linked_face)

    g = _create_datum_axis(nx.edge_start_point(linked_face.GetEdges()[0]), v)

    # Snap's NXOpenDisplayableObject of a datum-axis feature is its first entity, the DatumAxis.
    nx.print_(g.GetEntities()[0].OwningPart.Leaf)

    curves = [nx.edge_to_curve(edge) for edge in extracted_face.GetEdges()]

    stray = [c for c in curves if c.OwningPart.Tag != target_part.Tag]
    if stray:
        raise RuntimeError("{} boss curve(s) are in {}, not the target part {}".format(
            len(stray), stray[0].OwningPart.Leaf, target_part.Leaf))
    # The curves must lie on the linked face's edges; a gap means they were mapped through an assembly position.
    # body_box is UF_MODL_ask_bounding_box_exact, which takes any object's tag.
    face_box = nx.combine_boxes([nx.body_box(cast(Any, e)) for e in linked_face.GetEdges()])
    curve_box = nx.combine_boxes([nx.body_box(cast(Any, c)) for c in curves])
    gap = max(abs(face_box.MinX - curve_box.MinX), abs(face_box.MinY - curve_box.MinY),
              abs(face_box.MinZ - curve_box.MinZ))
    if gap > .001:
        raise RuntimeError("The boss curves are {:.3f} away from the linked tool face in {}".format(
            gap, target_part.Leaf))

    # Up to the target face: along the tool face's normal or against it, whichever way the target lies.
    target_point = nx.edge_start_point(target_prototype.GetEdges()[0])
    tool_point = nx.edge_start_point(linked_face.GetEdges()[0])
    to_target = (v.X * (target_point.X - tool_point.X) + v.Y * (target_point.Y - tool_point.Y)
                 + v.Z * (target_point.Z - tool_point.Z))
    if abs(to_target) < .0001:
        raise RuntimeError("The tool face is in the target face's plane - nothing to extrude")
    direction = v if to_target > 0 else nx.negate(v)

    extrude = _snap_extrude(curves, direction, BossExtrudeLength, until=target_prototype)

    _orphan(extrude)
    brep_feat = [f for f in nx.work_part().Features.GetFeatures() if not f.Suppressed][-1]
    faces_to_offset = [f for f in brep_feat.GetFaces()
                       if f.SolidFaceType != NXOpen.Face.FaceType.Planar
                       or not nx.vectors_equal(nx.face_normal(f), _VectorZ)
                       and not nx.vectors_equal(nx.face_normal(f), _VectorZN)]
    _snap_offset_face(BossSideOffset, False, faces_to_offset)
    nx.set_color(brep_feat.GetBodies()[0], target_color)
    # The end at the tool face (the extrude's start cap).
    bottom = [f for f in brep_feat.GetFaces()
              if f.SolidFaceType == NXOpen.Face.FaceType.Planar
              and nx.vectors_equal(nx.face_normal(f), nx.negate(direction))]
    if len(bottom) == 0:
        raise RuntimeError("Sequence contains no matching element")
    nx.set_color(bottom[0], BossBottomColor)
    nx.create_boolean(target_prototype.GetBody(), [brep_feat.GetBodies()[0]],
                      NXOpen.Features.Feature.BooleanType.Unite)
    _snap_delete([extracted_face])
    for curve in curves:
        _snap_delete([curve])


# ---------------------------------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------------------------------

def _planar_face_mask() -> NXOpen.Selection.MaskTriple:
    return NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type,
                                       NXOpen.UF.UFConstants.UF_solid_face_subtype,
                                       _UF_UI_SEL_FEATURE_PLANAR_FACE)


def _select_planar_face(cue: str, title: str) -> Optional[NXOpen.Face]:
    """
    Selection.select_planar_face(cue, title) - one planar face, any in assembly, not kept highlighted. Only an
    ObjectSelected response counts (the C# tests (int)Response == 5); anything else is None.
    """
    response, obj, _cursor = NXOpen.UI.GetUI().SelectionManager.SelectTaggedObject(
        cue,
        title,
        NXOpen.Selection.SelectionScope.AnyInAssembly,
        NXOpen.Selection.SelectionAction.ClearAndEnableSpecific,
        False,
        False,
        [_planar_face_mask()])
    if response != NXOpen.Selection.Response.ObjectSelected or not isinstance(obj, NXOpen.Face):
        return None
    return obj


def _select_planar_faces(cue: str, title: str) -> Optional[List[NXOpen.Face]]:
    """
    Selection.select_planar_faces(cue, title) - many planar faces, any in assembly. None on Cancel or an OK with
    nothing picked; any other response raises, as the C#'s ArgumentOutOfRangeException does.
    """
    response, objects = NXOpen.UI.GetUI().SelectionManager.SelectTaggedObjects(
        cue,
        title,
        NXOpen.Selection.SelectionScope.AnyInAssembly,
        NXOpen.Selection.SelectionAction.ClearAndEnableSpecific,
        False,
        False,
        [_planar_face_mask()])
    if response == NXOpen.Selection.Response.Ok:
        faces = [obj for obj in objects if isinstance(obj, NXOpen.Face)]
        if len(faces) == 0:
            return None
        return faces
    if response == NXOpen.Selection.Response.Cancel:
        return None
    raise ValueError("Specified argument was out of the range of valid values.")


# ---------------------------------------------------------------------------------------------------
# Geometry helpers (Globals.cs extensions and the SNAP calls StaticBoss makes)
# ---------------------------------------------------------------------------------------------------

def _normal_vector(face: NXOpen.Face) -> NXOpen.Vector3d:
    """Face.__NormalVector - UF_MODL_ask_face_data's direction for a planar face, not re-unitized."""
    face_type, _point, direction, _box, _radius, _rad_data, _norm_dir = nx.ufsession_.Modeling.AskFaceData(face.Tag)
    if face_type != nx.UF_MODL_PLANAR_FACE:
        raise RuntimeError("Cannot ask for the normal of a non planar face")
    return NXOpen.Vector3d(direction[0], direction[1], direction[2])


def _extract_face_without_holes(face: NXOpen.Face) -> NXOpen.Features.Feature:
    """Snap.NX.Face.__ExtractFaceWithoutHoles - wave-links face into the work part as one associative face, holes
    removed."""
    builder = nx.work_part().BaseFeatures.CreateWaveLinkBuilder(None)
    try:
        extract: Any = builder.ExtractFaceBuilder
        extract.ParentPart = NXOpen.Features.ExtractFaceBuilder.ParentPartType.OtherPart
        builder.Type = NXOpen.Features.WaveLinkBuilder.Types.FaceLink
        extract.Associative = True
        extract.FaceOption = NXOpen.Features.ExtractFaceBuilder.FaceOptionType.SingleFace
        extract.ObjectToExtract.Add(face)
        extract.DeleteHoles = True
        return cast(NXOpen.Features.Feature, builder.CommitFeature())
    finally:
        builder.Destroy()


def _create_datum_axis(origin: NXOpen.Point3d, direction: NXOpen.Vector3d) -> NXOpen.Features.Feature:
    """Snap.Create.DatumAxis(Position, Vector) - an associative point-and-direction datum axis in the work part."""
    part = nx.work_part()
    builder: Any = cast(Any, part.Features).CreateDatumAxisBuilder(None)
    try:
        builder.Type = cast(Any, NXOpen.Features).DatumAxisBuilder.Types.PointAndDir
        vector = part.Directions.CreateDirection(origin, direction, NXOpen.SmartObject.UpdateOption.WithinModeling)
        builder.IsAssociative = True
        builder.IsAxisReversed = False
        builder.Vector = vector
        builder.Point = part.Points.CreatePoint(origin)
        return cast(NXOpen.Features.Feature, builder.CommitFeature())
    finally:
        builder.Destroy()


def _snap_extrude(curves: Sequence[NXOpen.Curve], axis: NXOpen.Vector3d, length: float,
                  until: Optional[NXOpen.Face] = None, start: float = 0.0) -> NXOpen.Features.Extrude:
    """
    Snap.Create.Extrude(curves, axis, length) - a Create extrude of the curves (one CurveDumb rule each) from 0 to
    length along axis, no offset, no draft, in the work part. A closed loop gives a solid. With until (a face in the
    work part) the end is Until Extended to that face instead of length - Until Selected with the face's surface
    extended, so a profile wider than the face still closes on it. start moves the start from 0 (ProfileSubtract
    extrudes -10 .. 10).
    """
    part = nx.work_part()
    modeling: Any = cast(Any, part.Preferences).Modeling
    distance_tolerance = modeling.DistanceToleranceData
    angle_tolerance = modeling.AngleToleranceData

    # Snap.NX.Section.CreateSection(ICurve[])
    section = part.Sections.CreateSection(0.95 * distance_tolerance, distance_tolerance, angle_tolerance)
    section.AllowSelfIntersection(False)
    section.SetAllowedEntityTypes(NXOpen.Section.AllowTypes.CurvesAndPoints)
    for curve in curves:
        section.AddToSection([part.ScRuleFactory.CreateRuleCurveDumb([curve])], curve, None, None,
                             NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Section.Mode.Create, False)

    builder: Any = part.Features.CreateExtrudeBuilder(None)
    try:
        builder.DistanceTolerance = distance_tolerance
        builder.BooleanOperation.Type = NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Create
        builder.Limits.StartExtend.Value.RightHandSide = nx.cs_double_str(start)
        builder.Limits.EndExtend.Value.RightHandSide = nx.cs_double_str(length)
        if until is not None:
            builder.Limits.EndExtend.TrimType = NXOpen.GeometricUtilities.Extend.ExtendType.UntilExtended
            builder.Limits.EndExtend.Target = until
        geometric: Any = NXOpen.GeometricUtilities
        builder.Offset.Option = geometric.Type.NoOffset
        builder.Draft.DraftOption = geometric.SimpleDraft.SimpleDraftType.NoDraft
        builder.Draft.FrontDraftAngle.RightHandSide = "0"
        builder.Section = section
        builder.Direction = part.Directions.CreateDirection(NXOpen.Point3d(30.0, 0.0, 0.0), axis,
                                                            NXOpen.SmartObject.UpdateOption.WithinModeling)
        return cast(NXOpen.Features.Extrude, builder.CommitFeature())
    finally:
        builder.Destroy()


def _orphan(feature: NXOpen.Features.Feature) -> None:
    """Snap.NX.Feature.Orphan - a RemoveParametersBuilder in the work part over the feature's bodies."""
    bodies = feature.GetBodies()
    builder = nx.work_part().Features.CreateRemoveParametersBuilder()
    try:
        builder.Objects.Add(list(bodies))
        builder.Commit()
    finally:
        builder.Destroy()


def _snap_offset_face(distance: str, direction: bool, faces: Sequence[NXOpen.Face]) -> NXOpen.Features.OffsetFace:
    """Snap.Create.OffsetFace(distance, reverse, faces) - one FaceTangent rule per face, in the work part."""
    part = nx.work_part()
    builder = part.Features.CreateOffsetFaceBuilder(None)
    try:
        builder.Distance.RightHandSide = distance
        rule_factory: Any = part.ScRuleFactory
        rules = [rule_factory.CreateRuleFaceTangent(face, []) for face in faces]
        builder.FaceCollector.ReplaceRules(rules, False)
        builder.Direction = direction
        return cast(NXOpen.Features.OffsetFace, builder.CommitFeature())
    finally:
        builder.Destroy()


def _snap_delete(objects: Sequence[NXOpen.NXObject]) -> None:
    """Snap.NX.NXObject.Delete - delete list + DoUpdate under a visible "Snap_DeleteNXObjects999" mark."""
    session = nx.session_
    mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Snap_DeleteNXObjects999")
    session.UpdateManager.ClearErrorList()
    session.UpdateManager.AddObjectsToDeleteList(list(objects))
    session.UpdateManager.DoUpdate(mark)
    session.DeleteUndoMark(mark, "Snap_DeleteNXObjects999")


def main() -> None:
    """The boss UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db
    from tsg_dialog import ask_is_gm

    with usage_db.run("boss"):
        try:
            # The Customer dialog first: GM builds with the GM parts, TSG throws.
            is_gm = ask_is_gm("Cast Boss")
            if is_gm is not None:
                Boss.execute(is_gm)
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
