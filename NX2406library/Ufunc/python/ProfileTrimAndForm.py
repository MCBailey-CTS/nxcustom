"""
Python port of the NX work in the ProfileTrimAndForm form (src\\UFuncs\\ProfileTrimAndForm.cs), whose static methods
now live in src\\Static\\ProfileTrimAndForm.cs (partial class Static):

- ProfileTrimAndFormCreate(pairs, layer, isTrim, isOuter, isUpper, createFeatureGroup)
      -> ProfileTrimAndForm.create(directions, curves, group_sizes, layer, is_trim, is_outer, is_upper,
                                   create_feature_group)
- ProfileTrimAndFormBuildProfile (was ProfileBuilder.Create)           -> _build_profile
- ProfileTrimAndFormCreateFeatureGroup                                 -> ProfileTrimAndForm.create_feature_group
- ProfileTrimAndFormWaveLinkObject                                     -> ProfileTrimAndForm.wave_link_object
- ProfileTrimAndFormCreateCoordinateSystem                             -> ProfileTrimAndForm.create_coordinate_system
- ProfileTrimAndFormCreateLower / CreateOffsetPads / CreatePad / CreatePunches / MakeExtrude
      -> _create_lower / _create_offset_pads / _create_pad / _create_punches / _make_extrude
- ProfileTrimAndFormCreateSlugs / CreateUniteTargets (both [Obsolete], bodies commented out)
      -> _create_slugs / _create_unite_targets, which raise NotImplementedError like the C#
- The form's nested SlugObj / UniteTarget / Pad types -> _SlugObj / _UniteTarget / _Pad

THE WHOLE PIPELINE IS DEAD IN C# TOO. ProfileBuilder.Create's first statement is CreateSlugs, which throws
NotImplementedException, so every Execute run prints that exception (BtnExecute_Click's outer catch) and also skips
the LWR-/UPR-/PAD-PROFILE reference-set blocks. create() reproduces that: it raises NotImplementedError from
_create_slugs. Everything after it is ported faithfully anyway so the two stay comparable if CreateSlugs is ever
revived (the SlugObj constructor and UniteTarget.TopMostFace throw too, and would need reviving with it).

Not ported:
- SelectCurveGroups (the curve/datum-axis picker with its UF filter proc and highlight/colour bookkeeping): it is the
  selection, which stays C#, and Python cannot host a UF filter proc.
- The three reference-set blocks inline in BtnExecute_Click: they are in the event handler, which did not move.
- The form's Load/CheckedChanged handlers: pure WinForms.

The pairs (Tuple<Vector3d, ISet<Curve>>[]) cannot cross Session.Execute, so create() takes them flattened:
directions = x, y, z per group; curves = every group's curves, group after group; group_sizes = curves per group.

Differences from the C#:
- The punch unite goes through tsg_nx.create_boolean (tool-body collector); the C# __CreateUnite feeds the obsolete
  BooleanBuilder.Tools. Both build in the work part.
- UniteTarget/Pad are C# structs. CreatePad's `unite.SetPadObj(...)` mutates the foreach copy, so the caller's
  uniteTargets never see PadObj (it stays null and is filtered out of the feature group). _create_pad copies the
  target before setting pad_obj to keep that; the copy shares the punch list, as the struct copy shares its List.

WIRED (2026-10-21), NEVER RUN IN NX. Static.ProfileTrimAndFormExecute (the Execute button) flattens the pairs and calls
    PythonLibrary.Execute("ProfileTrimAndForm.py", "ProfileTrimAndForm", "create",
        directions /* double[] */, curves /* TaggedObject[] */, groupSizes /* int[] */,
        layer, isTrim, isOuter, isUpper, createFeatureGroup);
in place of ProfileTrimAndFormCreate, with no catch of its own: a failure reaches BtnExecute_Click's catch, which
prints it, and the reference-set steps are skipped, exactly as when the C# threw. The replaced C# (Create and the
whole ProfileBuilder) sits commented out in src\\Static\\ProfileTrimAndForm.cs. create_feature_group,
wave_link_object and create_coordinate_system are not called from C# (they return NX objects, and their C#
twins had no callers outside the builder).

Binding notes: UF Modl.CreateSetOfFeature(name, features, count, hideState) -> Tag and Csys.CreateTempCsys(origin,
matrixId) -> Tag are confirmed in NXOpen_UF.pyd; the ScRuleFactory rules, Face.GetBody, OffsetFaceBuilder,
WaveLinkBuilder.WaveDatumBuilder, ExtrudeBuilder.ParentFeatureInternal, BooleanOperation.SetTargetBodies and
Extend.ExtendType.UntilExtended exist in the NXOpen / Features / GeometricUtilities pyds, but none of these calls has
been run from Python.
"""

from __future__ import annotations

import copy
import math
import os
import sys
from typing import Iterable, List, Optional, Sequence, Set, Tuple, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.Features  # noqa: E402
import NXOpen.GeometricUtilities  # noqa: E402

import tsg_nx as nx  # noqa: E402

# ProfileTrimAndForm.Offset
_OFFSET_OUT = "Out"
_OFFSET_IN = "In"


class ProfileTrimAndForm(object):

    @staticmethod
    def create(directions: Sequence[float], curves: Sequence[NXOpen.Curve], group_sizes: Sequence[int],
               layer: int, is_trim: bool, is_outer: bool, is_upper: bool, create_feature_group: bool) -> None:
        """Static.ProfileTrimAndFormCreate - the pairs arrive flattened (see the module docstring)."""
        pair_array = _unflatten_pairs(directions, curves, group_sizes)

        if len(pair_array) == 0:
            return

        # sql
        color = 186 if is_trim else 42

        pad_offset = "p" if is_trim else ".5"

        offset_direction = _OFFSET_OUT if is_trim or is_outer else _OFFSET_IN

        _build_profile(pair_array,
                       layer,
                       pad_offset,
                       offset_direction,
                       is_upper,
                       is_trim,
                       color,
                       create_feature_group)

    @staticmethod
    def create_feature_group(name: str, show: bool,
                             objects: Sequence[NXOpen.TaggedObject]) -> NXOpen.Features.FeatureGroup:
        """Static.ProfileTrimAndFormCreateFeatureGroup"""
        return _create_feature_group(name, show, objects)

    @staticmethod
    def wave_link_object(body: NXOpen.Body, parent_type: Optional[NXOpen.Features.ExtractFaceBuilder.ParentPartType]
                         = None) -> NXOpen.Features.ExtractFace:
        """Static.ProfileTrimAndFormWaveLinkObject - parent_type None = the C# default, OtherPart."""
        return _wave_link_object(body, parent_type)

    @staticmethod
    def create_coordinate_system(vector: NXOpen.Vector3d,
                                 origin: NXOpen.Point3d) -> NXOpen.CartesianCoordinateSystem:
        """Static.ProfileTrimAndFormCreateCoordinateSystem - a temporary csys at origin, Z along vector."""
        n_matrix = nx.work_part().NXMatrices.Create(_to_matrix3x3(vector))
        temp_tag = nx.ufsession_.Csys.CreateTempCsys([origin.X, origin.Y, origin.Z], n_matrix.Tag)
        return cast(NXOpen.CartesianCoordinateSystem, nx.tagged_object(temp_tag))


# ---------------------------------------------------------------------------------------------------
# The form's nested types
# ---------------------------------------------------------------------------------------------------

class _SlugObj(object):
    """ProfileTrimAndForm.SlugObj - its only constructor throws ([Obsolete], body commented out)."""

    slug: NXOpen.Features.Extrude
    vector: NXOpen.Vector3d
    polyline: Set[NXOpen.Curve]
    top_face: NXOpen.Face

    def __init__(self, extrude_sp: NXOpen.Features.Extrude, vector: NXOpen.Vector3d,
                 polyline: Set[NXOpen.Curve]) -> None:
        raise NotImplementedError()

    @property
    def origin(self) -> NXOpen.Point3d:
        # SlugObj.Origin => Polyline.First().__StartPoint()
        return _curve_start_point(next(iter(self.polyline)))


class _UniteTarget(object):
    """ProfileTrimAndForm.UniteTarget"""

    def __init__(self, extrude: NXOpen.Features.Extrude, slugs: Sequence[_SlugObj]) -> None:
        self.unite = extrude
        self.slugs = slugs
        self.pad_obj: Optional[NXOpen.TaggedObject] = None
        self.punches: List[NXOpen.TaggedObject] = []

    @property
    def top_most_face(self) -> NXOpen.Face:
        # [Obsolete] - the body is commented out and throws.
        raise NotImplementedError()

    def add_punch(self, tagged: NXOpen.TaggedObject) -> None:
        self.punches.append(tagged)

    def set_pad_obj(self, tagged: NXOpen.TaggedObject) -> None:
        self.pad_obj = tagged


class _Pad(object):
    """ProfileTrimAndForm.Pad"""

    def __init__(self, pad_obj: NXOpen.Features.ExtractFace, unite_target: _UniteTarget) -> None:
        self.pad_obj = pad_obj
        self.unite_target = unite_target


# ---------------------------------------------------------------------------------------------------
# ProfileBuilder
# ---------------------------------------------------------------------------------------------------

def _build_profile(source: Sequence[Tuple[NXOpen.Vector3d, Set[NXOpen.Curve]]],
                   layer: int,
                   expression: str,
                   pad_offset_out: str,
                   is_upper: bool,
                   is_trim_profile: bool,
                   color: int,
                   create_feature_group: bool) -> None:
    """Static.ProfileTrimAndFormBuildProfile (was ProfileBuilder.Create)."""
    slugs = list(_create_slugs(source, color))

    # sql
    unite_target_layer = layer + 5 if is_trim_profile else (layer + 5 if is_upper else layer + 4)

    unite_targets = list(_create_unite_targets(slugs, color, unite_target_layer))
    _create_punches(unite_targets, color, layer)

    for target in unite_targets:
        tool_bodies = [body for extrude in cast(List[NXOpen.Features.Extrude], target.punches)
                       for body in extrude.GetBodies()]
        # __OwningPart().__CreateUnite - __CreateBoolean builds in the work part whatever part it is called on.
        nx.create_boolean(target.unite.GetBodies()[0], tool_bodies, NXOpen.Features.Feature.BooleanType.Unite)

    pads = _create_pad(unite_targets, color, layer + 6)
    _create_offset_pads(pads, expression, pad_offset_out)

    if is_trim_profile:
        lowers = list(_create_lower(unite_targets, color, layer + 4))
        _create_offset_pads(lowers, "b", pad_offset_out)

    if not create_feature_group:
        return

    for target in unite_targets:
        objects: List[Optional[NXOpen.TaggedObject]] = []
        objects.extend(obj.slug for obj in target.slugs)
        objects.append(target.unite)
        objects.append(target.pad_obj)
        objects.extend(target.unite.GetAllChildren())

        objects.extend(grandchild
                       for feature in target.unite.GetAllChildren()
                       for grandchild in feature.GetAllChildren())

        _create_feature_group("PTF", False, [o for o in objects if o is not None])


def _create_feature_group(name: str, show: bool,
                          objects: Sequence[NXOpen.TaggedObject]) -> NXOpen.Features.FeatureGroup:
    """Static.ProfileTrimAndFormCreateFeatureGroup - UF_MODL_create_set_of_feature, hidden unless show."""
    tag_objects = [obj.Tag for obj in objects]
    hide_result = 1
    if show:
        hide_result = 0
    tag = nx.ufsession_.Modeling.CreateSetOfFeature(name, tag_objects, len(tag_objects), hide_result)
    return cast(NXOpen.Features.FeatureGroup, nx.tagged_object(tag))


def _create_lower(unite_targets: Sequence[_UniteTarget], color: int, layer: int) -> Iterable[_Pad]:
    """Static.ProfileTrimAndFormCreateLower - a lazy generator, like the C# iterator."""
    for unite in unite_targets:
        linked_body = _wave_link_object(unite.unite.GetBodies()[0],
                                        NXOpen.Features.ExtractFaceBuilder.ParentPartType.WorkPart)
        linked_body.SetName("Lower")
        nx.set_color(linked_body.GetBodies()[0], color)
        nx.set_layer(linked_body.GetBodies()[0], layer)
        yield _Pad(linked_body, unite)


def _create_offset_pads(pads: Sequence[_Pad], expression: str, offset_direction: str) -> None:
    """Static.ProfileTrimAndFormCreateOffsetPads - offsets every face of each pad body by expression."""
    work = nx.work_part()
    for pad in pads:
        offset_face_builder = work.Features.CreateOffsetFaceBuilder(None)

        try:
            offset_face_builder.Distance.RightHandSide = expression + ""
            offset_face_builder.Direction = offset_direction == _OFFSET_IN
            face_body_rule1 = work.ScRuleFactory.CreateRuleFaceBody(pad.pad_obj.GetBodies()[0])
            rules1 = [face_body_rule1]
            offset_face_builder.FaceCollector.ReplaceRules(rules1, False)
            offset_face_builder.Commit()
        finally:
            offset_face_builder.Destroy()


def _wave_link_object(body: NXOpen.Body,
                      parent_type: Optional[NXOpen.Features.ExtractFaceBuilder.ParentPartType] = None
                      ) -> NXOpen.Features.ExtractFace:
    """Static.ProfileTrimAndFormWaveLinkObject - an associative body link of body into the work part."""
    if parent_type is None:
        parent_type = NXOpen.Features.ExtractFaceBuilder.ParentPartType.OtherPart

    work = nx.work_part()
    builder = work.BaseFeatures.CreateWaveLinkBuilder(None)

    try:
        builder.ExtractFaceBuilder.ParentPart = NXOpen.Features.ExtractFaceBuilder.ParentPartType.OtherPart
        rules = [work.ScRuleFactory.CreateRuleBodyDumb([body])]
        builder.ExtractFaceBuilder.ExtractBodyCollector.ReplaceRules(rules, False)
        builder.Type = NXOpen.Features.WaveLinkBuilder.Types.BodyLink
        builder.WaveDatumBuilder.Associative = True
        builder.ExtractFaceBuilder.ParentPart = parent_type
        n_x_object1 = builder.Commit()

        if n_x_object1 is None:
            raise Exception("Didnt create anything")

        return cast(NXOpen.Features.ExtractFace, n_x_object1)
    finally:
        builder.Destroy()


def _create_pad(unite_targets: Sequence[_UniteTarget], color: int, layer: int) -> List[_Pad]:
    """Static.ProfileTrimAndFormCreatePad"""
    pads: List[_Pad] = []

    for unite in unite_targets:
        # C# foreach over a struct: unite is a copy, so SetPadObj below never reaches the caller's targets.
        unite = copy.copy(unite)
        body = unite.unite.GetBodies()[0]
        linked_body = _wave_link_object(body, NXOpen.Features.ExtractFaceBuilder.ParentPartType.WorkPart)
        pad = _Pad(linked_body, unite)
        # sql
        linked_body.SetName("Pad")
        nx.set_layer(linked_body.GetBodies()[0], layer)
        nx.set_color(linked_body.GetBodies()[0], color)
        unite.set_pad_obj(linked_body)
        pads.append(_Pad(pad.pad_obj, unite))

    return pads


def _create_punches(unite_targets: Sequence[_UniteTarget], color: int, layer: int) -> None:
    """Static.ProfileTrimAndFormCreatePunches - per slug, extrude its top face's boundary until the target's top
    face. Like the C#, a failing slug prints and leaves its builder and collector undestroyed."""
    work = nx.work_part()
    for unite in unite_targets:
        for slug in unite.slugs:
            try:
                builder = work.Features.CreateExtrudeBuilder(None)
                builder.Section = work.Sections.CreateSection(0, 0, 0)
                builder.Limits.StartExtend.Value.RightHandSide = "-100"
                builder.Section.SetAllowedEntityTypes(NXOpen.Section.AllowTypes.OnlyCurves)
                edge_boundary_rule = work.ScRuleFactory.CreateRuleEdgeBoundary([slug.top_face])
                selection_rule = [edge_boundary_rule]
                builder.Section.AddToSection(selection_rule, slug.top_face, None, None, NXOpen.Point3d(0.0, 0.0, 0.0),
                                             NXOpen.Section.Mode.Create, False)
                builder.Direction = work.Directions.CreateDirection(slug.origin, slug.vector,
                                                                    NXOpen.SmartObject.UpdateOption.AfterModeling)
                sc_collector = work.ScCollectors.CreateCollector()
                rule = work.ScRuleFactory.CreateRuleFaceDumb([slug.top_face])
                sc_collector.ReplaceRules([rule], False)
                builder.Limits.EndExtend.TrimType = NXOpen.GeometricUtilities.Extend.ExtendType.UntilExtended
                builder.Limits.EndExtend.Target = unite.top_most_face
                builder.BooleanOperation.Type = NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Create
                builder.BooleanOperation.SetTargetBodies([slug.top_face.GetBody()])
                feature = builder.CommitFeature()
                builder.Destroy()
                sc_collector.Destroy()
                punch = cast(NXOpen.Features.Extrude, feature)
                punch.SetName("Punch")
                # Feature.__Layer / Feature.__Color - every body of the feature.
                for punch_body in punch.GetBodies():
                    nx.set_layer(punch_body, layer)
                for punch_body in punch.GetBodies():
                    nx.set_color(punch_body, color)
                unite.add_punch(punch)
            except Exception as ex:
                nx.print_exception(ex)


def _create_unite_targets(slugs: Sequence[_SlugObj], color: int, layer: int) -> Iterable[_UniteTarget]:
    """Static.ProfileTrimAndFormCreateUniteTargets - [Obsolete], body commented out: throws."""
    raise NotImplementedError()


def _create_slugs(source: Sequence[Tuple[NXOpen.Vector3d, Set[NXOpen.Curve]]], color: int) -> Iterable[_SlugObj]:
    """Static.ProfileTrimAndFormCreateSlugs - [Obsolete], body commented out: throws, and so ends every run."""
    raise NotImplementedError()


def _make_extrude(group: Iterable[NXOpen.Curve], direction: NXOpen.Direction, right_hand_side: str,
                  left_hand_side: str) -> NXOpen.Features.Extrude:
    """Static.ProfileTrimAndFormMakeExtrude - only the commented-out CreateSlugs/CreateUniteTargets bodies call it."""
    work = nx.work_part()
    extrude_builder = work.Features.CreateExtrudeBuilder(None)

    try:
        extrude_builder.Section = work.Sections.CreateSection(0.0, 0.0, 0.0)
        extrude_builder.BooleanOperation.Type = NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Create
        extrude_builder.Section.SetAllowedEntityTypes(NXOpen.Section.AllowTypes.OnlyCurves)
        extrude_builder.Section.AllowSelfIntersection(True)
        for curve in group:
            curve_dumb_rule = work.ScRuleFactory.CreateRuleBaseCurveDumb([curve])
            rule = [curve_dumb_rule]
            extrude_builder.Section.AddToSection(rule, curve, None, None, NXOpen.Point3d(0.0, 0.0, 0.0),
                                                 NXOpen.Section.Mode.Create, False)

        extrude_builder.Limits.StartExtend.Value.RightHandSide = right_hand_side
        extrude_builder.Limits.EndExtend.Value.RightHandSide = left_hand_side
        extrude_builder.Direction = direction
        extrude_builder.ParentFeatureInternal = False
        return cast(NXOpen.Features.Extrude, extrude_builder.CommitFeature())
    finally:
        extrude_builder.Destroy()


# ---------------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------------

def _unflatten_pairs(directions: Sequence[float], curves: Sequence[NXOpen.Curve],
                     group_sizes: Sequence[int]) -> List[Tuple[NXOpen.Vector3d, Set[NXOpen.Curve]]]:
    """Rebuilds the C# Tuple<Vector3d, ISet<Curve>>[] from the flattened Session.Execute arguments."""
    pairs: List[Tuple[NXOpen.Vector3d, Set[NXOpen.Curve]]] = []
    start = 0
    for index, size in enumerate(group_sizes):
        vector = NXOpen.Vector3d(directions[3 * index], directions[3 * index + 1], directions[3 * index + 2])
        pairs.append((vector, set(curves[start:start + size])))
        start += size
    return pairs


def _curve_start_point(curve: NXOpen.Curve) -> NXOpen.Point3d:
    """Curve.__StartPoint - the point at the start of the parameter range (as WireStartHole.py does it)."""
    evaluator = nx.ufsession_.Eval.Initialize2(curve.Tag)
    limits = nx.ufsession_.Eval.AskLimits(evaluator)
    point = nx.ufsession_.Eval.EvaluateUnitVectors(evaluator, limits[0])[0]
    return NXOpen.Point3d(point[0], point[1], point[2])


def _cross(u: NXOpen.Vector3d, v: NXOpen.Vector3d) -> NXOpen.Vector3d:
    """Vector3d.__Cross"""
    return NXOpen.Vector3d(u.Y * v.Z - u.Z * v.Y, u.Z * v.X - u.X * v.Z, u.X * v.Y - u.Y * v.X)


def _to_matrix3x3(axis_z: NXOpen.Vector3d) -> NXOpen.Matrix3x3:
    """Vector3d.__ToMatrix3x3() - an orientation whose Z is axis_z, X/Y picked off whichever absolute axis is least
    parallel to it."""
    u = NXOpen.Vector3d(0.0, 1.0, 0.0) if not math.fabs(axis_z.X) < math.fabs(axis_z.Y) \
        else NXOpen.Vector3d(1.0, 0.0, 0.0)

    axis_z = nx.unit(axis_z)
    v = nx.unit(_cross(u, axis_z))
    vector = nx.unit(_cross(axis_z, v))
    matrix = NXOpen.Matrix3x3()
    matrix.Xx = v.X
    matrix.Xy = v.Y
    matrix.Xz = v.Z
    matrix.Yx = vector.X
    matrix.Yy = vector.Y
    matrix.Yz = vector.Z
    matrix.Zx = axis_z.X
    matrix.Zy = axis_z.Y
    matrix.Zz = axis_z.Z
    return matrix
