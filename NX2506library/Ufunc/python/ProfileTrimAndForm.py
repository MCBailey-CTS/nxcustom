"""
The profile-trim-and-form UFunc: a standalone Python UFunc (no C# class, 2026-10-29); its menu button runs this
file's main(). It replaced the WinForms ProfileTrimAndForm form and src\\Static\\ProfileTrimAndForm.cs (in git at
5fb0e3c), whose builder this module had ported since 2026-10-21.

The dialog (ProfileTrimAndForm.dlx, tools\\make-dlx.py) is the form's options: Profile Type Trim / Form, for Form the
Form Type (Upper / Lower) and Pad Offset (Outer / Inner), the Curves source (All curves on the layer / Select
curves), the layer (11, 21 ... 241) and Create Feature Group. OK closes it and starts the profile pick
(select_profiles), then the build (create_from_profiles) and the LWR-/UPR-/PAD-PROFILE reference sets
(fill_profile_reference_sets).

The profile pick (SelectCurveGroups) is a loop of single picks with a cue that says what to do and what is picked:
- A curve adds its whole closed profile: a closed circle / ellipse on its own, or the chain of curves it is in (one
  pick takes the chain, through a curve-chain rule). The profile's curves turn white (7) and a datum axis shows the
  direction the profile is built in.
- Picking a datum axis flips that profile's direction; picking a curve of a picked profile drops the profile.
- OK (middle mouse) finishes; Cancel / Back ends the run with nothing built. The axes are deleted and the curves'
  colors put back either way.
- All curves on the layer starts with every non-spline curve on that layer of the work part already picked
  (unblanked), as the form's All Curves did; the pick loop then follows to adjust it.
The cue names what the last pick did (added a circle, a 6-curve chain, flipped, dropped, or why it was refused) and
the title counts the profiles and curves picked so far - the C# showed only the count, in both.

Differences in the pick:
- Python cannot host a UF selection filter proc, so any datum axis can be picked; one that is not a profile's is
  refused with a message, as the filter refused it.
- A multi-curve chain was checked for flatness and then run through CreateBoundedPlane, whose datum plane was left in
  the part and never used. The flatness check stays; the plane is not made.
- A chain with no arc in it was silently ignored by the C#; it still is not picked, but the cue says why.

The C# it ports, member by member:

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
      -> _create_slugs / _create_unite_targets, revived from their commented-out C# (below)
- The form's nested SlugObj / UniteTarget / Pad types -> _SlugObj / _UniteTarget / _Pad

The build was dead in the C#: CreateSlugs, CreateUniteTargets, the SlugObj constructor and UniteTarget.TopMostFace
were commented out and threw NotImplementedException, so every run printed that and built nothing. They were revived
here from the commented-out C# on 2026-10-29 (never run in NX): the slugs extrude each profile from -e to -em, so the
work part needs the strip layout's e / em expressions (and p / b for a trim) - execute checks for them before the pick
and stops with an error box when any is missing. The 500 / 50 / 100 sizes of the unite targets and punches are part
units, as in the C#.

The form's three reference-set blocks (BtnExecute_Click) are fill_profile_reference_sets. NEVER RUN IN NX.

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
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# From the source tree (src\UFuncs) the shared modules are in src\python; deployed, they are beside this file.
_shared_python = os.path.join(os.path.dirname(_here), "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.Features  # noqa: E402
import NXOpen.GeometricUtilities  # noqa: E402

import NXOpen.BlockStyler  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
from tsg_dialog import Dialog, title_with_version  # noqa: E402

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
    """
    ProfileTrimAndForm.SlugObj, from its commented-out constructor (revived 2026-10-29): the slug extrude, its
    direction and profile curves, and its top face - the planar face square to the direction that lies furthest along
    it. (The C# picked it twice: a MaxBy, then a loop that never raised its running maximum and so took the last
    face; the MaxBy is the one kept.)
    """

    def __init__(self, extrude_sp: NXOpen.Features.Extrude, vector: NXOpen.Vector3d,
                 polyline: Set[NXOpen.Curve]) -> None:
        self.slug = extrude_sp
        self.vector = vector
        self.polyline = polyline
        faces = _faces_square_to(extrude_sp.GetBodies()[0], vector)
        if not faces:
            raise RuntimeError("The slug extrude {} has no planar face square to its direction.".format(
                extrude_sp.JournalIdentifier))
        self.top_face = max(faces, key=lambda face: _height_along(_face_point(face), vector))

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
        """UniteTarget.TopMostFace, from its commented-out body (revived 2026-10-29): the unite target's planar face
        square to the slugs' direction that lies furthest along it."""
        vector = self.slugs[0].vector
        faces = _faces_square_to(self.unite.GetBodies()[0], vector)
        if not faces:
            raise RuntimeError("The unite target has no planar face square to the slugs' direction.")
        return max(faces, key=lambda face: _height_along(_face_point(face), vector))

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
    """
    Static.ProfileTrimAndFormCreateUniteTargets, from its commented-out body (revived 2026-10-29): one retainer block
    per slug direction. In a frame whose Z is that direction, the box round every slug's curve ends (and arc
    centers) grown 50 a side in X / Y, at 500 past the highest of them, drawn as four lines (layer 15) and extruded
    0 to 50 along the direction: named UniteTarget, colored and put on layer. A failing direction prints and is
    skipped. The 500 / 50 are part units, as in the C#.
    """
    groups: List[Tuple[NXOpen.Vector3d, List[_SlugObj]]] = []
    for slug in slugs:
        group = next((g for g in groups if nx.vectors_equal(g[0], slug.vector)), None)
        if group is None:
            groups.append((slug.vector, [slug]))
        else:
            group[1].append(slug)

    work = nx.work_part()
    unite_targets: List[_UniteTarget] = []
    for vector, group_slugs in groups:
        try:
            frame = _to_matrix3x3(vector)
            points: List[NXOpen.Point3d] = []
            for slug in group_slugs:
                for curve in slug.polyline:
                    points.append(_curve_start_point(curve))
                    points.append(_curve_end_point(curve))
                    if isinstance(curve, NXOpen.Arc):
                        points.append(curve.CenterPoint)
            mapped = [_to_frame(point, frame) for point in points]

            max_z = max(m[2] for m in mapped) + 500
            min_y = min(m[1] for m in mapped) - 50
            max_y = max(m[1] for m in mapped) + 50
            min_x = min(m[0] for m in mapped) - 50
            max_x = max(m[0] for m in mapped) + 50

            bottom_left = _from_frame(min_x, min_y, max_z, frame)
            top_left = _from_frame(min_x, max_y, max_z, frame)
            bottom_right = _from_frame(max_x, min_y, max_z, frame)
            top_right = _from_frame(max_x, max_y, max_z, frame)

            retainer_lines = [work.Curves.CreateLine(bottom_left, bottom_right),
                              work.Curves.CreateLine(top_left, top_right),
                              work.Curves.CreateLine(top_right, bottom_right),
                              work.Curves.CreateLine(top_left, bottom_left)]
            for line in retainer_lines:
                nx.set_layer(line, 15)

            # The C# read the direction off the first slug's extrude builder - the slug's own direction.
            direction = work.Directions.CreateDirection(bottom_left, vector, NXOpen.SmartObject.UpdateOption.AfterModeling)
            extrude = _make_extrude(cast(List[NXOpen.Curve], retainer_lines), direction, "0", "50")
            for body in extrude.GetBodies():
                nx.set_color(body, color)
                nx.set_layer(body, layer)
            extrude.SetName("UniteTarget")
            unite_targets.append(_UniteTarget(extrude, group_slugs))
        except Exception as ex:
            nx.print_exception(ex)

    return unite_targets


def _create_slugs(source: Sequence[Tuple[NXOpen.Vector3d, Set[NXOpen.Curve]]], color: int) -> Iterable[_SlugObj]:
    """
    Static.ProfileTrimAndFormCreateSlugs, from its commented-out body (revived 2026-10-29): each profile extruded from
    -e to -em along its direction (the strip layout's e / em expressions - see _required_expressions), named
    SlugPTF and colored.
    """
    work = nx.work_part()
    for vector, curves in source:
        direction = work.Directions.CreateDirection(_curve_start_point(next(iter(curves))), vector,
                                                    NXOpen.SmartObject.UpdateOption.AfterModeling)
        slug = _make_extrude(list(curves), direction, "-e", "-em")
        slug.SetName("SlugPTF")
        for body in slug.GetBodies():
            nx.set_color(body, color)
        yield _SlugObj(slug, vector, curves)


def _required_expressions(is_trim: bool) -> List[str]:
    """
    The expressions the build reads from the work part: e / em (the slug limits), p (a trim's pad offset; a form's
    is .5) and b (a trim's lower offset) - a strip layout's, which Clone Strip links into every station layout.
    """
    return ["e", "em"] + (["p", "b"] if is_trim else [])


def missing_expressions(part: NXOpen.BasePart, is_trim: bool) -> List[str]:
    """The _required_expressions part has no expression for."""
    names = {expression.Name for expression in part.Expressions}
    return [name for name in _required_expressions(is_trim) if name not in names]


def _make_extrude(group: Iterable[NXOpen.Curve], direction: NXOpen.Direction, right_hand_side: str,
                  left_hand_side: str) -> NXOpen.Features.Extrude:
    """Static.ProfileTrimAndFormMakeExtrude - the slugs' and unite targets' extrudes."""
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


def _curve_end_point(curve: NXOpen.Curve) -> NXOpen.Point3d:
    """Curve.__EndPoint - the point at the end of the parameter range (as _curve_start_point)."""
    evaluator = nx.ufsession_.Eval.Initialize2(curve.Tag)
    limits = nx.ufsession_.Eval.AskLimits(evaluator)
    point = nx.ufsession_.Eval.EvaluateUnitVectors(evaluator, limits[1])[0]
    return NXOpen.Point3d(point[0], point[1], point[2])


def _faces_square_to(body: NXOpen.Body, vector: NXOpen.Vector3d) -> List[NXOpen.Face]:
    """The body's planar faces whose normal is vector or its reverse."""
    faces: List[NXOpen.Face] = []
    for face in body.GetFaces():
        if face.SolidFaceType != NXOpen.Face.FaceType.Planar:
            continue
        normal = nx.face_normal(face)
        if nx.vectors_equal(normal, vector) or nx.vectors_equal(normal, nx.negate(vector)):
            faces.append(face)
    return faces


def _face_point(face: NXOpen.Face) -> NXOpen.Point3d:
    """A point on a planar face (UF_MODL_ask_face_data's point)."""
    _type, point, _direction, _box, _radius, _rad_data, _norm_dir = nx.ufsession_.Modeling.AskFaceData(face.Tag)
    return NXOpen.Point3d(point[0], point[1], point[2])


def _height_along(point: NXOpen.Point3d, vector: NXOpen.Vector3d) -> float:
    """How far point lies along vector (its Z in a frame whose Z is vector)."""
    v = nx.unit(vector)
    return point.X * v.X + point.Y * v.Y + point.Z * v.Z


def _to_frame(point: NXOpen.Point3d, frame: NXOpen.Matrix3x3) -> Tuple[float, float, float]:
    """__MapCsysToCsys(point, absolute, frame) for a frame at the absolute origin: (x, y, z) in it."""
    return (point.X * frame.Xx + point.Y * frame.Xy + point.Z * frame.Xz,
            point.X * frame.Yx + point.Y * frame.Yy + point.Z * frame.Yz,
            point.X * frame.Zx + point.Y * frame.Zy + point.Z * frame.Zz)


def _from_frame(x: float, y: float, z: float, frame: NXOpen.Matrix3x3) -> NXOpen.Point3d:
    """__MapCsysToCsys(point, frame, absolute) for a frame at the absolute origin."""
    return NXOpen.Point3d(x * frame.Xx + y * frame.Yx + z * frame.Zx,
                          x * frame.Xy + y * frame.Yy + z * frame.Zy,
                          x * frame.Xz + y * frame.Yz + z * frame.Zz)


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


# ---------------------------------------------------------------------------------------------------
# The profile-trim-and-form UFunc: the profile pick, the reference sets and the dialog (2026-10-29)
# ---------------------------------------------------------------------------------------------------

ufunc_name = "profile-trim-and-form"

# NX will not create a dialog from inside another dialog's callback.
_ErrorCannotLaunchDialog = 3520048

ProfileTrim, ProfileForm = "Trim", "Form"
FormUpper, FormLower = "Upper", "Lower"
PadOuter, PadInner = "Outer", "Inner"
CurvesAll, CurvesSelect = "All curves on the layer", "Select curves"
# The form's layer combo box: 11, 21 ... 241.
Layers = [str(i) for i in range(11, 242, 10)]

# NXOpen.Conic (Arc, Ellipse ...) - not in the local stubs.
_Conic: Any = getattr(NXOpen, "Conic")

# The color a picked profile's curves take while picked (the C#'s __Color(7)).
_PickedColor = 7

_Picked = (NXOpen.Selection.Response.ObjectSelected, NXOpen.Selection.Response.ObjectSelectedByName)

_PickHelp = ("Select a curve of a closed profile (a circle, or one curve of a closed chain with an arc in it). "
             "Select a profile's datum axis to flip its direction, or one of its curves to drop it. OK when done.")


class _Profile(object):
    """One picked profile: its curves, their colors before the pick, and the datum axis showing its direction."""

    def __init__(self, curves: List[NXOpen.Curve], axis: NXOpen.DatumAxis) -> None:
        self.curves = curves
        self.colors = {c.Tag: c.Color for c in curves}
        self.axis = axis


class _ProfilePicker(object):
    """ProfileTrimAndForm.SelectCurveGroups: the profiles picked so far and the pick / flip / drop bookkeeping."""

    def __init__(self) -> None:
        self.profiles: List[_Profile] = []

    @property
    def curve_count(self) -> int:
        return sum(len(p.curves) for p in self.profiles)

    def summary(self) -> str:
        return "{} profile(s), {} curve(s) picked".format(len(self.profiles), self.curve_count)

    def profile_of_curve(self, curve: NXOpen.Curve) -> Optional[_Profile]:
        return next((p for p in self.profiles if any(c.Tag == curve.Tag for c in p.curves)), None)

    def profile_of_axis(self, axis: NXOpen.DatumAxis) -> Optional[_Profile]:
        return next((p for p in self.profiles if p.axis.Tag == axis.Tag), None)

    def pick_curve(self, curve: NXOpen.Curve) -> str:
        """Select(curve): drops the profile the curve is in, else adds its profile. Returns what happened."""
        picked = self.profile_of_curve(curve)
        if picked is not None:
            self._drop(picked)
            return "Dropped a {}-curve profile.".format(len(picked.curves))

        chain = _curve_chain(curve)
        if len(chain) == 0:
            return "Could not find the profile that curve is in."
        if len(chain) == 1:
            return self._add_single(chain[0])
        return self._add_chain(chain)

    def flip(self, axis: NXOpen.DatumAxis) -> str:
        """Selected(DatumAxis): the profile's axis is replaced by one pointing the other way."""
        profile = self.profile_of_axis(axis)
        if profile is None:
            return "That datum axis is not a picked profile's - pick one of the axes this pick made."
        part = cast(NXOpen.BasePart, axis.OwningPart)
        profile.axis = _fixed_datum_axis(part, axis.Origin, nx.negate(axis.Direction))
        nx.delete_objects([axis])
        nx.ufsession_.Modeling.Update()
        return "Flipped a {}-curve profile's direction.".format(len(profile.curves))

    def _add_single(self, curve: NXOpen.Curve) -> str:
        """Selected(Curve): a closed circle / ellipse on its own, its axis along its normal at its center."""
        if cast(Any, nx.ufsession_.Modeling).AskCurveClosed(curve.Tag) != 1:
            return "That curve is not closed and is not part of a closed chain - not picked."
        if not isinstance(curve, _Conic):
            return "A single closed curve must be a circle or ellipse - not picked."
        center, x_direction, y_direction = _conic_orientation(curve)
        normal = _cross(x_direction, y_direction)
        axis = _fixed_datum_axis(cast(NXOpen.BasePart, curve.OwningPart), center, normal)
        self._add(_Profile([curve], axis))
        return "Added a closed {}.".format("circle" if isinstance(curve, NXOpen.Arc) else "conic")

    def _add_chain(self, curves: List[NXOpen.Curve]) -> str:
        """Selected(Curve[]): a flat chain of 3+ curves with an arc in it, its axis normal to the chain."""
        if len(curves) < 3:
            return "A chain of {} curves cannot close a profile - not picked.".format(len(curves))

        def chord(c: NXOpen.Curve) -> NXOpen.Vector3d:
            s, e = _curve_start_point(c), _curve_end_point(c)
            return NXOpen.Vector3d(s.X - e.X, s.Y - e.Y, s.Z - e.Z)

        cross_vec = _cross(chord(curves[1]), chord(curves[0]))
        for c in curves[2:]:
            v = chord(c)
            if abs(cross_vec.X * v.X + cross_vec.Y * v.Y + cross_vec.Z * v.Z) >= 0.0001:
                return "That chain's {} curves do not all lie on one plane - not picked.".format(len(curves))

        if not any(isinstance(c, _Conic) for c in curves):
            # The C# returned here without a word.
            return "That {}-curve chain has no arc in it - not picked.".format(len(curves))

        axis = _fixed_datum_axis(cast(NXOpen.BasePart, curves[0].OwningPart), _curve_start_point(curves[0]),
                                 cross_vec)
        self._add(_Profile(curves, axis))
        return "Added a {}-curve chain.".format(len(curves))

    def _add(self, profile: _Profile) -> None:
        self.profiles.append(profile)
        for curve in profile.curves:
            nx.set_color(curve, _PickedColor)

    def _drop(self, profile: _Profile) -> None:
        self._restore(profile)
        nx.delete_objects([profile.axis])
        self.profiles.remove(profile)
        nx.ufsession_.Modeling.Update()

    @staticmethod
    def _restore(profile: _Profile) -> None:
        for curve in profile.curves:
            try:
                nx.set_color(curve, profile.colors[curve.Tag])
            except Exception as ex:
                nx.print_exception(ex)

    def finish(self, keep: bool) -> List[Tuple[NXOpen.Vector3d, Set[NXOpen.Curve]]]:
        """The end of SelectCurveGroups1: each profile's (negated axis direction, curves) when keep, the axes deleted
        and the colors put back either way."""
        pairs: List[Tuple[NXOpen.Vector3d, Set[NXOpen.Curve]]] = []
        for profile in self.profiles:
            if keep:
                pairs.append((nx.negate(profile.axis.Direction), set(profile.curves)))
            try:
                nx.delete_objects([profile.axis])
            except Exception as ex:
                nx.print_exception(ex)
            self._restore(profile)
        self.profiles = []
        return pairs


def _curve_chain(curve: NXOpen.Curve) -> List[NXOpen.Curve]:
    """Select(curve)'s collector: the curves of the chain curve is in (a curve-chain rule, gap .01)."""
    part = cast(NXOpen.BasePart, curve.OwningPart)
    collector = part.ScCollectors.CreateCollector()
    try:
        rule = cast(Any, part.ScRuleFactory).CreateRuleCurveChain(curve, curve, True, .01)
        collector.ReplaceRules([rule], False)
        return [cast(NXOpen.Curve, o) for o in cast(Any, collector).GetObjects() if isinstance(o, NXOpen.Curve)]
    finally:
        collector.Destroy()


def _conic_orientation(conic: Any) -> Tuple[NXOpen.Point3d, NXOpen.Vector3d, NXOpen.Vector3d]:
    """Conic.GetOrientation's out parameters (center, x direction, y direction)."""
    result = cast(Any, conic).GetOrientation()
    return result[0], result[1], result[2]


def _fixed_datum_axis(part: NXOpen.BasePart, origin: NXOpen.Point3d, vector: NXOpen.Vector3d) -> NXOpen.DatumAxis:
    """BasePart.__CreateFixedDatumAxis(origin, vector): an axis from origin to origin + vector."""
    return cast(Any, part).Datums.CreateFixedDatumAxis(origin, NXOpen.Point3d(origin.X + vector.X, origin.Y + vector.Y,
                                                                   origin.Z + vector.Z))


def select_profiles(pre_select: bool, layer: int) -> List[Tuple[NXOpen.Vector3d, Set[NXOpen.Curve]]]:
    """
    SelectCurveGroups.SelectCurveGroups1: the pick loop (see the module docstring). pre_select first picks every
    non-spline curve on layer in the work part, unblanking it. Returns [] on Cancel / Back or with nothing picked.
    """
    picker = _ProfilePicker()
    status = ""

    if pre_select:
        work = nx.work_part()
        for curve in list(work.Curves):
            try:
                if curve.Layer != layer or isinstance(curve, NXOpen.Spline) or picker.profile_of_curve(curve):
                    continue
                if curve.IsBlanked:
                    curve.Unblank()
                picker.pick_curve(curve)
            except Exception as ex:
                nx.print_exception(ex)
        if len(picker.profiles) == 0:
            picker.finish(False)
            nx.print_("Profile Trim and Form: did not find any closed profiles on layer {}.".format(layer))
            return []
        status = "Picked {} profile(s) on layer {}.".format(len(picker.profiles), layer)

    c: Any = NXOpen.UF.UFConstants
    masks = [NXOpen.Selection.MaskTriple(c.UF_line_type, 0, 0),
             NXOpen.Selection.MaskTriple(c.UF_circle_type, 0, 0),
             NXOpen.Selection.MaskTriple(c.UF_conic_type, 0, 0),
             NXOpen.Selection.MaskTriple(c.UF_spline_type, 0, 0),
             NXOpen.Selection.MaskTriple(c.UF_datum_axis_type, 0, 0)]

    keep = False
    try:
        while True:
            message = "{} {}".format(status, _PickHelp).strip()
            title = "Profile Trim and Form - {}".format(picker.summary())
            result: Any = NXOpen.UI.GetUI().SelectionManager.SelectTaggedObject(
                message, title, NXOpen.Selection.SelectionScope.WorkPart,
                NXOpen.Selection.SelectionAction.ClearAndEnableSpecific, False, False, masks)
            response, obj = result[0], result[1]

            if response in _Picked:
                if isinstance(obj, NXOpen.DatumAxis):
                    status = picker.flip(obj)
                elif isinstance(obj, NXOpen.Curve):
                    status = picker.pick_curve(obj)
                else:
                    status = "Pick a curve or a profile's datum axis."
                continue

            if response == NXOpen.Selection.Response.Ok:
                if len(picker.profiles) == 0:
                    status = "Nothing is picked yet."
                    continue
                keep = True
            break
    finally:
        pairs = picker.finish(keep)

    if not keep:
        nx.mark_cancelled("the Profile Trim and Form profile pick")
    return pairs


def create_from_profiles(pairs: Sequence[Tuple[NXOpen.Vector3d, Set[NXOpen.Curve]]], layer: int, is_trim: bool,
                         is_outer: bool, is_upper: bool, create_feature_group: bool) -> None:
    """ProfileTrimAndForm.create on the picked profiles (flattened as the C# caller did)."""
    directions: List[float] = []
    curves: List[NXOpen.Curve] = []
    sizes: List[int] = []
    for vector, group in pairs:
        directions.extend([vector.X, vector.Y, vector.Z])
        curves.extend(group)
        sizes.append(len(group))
    ProfileTrimAndForm.create(directions, curves, sizes, layer, is_trim, is_outer, is_upper, create_feature_group)


def fill_profile_reference_sets() -> None:
    """
    The rest of ProfileTrimAndFormExecute: the display part's LWR-PROFILE (the LOWER extract faces' offset bodies),
    UPR-PROFILE (the UNITETARGET extrudes' bodies) and PAD-PROFILE (the PAD extract faces' offset bodies), each in
    its own try.
    """
    display = nx.display_part()
    features = list(display.Features.GetFeatures())

    def offset_bodies(name: str) -> List[NXOpen.NXObject]:
        bodies: List[NXOpen.NXObject] = []
        for feature in features:
            if feature.Name.upper() != name or not isinstance(feature, NXOpen.Features.ExtractFace):
                continue
            child = feature.GetAllChildren()[0]
            if isinstance(child, NXOpen.Features.OffsetFace):
                bodies.extend(child.GetBodies())
        return bodies

    def extrude_bodies(name: str) -> List[NXOpen.NXObject]:
        bodies: List[NXOpen.NXObject] = []
        for feature in features:
            if feature.Name.upper() == name and isinstance(feature, NXOpen.Features.Extrude):
                bodies.extend(feature.GetBodies())
        return bodies

    for refset_name, objects in (("LWR-PROFILE", lambda: offset_bodies("LOWER")),
                                 ("UPR-PROFILE", lambda: extrude_bodies("UNITETARGET")),
                                 ("PAD-PROFILE", lambda: offset_bodies("PAD"))):
        try:
            refset = nx.find_or_create_reference_set(display, refset_name)
            refset.AddObjectsToReferenceSet(objects())
        except Exception as ex:
            nx.print_exception(ex)


class _ProfileTrimAndFormDialog(Dialog):
    """ProfileTrimAndForm.dlx: the form's Profile Type, Form Type, Pad Offset, Curve Selection, layer and feature
    group boxes."""

    dlx_name = "ProfileTrimAndForm.dlx"

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__()
        # Captured in ok(): the blocks are gone once Launch returns.
        self.is_trim = True
        self.is_upper = True
        self.is_outer = False
        self.pre_select = True
        self.layer = 11
        self.feature_group = True

    def shown(self) -> None:
        # MainForm_Load: Trim, Upper, Inner, All Curves, layer 11, Create Feature Group - every time.
        self.block("profile_type").ValueAsString = ProfileTrim
        self.block("form_type").ValueAsString = FormUpper
        self.block("pad_offset").ValueAsString = PadInner
        self.block("curves").ValueAsString = CurvesAll
        self.block("layer").ValueAsString = Layers[0]
        self.block("feature_group").Value = True
        self._show_form()

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        if block == self.block("profile_type"):
            self._show_form()
        elif block == self.block("curves"):
            self._show_form()

    def ok(self) -> bool:
        self.is_trim = str(self.block("profile_type").ValueAsString) == ProfileTrim
        self.is_upper = str(self.block("form_type").ValueAsString) == FormUpper
        self.is_outer = str(self.block("pad_offset").ValueAsString) == PadOuter
        self.pre_select = str(self.block("curves").ValueAsString) == CurvesAll
        self.layer = int(str(self.block("layer").ValueAsString))
        self.feature_group = bool(self.block("feature_group").Value)
        return True

    def _show_form(self) -> None:
        """RdoTrim_CheckedChanged: the Form Type group only for Form."""
        form = str(self.block("profile_type").ValueAsString) == ProfileForm
        self.block("form_type").Enable = form
        self.block("pad_offset").Enable = form


def execute() -> None:
    if nx.work_part() is None:
        nx.show_error("Profile Trim and Form needs a work part.")
        return

    title = title_with_version("Profile Trim and Form")
    dialog: Optional[_ProfileTrimAndFormDialog] = None
    try:
        dialog = _ProfileTrimAndFormDialog(title)
        if not dialog.run():
            return
    except NXOpen.NXException as ex:
        if ex.ErrorCode != _ErrorCannotLaunchDialog:
            raise
        nx.print_exception(ex)
        nx.show_error("NX would not open the {} dialog (error {} - it will not create a dialog from inside a "
                      "callback).\n\nTry running it from File -> Execute -> NX Open rather than from a menu or "
                      "toolbar button.".format(title, _ErrorCannotLaunchDialog))
        return

    missing = missing_expressions(nx.work_part(), dialog.is_trim)
    if missing:
        nx.show_error("Profile Trim and Form builds from the strip layout's expressions, and the work part {} has no "
                      "{}.\n\nMake the station layout (or the strip) the work part, or add the expressions.".format(
                          nx.work_part().Leaf, " / ".join(missing)))
        return

    try:
        pairs = select_profiles(dialog.pre_select, dialog.layer)
        if not pairs:
            return
        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Profile Trim and Form")
        # As in the C#: a build failure skips the reference sets.
        create_from_profiles(pairs, dialog.layer, dialog.is_trim, dialog.is_outer, dialog.is_upper,
                             dialog.feature_group)
        fill_profile_reference_sets()
    finally:
        nx.prompt("Profile Trim and Form exited")


def main() -> None:
    """The profile-trim-and-form UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
