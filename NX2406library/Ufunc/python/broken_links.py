"""
Relinking broken LINKED_BODY features (2026-11-06), shared by repair-broken-links and mirror-merlin.

UF_WAVE_ask_broken_link_source_part names the part a broken link came from (nothing when the source geometry is gone or
the part is not loaded), but not the body, and the link's own body was used up by its boolean: GetBodies() returns the
target. What is left of it is the cut, so the source is the one solid body, in an occurrence of that part under the
display part, with every corner of the boolean's faces on its surface. The part is matched by its leaf, not its folder,
so a copied job's links, which still name the old folder, find the copy.

The corners must stay exact: rounded, they fall to either side of the surface. The bodies are tested in their own part
(the corners moved into it), since a strip's LWR-3D is not in the BODY its layout is on and has no occurrence there, so
finding a source changes nothing. A face a later feature moved, or an Offset / Delete / Move Face on the link itself,
takes corners off the source: such a link has no exact match and is left for the user, with the best body named.

relink() points the feature at the source with UF_WAVE_set_link_data, so it keeps its place in the feature order, and
updates. It undoes its own change when the update fails, the link stays broken or the part's volume moves: a relink is
meant to restore the link, not to change the part. A feature built straight on the link - a Chamfer on the cut's edge,
an Offset Face - makes NX refuse: the relinked body has new edges and faces, so the feature has lost its own. The link
relinks with it suppressed and the volume comes back exactly, but unsuppressing it is refused too (006311-010, 7 links,
2026-11-06). Such a feature has to be reselected by hand, so the reason names it.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple, Union, cast

import NXOpen
import NXOpen.Assemblies
import NXOpen.Features

import tsg_nx as nx

# UF_MODL_ask_point_containment: the point is on the body's surface.
_OnBoundary = 3

# The fewest corners that say which body a cut came from: a round cut has too few.
MinimumCorners = 3

# The booleans a link feeds whose faces lie on the link's body.
_CutFeatures = ("SUBTRACT", "INTERSECT")

# How far a part's volume may move, as a fraction, and still be the same part (mass properties repeat to about 1e-7).
_VolumeTolerance = 1e-6


class Source(NamedTuple):
    """Where a broken link goes: the linking part's occurrence, the source's occurrence and its prototype body."""
    component: NXOpen.Assemblies.Component
    occurrence: NXOpen.Assemblies.Component
    body: NXOpen.Body


def is_broken(feature: NXOpen.Features.Feature) -> bool:
    """An unsuppressed LINKED_BODY that is broken."""
    return feature.FeatureType == "LINKED_BODY" and not feature.Suppressed and nx.is_link_broken(feature)


def occurrences_by_leaf(top: NXOpen.BasePart) -> Dict[str, List[NXOpen.Assemblies.Component]]:
    """Every loaded, unsuppressed occurrence under top, by its part's lower case leaf."""
    occurrences: Dict[str, List[NXOpen.Assemblies.Component]] = {}
    root = nx.root_component(top)
    if root is not None:
        for occurrence in nx.descendants(root, include_root=False):
            occurrences.setdefault(nx.prototype(occurrence).Leaf.lower(), []).append(occurrence)
    return occurrences


def cut_corners(feature: NXOpen.Features.Feature, component: NXOpen.Assemblies.Component) -> List[NXOpen.Point3d]:
    """The corners, in the display part, of the faces of the booleans a link of component's part feeds."""
    corners: Dict[Tuple[float, float, float], NXOpen.Point3d] = {}
    for child in feature.GetChildren():
        if child.FeatureType not in _CutFeatures:
            continue
        for face in child.GetFaces():
            occurrence = component.FindOccurrence(face)
            if not isinstance(occurrence, NXOpen.Face):
                continue
            for edge in occurrence.GetEdges():
                for corner in edge.GetVertices():
                    # Only to drop the repeats: the points themselves stay exact.
                    corners[(round(corner.X, 7), round(corner.Y, 7), round(corner.Z, 7))] = corner
    return list(corners.values())


def _in_part(occurrence: NXOpen.Assemblies.Component, corners: Sequence[NXOpen.Point3d]) -> List[List[float]]:
    """corners, in the display part, in occurrence's part: its own axes and units. GetPosition is the display part's."""
    origin, m = occurrence.GetPosition()
    display, part = nx.display_part(), nx.prototype(occurrence)
    scale = 1.0
    if part.PartUnits != display.PartUnits:
        scale = 25.4 if part.PartUnits == NXOpen.BasePart.Units.Millimeters else 1.0 / 25.4
    moved = []
    for c in corners:
        x, y, z = c.X - origin.X, c.Y - origin.Y, c.Z - origin.Z
        moved.append([scale * (m.Xx * x + m.Xy * y + m.Xz * z), scale * (m.Yx * x + m.Yy * y + m.Yz * z),
                      scale * (m.Zx * x + m.Zy * y + m.Zz * z)])
    return moved


def _corners_on(occurrence: NXOpen.Assemblies.Component,
                corners: Sequence[NXOpen.Point3d]) -> List[Tuple[int, NXOpen.Body]]:
    """Each solid body of occurrence's part, with how many corners are on its surface."""
    points = _in_part(occurrence, corners)
    counts = []
    for body in cast(NXOpen.Part, nx.prototype(occurrence)).Bodies:
        if body.IsSolidBody:
            # A point on the body's surface is inside its box: only those are asked (a layout holds ~200 bodies, and
            # AskPointContainment costs ~3 ms a call).
            box = _box_of(body)
            inside = [p for p in points if all(box[i] - _BoxSlack <= p[i] <= box[i + 3] + _BoxSlack for i in range(3))]
            counts.append((sum(1 for p in inside if nx.ufsession_.Modeling.AskPointContainment(p, body.Tag)
                               == _OnBoundary), body))
    return counts


_BoxSlack = .01
_boxes: Dict[int, List[float]] = {}


def _box_of(body: NXOpen.Body) -> List[float]:
    """The body's box (min x, y, z, max x, y, z) in its part, kept by tag: a link's source bodies do not change."""
    box = _boxes.get(body.Tag)
    if box is None:
        box = list(cast(Any, nx.ufsession_.ModlGeneral).AskBoundingBox(body.Tag))
        _boxes[body.Tag] = box
    return box


def _reference_sets_of(part: NXOpen.BasePart, body: NXOpen.Body) -> List[str]:
    return sorted(r.Name for r in part.GetAllReferenceSets() if body.Tag in {m.Tag for m in r.AskAllDirectMembers()})


def find_source(feature: NXOpen.Features.Feature, components: Sequence[NXOpen.Assemblies.Component],
                by_leaf: Dict[str, List[NXOpen.Assemblies.Component]]) -> Union[Source, str]:
    """
    The Source of a broken link of the part components are occurrences of, or why there is none. The cut is only on the
    source from the occurrence the link was made in, so each occurrence is tried. Changes nothing.
    """
    path = nx.ufsession_.Wave.AskBrokenLinkSourcePart(feature.Tag)[0]
    if not path:
        return "NX cannot name its source part"
    leaf = os.path.splitext(os.path.basename(path))[0]
    sources = by_leaf.get(leaf.lower(), [])
    if not sources:
        return "its source {} is not in the assembly".format(path)

    exact: List[Source] = []
    best: Optional[Tuple[int, int, NXOpen.Assemblies.Component, NXOpen.Body]] = None
    for component in components:
        corners = cut_corners(feature, component)
        if len(corners) < MinimumCorners:
            continue
        for occurrence in sources:
            if occurrence.Tag == component.Tag:
                continue
            for count, body in _corners_on(occurrence, corners):
                if count == len(corners):
                    exact.append(Source(component, occurrence, body))
                elif count > 0 and (best is None or count * best[1] > best[0] * len(corners)):
                    best = (count, len(corners), occurrence, body)

    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return "{} bodies of {} fit its cut".format(len(exact), leaf)
    if best is None:
        return "no body of {} touches its cut, or the cut has too few corners".format(leaf)
    names = _reference_sets_of(nx.prototype(best[2]), best[3])
    return "no body of {} fits its cut; the closest is {} with {} of {} corners".format(
        leaf, ", ".join(names) or "body {}".format(best[3].Tag), best[0], best[1])


def solid_volume(part: NXOpen.BasePart) -> float:
    """The volume of part's solid bodies, in the units AskMassProps3d gives."""
    total = 0.0
    for body in cast(NXOpen.Part, part).Bodies:
        if body.IsSolidBody:
            total += nx.ufsession_.Modeling.AskMassProps3d([body.Tag], 1, 1, 1, 1.0, 1, [0.99] + [0.0] * 10)[0][1]
    return total


def relink(feature: NXOpen.Features.Feature, source: Source) -> Optional[str]:
    """
    Points feature at source and updates, with source's component left the work component (the caller puts the work
    part back). The transform goes from the source's occurrence to the linking one and lives in the linking part
    (UF_SO_create_xform_assy_ctxt). Returns None, or why the relink was undone.
    """
    part = nx.prototype(source.component)
    volume = solid_volume(part)
    mark = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "Relink")
    reason: Optional[str] = None
    try:
        nx.set_work_component(source.component)
        xform = nx.ufsession_.So.CreateXformAssyCtxt(feature.Tag, source.occurrence.Tag, source.component.Tag)
        nx.ufsession_.Wave.SetLinkData(feature.Tag, source.body.Tag, xform, False)
        nx.ufsession_.Modeling.Update()
        after = solid_volume(part)
        if nx.is_link_broken(feature):
            reason = "the link stayed broken"
        elif abs(after - volume) > _VolumeTolerance * max(abs(volume), 1.0):
            reason = "the part's volume would go from {:.4f} to {:.4f}".format(volume, after)
    except NXOpen.NXException as ex:
        built_on = [c.GetFeatureName() for c in feature.GetChildren() if c.FeatureType not in _CutFeatures]
        reason = "NX refused it ({}){}".format(ex, ": {} on the link would not rebuild".format(", ".join(built_on))
                                               if built_on else "")
    if reason is not None:
        nx.session_.UndoToMark(mark, None)
    return reason
