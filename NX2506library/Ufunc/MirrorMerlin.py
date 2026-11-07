"""
The mirror-merlin UFunc: a new detail that is the mirror image of a DYNAMIC BLOCK detail through the display part's
absolute XZ plane (Y = 0). The original is left alone, but for its broken links, below. Its menu button runs this file's
main().

Pick the detail components (several are built one after the other). For each one:
  - Each broken LINKED_BODY of the source is relinked first (2026-11-06, broken_links, shared with
    repair-broken-links), so the steps below can read it like any other link. The feature keeps its place in the order.
    One with no exact match, or whose relink NX refuses or that would change the source's volume, is listed, stays
    broken and is not carried over.
  - A new block, the size of the source's DYNAMIC BLOCK, is built in the assembly that holds the source, promoted to
    mirror-merlin-{n}.prt beside that assembly and set up like any Merlin block (Nine99._set_up_as_merlin_block):
    CSPC / GM Tool Number, re-based onto its block, station expressions, BODY, DYNAMIC BLOCK, SUBTOOL on hidden layer
    15, the AutoSize UDO, BODY up the assemblies above it. MATERIAL and DETAIL NAME and the station expressions' values
    (AddX, Burnout, ...) are copied from the source, DESCRIPTION is the block's size, and the body and side face colors
    follow the source's, the -Y and +Y sides swapped.
  - Each chamfer on the block's own edges is made again on the mirrored edge, with its size and face color, in the same
    place in the feature order: after the SUBTOOL, so that stays square, and before the fasteners' cuts. The edge a
    chamfer was built on is gone (NX refuses to read it), so it is found from the chamfer's face: the face's normal
    says which two block axes it leans between, and its corners which end of each. That is a block edge only if the
    face lies within the chamfer's size of both sides. An unequal chamfer (the face reaches further along one side than
    the other) or one elsewhere, such as on a pocket, is left out. The expressions only give the size: a chamfer can
    hold one, or offset, offset and angle. Never read one through CreateChamferBuilder(feature): that is what adds them.
  - Each Offset Face and Edge Blend is made again, read from the feature's faces and expression, never a builder. One
    on the block or its SUBTOOL goes in after the chamfers and before the cuts, offsets first: a later cut can run
    through what an offset added. An offset moves whole block sides, which is found from each face being the outermost
    on its side (so stacked offsets of one side work). A blend's edges are found from its faces: a cylinder's sharp edge
    is the straight edge along its axis inside its box, a torus's the curved edge with both ends inside it.
    One on the faces of a cut (a pocket's rim, a hole opened up) goes in after the subtracts, and needs that cut: the
    face it moved is looked for at the mirrored spot, the offset away. With the cut not carried over, it is left out.
  - Each child (fasteners, keys) is added to the new part on the same library part, at its mirrored position, with
    the source's name, layer and reference set, and in BODY when the source's is. A child that is a dynamic block
    detail itself is left out: it would need mirroring too.
  - Each LINKED_BODY of the source that comes from one of its children is made again: the same body of the new child
    (a SHORT-TAP, a CBORE_BLIND, ...) is wave-linked into the new part and subtracted from its DYNAMIC BLOCK.
  - Each LINKED_BODY that comes from a neighbour - a part beside the source in the same assembly, such as a key, an
    ejector pin or a pilot - brings that neighbour across. The same part is added to that assembly at its mirrored
    position, with the source's name, layer, reference set and reference set membership, and the same body (so the same
    SUBTOOL) is linked into the new part and subtracted. The link's source occurrence is what says which neighbour: a
    part can sit beside the detail many times. A neighbour already at that spot is used, not added again, so details
    that share a key share its mirror. A neighbour that is a dynamic block detail itself is not brought across: its
    link is treated like one from outside the assembly, below.

The mirror. A reflection turns a right-handed part left-handed, and NX places a component by a rigid move only, so
the reflection is split in two: the new component's position is the source's reflected and then flipped across its
own block (X along the mirrored X, Y against the mirrored Y, the origin W along the mirrored Y), and what is inside
the new part is flipped back: a source point (a, b, c) in block axes is (a, W - b, c) in the new part. The block is a
box, so it needs no flip, and a block square to the assembly stays square to it with its Length and Width.
A child is placed the same way, with its own Y turned back over (X and Z mirrored, Y = Z x X): a fastener is round
about its Z, so it is the true mirror image. A child that is not symmetric about its own XZ plane cannot be: the
library part is shared, not mirrored.
A neighbour is placed the same way but its origin can be anywhere (a key's is on a corner), so it is turned over across
the middle of the linked body, along the part axis its corners are most alike across (Y first): that keeps a key's
counterbored side down, and is the true mirror image of a body that is symmetric across that plane.

Everything is worked out through UF_CSYS_map_point (source -> root -> holder), so a station that is moved, turned or
upside down in the assembly needs nothing of its own.

  - Each LINKED_BODY from a strip or layout - its LWR-3D or LWR-PROFILE - is made again the way the Merlin UFuncs do it
    (2026-11-06): the layout goes on the reference set holding the body, the body is linked into the new part and
    subtracted, and the layout goes back. The die is symmetric across Y = 0, so the new detail's cut comes off the far
    side of the same body. One that is not symmetric there has nothing to cut, or cuts the wrong shape.
    A strip or layout counts wherever it is, so a Strip held under the source's own assembly does too (2026-11-06): its
    Empty occurrence there cannot be linked from, so the same layout at the same spot under the top Strip is used.
    One the source intersects its block with is intersected again, not subtracted, the Intersect then counting as carried
    over: that link is what shapes the detail, and a subtract would throw away the side the fasteners are in. It is a
    mirror body link, not a plain one: a die that is not symmetric there would leave the wrong shape, or next to nothing.
  - Each LINKED_BODY from a detail beside the source, or from outside the assembly and not a strip or layout, is made
    again as a mirror body link across the display part's Y = 0, and subtracted: that detail is not mirrored, so a
    plain link would cut the shape from the source's side. The new detail's cut stays tied to the original, not to any
    mirror of it made later. The mirror plane is a fixed datum plane on layer 96 of the new part, one per link.
  - Each Extrude that cuts the block (2026-11-07) is made again as a subtract, in the source's feature order with the
    links: one with its own Subtract into the block (a Create extrude, then a Subtract) as well as one that subtracts
    itself. Its section's lines and arcs are made again exactly at the mirrored spot, a spline through points taken
    along it (Eval points over the spline's own parameter range: Python's UF.Modeling has no AskCurveProps); the
    direction is mirrored, and the limits, offset and draft copied. It is read through
    CreateExtrudeBuilder, under an undo mark that is undone if the part ends up modified: no source part tried was. One
    that is suppressed, does not end at distances, unites, intersects or makes a body of its own is left out.
  - All these links are made in the source's feature order (2026-11-06), Linked Body by Linked Body: the children and
    neighbours are placed first, then the links run by each source link's Timestamp. They are subtracted together in
    one Subtract after the last (2026-11-07: one Commit costs about what one tool's does), each on its own only if NX
    refuses the lot; an Intersect is still made in its place. Chamfers and the block's offsets and blends still go in
    before them and the cuts' offsets and blends after them, wherever the source has them.
  - A strip's or layout's reference set changed for a far link is put back once, at the end of the run (2026-11-07):
    each switch at the top costs ~0.2 s, and one set serves link after link.
  - The Information window gets only what went wrong: failures and links that stay broken. Each detail's summary, its
    "not carried over" list, its relinks and the picks with no DYNAMIC BLOCK (a window pick's fasteners) go to the
    syslog (2026-11-07).
  - A child that is not loaded (a fastener on Empty often is not) is opened first, since its links cannot be read
    otherwise. One that will not open is an error.

Left out: every other feature of the source - a neighbour's own fastener's links,
a blend or offset on a cut that was not carried over, or with more than one size, tapers, text. The new detail is the
block with its chamfers, offsets and blends and its fasteners' and neighbours' cuts, and the listing window names what
was not carried over.
Nothing is saved. One visible undo mark, "Mirror Merlin", covers the run.

Speed (2026-11-06, from a profiled run on 006356-010: 63% of it was SetDisplay, the -000 about 1.5 s a time). run() reads
every picked detail first, with the display part left on top, then builds them all without going back to it between
details, all of it under nx.suppress_display. A source is read without being displayed: GetPosition on a part's own
children is in that part's coordinates whatever is displayed (read on a mirror that sits flipped under the -000).
Batch tested the same day on ten of 006356-010's details: volumes, face counts and errors as before. Not yet run with graphics.

Progress window (2026-11-06): once the details are picked, progress_window.ProgressWindow (ProgressWindow.ps1, Auto
Design's and Export Strip's; bottom right, out of the way of the end of run Error box) lists each detail, its steps and
each link as it is made, then how many were built and the time. It stays open after the run until closed.

Tested 2026-11-06 in a batch NX 2306 on build(), on made-up assemblies with library fasteners: a detail under the top
assembly, under a station turned 90 degrees, under one flipped 180, and turned 30 degrees in its station. Volume, centre
of mass, block corners and the fasteners' bodies all came out the exact reflection. Run the same day through main() in
NX on 006066-010's Window1-blank-2 in upd01: 12 children, 12 subtracts, the AutoSize UDO on, and the source's 4 chamfers
and one outside link left out, which is the 12.7 cu in the new detail has over its source. The chamfers were added after
that run, batch tested the same day on lopsided chamfers (sizes mixed, one feature on two edges); not yet built on a
real job's detail, though the reader was run on real ones. Neighbours were added after that, batch tested the same day
on a metric key with its origin on a corner in the same four assemblies, a second mirror sharing it, then run through
main() on six details of 006311-010's lad02: 18 keys, pins and pilots brought across, no errors.
Offsets and blends came after that, batch tested the same day in those assemblies: a block side, a block corner, and
a pocket floor, a hole and a pocket rim on cuts. Not yet built on a real job's detail.
Mirrored far links came after that, batch tested the same day in the turned, flipped and angled assemblies: a lopsided
body in a Layout under a Strip assembly, on Empty, came out the exact reflection and the Layout went back to Empty.
Run the same day on 006311-010-210: the LWR-3D link built. Links from a detail beside the source and the loading of
unloaded children came after that, batch tested the same day: a detail's SUBTOOL in all four assemblies, and the SHCS
closed before the read.
Feature order, plain layout links and the broken link repair came after that, batch tested the same day on the job's own
006311-010-239 (not saved): Linked Body(16) relinked, the feature lists alike link by link, same volume and 78 faces.
"""

from __future__ import annotations

import math
import os
import re
import sys
import time
from functools import partial
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence, Set, Tuple, Union, cast

# Session.Execute does not put the script's folder on sys.path, so the shared modules would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# The shared modules are in the python folder beside this file (src\UFuncs\python; deployed, Ufunc\python).
_shared_python = os.path.join(_here, "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.Features  # noqa: E402

import tsg_nx as nx  # noqa: E402
import PointComponent as merlin  # noqa: E402
import DrawDie as drawdie  # noqa: E402
import SplitForm as splitform  # noqa: E402
import Nine99 as nine99  # noqa: E402
import broken_links  # noqa: E402
import progress_window  # noqa: E402
from tsg_dialog import title_with_version  # noqa: E402

ufunc_name = "mirror-merlin"

PartName = "mirror-merlin"

_DynamicBlockName = "DYNAMIC BLOCK"
_RefsetBody = "BODY"
_RefsetEmpty = "Empty"

# Merlin's working layer during subtracts.
_SubtractLayer = 96

# The expressions setup_station_expressions makes, whose values the mirrored detail keeps.
_StationExpressions = ("AddX", "AddY", "AddZ", "Burnout", "Grind", "GrindTolerance", "BurnDir")

# The features a mirrored detail has of its own: the fastener links and their subtracts are made again.
_RebuiltFeatures = ("LINKED_BODY", "SUBTRACT")


# The progress window while run() is going, else None.
_progress: Optional[progress_window.ProgressWindow] = None


def _step(message: str) -> None:
    """A line in the progress window and the syslog."""
    nx.syslog("Mirror Merlin: {}".format(message))
    if _progress is not None:
        _progress.write_line(message)


class _Link(NamedTuple):
    """A child's body that the source links in, the link's name and its Timestamp in the source."""
    body: NXOpen.Body
    name: str
    order: int


class _Child(NamedTuple):
    """One child of the source, read while the source is displayed. The frame is in the source part."""
    prototype: NXOpen.BasePart
    name: str
    reference_set: str
    layer: int
    origin: NXOpen.Point3d
    x_axis: NXOpen.Vector3d
    y_axis: NXOpen.Vector3d
    reference_sets: Set[str]
    links: List[_Link]


class _Neighbour(NamedTuple):
    """A part beside the source that the source links from. The frame is its mirrored one, in the display part."""
    prototype: NXOpen.BasePart
    name: str
    reference_set: str
    layer: int
    origin: NXOpen.Point3d
    x_axis: NXOpen.Vector3d
    y_axis: NXOpen.Vector3d
    reference_sets: Set[str]
    links: List[_Link]


class _FarLink(NamedTuple):
    """A far link (_read_far_links): the occurrence under the display part it comes from, its body, name and Timestamp."""
    occurrence: NXOpen.Assemblies.Component
    body: NXOpen.Body
    name: str
    order: int
    intersect: int  # The tag of the Intersect the link is the tool of, 0 for a subtract.


class _Block(NamedTuple):
    """The source's DYNAMIC BLOCK in its own part: its corner, unit axes and lengths along them."""
    origin: NXOpen.Point3d
    x_axis: NXOpen.Vector3d
    y_axis: NXOpen.Vector3d
    z_axis: NXOpen.Vector3d
    length: float
    width: float
    height: float

    def local(self, p: NXOpen.Point3d) -> Tuple[float, float, float]:
        """A source part point in block axes."""
        o = self.origin
        offset = NXOpen.Vector3d(p.X - o.X, p.Y - o.Y, p.Z - o.Z)
        return _dot(offset, self.x_axis), _dot(offset, self.y_axis), _dot(offset, self.z_axis)

    def point(self, p: NXOpen.Point3d) -> NXOpen.Point3d:
        """A source part point in the new part: (a, b, c) in block axes to (a, W - b, c)."""
        a, b, c = self.local(p)
        return NXOpen.Point3d(a, self.width - b, c)

    def vector(self, v: NXOpen.Vector3d) -> NXOpen.Vector3d:
        """A source part direction in the new part."""
        return NXOpen.Vector3d(_dot(v, self.x_axis), -_dot(v, self.y_axis), _dot(v, self.z_axis))


class _Chamfer(NamedTuple):
    """A symmetric chamfer on block edges. An edge is a sign per block axis: 0 along the edge, -1 / 1 at that end."""
    offset: float
    edges: List[Tuple[int, int, int]]
    color: int


class _SideOffset(NamedTuple):
    """An Offset Face of whole block sides, (axis, sign) as in _Source.side_colors. Distance is outward from the part."""
    distance: float
    sides: List[Tuple[int, int]]
    on_subtool: bool
    label: str


class _CutFace(NamedTuple):
    """A face an offset left, in the new part: a point on it and its normal, or on its axis and the axis, its radius."""
    is_plane: bool
    point: NXOpen.Point3d
    direction: NXOpen.Vector3d
    radius: float


class _CutOffset(NamedTuple):
    """An Offset Face of a cut's faces."""
    distance: float
    faces: List[_CutFace]
    color: int
    label: str


class _BlendFace(NamedTuple):
    """One face of a blend, in the new part: a box around it, and its axis when it is a cylinder."""
    axis: Optional[NXOpen.Vector3d]
    low: Tuple[float, float, float]
    high: Tuple[float, float, float]


class _Blend(NamedTuple):
    """A constant radius Edge Blend."""
    radius: float
    faces: List[_BlendFace]
    color: int
    on_subtool: bool
    label: str


class _ExtrudeCut(NamedTuple):
    """An Extrude that cuts the source's block, everything in the new part's coordinates."""
    # ("line", start, end), ("arc", center, x axis, y axis, radius, start angle, end angle), ("spline", points).
    curves: List[Tuple[Any, ...]]
    direction: NXOpen.Vector3d
    start: str
    end: str
    offset_option: Any
    offset_start: str
    offset_end: str
    draft_option: Any
    front_draft: str
    back_draft: str
    # The Timestamp the block is cut at: the Extrude's own, or its Subtract's.
    order: int
    label: str
    tags: Set[int]


class _Source(NamedTuple):
    """Everything the new detail takes from the source."""
    part: NXOpen.BasePart
    block: _Block
    body_color: int
    # (axis 0 / 1 / 2, sign) in block axes -> the color of that side.
    side_colors: Dict[Tuple[int, int], int]
    chamfers: List[_Chamfer]
    side_offsets: List[_SideOffset]
    block_blends: List[_Blend]
    # In feature order, made after the subtracts.
    cut_features: List[Union[_CutOffset, _Blend]]
    children: List[_Child]
    neighbours: List[_Neighbour]
    far_links: List[_FarLink]
    left_out: List[str]
    material: str
    detail_name: str
    expressions: Dict[str, str]
    extrudes: List[_ExtrudeCut]


class _Plan(NamedTuple):
    """What build needs from a picked detail, all read with the display part on top."""
    top: NXOpen.Part
    component: NXOpen.Assemblies.Component
    source: _Source
    corner: NXOpen.Point3d
    x_axis: NXOpen.Vector3d
    y_axis: NXOpen.Vector3d
    z_axis: NXOpen.Vector3d
    neighbour_frames: List[Tuple[NXOpen.Point3d, NXOpen.Vector3d, NXOpen.Vector3d]]


def _dot(v0: NXOpen.Vector3d, v1: NXOpen.Vector3d) -> float:
    return v0.X * v1.X + v0.Y * v1.Y + v0.Z * v1.Z


def _cross(v0: NXOpen.Vector3d, v1: NXOpen.Vector3d) -> NXOpen.Vector3d:
    return NXOpen.Vector3d(v0.Y * v1.Z - v0.Z * v1.Y, v0.Z * v1.X - v0.X * v1.Z, v0.X * v1.Y - v0.Y * v1.X)


def _along(point: NXOpen.Point3d, direction: NXOpen.Vector3d, distance: float = 1.0) -> NXOpen.Point3d:
    return NXOpen.Point3d(point.X + direction.X * distance, point.Y + direction.Y * distance,
                          point.Z + direction.Z * distance)


def _between(start: NXOpen.Point3d, end: NXOpen.Point3d) -> NXOpen.Vector3d:
    return NXOpen.Vector3d(end.X - start.X, end.Y - start.Y, end.Z - start.Z)


def _map_point(point: NXOpen.Point3d, from_csys: int, to_csys: int) -> NXOpen.Point3d:
    x, y, z = nx.ufsession_.Csys.MapPoint(from_csys, [point.X, point.Y, point.Z], to_csys)
    return NXOpen.Point3d(x, y, z)


def _reflect(point: NXOpen.Point3d) -> NXOpen.Point3d:
    """Through the absolute XZ plane."""
    return NXOpen.Point3d(point.X, -point.Y, point.Z)


def _reflect_vector(vector: NXOpen.Vector3d) -> NXOpen.Vector3d:
    return NXOpen.Vector3d(vector.X, -vector.Y, vector.Z)


def _dynamic_block_or_none(part: NXOpen.BasePart) -> Optional[NXOpen.Features.Block]:
    for feature in part.Features.GetFeatures():
        if isinstance(feature, NXOpen.Features.Block) and feature.Name == _DynamicBlockName:
            return feature
    return None


def _side_normal(block_axes: Sequence[NXOpen.Vector3d], side: Tuple[int, int]) -> NXOpen.Vector3d:
    axis = block_axes[side[0]]
    return NXOpen.Vector3d(axis.X * side[1], axis.Y * side[1], axis.Z * side[1])


_PlanarFace = Tuple[NXOpen.Face, NXOpen.Vector3d, NXOpen.Vector3d]


def _planar_faces(body: NXOpen.Body) -> List[_PlanarFace]:
    """Each planar face of body with its unit normal and a point on it: one AskFaceData a face."""
    faces: List[_PlanarFace] = []
    for face in body.GetFaces():
        if face.SolidFaceType != NXOpen.Face.FaceType.Planar:
            continue
        _type, point, direction, _box, _radius, _rad_data, _norm_dir = nx.ufsession_.Modeling.AskFaceData(face.Tag)
        faces.append((face, nx.unit(NXOpen.Vector3d(direction[0], direction[1], direction[2])),
                      NXOpen.Vector3d(point[0], point[1], point[2])))
    return faces


def _outer_faces(body: NXOpen.Body, normal: NXOpen.Vector3d,
                 planar: Optional[List[_PlanarFace]] = None) -> List[NXOpen.Face]:
    """
    The planar faces of body facing normal that lie furthest along it: that side of the block, not a pocket floor.
    planar is _planar_faces(body), when the caller asks for several sides of an unchanged body.
    """
    heights: List[Tuple[float, NXOpen.Face]] = []
    for face, face_normal, point in (planar if planar is not None else _planar_faces(body)):
        if not nx.vectors_equal(face_normal, normal):
            continue
        heights.append((_dot(point, normal), face))
    if not heights:
        return []
    top = max(height for height, _face in heights)
    return [face for height, face in heights if abs(height - top) < .001]


def _attribute_or(part: NXOpen.BasePart, title: str, default: str) -> str:
    if nx.has_attribute(part, title) and nx.get_attribute(part, title).strip():
        return nx.get_attribute(part, title)
    return default


def _reference_sets_holding(part: NXOpen.BasePart, tag: int) -> Set[str]:
    return {refset.Name for refset in part.GetAllReferenceSets()
            if tag in {member.Tag for member in refset.AskAllDirectMembers()}}


def _expressions_of(part: NXOpen.BasePart) -> Dict[str, NXOpen.Expression]:
    return {e.Name: e for e in part.Expressions if e.Name in _StationExpressions}


# ---------------------------------------------------------------------------------------------------
# Reading the source
# ---------------------------------------------------------------------------------------------------

def _read_block(part: NXOpen.BasePart, feature: NXOpen.Features.Block) -> _Block:
    """
    The source's block, by UF asks only. Never CreateBlockFeatureBuilder(feature): just opening and destroying it marks
    the source modified (all 25 clean parts tried, 2026-11-06), and the asks give the same origin and axes to 1e-12.
    """
    length, width, height = (part.Expressions.FindObject(parm.split("=", 1)[0].strip()).Value
                             for parm in nx.ufsession_.ModlFeatures.AskBlockParms(feature.Tag, 0))
    origin = nx.ufsession_.Modeling.AskFeatLocation(feature.Tag)
    x_direction, y_direction = nx.ufsession_.Modeling.AskFeatDirection(feature.Tag)
    x_axis = nx.unit(NXOpen.Vector3d(x_direction[0], x_direction[1], x_direction[2]))
    y_axis = nx.unit(NXOpen.Vector3d(y_direction[0], y_direction[1], y_direction[2]))
    return _Block(NXOpen.Point3d(origin[0], origin[1], origin[2]), x_axis, y_axis, _cross(x_axis, y_axis),
                  length, width, height)


def _length_of(feature: NXOpen.Features.Feature) -> Optional[float]:
    """The one length the feature was made with, None when it has several. An angle is not one: a chamfer can hold 45."""
    lengths = {round(e.Value, 6) for e in feature.GetExpressions()
               if e.Type == "Number" and (e.Units is None or e.Units.Name != "Degrees")}
    return lengths.pop() if len(lengths) == 1 else None


def _chamfer_edge(face: NXOpen.Face, block: _Block, offset: float) -> Optional[Tuple[int, int, int]]:
    """The block edge a chamfer's face sits on, None when it is not on one."""
    if face.SolidFaceType != NXOpen.Face.FaceType.Planar:
        return None
    normal = nx.face_normal(face)
    leaning = [abs(_dot(normal, axis)) > .01 for axis in (block.x_axis, block.y_axis, block.z_axis)]
    if sum(leaning) != 2:
        return None

    # The sign comes from where the face is, not its normal: NX's face normal does not carry the face's sense.
    corners = [block.local(v) for edge in face.GetEdges() for v in edge.GetVertices()]
    lengths = (block.length, block.width, block.height)
    signs = [0, 0, 0]
    reaches: List[float] = []
    for axis in range(3):
        if not leaning[axis]:
            continue
        values = [corner[axis] for corner in corners]
        if max(values) <= offset + .001:
            signs[axis] = -1
            reaches.append(max(values))
        elif min(values) >= lengths[axis] - offset - .001:
            signs[axis] = 1
            reaches.append(lengths[axis] - min(values))
        else:
            return None
    if abs(reaches[0] - reaches[1]) > .001:
        return None
    return signs[0], signs[1], signs[2]


def _read_chamfer(feature: NXOpen.Features.Feature, block: _Block) -> Optional[_Chamfer]:
    """The chamfer, None when it cannot be made again: unequal, or not all on block edges."""
    offset = _length_of(feature)
    faces = feature.GetFaces()
    if offset is None or not faces:
        return None
    edges = [_chamfer_edge(face, block, offset) for face in faces]
    if any(edge is None for edge in edges):
        return None
    return _Chamfer(offset, list({cast(Tuple[int, int, int], edge) for edge in edges}), faces[0].Color)


def _read_chamfers(part: NXOpen.BasePart, block: _Block) -> Tuple[List[_Chamfer], Set[int]]:
    """The chamfers to make again, and their features' tags."""
    chamfers: List[_Chamfer] = []
    tags: Set[int] = set()
    for feature in part.Features.GetFeatures():
        if feature.FeatureType != "CHAMFER":
            continue
        chamfer = _read_chamfer(feature, block)
        if chamfer is not None:
            chamfers.append(chamfer)
            tags.add(feature.Tag)
    return chamfers, tags


def _read_side_offset(feature: NXOpen.Features.Feature, block: _Block,
                      block_body: NXOpen.Body) -> Optional[_SideOffset]:
    """The offset, None when it moves anything but whole sides, or some out and some in."""
    length = _length_of(feature)
    faces = feature.GetFaces()
    if length is None or not faces:
        return None
    axes = (block.x_axis, block.y_axis, block.z_axis)
    lengths = (block.length, block.width, block.height)
    sides: Set[Tuple[int, int]] = set()
    outward: Set[bool] = set()
    for face in faces:
        if face.SolidFaceType != NXOpen.Face.FaceType.Planar:
            return None
        body = face.GetBody()
        planar = _planar_faces(body)
        found = [(axis, sign) for axis in range(3) for sign in (1, -1)
                 if face.Tag in {f.Tag for f in _outer_faces(body, _side_normal(axes, (axis, sign)), planar)}]
        if len(found) != 1:
            return None
        axis, sign = found[0]
        point = nx.ufsession_.Modeling.AskFaceData(face.Tag)[1]
        position = block.local(NXOpen.Point3d(point[0], point[1], point[2]))[axis]
        outward.add((position - (lengths[axis] if sign > 0 else 0.0)) * sign > -.001)
        sides.add((axis, sign))
    if len(outward) != 1:
        return None
    return _SideOffset(length if outward.pop() else -length, sorted(sides), faces[0].GetBody().Tag != block_body.Tag,
                       _feature_label(feature))


def _read_cut_offset(feature: NXOpen.Features.Feature, block: _Block) -> Optional[_CutOffset]:
    """The offset, None when it moved anything but planes and cylinders."""
    length = _length_of(feature)
    faces = feature.GetFaces()
    if length is None or not faces:
        return None
    targets: List[_CutFace] = []
    for face in faces:
        is_plane = face.SolidFaceType == NXOpen.Face.FaceType.Planar
        if not is_plane and face.SolidFaceType != NXOpen.Face.FaceType.Cylindrical:
            return None
        _type, point, direction, _box, radius, _rad_data, _norm_dir = nx.ufsession_.Modeling.AskFaceData(face.Tag)
        targets.append(_CutFace(is_plane, block.point(NXOpen.Point3d(point[0], point[1], point[2])),
                                block.vector(NXOpen.Vector3d(direction[0], direction[1], direction[2])), radius))
    return _CutOffset(length, targets, faces[0].Color, _feature_label(feature))


def _read_blend(feature: NXOpen.Features.Feature, block: _Block, block_body: NXOpen.Body) -> Optional[_Blend]:
    """The blend, None when it has more than one radius."""
    radius = _length_of(feature)
    faces = feature.GetFaces()
    if radius is None or not faces:
        return None
    read: List[_BlendFace] = []
    for face in faces:
        _type, _point, direction, box, _radius, _rad_data, _norm_dir = nx.ufsession_.Modeling.AskFaceData(face.Tag)
        ends = [block.point(NXOpen.Point3d(box[0], box[1], box[2])), block.point(NXOpen.Point3d(box[3], box[4], box[5]))]
        axis = None
        if face.SolidFaceType == NXOpen.Face.FaceType.Cylindrical:
            axis = block.vector(NXOpen.Vector3d(direction[0], direction[1], direction[2]))
        read.append(_BlendFace(axis, (min(e.X for e in ends), min(e.Y for e in ends), min(e.Z for e in ends)),
                               (max(e.X for e in ends), max(e.Y for e in ends), max(e.Z for e in ends))))
    return _Blend(radius, read, faces[0].Color, faces[0].GetBody().Tag != block_body.Tag, _feature_label(feature))


_Literal = re.compile(r"^\s*-?[0-9]*\.?[0-9]+(e-?[0-9]+)?\s*(mm|in)?\s*$", re.IGNORECASE)


def _value_text(expression: NXOpen.Expression) -> str:
    """The expression as text to give a new one: its own text when that is a number, else its value."""
    text = expression.RightHandSide
    return text if _Literal.match(text) else nx.cs_double_str(expression.Value)


def _spline_points(curve: NXOpen.Curve) -> List[NXOpen.Point3d]:
    """Points along a spline, enough for a fit through them to follow it: four per pole, at least 24."""
    count = max(24, 4 * len(cast(Any, curve).GetPoles()))
    # Python's UF.Modeling has no AskCurveProps: the evaluator over the curve's own parameter range instead.
    evaluator = nx.ufsession_.Eval.Initialize2(curve.Tag)
    try:
        low, high = nx.ufsession_.Eval.AskLimits(evaluator)[:2]
        points = []
        for index in range(count + 1):
            point = nx.ufsession_.Eval.EvaluateUnitVectors(evaluator, low + (high - low) * index / count)[0]
            points.append(NXOpen.Point3d(point[0], point[1], point[2]))
        return points
    finally:
        free = getattr(nx.ufsession_.Eval, "Free", None)
        if free is not None:
            free(evaluator)


def _mirrored_curve(curve: NXOpen.Curve, block: _Block) -> Optional[Tuple[Any, ...]]:
    """The curve in the new part's coordinates, None for a kind that is not made again."""
    if isinstance(curve, NXOpen.Line):
        return "line", block.point(curve.StartPoint), block.point(curve.EndPoint)
    if isinstance(curve, NXOpen.Arc):
        m = curve.Matrix.Element
        return ("arc", block.point(curve.CenterPoint), block.vector(NXOpen.Vector3d(m.Xx, m.Xy, m.Xz)),
                block.vector(NXOpen.Vector3d(m.Yx, m.Yy, m.Yz)), curve.Radius, curve.StartAngle, curve.EndAngle)
    if isinstance(curve, NXOpen.Spline):
        return "spline", [block.point(point) for point in _spline_points(curve)]
    return None


def _read_extrude(part: NXOpen.BasePart, feature: NXOpen.Features.Feature, block: _Block,
                  block_body: NXOpen.Body) -> Optional[_ExtrudeCut]:
    """The Extrude as a cut of the block, None when it is not one that is made again."""
    boolean_type = NXOpen.GeometricUtilities.BooleanOperation.BooleanType
    by_value = NXOpen.GeometricUtilities.Extend.ExtendType.Value
    subtracts = [child for child in feature.GetChildren() if child.FeatureType == "SUBTRACT"]
    was_modified = part.IsModified
    mark = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "Mirror Merlin read")
    builder: Any = part.Features.CreateExtrudeBuilder(feature)
    try:
        operation = builder.BooleanOperation.Type
        if operation == boolean_type.Subtract:
            if [body.Tag for body in builder.BooleanOperation.GetTargetBodies()] != [block_body.Tag]:
                return None
            order, tags = feature.Timestamp, {feature.Tag}
        elif (operation == boolean_type.Create and len(subtracts) == 1
              and block_body.Tag in {body.Tag for body in subtracts[0].GetBodies()}):
            order, tags = subtracts[0].Timestamp, {feature.Tag, subtracts[0].Tag}
        else:
            return None
        limits = builder.Limits
        if limits.StartExtend.TrimType != by_value or limits.EndExtend.TrimType != by_value:
            return None
        curves: List[Tuple[Any, ...]] = []
        for section in cast(Any, feature).GetSections():
            for curve in section.GetOutputCurves():
                mirrored = _mirrored_curve(curve, block)
                if mirrored is None:
                    return None
                curves.append(mirrored)
        if not curves:
            return None
        direction = builder.Direction.Vector
        offset, draft = builder.Offset, builder.Draft
        return _ExtrudeCut(curves, block.vector(nx.unit(direction)),
                           _value_text(limits.StartExtend.Value), _value_text(limits.EndExtend.Value),
                           offset.Option, _value_text(offset.StartOffset), _value_text(offset.EndOffset),
                           draft.DraftOption, _value_text(draft.FrontDraftAngle), _value_text(draft.BackDraftAngle),
                           order, _feature_label(feature), tags)
    finally:
        builder.Destroy()
        if part.IsModified and not was_modified:
            nx.session_.UndoToMark(mark, "Mirror Merlin read")
        nx.session_.DeleteUndoMark(mark, "Mirror Merlin read")


def _read_extrudes(part: NXOpen.BasePart, block: _Block, block_body: NXOpen.Body) -> Tuple[List[_ExtrudeCut], Set[int]]:
    """The Extrudes to make again, and their features' (and Subtracts') tags."""
    cuts: List[_ExtrudeCut] = []
    tags: Set[int] = set()
    for feature in part.Features.GetFeatures():
        if feature.FeatureType != "EXTRUDE" or feature.Suppressed:
            continue
        try:
            cut = _read_extrude(part, feature, block, block_body)
        except Exception as ex:
            nx.syslog("Mirror Merlin: could not read {} of {}: {}".format(_feature_label(feature), part.Leaf, ex))
            cut = None
        if cut is not None:
            cuts.append(cut)
            tags |= cut.tags
    return cuts, tags


def _on_block(feature: NXOpen.Features.Feature) -> bool:
    """Whether the feature was made on the block or its SUBTOOL as they were, not on a cut."""
    parents = feature.GetParents()
    return bool(parents) and all(isinstance(parent, NXOpen.Features.Block) or parent.FeatureType == "EXTRACT_BODY"
                                 for parent in parents)


def _read_offsets_and_blends(part: NXOpen.BasePart, block: _Block, block_body: NXOpen.Body
                             ) -> Tuple[List[_SideOffset], List[_Blend], List[Union[_CutOffset, _Blend]], Set[int]]:
    """The offsets and blends to make again, and their features' tags."""
    side_offsets: List[_SideOffset] = []
    block_blends: List[_Blend] = []
    cut_features: List[Union[_CutOffset, _Blend]] = []
    tags: Set[int] = set()
    for feature in part.Features.GetFeatures():
        if feature.FeatureType == "OFFSET":
            if _on_block(feature):
                side_offset = _read_side_offset(feature, block, block_body)
                if side_offset is not None:
                    side_offsets.append(side_offset)
                    tags.add(feature.Tag)
                continue
            cut_offset = _read_cut_offset(feature, block)
            if cut_offset is not None:
                cut_features.append(cut_offset)
                tags.add(feature.Tag)
        elif feature.FeatureType == "BLEND":
            blend = _read_blend(feature, block, block_body)
            if blend is not None:
                (block_blends if _on_block(feature) else cut_features).append(blend)
                tags.add(feature.Tag)
    return side_offsets, block_blends, cut_features, tags


def _read_links(part: NXOpen.BasePart, handled: Set[int]) -> Tuple[Dict[int, List[_Link]], List[str]]:
    """
    Each LINKED_BODY that comes from a child of part, by the child's instance tag, and the names of the rest, leaving
    out the handled features. A link from outside the part has no occurrence in it, or (when its parent is not in
    session) no transform NX will read.
    """
    root = nx.root_component(part)
    links: Dict[int, List[_Link]] = {}
    others: List[str] = []
    for feature in part.Features.GetFeatures():
        if feature.FeatureType != "LINKED_BODY" or feature.Tag in handled:
            continue
        link = _child_link(feature, root) if root is not None else None
        if link is None:
            others.append(_feature_label(feature))
        else:
            links.setdefault(link[0], []).append(link[1])
    return links, others


def _child_link(feature: NXOpen.Features.Feature,
                root: NXOpen.Assemblies.Component) -> Optional[Tuple[int, _Link]]:
    """The child instance and body behind the link (Nine99._subtract_punch_links' trace), None when it has neither."""
    try:
        if nx.is_link_broken(feature):
            return None
        xform = nx.ufsession_.Wave.AskLinkXform(feature.Tag)
        occurrence = nx.ufsession_.So.AskAssyCtxtPartOcc(xform, root.Tag) if xform != 0 else 0
        if occurrence == 0:
            return None
        body = nx.tagged_object(nx.ufsession_.Wave.AskLinkSource(feature.Tag, True))
        if not isinstance(body, NXOpen.Body):
            return None
        return nx.ufsession_.Assem.AskInstOfPartOcc(occurrence), _Link(body, feature.Name, feature.Timestamp)
    except NXOpen.NXException as ex:
        nx.syslog("MirrorMerlin: {} is not a child's link: {}".format(feature.GetFeatureName(), ex))
        return None


def _link_source(feature: NXOpen.Features.Feature, component: NXOpen.Assemblies.Component
                 ) -> Optional[Tuple[NXOpen.Assemblies.Component, NXOpen.Body]]:
    """
    The occurrence and body a link of component's part comes from, None when NX cannot say. The transform names the
    occurrence only when asked with the linking part's own occurrence: an assembly's root is refused as invalid.
    """
    try:
        if nx.is_link_broken(feature):
            return None
        xform = nx.ufsession_.Wave.AskLinkXform(feature.Tag)
        tag = nx.ufsession_.So.AskAssyCtxtPartOcc(xform, component.Tag) if xform != 0 else 0
        if tag == 0:
            return None
        occurrence = nx.tagged_object(tag)
        body = nx.tagged_object(nx.ufsession_.Wave.AskLinkSource(feature.Tag, True))
        if isinstance(occurrence, NXOpen.Assemblies.Component) and isinstance(body, NXOpen.Body):
            return occurrence, body
    except NXOpen.NXException as ex:
        nx.syslog("MirrorMerlin: no source for {}: {}".format(feature.GetFeatureName(), ex))
    return None


def _turn_over(body: NXOpen.Body) -> Tuple[int, float]:
    """The part axis (0 / 1 / 2) to turn body over along, and the middle of the body along it, in its part's units."""
    box = nx.ufsession_.ModlGeneral.AskBoundingBox(body.Tag)
    corners = {(round(p.X, 3), round(p.Y, 3), round(p.Z, 3)) for edge in body.GetEdges() for p in edge.GetVertices()}

    def unlike(axis: int) -> int:
        far = box[axis] + box[axis + 3]
        turned = {tuple(round(far - v, 3) if i == axis else v for i, v in enumerate(corner)) for corner in corners}
        return len(corners ^ turned)

    axis = min((1, 0, 2), key=unlike)
    return axis, (box[axis] + box[axis + 3]) / 2.0


def _units_scale(part: NXOpen.BasePart, assembly: NXOpen.BasePart) -> float:
    """A length in part's units to assembly's: a metric key in an inch die."""
    if part.PartUnits == assembly.PartUnits:
        return 1.0
    return 1.0 / 25.4 if assembly.PartUnits == NXOpen.BasePart.Units.Inches else 25.4


def _read_neighbour(occurrence: NXOpen.Assemblies.Component, holder: NXOpen.BasePart, body: NXOpen.Body,
                    link: _Link) -> _Neighbour:
    """occurrence's mirrored frame, from its position in the display part: one axis turned over across the body."""
    prototype = nx.prototype(occurrence)
    origin, orientation = occurrence.GetPosition()
    axes = [_reflect_vector(axis) for axis in (nx.axis_x(orientation), nx.axis_y(orientation), nx.axis_z(orientation))]
    axis, middle = _turn_over(body)
    new_origin = _along(_reflect(origin), axes[axis], 2.0 * middle * _units_scale(prototype, nx.display_part()))
    axes[axis] = nx.negate(axes[axis])

    instance = nx.ufsession_.Assem.AskInstOfPartOcc(occurrence.Tag)
    held = [child for child in nx.children(holder) if nx.ufsession_.Assem.AskInstOfPartOcc(child.Tag) == instance]
    reference_sets = _reference_sets_holding(holder, held[0].Tag) if held else set()
    return _Neighbour(prototype, occurrence.Name, occurrence.ReferenceSet, occurrence.Layer, new_origin, axes[0], axes[1],
                      reference_sets, [link])


def _read_neighbours(component: NXOpen.Assemblies.Component) -> Tuple[List[_Neighbour], Set[int]]:
    """
    The neighbours component's part links from, one per occurrence, and the link features that takes care of. A detail
    beside it is not a neighbour: _read_far_links has those. Runs with the display part still on top, which is what
    GetPosition is relative to.
    """
    part = nx.prototype(component)
    parent = cast(NXOpen.Assemblies.Component, component.Parent)
    holder = nx.prototype(parent)
    neighbours: Dict[int, _Neighbour] = {}
    handled: Set[int] = set()
    for feature in part.Features.GetFeatures():
        if feature.FeatureType != "LINKED_BODY":
            continue
        source = _link_source(feature, component)
        if source is None:
            continue
        occurrence, body = source
        if occurrence.Parent is None or occurrence.Parent.Tag != parent.Tag or not nx.is_loaded(occurrence):
            continue
        if _dynamic_block_or_none(nx.prototype(occurrence)) is not None or _is_strip_or_layout(occurrence):
            continue
        handled.add(feature.Tag)
        link = _Link(body, feature.Name, feature.Timestamp)
        if occurrence.Tag in neighbours:
            neighbours[occurrence.Tag].links.append(link)
        else:
            neighbours[occurrence.Tag] = _read_neighbour(occurrence, holder, body, link)
    return list(neighbours.values()), handled


def _is_under(occurrence: NXOpen.Assemblies.Component, ancestor: NXOpen.Assemblies.Component) -> bool:
    current = occurrence.Parent
    while current is not None:
        if current.Tag == ancestor.Tag:
            return True
        current = current.Parent
    return False


def _under_empty(occurrence: NXOpen.Assemblies.Component) -> bool:
    """Whether an assembly above occurrence is on Empty: NX will not set its reference set, or show its bodies."""
    current = occurrence.Parent
    while current is not None and current.Parent is not None:
        if current.ReferenceSet == _RefsetEmpty:
            return True
        current = current.Parent
    return False


def _same_place(first: NXOpen.Assemblies.Component, second: NXOpen.Assemblies.Component) -> bool:
    (p0, m0), (p1, m1) = first.GetPosition(), second.GetPosition()
    return all(abs(getattr(p0, a) - getattr(p1, a)) < .0001 for a in "XYZ") and all(
        abs(getattr(m0, a + b) - getattr(m1, a + b)) < .0001 for a in "XYZ" for b in "xyz")


def _occurrence_in_view(occurrence: NXOpen.Assemblies.Component) -> NXOpen.Assemblies.Component:
    """
    A layout under a Strip on Empty cannot be linked from. A job can hold the Strip twice, under a station on Empty and at
    the top, so this is the same part at the same spot that can be, or occurrence itself when there is none.
    """
    if not _under_empty(occurrence):
        return occurrence
    tags, _count = nx.ufsession_.Assem.AskOccsOfPart(nx.display_part().Tag, nx.prototype(occurrence).Tag)
    for tag in tags:
        other = cast(NXOpen.Assemblies.Component, nx.tagged_object(tag))
        if other.Tag != occurrence.Tag and not _under_empty(other) and _same_place(other, occurrence):
            return other
    return occurrence


def _intersect_of(feature: NXOpen.Features.Feature) -> int:
    """The tag of the Intersect that follows the link, 0 when there is none."""
    return next((child.Tag for child in feature.GetChildren() if child.FeatureType == "INTERSECT"), 0)


def _read_far_links(component: NXOpen.Assemblies.Component, handled: Set[int]) -> List[_FarLink]:
    """
    The links of component's part from outside the assembly holding it, from a detail beside it or from a strip or
    layout anywhere (a job can hold a Strip under the station itself), added to handled.
    A detail straight under the display part has nothing outside its assembly. Runs with the display part still on top.
    """
    parent = cast(NXOpen.Assemblies.Component, component.Parent)
    links: List[_FarLink] = []
    for feature in nx.prototype(component).Features.GetFeatures():
        if feature.FeatureType != "LINKED_BODY" or feature.Tag in handled:
            continue
        source = _link_source(feature, component)
        if source is None or not nx.is_loaded(source[0]):
            continue
        occurrence = source[0]
        beside = occurrence.Parent is not None and occurrence.Parent.Tag == parent.Tag
        if (_is_under(occurrence, parent) and not _is_strip_or_layout(occurrence)
                and not (beside and _dynamic_block_or_none(nx.prototype(occurrence)) is not None)):
            continue
        handled.add(feature.Tag)
        far = _occurrence_in_view(occurrence) if _is_strip_or_layout(occurrence) else occurrence
        links.append(_FarLink(far, source[1], feature.Name, feature.Timestamp, _intersect_of(feature)))
    return links


@nx.traced("Mirror Merlin")
def _repair_broken_links(component: NXOpen.Assemblies.Component) -> None:
    """
    Relinks the broken LINKED_BODY features of component's part that broken_links can place. One it cannot place, or
    whose relink it undoes, stays broken and is listed. Runs with the display part on top.
    """
    part = nx.prototype(component)
    broken = [f for f in part.Features.GetFeatures() if broken_links.is_broken(f)]
    if not broken:
        return
    by_leaf = broken_links.occurrences_by_leaf(nx.display_part())
    with nx.display_part_reset():
        for feature in broken:
            label = "{} of {}".format(_feature_label(feature), part.Leaf)
            try:
                source = broken_links.find_source(feature, [component], by_leaf)
                reason = source if isinstance(source, str) else broken_links.relink(feature, source)
                if reason is not None:
                    nx.print_("Mirror Merlin: {} stays broken: {}.".format(label, reason))
                    continue
                occurrence = cast(broken_links.Source, source).occurrence.DisplayName
                nx.syslog("Mirror Merlin: relinked {} to {}.".format(label, occurrence))
                _step("  relinked {} to {}".format(_feature_label(feature), occurrence))
            except Exception as ex:
                nx.print_exception(ex, "Mirror Merlin: could not relink {}".format(label))


def _feature_label(feature: NXOpen.Features.Feature) -> str:
    return "{} ({})".format(feature.GetFeatureName(), feature.Name) if feature.Name else feature.GetFeatureName()


def _read_children(part: NXOpen.BasePart, links: Dict[int, List[_Link]]) -> Tuple[List[_Child], List[str]]:
    """The children to mirror, and the names of the ones left out."""
    children: List[_Child] = []
    left_out: List[str] = []
    for child in nx.children(part):
        if child.IsSuppressed:
            left_out.append("{} (suppressed)".format(child.DisplayName))
            continue
        if not nx.is_loaded(child):
            nx.error("Mirror Merlin: {} in {} could not be loaded, so it and its cuts are not carried over.".format(
                child.DisplayName, part.Leaf))
            left_out.append("{} (not loaded)".format(child.DisplayName))
            continue
        prototype = nx.prototype(child)
        if _dynamic_block_or_none(prototype) is not None:
            left_out.append("{} (a detail: mirror it on its own)".format(child.DisplayName))
            continue
        position, orientation = child.GetPosition()
        children.append(_Child(prototype, child.Name, child.ReferenceSet, child.Layer, position,
                               nx.axis_x(orientation), nx.axis_y(orientation),
                               _reference_sets_holding(part, child.Tag),
                               links.get(nx.ufsession_.Assem.AskInstOfPartOcc(child.Tag), [])))
    return children, left_out


@nx.traced("Mirror Merlin")
def _read_source(component: NXOpen.Assemblies.Component) -> _Source:
    """
    Reads the source with the display part left on top, which _read_neighbours needs. Showing the source is not needed:
    the children's positions are in its own coordinates anyway, and the -000 costs about 1.5 s to show again.
    """
    part = nx.prototype(component)
    for child in nx.children(part):
        if not child.IsSuppressed and not nx.is_loaded(child):
            nx.ensure_loaded_quietly(child)
    neighbours, handled = _read_neighbours(component)
    far_links = _read_far_links(component, handled)

    feature = cast(NXOpen.Features.Block, _dynamic_block_or_none(part))
    block = _read_block(part, feature)
    body = feature.GetBodies()[0]

    block_axes = (block.x_axis, block.y_axis, block.z_axis)
    side_colors: Dict[Tuple[int, int], int] = {}
    planar = _planar_faces(body)
    for axis in range(3):
        for sign in (1, -1):
            faces = _outer_faces(body, _side_normal(block_axes, (axis, sign)), planar)
            if faces:
                side_colors[(axis, sign)] = faces[0].Color

    links, outside_links = _read_links(part, handled)
    children, children_left_out = _read_children(part, links)
    chamfers, chamfer_tags = _read_chamfers(part, block)
    side_offsets, block_blends, cut_features, finish_tags = _read_offsets_and_blends(part, block, body)

    extrudes, extrude_tags = _read_extrudes(part, block, body)

    intersect_tags = {link.intersect for link in far_links}
    other_features = [_feature_label(f) for f in part.Features.GetFeatures()
                      if f.FeatureType not in _RebuiltFeatures
                      and f.Tag != feature.Tag and f.Name != "SUBTOOL"
                      and f.Tag not in chamfer_tags and f.Tag not in finish_tags and f.Tag not in intersect_tags
                      and f.Tag not in extrude_tags]

    return _Source(part, block, body.Color, side_colors, chamfers, side_offsets, block_blends, cut_features,
                   children, neighbours, far_links,
                   outside_links + other_features + children_left_out,
                   _attribute_or(part, "MATERIAL", "FILL IN"), _attribute_or(part, "DETAIL NAME", "FILL IN"),
                   {name: e.RightHandSide for name, e in _expressions_of(part).items()}, extrudes)


# ---------------------------------------------------------------------------------------------------
# The new detail
# ---------------------------------------------------------------------------------------------------

def _make_holder_the_work_part(component: NXOpen.Assemblies.Component) -> None:
    parent = cast(NXOpen.Assemblies.Component, component.Parent)
    if parent.Parent is None:
        nx.set_work_part(nx.display_part())
    else:
        nx.set_work_component(parent)


def _in_holder(origin: NXOpen.Point3d, x_axis: NXOpen.Vector3d,
               y_axis: NXOpen.Vector3d) -> Tuple[NXOpen.Point3d, NXOpen.Vector3d, NXOpen.Vector3d]:
    """A frame in the display part in the coordinates of the work part, the assembly holding the source."""
    work, root = drawdie._UF_CSYS_WORK_COORDS, drawdie._UF_CSYS_ROOT_COORDS
    corner, x_end, y_end = (_map_point(p, root, work) for p in (origin, _along(origin, x_axis), _along(origin, y_axis)))
    return corner, nx.unit(_between(corner, x_end)), nx.unit(_between(corner, y_end))


def _mirrored_frame(component: NXOpen.Assemblies.Component,
                    block: _Block) -> Tuple[NXOpen.Point3d, NXOpen.Vector3d, NXOpen.Vector3d, NXOpen.Vector3d]:
    """
    The new block's corner and unit X, Y, Z in the coordinates of the assembly holding the source. In the display part:
    the corner is the source's reflected and moved W along the mirrored Y, X is the mirrored X and Y the mirrored Y
    turned back. Leaves the holder as the work part.
    """
    work, root = drawdie._UF_CSYS_WORK_COORDS, drawdie._UF_CSYS_ROOT_COORDS

    nx.set_work_component(component)
    origin, x_end, y_end = (_reflect(_map_point(p, work, root)) for p in (
        block.origin, _along(block.origin, block.x_axis), _along(block.origin, block.y_axis)))
    x_axis, y_axis = _between(origin, x_end), _between(origin, y_end)
    new_origin = _along(origin, y_axis, block.width)

    _make_holder_the_work_part(component)
    corner, new_x, new_y = _in_holder(new_origin, x_axis, nx.negate(y_axis))
    return corner, new_x, new_y, _cross(new_x, new_y)


def _block_edge(body: NXOpen.Body, block: _Block, signs: Tuple[int, int, int]) -> Optional[NXOpen.Edge]:
    """The edge of the new block at signs. The new block fills (0,0,0)..(L,W,H), so each side is 0 or a length."""
    lengths = (block.length, block.width, block.height)
    for edge in body.GetEdges():
        ends = [(v.X, v.Y, v.Z) for v in edge.GetVertices()]
        if all(sign == 0 or abs(end[axis] - (lengths[axis] if sign > 0 else 0.0)) < .001
               for axis, sign in enumerate(signs) for end in ends):
            return edge
    return None


@nx.traced("Mirror Merlin")
def _make_chamfers(new_part: NXOpen.BasePart, source: _Source) -> List[Tuple[NXOpen.Features.Feature, int]]:
    """Each chamfer on the mirrored edges (Y turned over). Returns the features and their colors, for _color_chamfers."""
    made: List[Tuple[NXOpen.Features.Feature, int]] = []
    for chamfer in source.chamfers:
        try:
            body = nx.dynamic_block(new_part).GetBodies()[0]
            edges = [_block_edge(body, source.block, (x, -y, z)) for x, y, z in chamfer.edges]
            found = [edge for edge in edges if edge is not None]
            if len(found) != len(edges):
                nx.error("Mirror Merlin: {} of {} edges of a {} chamfer not found on {}.".format(
                    len(edges) - len(found), len(edges), nx.cs_double_str(chamfer.offset), new_part.Leaf))
            if not found:
                continue
            builder = new_part.Features.CreateChamferBuilder(None)
            try:
                builder.Option = NXOpen.Features.ChamferBuilder.ChamferOption.SymmetricOffsets
                builder.Method = NXOpen.Features.ChamferBuilder.OffsetMethod.EdgesAlongFaces
                builder.FirstOffset = nx.cs_double_str(chamfer.offset)
                collector = new_part.ScCollectors.CreateCollector()
                collector.ReplaceRules([new_part.ScRuleFactory.CreateRuleEdgeDumb(found)], False)
                builder.SmartCollector = collector
                made.append((cast(NXOpen.Features.Feature, builder.CommitFeature()), chamfer.color))
            finally:
                builder.Destroy()
        except Exception as ex:
            nx.print_exception(ex, "Mirror Merlin: could not make a {} chamfer on {}".format(
                nx.cs_double_str(chamfer.offset), new_part.Leaf))
    return made


def _subtool_body(part: NXOpen.BasePart) -> Optional[NXOpen.Body]:
    for feature in part.Features.GetFeatures():
        if feature.Name == "SUBTOOL":
            return feature.GetBodies()[0]
    return None


def _body_for(part: NXOpen.BasePart, on_subtool: bool) -> Optional[NXOpen.Body]:
    return _subtool_body(part) if on_subtool else nx.dynamic_block(part).GetBodies()[0]


def _offset_faces(part: NXOpen.BasePart, faces: Sequence[NXOpen.Face], distance: float) -> NXOpen.Features.Feature:
    """Outward from the part by distance, inward when it is negative."""
    builder = part.Features.CreateOffsetFaceBuilder(None)
    try:
        builder.Distance.RightHandSide = nx.cs_double_str(abs(distance))
        builder.Direction = distance < 0.0
        builder.FaceCollector.ReplaceRules([part.ScRuleFactory.CreateRuleFaceDumb(list(faces))], False)
        return cast(NXOpen.Features.Feature, builder.CommitFeature())
    finally:
        builder.Destroy()


def _make_side_offset(new_part: NXOpen.BasePart, source: _Source, offset: _SideOffset) -> bool:
    """False, with the feature named as left out, when a side is not there."""
    body = _body_for(new_part, offset.on_subtool)
    axes = (NXOpen.Vector3d(1.0, 0.0, 0.0), NXOpen.Vector3d(0.0, 1.0, 0.0), NXOpen.Vector3d(0.0, 0.0, 1.0))
    planar = _planar_faces(body) if body is not None else []
    sides = [_outer_faces(body, _side_normal(axes, (axis, -sign if axis == 1 else sign)), planar)
             if body is not None else [] for axis, sign in offset.sides]
    if not all(sides):
        source.left_out.append("{} (a side not found)".format(offset.label))
        return False
    _offset_faces(new_part, [face for side in sides for face in side], offset.distance)
    return True


def _moved_by(face: NXOpen.Face, target: _CutFace, length: float) -> Optional[float]:
    """How far outward face has to move to be target, None when it is not length away from it."""
    _type, point, direction, _box, radius, _rad_data, norm_dir = nx.ufsession_.Modeling.AskFaceData(face.Tag)
    axis = nx.unit(NXOpen.Vector3d(direction[0], direction[1], direction[2]))
    if abs(abs(_dot(axis, nx.unit(target.direction))) - 1.0) > .001:
        return None
    gap = _between(NXOpen.Point3d(point[0], point[1], point[2]), target.point)
    along = _dot(gap, axis)
    if target.is_plane:
        # A plane's direction already points out of the part, whatever norm_dir says.
        moved = along
    else:
        off_axis = NXOpen.Vector3d(gap.X - axis.X * along, gap.Y - axis.Y * along, gap.Z - axis.Z * along)
        if _dot(off_axis, off_axis) > 1e-6:
            return None
        # A hole's faces point at its axis, so moving out of the part makes it smaller.
        moved = (target.radius - radius) * norm_dir
    return moved if abs(abs(moved) - length) < .001 else None


def _make_cut_offset(new_part: NXOpen.BasePart, source: _Source, offset: _CutOffset) -> Optional[NXOpen.Features.Feature]:
    """None, with the feature named as left out, when a face it moved is not on the new block."""
    faces: List[NXOpen.Face] = []
    moves: Set[bool] = set()
    candidates = nx.dynamic_block(new_part).GetBodies()[0].GetFaces()
    for target in offset.faces:
        wanted = NXOpen.Face.FaceType.Planar if target.is_plane else NXOpen.Face.FaceType.Cylindrical
        found = [(face, _moved_by(face, target, offset.distance)) for face in candidates
                 if face.SolidFaceType == wanted]
        found = [pair for pair in found if pair[1] is not None]
        if not found:
            source.left_out.append("{} (its cut was not carried over)".format(offset.label))
            return None
        faces += [face for face, _moved in found]
        moves |= {cast(float, moved) > 0.0 for _face, moved in found}
    if len(moves) != 1:
        source.left_out.append("{} (some faces out, some in)".format(offset.label))
        return None
    return _offset_faces(new_part, list({face.Tag: face for face in faces}.values()),
                         offset.distance if moves.pop() else -offset.distance)


def _edge_under(edge: NXOpen.Edge, face: _BlendFace) -> bool:
    """Whether edge is what face was blended from: a blend's box holds the sharp edge it replaced, as far as it runs."""
    ends = [(v.X, v.Y, v.Z) for v in edge.GetVertices()]
    linear = edge.SolidEdgeType == NXOpen.Edge.EdgeType.Linear
    if face.axis is None:
        return not linear and all(face.low[i] - .001 <= end[i] <= face.high[i] + .001 for end in ends for i in range(3))
    if not linear:
        return False
    run = _between(edge.GetVertices()[0], edge.GetVertices()[1])
    if abs(abs(_dot(nx.unit(run), nx.unit(face.axis))) - 1.0) > .001:
        return False
    return all(max(end[i] for end in ends) >= face.low[i] - .001 and min(end[i] for end in ends) <= face.high[i] + .001
               for i in range(3))


def _make_blend(new_part: NXOpen.BasePart, source: _Source, blend: _Blend) -> Optional[NXOpen.Features.Feature]:
    """None, with the feature named as left out, when an edge is not there: its cut was not carried over."""
    body = _body_for(new_part, blend.on_subtool)
    edges = body.GetEdges() if body is not None else []
    under = [[edge for edge in edges if _edge_under(edge, face)] for face in blend.faces]
    if not all(under):
        source.left_out.append("{} (its edges were not carried over)".format(blend.label))
        return None
    # Features.CreateEdgeBlendBuilder / EdgeBlendBuilder are not in the stubs.
    builder = cast(Any, new_part.Features).CreateEdgeBlendBuilder(None)
    try:
        builder.Tolerance = nx.distance_tolerance()
        collector = new_part.ScCollectors.CreateCollector()
        collector.ReplaceRules([new_part.ScRuleFactory.CreateRuleEdgeDumb(
            list({edge.Tag: edge for found in under for edge in found}.values()))], False)
        builder.AddChainset(collector, nx.cs_double_str(blend.radius))
        return cast(NXOpen.Features.Feature, builder.CommitFeature())
    finally:
        builder.Destroy()


@nx.traced("Mirror Merlin")
def _make_block_finishes(new_part: NXOpen.BasePart, source: _Source) -> List[Tuple[NXOpen.Features.Feature, int]]:
    """
    The block's and SUBTOOL's offsets, then their blends. Offsets first: a blend's faces were read off the finished
    part, where the sides have moved. Returns the blends and their colors, for _color_finishes.
    """
    made: List[Tuple[NXOpen.Features.Feature, int]] = []
    for offset in source.side_offsets:
        try:
            _make_side_offset(new_part, source, offset)
        except Exception as ex:
            nx.print_exception(ex, "Mirror Merlin: could not make {} on {}".format(offset.label, new_part.Leaf))
    for blend in source.block_blends:
        try:
            feature = _make_blend(new_part, source, blend)
            if feature is not None:
                made.append((feature, blend.color))
        except Exception as ex:
            nx.print_exception(ex, "Mirror Merlin: could not make {} on {}".format(blend.label, new_part.Leaf))
    return made


@nx.traced("Mirror Merlin")
def _make_cut_finishes(new_part: NXOpen.BasePart, source: _Source) -> List[Tuple[NXOpen.Features.Feature, int]]:
    """The offsets and blends on the cuts' faces, in feature order. Returns them with their colors."""
    made: List[Tuple[NXOpen.Features.Feature, int]] = []
    for item in source.cut_features:
        try:
            if isinstance(item, _CutOffset):
                feature = _make_cut_offset(new_part, source, item)
            else:
                feature = _make_blend(new_part, source, item)
            if feature is not None:
                made.append((feature, item.color))
        except Exception as ex:
            nx.print_exception(ex, "Mirror Merlin: could not make {} on {}".format(item.label, new_part.Leaf))
    return made


def _color_finishes(finishes: Sequence[Tuple[NXOpen.Features.Feature, int]]) -> None:
    """After the subtracts, like the sides."""
    for feature, color in finishes:
        for face in feature.GetFaces():
            nx.set_color(face, color)


def _add_child(new_part: NXOpen.BasePart, source: _Source, child: _Child) -> NXOpen.Assemblies.Component:
    """
    The child at its mirrored position, on Entire Part: a body has to be in the current reference set to be linked.
    X is the mirrored X and Y the mirrored Y turned back, so Z is the mirrored Z.
    """
    block = source.block
    x_axis, y_axis = block.vector(child.x_axis), block.vector(child.y_axis)
    orientation = nx.matrix_from_axes(x_axis, NXOpen.Vector3d(-y_axis.X, -y_axis.Y, -y_axis.Z))
    return nx.add_component(new_part, child.prototype, nx.RefsetEntirePart, child.name, block.point(child.origin),
                            orientation, child.layer)


def _link_child_body(component: NXOpen.Assemblies.Component, link: _Link) -> Optional[NXOpen.Features.Feature]:
    """The link made in the work part, to be subtracted with the rest by _subtract_all; None when there is no body."""
    occurrence = component.FindOccurrence(link.body)
    if not isinstance(occurrence, NXOpen.Body):
        nx.error("Mirror Merlin: {} has no occurrence of the linked body, not subtracted.".format(
            component.DisplayName))
        return None
    feature = nine99._link_body_into_work_part(occurrence)
    if link.name:
        feature.SetName(link.name)
    return feature


def _subtract_all(new_part: NXOpen.BasePart, links: Sequence[NXOpen.Features.Feature]) -> int:
    """
    Every link subtracted from the block in one Subtract (2026-11-07): one Commit costs about what one tool's does. When
    NX refuses the lot (a tool that misses the block, 670030), each is subtracted on its own, so only the one that fails
    is lost. Returns the links subtracted.
    """
    if not links:
        return 0
    try:
        tools = [body for link in links for body in link.GetBodies()]
        builder = new_part.Features.CreateBooleanBuilderUsingCollector(None)
        try:
            builder.Target = nx.dynamic_block(new_part).GetBodies()[0]
            collector = new_part.ScCollectors.CreateCollector()
            collector.ReplaceRules([new_part.ScRuleFactory.CreateRuleBodyDumb(tools)], False)
            builder.ToolBodyCollector = collector
            builder.Operation = NXOpen.Features.Feature.BooleanType.Subtract
            builder.Commit()
        finally:
            builder.Destroy()
        return len(links)
    except Exception as ex:
        nx.syslog("Mirror Merlin: one subtract of {} links on {} refused ({}), subtracting each".format(
            len(links), new_part.Leaf, ex))
    count = 0
    for link in links:
        try:
            splitform._subtract_linked_body(new_part, nx.dynamic_block(new_part).GetBodies()[0], link)
            count += 1
        except Exception as ex:
            nx.print_exception(ex, "Mirror Merlin: could not subtract {} on {}".format(
                link.GetFeatureName(), new_part.Leaf))
    return count


# Strip and layout occurrences a far link showed through another reference set, with the set to put back at the end of
# the run (2026-11-07): switching a layout's set at the top costs ~0.2 s, and one set serves link after link.
_reference_sets_to_restore: Dict[int, Tuple[NXOpen.Assemblies.Component, str]] = {}


def _show_through(occurrence: NXOpen.Assemblies.Component, name: str) -> None:
    if occurrence.Tag not in _reference_sets_to_restore:
        _reference_sets_to_restore[occurrence.Tag] = (occurrence, occurrence.ReferenceSet)
    if occurrence.ReferenceSet != name:
        nx.set_reference_set(occurrence, name)


def _restore_reference_sets() -> None:
    for occurrence, name in _reference_sets_to_restore.values():
        try:
            if occurrence.ReferenceSet != name:
                nx.set_reference_set(occurrence, name)
        except Exception as ex:
            nx.print_exception(ex, "Mirror Merlin: could not put {} back on {}".format(occurrence.DisplayName, name))
    _reference_sets_to_restore.clear()


def _set_membership(part: NXOpen.BasePart, component: NXOpen.Assemblies.Component, names: Set[str]) -> None:
    """
    In the named reference sets of part and no others. A reference set with Add Components Automatically on (the
    default in a batch session) takes every new component, SUBTOOL included.
    """
    for refset in part.GetAllReferenceSets():
        member = component.Tag in {m.Tag for m in refset.AskAllDirectMembers()}
        wanted = refset.Name in names
        if member and not wanted:
            refset.RemoveObjectsFromReferenceSet([component])
        elif wanted and not member:
            refset.AddObjectsToReferenceSet([component])


@nx.traced("Mirror Merlin")
def _placed_at(holder: NXOpen.BasePart, prototype: NXOpen.BasePart, origin: NXOpen.Point3d, x_axis: NXOpen.Vector3d,
               y_axis: NXOpen.Vector3d) -> Optional[NXOpen.Assemblies.Component]:
    """holder's component of prototype at that frame: the mirror of a neighbour another detail shares."""
    for child in nx.children(holder):
        if child.IsSuppressed or not nx.is_loaded(child) or nx.prototype(child).Tag != prototype.Tag:
            continue
        position, orientation = child.GetPosition()
        offset = _between(position, origin)
        if (_dot(offset, offset) < 1e-6 and nx.vectors_equal(nx.axis_x(orientation), x_axis)
                and nx.vectors_equal(nx.axis_y(orientation), y_axis)):
            return child
    return None


def _mirror_plane(new_part: NXOpen.BasePart) -> NXOpen.DatumPlane:
    """The display part's Y = 0 as a datum plane in new_part, which is the work part under the display part."""
    work, root = drawdie._UF_CSYS_WORK_COORDS, drawdie._UF_CSYS_ROOT_COORDS
    origin, x_end, z_end = (_map_point(NXOpen.Point3d(x, 0.0, z), root, work)
                            for x, z in ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)))
    plane = cast(NXOpen.Part, new_part).Datums.CreateFixedDatumPlane(
        origin, nx.matrix_from_axes(nx.unit(_between(origin, x_end)), nx.unit(_between(origin, z_end))))
    plane.Layer = _SubtractLayer
    return plane


def _link_mirrored(part: NXOpen.BasePart, body: NXOpen.Body, plane: NXOpen.DatumPlane) -> NXOpen.Features.Feature:
    """body (an occurrence in the display part) wave-linked into the work part as its mirror image across plane."""
    builder = part.BaseFeatures.CreateWaveLinkBuilder(None)
    try:
        builder.Type = NXOpen.Features.WaveLinkBuilder.Types.MirrorBodyLink
        mirror = builder.MirrorBodyBuilder
        mirror.ParentPartType = NXOpen.Features.MirrorBodyBuilder.ParentPart.OtherPart
        mirror.Associative = True
        mirror.FixAtCurrentTimestamp = False
        mirror.MirrorBodyCollector.ReplaceRules([part.ScRuleFactory.CreateRuleBodyDumb([body], False)], False)
        mirror.Plane.Value = plane
        return cast(NXOpen.Features.Feature, builder.Commit())
    finally:
        builder.Destroy()


def _make_curve(part: NXOpen.BasePart, curve: Tuple[Any, ...]) -> NXOpen.Curve:
    """One section curve in part, the work part, on its work layer."""
    if curve[0] == "line":
        return cast(Any, part).Curves.CreateLine(curve[1], curve[2])
    if curve[0] == "arc":
        _kind, center, x_axis, y_axis, radius, start, end = curve
        matrix = part.NXMatrices.Create(nx.matrix_from_axes(x_axis, y_axis))
        return cast(NXOpen.Curve, cast(Any, part).Curves.CreateArc(center, matrix, radius, start, end))
    data: List[Any] = []
    points = curve[1]
    for index, point in enumerate(points):
        entry: Any = NXOpen.UF.Curve.PtSlopeCrvatr()
        entry.Point = [point.X, point.Y, point.Z]
        entry.SlopeType = (NXOpen.UF.UFConstants.UF_CURVE_SLOPE_AUTO if index in (0, len(points) - 1)
                           else NXOpen.UF.UFConstants.UF_CURVE_SLOPE_NONE)
        entry.CrvatrType = NXOpen.UF.UFConstants.UF_CURVE_CRVATR_NONE
        entry.Slope = [0.0, 0.0, 0.0]
        entry.Crvatr = [0.0, 0.0, 0.0]
        data.append(entry)
    return cast(NXOpen.Curve, nx.tagged_object(nx.ufsession_.Curve.CreateSplineThruPts(3, 0, len(data), data, None, 0)))


def _make_extrude(new_part: NXOpen.BasePart, cut: _ExtrudeCut) -> NXOpen.Features.Feature:
    """The Extrude made again, subtracted from the new block. new_part is displayed and the work part."""
    curves = [_make_curve(new_part, curve) for curve in cut.curves]
    modeling: Any = cast(Any, new_part.Preferences).Modeling
    distance_tolerance = modeling.DistanceToleranceData
    section = cast(Any, new_part).Sections.CreateSection(0.95 * distance_tolerance, distance_tolerance,
                                              modeling.AngleToleranceData)
    section.AllowSelfIntersection(False)
    section.SetAllowedEntityTypes(NXOpen.Section.AllowTypes.CurvesAndPoints)
    for curve in curves:
        section.AddToSection([new_part.ScRuleFactory.CreateRuleCurveDumb([curve])], curve, None, None,
                             NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Section.Mode.Create, False)
    builder: Any = new_part.Features.CreateExtrudeBuilder(None)
    try:
        builder.DistanceTolerance = distance_tolerance
        builder.Section = section
        builder.Direction = new_part.Directions.CreateDirection(NXOpen.Point3d(0.0, 0.0, 0.0), cut.direction,
                                                                NXOpen.SmartObject.UpdateOption.WithinModeling)
        builder.Limits.StartExtend.Value.RightHandSide = cut.start
        builder.Limits.EndExtend.Value.RightHandSide = cut.end
        builder.Offset.Option = cut.offset_option
        builder.Offset.StartOffset.RightHandSide = cut.offset_start
        builder.Offset.EndOffset.RightHandSide = cut.offset_end
        builder.Draft.DraftOption = cut.draft_option
        builder.Draft.FrontDraftAngle.RightHandSide = cut.front_draft
        builder.Draft.BackDraftAngle.RightHandSide = cut.back_draft
        builder.BooleanOperation.Type = NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Subtract
        builder.BooleanOperation.SetTargetBodies([nx.dynamic_block(new_part).GetBodies()[0]])
        return cast(NXOpen.Features.Feature, builder.CommitFeature())
    finally:
        builder.Destroy()


def _show(part: NXOpen.BasePart) -> None:
    """Displays part, which on a big assembly is worth skipping when it already is."""
    if nx.display_part().Tag != part.Tag:
        nx.set_display_part(part)


def _is_strip_or_layout(component: NXOpen.Assemblies.Component) -> bool:
    name = component.DisplayName.lower()
    return "layout" in name or "strip" in name


def _link_reference_set(link: _FarLink) -> str:
    """The reference set that shows the link's body: LWR-3D and the like before BODY, Entire Part if it is in none."""
    names = _reference_sets_holding(nx.prototype(link.occurrence), link.body.Tag)
    return (sorted(names - {_RefsetBody}) or sorted(names) or [nx.RefsetEntirePart])[0]


def _make_far_link(top: NXOpen.BasePart, parent: NXOpen.Assemblies.Component, new_part: NXOpen.BasePart,
                   link: _FarLink) -> Union[bool, NXOpen.Features.Feature]:
    """
    One far link, made and cut with top displayed, the only part holding both occurrences: subtracted, or intersected
    when the source's was (the block is then what the body and the block share). A strip's or layout's
    body is linked as it stands, through the reference set that shows it, as the Merlin UFuncs do: the die is symmetric
    across Y = 0, so the new detail's cut comes off the far side of the same body. A detail beside the source is not
    mirrored, so its body is linked as its mirror image. The source's reference set is shared, so it goes back, at the
    end of the run (_restore_reference_sets). Returns the link to subtract, True for an intersect made, False for none.
    """
    _show(top)
    new_occurrence = next(c for c in parent.GetChildren() if nx.prototype(c).Tag == new_part.Tag)
    nx.set_work_part(top)
    try:
        # An Intersect's tool is the detail's shape, so it is a true mirror image: the die may not be symmetric there.
        plain = _is_strip_or_layout(link.occurrence) and not link.intersect
        _show_through(link.occurrence, _link_reference_set(link) if plain else nx.RefsetEntirePart)
        body = link.occurrence.FindOccurrence(link.body)
        if not isinstance(body, NXOpen.Body):
            nx.error("Mirror Merlin: {} has no occurrence of the linked body, {} not subtracted.".format(
                link.occurrence.DisplayName, link.name))
            return False
        nx.set_work_component(new_occurrence)
        feature = (nine99._link_body_into_work_part(body) if plain
                   else _link_mirrored(new_part, body, _mirror_plane(new_part)))
        if link.name:
            feature.SetName(link.name)
        if link.intersect:
            target = nx.dynamic_block(new_part).GetBodies()[0]
            nx.create_boolean(target, feature.GetBodies(), NXOpen.Features.Feature.BooleanType.Intersect)
            return True
        return feature
    finally:
        nx.set_work_part(top)


@nx.traced("Mirror Merlin")
def _mirror_links(top: NXOpen.BasePart, parent: NXOpen.Assemblies.Component, holder: NXOpen.BasePart,
                  new_component: NXOpen.Assemblies.Component, new_part: NXOpen.BasePart, source: _Source,
                  frames: Sequence[Tuple[NXOpen.Point3d, NXOpen.Vector3d, NXOpen.Vector3d]]) -> int:
    """
    The children and neighbours placed, then every link made and subtracted in the source's feature order, so the two
    feature lists read alike, then the reference sets put back. A child's link needs new_part displayed, a neighbour's
    holder (both occurrences in one assembly, with the new detail the work part) and a far link top. One failure costs
    only that link, or that child's or neighbour's. Returns the links made.
    """
    steps: List[Tuple[int, str, Callable[[], Union[bool, None, NXOpen.Features.Feature]]]] = []

    def child_step(component: NXOpen.Assemblies.Component, link: _Link) -> Optional[NXOpen.Features.Feature]:
        _show(new_part)
        nx.set_work_part(new_part)
        return _link_child_body(component, link)

    def neighbour_step(component: NXOpen.Assemblies.Component, link: _Link) -> Optional[NXOpen.Features.Feature]:
        _show(holder)
        nx.set_work_component(new_component)
        return _link_child_body(component, link)

    children: List[Tuple[NXOpen.Assemblies.Component, _Child]] = []
    for child in source.children:
        try:
            component = _add_child(new_part, source, child)
            children.append((component, child))
            steps.extend((link.order, link.name or child.name, partial(child_step, component, link))
                         for link in child.links)
        except Exception as ex:
            nx.print_exception(ex, "Mirror Merlin: could not mirror {}".format(child.name))

    neighbours: List[Tuple[NXOpen.Assemblies.Component, _Neighbour, str, bool]] = []
    if source.neighbours:
        nx.set_display_part(holder)
    for neighbour, (origin, x_axis, y_axis) in zip(source.neighbours, frames):
        try:
            nx.set_work_part(holder)
            placed = _placed_at(holder, neighbour.prototype, origin, x_axis, y_axis)
            is_new = placed is None
            component = placed if placed is not None else nx.add_component(
                holder, neighbour.prototype, nx.RefsetEntirePart, neighbour.name, origin,
                nx.matrix_from_axes(x_axis, y_axis), neighbour.layer)
            reference_set = neighbour.reference_set if is_new else component.ReferenceSet
            nx.set_reference_set(component, nx.RefsetEntirePart)
            neighbours.append((component, neighbour, reference_set, is_new))
            steps.extend((link.order, link.name or neighbour.name or neighbour.prototype.Leaf,
                          partial(neighbour_step, component, link)) for link in neighbour.links)
        except Exception as ex:
            nx.print_exception(ex, "Mirror Merlin: could not mirror {}".format(neighbour.prototype.Leaf))

    steps.extend((link.order, link.name or link.occurrence.DisplayName,
                  partial(_make_far_link, top, parent, new_part, link)) for link in source.far_links)

    def extrude_step(cut: _ExtrudeCut) -> bool:
        _show(new_part)
        nx.set_work_part(new_part)
        _make_extrude(new_part, cut)
        return True

    steps.extend((cut.order, cut.label, partial(extrude_step, cut)) for cut in source.extrudes)

    count = 0
    to_subtract: List[NXOpen.Features.Feature] = []
    for index, (_, label, step) in enumerate(sorted(steps, key=lambda s: s[0])):
        _step("  link {} of {}: {}".format(index + 1, len(steps), label))
        try:
            made = step()
            if isinstance(made, NXOpen.Features.Feature):
                to_subtract.append(made)
            elif made:
                count += 1
        except Exception as ex:
            nx.print_exception(ex, "Mirror Merlin: could not make a link of {}".format(new_part.Leaf))
    _show(new_part)
    nx.set_work_part(new_part)
    _step("  subtracting {} link(s)".format(len(to_subtract)))
    count += _subtract_all(new_part, to_subtract)

    if neighbours:
        _show(holder)
        nx.set_work_part(holder)
    for component, neighbour, reference_set, is_new in neighbours:
        try:
            nx.set_reference_set(component, reference_set)
            if is_new:
                _set_membership(holder, component, neighbour.reference_sets)
        except Exception as ex:
            nx.print_exception(ex, "Mirror Merlin: could not finish {}".format(neighbour.prototype.Leaf))

    _show(new_part)
    nx.set_work_part(new_part)
    for component, child in children:
        try:
            nx.set_reference_set(component, child.reference_set)
            _set_membership(new_part, component, child.reference_sets)
        except Exception as ex:
            nx.print_exception(ex, "Mirror Merlin: could not finish {}".format(child.name))
    return count


def _color_sides(new_part: NXOpen.BasePart, source: _Source) -> None:
    """After the subtracts, which would otherwise leave their own colors on the cut faces. -Y and +Y change places."""
    body = nx.dynamic_block(new_part).GetBodies()[0]
    axes = (NXOpen.Vector3d(1.0, 0.0, 0.0), NXOpen.Vector3d(0.0, 1.0, 0.0), NXOpen.Vector3d(0.0, 0.0, 1.0))
    planar = _planar_faces(body)
    for (axis, sign), color in source.side_colors.items():
        for face in _outer_faces(body, _side_normal(axes, (axis, -sign if axis == 1 else sign)), planar):
            nx.set_color(face, color)


def _copy_expressions(new_part: NXOpen.BasePart, source: _Source) -> None:
    for name, expression in _expressions_of(new_part).items():
        if name in source.expressions:
            expression.RightHandSide = source.expressions[name]


@nx.traced("Mirror Merlin")
def _read_plan(component: NXOpen.Assemblies.Component) -> _Plan:
    """
    Everything build needs from component, an occurrence under the display part, which has to be the top assembly.
    Relinks its broken links first. Leaves the top displayed, and the assembly holding the source the work part.
    """
    _step("  checking for broken links")
    _repair_broken_links(component)
    _step("  reading the source")
    source = _read_source(component)
    corner, x_axis, y_axis, z_axis = _mirrored_frame(component, source.block)
    return _Plan(nx.display_part(), component, source, corner, x_axis, y_axis, z_axis,
                 [_in_holder(n.origin, n.x_axis, n.y_axis) for n in source.neighbours])


@nx.traced("Mirror Merlin")
def build(plan: _Plan) -> NXOpen.Assemblies.Component:
    """
    The mirrored detail of plan's component, in the same assembly. Any part can be displayed. Returns the new component,
    as promoted in that assembly. The caller puts the display and work parts back.
    """
    top, component, source = plan.top, plan.component, plan.source
    corner, x_axis, y_axis, z_axis, neighbour_frames = (plan.corner, plan.x_axis, plan.y_axis, plan.z_axis,
                                                        plan.neighbour_frames)
    block = source.block
    far_corner = _along(_along(_along(corner, x_axis, block.length), y_axis, block.width), z_axis, block.height)

    _step("  building the block")
    # Displayed, so the corners and the WCS the block is turned by are in one part's coordinates.
    holder = nx.prototype(cast(NXOpen.Assemblies.Component, component.Parent))
    nx.set_display_part(holder)
    nx.set_work_part(holder)
    holder.Layers.WorkLayer = 1
    feature = nx.create_block(corner, far_corner, x_axis, y_axis)
    nx.set_color(feature.GetBodies()[0], source.body_color)

    path = merlin._next_part_path(os.path.dirname(holder.FullPath), PartName)
    new_component = nine99._promote_to_named_component(feature, path)
    nine99._set_up_as_merlin_block(new_component, top, "{} X {} X {}".format(
        merlin._format_0_000(block.length), merlin._format_0_000(block.width), merlin._format_0_000(block.height)),
        source.material)

    new_part = nx.prototype(new_component)
    nx.set_attribute(new_part, "DETAIL NAME", source.detail_name)

    nx.set_display_part(new_part)
    nx.set_work_part(new_part)
    _copy_expressions(new_part, source)
    _step("  chamfers, offsets and blends on the block")
    chamfers = _make_chamfers(new_part, source)
    finishes = _make_block_finishes(new_part, source)

    new_part.Layers.WorkLayer = _SubtractLayer
    _step("  placing the children and neighbours")
    subtracted = _mirror_links(top, cast(NXOpen.Assemblies.Component, component.Parent), holder, new_component, new_part,
                               source, neighbour_frames)
    _step("  offsets, blends and colors on the cuts")
    finishes += _make_cut_finishes(new_part, source)
    _color_sides(new_part, source)
    _color_finishes(chamfers + finishes)
    # Last, and while it is displayed: a part's work layer can only be set then.
    new_part.Layers.WorkLayer = merlin.DetailWorkLayer
    nx.ufsession_.Modeling.Update()

    nx.syslog("Mirror Merlin: {} is {} mirrored, with {} chamfer(s), {} side offset(s), {} blend(s) and cut offset(s), "
              "{} child component(s), {} neighbour(s), {} outside link(s), {} extrude(s) and {} subtract(s).".format(
                  new_part.Leaf, source.part.Leaf, len(chamfers), len(source.side_offsets), len(finishes),
                  len(source.children), len(source.neighbours), len(source.far_links), len(source.extrudes),
                  subtracted))
    _step("  {} done: {} subtract(s)".format(new_part.Leaf, subtracted))
    if source.left_out:
        nx.syslog("Mirror Merlin: not carried over from {}: {}".format(source.part.Leaf, ", ".join(source.left_out)))
        _step("  not carried over: {}".format(", ".join(source.left_out)))
    return new_component


# ---------------------------------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------------------------------

def _refusal(component: NXOpen.Assemblies.Component) -> Optional[str]:
    """Why the component cannot be mirrored, or None."""
    if not nx.is_loaded(component):
        return "{} is not loaded.".format(component.DisplayName)
    part = nx.prototype(component)
    if _dynamic_block_or_none(part) is None:
        return "{} has no DYNAMIC BLOCK.".format(part.Leaf)
    if part.PartUnits != nx.display_part().PartUnits:
        return "{} is skipped: its units differ from {}'s.".format(part.Leaf, nx.display_part().Leaf)
    return None


def _read_plans(components: Sequence[NXOpen.Assemblies.Component], title: str) -> List[_Plan]:
    """The details that can be built, each read with the top displayed. One that fails costs only itself."""
    assert _progress is not None
    plans: List[_Plan] = []
    # A window pick brings fasteners, dowels and jacks along: dropped first, each part looked at once, and not an error.
    has_block: Dict[int, bool] = {}
    details = []
    for component in components:
        if nx.is_loaded(component):
            tag = nx.prototype(component).Tag
            if tag not in has_block:
                has_block[tag] = _dynamic_block_or_none(nx.prototype(component)) is not None
            if not has_block[tag]:
                continue
        details.append(component)
    if len(details) < len(components):
        nx.syslog("Mirror Merlin: {} of the {} picked components have no DYNAMIC BLOCK and are left out.".format(
            len(components) - len(details), len(components)))
        _step("{} picked component(s) without a DYNAMIC BLOCK left out".format(len(components) - len(details)))
    components = details
    for index, component in enumerate(components):
        name = component.DisplayName
        nx.prompt("Mirror Merlin: reading {} ({} of {})".format(name, index + 1, len(components)))
        _progress.set_title("{} - reading {} ({} of {})".format(title, name, index + 1, len(components)))
        _step("Reading {} ({} of {})".format(name, index + 1, len(components)))
        try:
            refusal = _refusal(component)
            if refusal is not None:
                nx.error("Mirror Merlin: {}".format(refusal))
                _step("  skipped: {}".format(refusal))
                continue
            plans.append(_read_plan(component))
        except Exception as ex:
            nx.print_exception(ex, "Mirror Merlin: could not read {}".format(name))
            _step("  FAILED: {} (see the Information window)".format(ex))
    return plans


def run(components: Sequence[NXOpen.Assemblies.Component]) -> None:
    """
    Every picked detail read, then each built in turn; one that fails costs only itself. The display is suppressed and
    the top put back once, at the end. The progress window follows the run.
    """
    global _progress
    title = title_with_version("Mirror Merlin")
    _progress = progress_window.ProgressWindow(title, "MirrorMerlin", progress_window.BottomRight)
    started = time.time()
    built = 0
    plans: List[_Plan] = []
    try:
        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Mirror Merlin")
        top = nx.display_part()
        with nx.suppress_display(), nx.display_part_reset():
            try:
                plans = _read_plans(components, title)
                for index, plan in enumerate(plans):
                    name = plan.component.DisplayName
                    nx.prompt("Mirror Merlin: {} ({} of {})".format(name, index + 1, len(plans)))
                    _progress.set_title("{} - {} ({} of {})".format(title, name, index + 1, len(plans)))
                    _step("{} ({} of {})".format(name, index + 1, len(plans)))
                    try:
                        build(plan)
                        built += 1
                    except Exception as ex:
                        nx.print_exception(ex, "Mirror Merlin: could not mirror {}".format(name))
                        _step("  FAILED: {} (see the Information window)".format(ex))
            finally:
                # The strips' and layouts' reference sets the far links changed, once, with the top displayed.
                _show(top)
                nx.set_work_part(top)
                _restore_reference_sets()
    finally:
        minutes, seconds = divmod(int(round(time.time() - started)), 60)
        _progress.set_title("{} - finished".format(title))
        _step("Finished: {} of {} built in {}m {:02d}s".format(built, len(plans), minutes, seconds))
        _progress.stop_following()
        _progress = None


def execute() -> None:
    units_ok, message = drawdie._check_info_units()
    if not units_ok:
        nx.show_error(message)
        return

    components = nx.select_many_components("Select dynamic block details to mirror",
                                           title_with_version("Mirror Merlin"))
    if not components:
        nx.mark_cancelled("the component pick")
        return
    run(components)


def main() -> None:
    """The mirror-merlin UFunc - its menu button runs this file. An escaping exception is printed."""
    with nx.merlin_run(ufunc_name):
        try:
            # No confirm: it starts with the component pick, which the user can cancel.
            execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
