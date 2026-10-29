"""
Python port of the cast-post UFunc (Merlin.StaticGmCastPost / Merlin.BuildGmCastPosts, src\\UFuncs\\Merlin.cs,
region "GM Post - Entry Points, Builders, Keys & Feet").
The C# wrapper was deleted 2026-10-22 (in git at 1cb53d8): the UFunc's menu button runs this file's main().

Run from an upper or lower station (uad/upd/ush/usp or lad/lsh/lsp as the work part). Select the part bodies; each
body gets its own post, built into the station: the body's box, +.375" on every side (rounded up to 1/8"), as an 8"
block, color 181. A lower post's bottom is 90 mm under the lowest point of its component's LWR-3D bodies, an upper
post's top 90 mm over the highest point of its UPR-3D bodies (each component is switched to that reference set to
measure, then put back). A component without it gets one Question box per run: Yes falls back on the picked body,
No cancels before anything is built. It is promoted to [cts-]cast-post (DESCRIPTION "{x} X {y} X {h}", MATERIAL ##, BODY,
DYNAMIC BLOCK, SUBTOOL on hidden layer 15), re-based onto the block (the opposite corner for an upper), and gets:
  - two 2"-tall feet extruded off the bottom (lower) or top (upper) long edges, 2.25" out in X, united, color 181,
    their outer edge blended .3";
  - the mounting face colored 42 (the -Z face is also colored 42 by FindBottomFace);
  - the GM POST CAST TEXT part imported at the centre, on layer 20;
  - 8 20mm-shcs-070-2x through the feet (CBORE subtracted from the post, then BODY), on layer 99;
  - 8 GM hoist rings on layer 99, not subtracted and kept out of the post's BODY reference set;
  - 4 keys (lower: PlaceKey; upper: PlaceGmCastPostUpperKeys, which turns the display part's WCS and restores it),
    the last key's prototype Save As'd as [cts-]cast-post-key-{token}.prt next to the post;
then the AutoSize UDO is switched off, DETAIL NAME / DESCRIPTION CAST FORM POST, and each picked body's component has
its UPR-3D / LWR-3D reference set linked in and subtracted from the post. BODY is set up in every loaded ancestor
assembly. Each body is caught on its own; the station is restored as display and work part after every post, and the
run ends back on the display part it started on with the starting work part.

Three ways in:
  - File -> Execute -> NX Open on this file runs main() with is_gm = True, as the cast-post UFunc does.
  - Session.Execute("CastPost.py", "CastPost", "execute", is_gm) from C# - gates and pick included.
  - Session.Execute("CastPost.py", "CastPost", "build", is_gm, is_upper, bodies, reference_set) - the build
    half only (Merlin.BuildGmCastPosts): no units gate, no upper/lower detection, no pick, no WCS reset. The work
    part must already be the station. This is what AutoDesign calls.

Differences from the C#:
  - The edge blend on each foot is an NXOpen EdgeBlendBuilder (the option set and multiple-seed-tangent rule of
    Globals.cs __CreateEdgeBlend, which mirrors SNAP's) instead of Snap.Create.EdgeBlend(".3in", edge), since SNAP is
    .NET-only. The radius is written in the part's units (.3 for an inch part, 7.62 for a millimetre one) rather than
    as the ".3in" string. The stubs have no EdgeBlendBuilder, so that block goes through Any.
  - The body box is nx.body_box. The C# builds eight NXOpen.Points on the box corners, takes their min/max and deletes
    them (one DoUpdate undo mark each) - the same box, without the temporary points or their undo marks.
  - The foot profile uses the curve's start/end at its parameter limits (WireStartHole._curve_start_point and a
    matching end-point evaluator), as Curve.__StartPoint/__EndPoint do; the extrude is WireStartHole._create_extrude
    (BasePart.__CreateExtrude). The four profile lines are made visible through Any (SetVisibility is not stubbed).
  - SubtractComponents is ported here rather than imported from PointComponent.py: the C# now skips a component
    whose reference set holds no solid bodies (with a print), which PointComponent._subtract_components predates.
  - The AutoSize UDO class can only be registered from C# (see tsg_nx.create_auto_size_udo). Run standalone in a
    session where TSG_Library never registered it, the post gets no UDO and there is nothing to switch off - both
    print and carry on.
  - The re-base reads the block size through UF_MODL_ask_block_parms (DrawDie._rebase_block_to_part_origin), since
    BlockFeatureBuilder.Length/Width/Height come back None in Python.
  - GFolder.create_or_null (print-only, result unused) in PromoteToComponent is not ported.

Kept from the C#: a body picked outside any component leaves a None in the subtract list, so that post fails in the
subtract (printed by the per-body handler) after it is otherwise built, as the C#'s null component does.

The Merlin helpers DrawDie.py, PointComponent.py, CastTrimPad.py and WireStartHole.py already port are imported from
them rather than copied.
"""

from __future__ import annotations

import datetime
import os
import sys
from typing import Any, Callable, Iterable, List, Optional, Sequence, Tuple, cast

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
import NXOpen.Layer  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
import PointComponent as merlin  # noqa: E402
import DrawDie as drawdie  # noqa: E402
import CastTrimPad as trimpad  # noqa: E402
import WireStartHole as wirestart  # noqa: E402

# ---------------------------------------------------------------------------------------------------
# Constants (Merlin's, inches unless the name says otherwise)
# ---------------------------------------------------------------------------------------------------

# Block: the body's box plus this much on every side, 8" tall. A lower post's bottom sits PostClearance under the
# lowest point of the LWR-3D bodies, an upper post's top PostClearance over the highest point of the UPR-3D bodies
# (the C# built every post from Z -4).
PostGrow = .375
PostHeight = 8.0
PostClearance = 90 / 25.4
PostColor = 181

# Feet: 2.25" out in X off the long edges, 2" tall, outer edge blended .3".
FootXOffset = 2.25
FootHeight = 2.0
FootBlendRadius = .3

_shcs20mm070Path = "G:\\0Library\\Fasteners\\Metric\\SocketHeadCapScrews-2X\\020-2x\\20mm-shcs-070-2x.prt"
_gmHoistRingPath = "G:\\0Library\\0Customer\\GM\\GM 16MM DIA PLDW Hoist Ring.prt"
_gmPostCastTextPath = "G:\\CTS\\junk\\blank-station-data\\GM POST CAST TEXT.prt"
_gmKeyPath = "G:\\0Library\\0Customer\\GM\\Smart GM Key.prt"
_ctsSmartKeyMetric = "G:\\0Library\\Keys\\Smart Key Metric.prt"

_VectorX = NXOpen.Vector3d(1.0, 0.0, 0.0)
_VectorXN = NXOpen.Vector3d(-1.0, 0.0, 0.0)
_VectorY = NXOpen.Vector3d(0.0, 1.0, 0.0)
_VectorYN = NXOpen.Vector3d(0.0, -1.0, 0.0)
_VectorZ = NXOpen.Vector3d(0.0, 0.0, 1.0)
_VectorZN = NXOpen.Vector3d(0.0, 0.0, -1.0)


class CastPost(object):

    @staticmethod
    def execute(is_gm: bool = True) -> None:
        """Merlin.StaticGmCastPost(is_gm) - the cast-post UFunc passes is_gm = True."""
        static_gm_cast_post(bool(is_gm))

    @staticmethod
    def build(is_gm: bool, is_upper: bool, bodies: Sequence[NXOpen.TaggedObject], reference_set: str,
              quiet: bool = False, refsets_confirmed: bool = False) -> None:
        """
        Merlin.BuildGmCastPosts(is_gm, is_upper, bodies, reference_set) - the build half, on bodies the caller already
        picked. No gates and no pick: the work part must be the station. reference_set is UPR-3D / LWR-3D. quiet
        leaves out the elapsed time and "Created reference set" lines (AutoDesign). refsets_confirmed skips the
        missing-reference-set question, for a caller that already asked (AutoDesign's restrike, once for both posts).
        """
        with nx.quiet_listing(quiet):
            build_gm_cast_posts(bool(is_gm), bool(is_upper), [cast(NXOpen.Body, body) for body in bodies],
                                str(reference_set), bool(refsets_confirmed))


def static_gm_cast_post(is_gm: bool) -> None:
    """
    Merlin.StaticGmCastPost - TryBeginGmEntry (units gate, upper/lower from the work part, body pick, UPR-3D /
    LWR-3D, WCS to absolute), then BuildGmCastPosts.
    """
    ok, message = drawdie._check_info_units()
    if not ok:
        nx.show_error(message)
        return

    is_upper = trimpad._try_detect_is_upper()
    if is_upper is None:
        return

    label = "Cast Post"
    version = nx.assembly_file_version()
    bodies = drawdie._select_bodies("Select solid bodies for {}: {}".format(label, version),
                                    "{}: {}".format(label, version))
    if len(bodies) == 0:
        return

    reference_set = "UPR-3D" if is_upper else "LWR-3D"
    drawdie._set_wcs_to_absolute(nx.display_part())

    build_gm_cast_posts(is_gm, is_upper, bodies, reference_set)


def build_gm_cast_posts(is_gm: bool, is_upper: bool, bodies: List[NXOpen.Body], reference_set: str,
                        refsets_confirmed: bool = False) -> None:
    """
    Merlin.BuildGmCastPosts - one post per body, built into the work part's station and subtracting reference_set.
    Each body is caught on its own and the station is restored after it; the run ends on the starting display part
    with the starting work part.
    """
    top_level = nx.display_part()
    starting_work = nx.work_part()

    # Everything read off the picked bodies is captured up front: measuring a reference set, and every post's
    # subtract, switch the components' reference sets, which kills the picked body occurrences.
    picked = [(nx.body_box(body), body.OwningComponent) for body in bodies]

    # Distinct, in pick order - a body outside any component leaves a None, as the C#'s HashSet keeps its null.
    selected_components: List[Optional[NXOpen.Assemblies.Component]] = []
    for _, comp in picked:
        if not any(_same_component(comp, seen) for seen in selected_components):
            selected_components.append(comp)
    components = [c for c in selected_components if c is not None]

    # The post's Z comes off the components' reference_set bodies (UPR-3D top / LWR-3D bottom). A caller that asked
    # already (refsets_confirmed) is not asked again; a missing set still falls back on the picked body.
    if not refsets_confirmed and not nx.confirm_missing_reference_sets(
            "Cast Post", "The {} post is placed off {}".format("upper" if is_upper else "lower", reference_set),
            components, (reference_set,)):
        return
    z_boxes = {c.Tag: nx.reference_set_box(c, reference_set, "Cast Post") for c in components}

    nx.set_display_part(nx.work_part())

    start = datetime.datetime.now()
    try:
        for i, (box, comp) in enumerate(picked):
            nx.prompt("{} of {} -> {} cast post".format(i + 1, len(picked), "upper" if is_upper else "lower"))
            try:
                z_box = (z_boxes.get(comp.Tag) if comp is not None else None) or box
                _build_one_post(is_gm, is_upper, box, z_box, selected_components, reference_set, top_level)
            except Exception as ex:
                nx.print_exception(ex)
            finally:
                # Every post builds into the station: the block and the promote both go through the display part.
                # The body switches to top_level part-way (the occurrence lookups need the -000 tree), so the
                # station is restored here - otherwise the next body would build its block into the -000, and a
                # mid-body failure would leave it building inside the half-finished post part.
                nx.set_display_part(starting_work)
                nx.set_work_part(nx.display_part())
    finally:
        # Session.__UsingTimer prints the elapsed TimeSpan.
        if not nx.quiet:
            nx.warn(drawdie._time_span(datetime.datetime.now() - start))

    # Leave the session on the -000 with the work part we started on.
    nx.set_display_part(top_level)
    nx.set_work_part(starting_work)


def _build_one_post(is_gm: bool, is_upper: bool, box: nx.Box3d, z_box: nx.Box3d,
                    selected_components: List[Optional[NXOpen.Assemblies.Component]], reference_set: str,
                    top_level: NXOpen.Part) -> None:
    """
    One post over the picked body's box. z_box (the component's UPR-3D / LWR-3D bodies, or the picked body) sets Z:
    a lower post's bottom is PostClearance under its lowest point, an upper post's top PostClearance over its highest.
    """
    # gm post
    # - feet don't move when we dynamically stretch the block.
    length = box.MaxX - box.MinX
    width = box.MaxY - box.MinY
    height = box.MaxZ - box.MinZ
    xlength = nx.round_to_125(length) + PostGrow * 2
    ywidth = nx.round_to_125(width) + PostGrow * 2
    nx.display_part().Layers.WorkLayer = 1

    block_origin = NXOpen.Point3d(box.MinX - (xlength - length) / 2,
                                  box.MinY - (ywidth - width) / 2,
                                  z_box.MaxZ + PostClearance - PostHeight if is_upper
                                  else z_box.MinZ - PostClearance)

    block = drawdie._create_block_origin_and_lengths(block_origin, xlength, ywidth, PostHeight)
    nx.set_color(block.GetBodies()[0], PostColor)

    new_part, post_component = _promote_to_component(
        block,
        "{} X {} X {}".format(nx.cs_double_str(xlength), nx.cs_double_str(ywidth), nx.cs_double_str(height)),
        "cast-post" if is_gm else "cts-cast-post",
        rebase_to_block=True,
        opposite_corner=is_upper)

    # The post part's origin is now the block's corner (a pure translation - the block is built at the assembly's
    # absolute orientation, so there is no rotation to undo). Everything below is placed *inside* that part, so it
    # measures from the part origin instead of the assembly-space corner the block was built at.
    block_origin = NXOpen.Point3d(0.0, 0.0, 0.0)

    bottom_face = _find_bottom_face()
    solid_body = bottom_face.GetBody()
    vec = _VectorZN if is_upper else _VectorZ

    if not is_upper:
        _extrude_foot_from_edge(ywidth, solid_body, +FootXOffset, src_max_x=True, src_max_z=False,
                                extrude_dir=_VectorZ, edge_name="bottom right")
        _extrude_foot_from_edge(ywidth, solid_body, -FootXOffset, src_max_x=False, src_max_z=False,
                                extrude_dir=_VectorZ, edge_name="bottom left")
    else:
        _extrude_foot_from_edge(ywidth, solid_body, +FootXOffset, src_max_x=True, src_max_z=True,
                                extrude_dir=_VectorZN, edge_name="top right")
        _extrude_foot_from_edge(ywidth, solid_body, -FootXOffset, src_max_x=False, src_max_z=True,
                                extrude_dir=_VectorZN, edge_name="top left")

    mounting_face = nx.planar_face_with_normal_or_null(trimpad._single_solid_body_on_layer1(nx.display_part()),
                                                       nx.negate(vec))
    if mounting_face is None:
        raise RuntimeError("Sequence contains no matching element")
    nx.set_color(mounting_face, 42)
    trimpad._import_cast_text(nx.work_part(), _gmPostCastTextPath, xlength, ywidth, block_origin)
    body_reference_set = nx.find_reference_set_or_null(nx.display_part(), "BODY")
    if body_reference_set is None:
        raise RuntimeError("{} has no BODY reference set".format(nx.display_part().Leaf))

    orientation = drawdie._z_matrix(_VectorZN if is_upper else _VectorZ)
    z_top = 8.0 if is_upper else 0.0

    def at(x: float, y: float, z: float) -> NXOpen.Point3d:
        return NXOpen.Point3d(block_origin.X + x, block_origin.Y + y, block_origin.Z + z)

    display = nx.display_part()
    fasteners = [nx.add_component(display, _shcs20mm070Path, "CBORE", None, at(x, y, z_top), orientation, 99)
                 for x, y in (
                     (-1.125, 1.125),                     # -X foot, front corner (-Y): left of MinX, near MinY
                     (1.125 + xlength, 1.125),            # +X foot, front corner (-Y): right of MaxX, near MinY
                     (-1.125, ywidth / 4),                # -X foot, lower-mid: left of MinX, 1/4 up in Y
                     (-1.125, ywidth / 4 * 3),            # -X foot, upper-mid: left of MinX, 3/4 up in Y
                     (xlength + 1.125, ywidth / 4),       # +X foot, lower-mid: right of MaxX, 1/4 up in Y
                     (xlength + 1.125, ywidth / 4 * 3),   # +X foot, upper-mid: right of MaxX, 3/4 up in Y
                     (xlength + 1.125, ywidth - 1.125),   # +X foot, back corner (+Y): right of MaxX, near MaxY
                     (-1.125, ywidth - 1.125))]           # -X foot, back corner (+Y): left of MinX, near MaxY

    _subtract_and_refset_fasteners(fasteners, bottom_face, body_reference_set)

    # 8 GM 16mm hoist rings on layer 99 - not subtracted from the post, and kept out of its BODY reference set.
    # 4 on the X faces (beyond the feet) at Y=10 / ywidth-10, and 4 on the Y faces (front/back) 3" inboard of each
    # edge foot.
    ring_z = 8 - 1 if is_upper else 1.0
    ring_standoff = 1.825 / 25.4
    for x, y, direction in (
            (-2.375 - ring_standoff, 10.0, _VectorXN),               # -X side, front (faces -X)
            (-2.375 - ring_standoff, ywidth - 10, _VectorXN),        # -X side, back (faces -X)
            (xlength + 2.375 + ring_standoff, 10.0, _VectorX),       # +X side, front (faces +X)
            (xlength + 2.375 + ring_standoff, ywidth - 10, _VectorX),  # +X side, back (faces +X)
            (0.75, -0.125 - ring_standoff, _VectorYN),               # -Y face, near left foot
            (xlength - 0.75, -0.125 - ring_standoff, _VectorYN),     # -Y face, near right foot
            (0.75, ywidth + 0.125 + ring_standoff, _VectorY),        # +Y face, near left foot
            (xlength - 0.75, ywidth + 0.125 + ring_standoff, _VectorY),  # +Y face, near right foot
    ):
        nx.add_component(display, _gmHoistRingPath, "BODY", None, at(x, y, ring_z), drawdie._z_matrix(direction), 99)

    prefix = "" if is_gm else "cts-"

    if not is_upper:
        side_key_orientation = nx.matrix_from_axes(_VectorYN, _VectorX)
        keys = [
            # -Y edge (front): X-centered, sitting near MinY (nudged +Y toward center)
            _place_key(at(xlength / 2, 1.5 + 1.9 / 25.4, 0.0), side_key_orientation, layer=99, is_gm=is_gm),
            # +X edge (right): Y-centered, sitting near MaxX (nudged -X toward center)
            _place_key(at(xlength + (1.5 - .625) - 1.9 / 25.4 - .125, ywidth / 2, 0.0), layer=99, is_gm=is_gm),
            # -X edge (left): Y-centered, sitting near MinX (nudged +X toward center)
            _place_key(at(-(1.5 - .625) + 1.9 / 25.4 + .125, ywidth / 2, 0.0), layer=99, is_gm=is_gm),
            # +Y edge (back): X-centered, sitting near MaxY (nudged -Y toward center)
            _place_key(at(xlength / 2, ywidth - 1.5 - 1.9 / 25.4, 0.0), side_key_orientation, layer=99,
                       is_gm=is_gm),
        ]

        body_reference_set.AddObjectsToReferenceSet(keys)
        nx.prototype(keys[0]).SaveAs("{}\\{}cast-post-key-{}.prt".format(
            os.path.dirname(nx.display_part().FullPath), prefix, merlin._random_file_token()))
    else:
        current_wcs, key = _place_gm_cast_post_upper_keys(is_upper, xlength, ywidth, block_origin,
                                                          body_reference_set, orientation, is_gm)
        body_reference_set.AddObjectsToReferenceSet([key])
        nx.prototype(key).SaveAs("{}\\{}cast-post-key-{}.prt".format(
            os.path.dirname(nx.display_part().FullPath), prefix, merlin._random_file_token()))
        nx.display_part().WCS.SetOriginAndMatrix(NXOpen.Point3d(0.0, 0.0, 0.0), current_wcs)

    # Cast details are not resized - force the AutoSize UDO off (UDO + AUTO UPDATE attribute).
    post_proto = nx.prototype(post_component)
    drawdie._switch_auto_size_off(post_proto)
    nx.find_or_create_reference_set(post_component.OwningPart, "BODY").AddObjectsToReferenceSet([post_component])
    nx.set_reference_set(post_component, "BODY")
    nx.set_attribute(post_proto, "DETAIL NAME", "CAST FORM POST")
    nx.set_attribute(post_proto, "DESCRIPTION", "CAST FORM POST")
    new_part.Layers.WorkLayer = 1
    nx.set_display_part(top_level)
    nx.set_work_part(new_part)
    new_comp = nx.first_occurrence_in(new_part, nx.display_part())

    nx.set_work_part(new_part)
    new_part.Layers.SetState(1, NXOpen.Layer.State.WorkLayer)
    new_part.Layers.SetState(15, NXOpen.Layer.State.Hidden)
    _subtract_components(lambda: nx.dynamic_block(nx.work_part()).GetBodies()[0],
                         cast(List[NXOpen.Assemblies.Component], selected_components), reference_set)
    nx.set_reference_set(new_comp, "BODY")
    # Propagate BODY as the used reference set to every ancestor assembly (start_work .. -000).
    merlin._set_reference_set_in_ancestor_assemblies(new_comp)
    new_comp.Unblank()
    new_part.Layers.WorkLayer = 1


# ---------------------------------------------------------------------------------------------------
# Merlin helpers
# ---------------------------------------------------------------------------------------------------

def _promote_to_component(block: NXOpen.Features.Block, description: str, text: str, rebase_to_block: bool = False,
                          opposite_corner: bool = False) -> Tuple[NXOpen.Part, NXOpen.Assemblies.Component]:
    """
    Merlin.PromoteToComponent - CreateCtsComponent, optionally RebaseBlockToPartOrigin, the station expressions,
    every body into BODY, the first block named DYNAMIC BLOCK, DESCRIPTION / MATERIAL ##, and a SUBTOOL on layer 15
    (hidden). Returns the new part (the display part by then) and its component.
    """
    component = merlin._create_cts_component(block, text)
    if rebase_to_block:
        drawdie._rebase_block_to_part_origin(component, cast(NXOpen.Part, component.OwningPart),
                                             opposite_corner=opposite_corner)
    nx.setup_station_expressions(nx.work_part())
    refset = nx.find_or_create_reference_set(nx.display_part(), "BODY")
    refset.AddObjectsToReferenceSet(list(nx.display_part().Bodies))
    new_part = nx.display_part()
    first_block = nx.first_block_feature(new_part)
    if first_block is None:
        raise RuntimeError("Sequence contains no elements")
    first_block.SetName("DYNAMIC BLOCK")
    nx.set_attribute(new_part, "DESCRIPTION", description)
    nx.set_attribute(new_part, "MATERIAL", "##")
    new_part.Layers.WorkLayer = 15
    merlin._create_subtool(new_part)
    new_part.Layers.WorkLayer = 1
    new_part.Layers.SetState(15, NXOpen.Layer.State.Hidden)
    return new_part, component


def _find_bottom_face() -> NXOpen.Face:
    """Merlin.FindBottomFace - the planar -Z face of the display part's layer-1 solid body, colored 42."""
    bottom_face = nx.planar_face_with_normal_or_null(trimpad._single_solid_body_on_layer1(nx.display_part()),
                                                     _VectorZN)
    if bottom_face is None:
        raise RuntimeError("Sequence contains no matching element")
    nx.set_color(bottom_face, 42)
    return bottom_face


def _subtract_and_refset_fasteners(fasteners: Sequence[NXOpen.Assemblies.Component], bottom_face: NXOpen.Face,
                                   body_refset: Optional[NXOpen.ReferenceSet]) -> None:
    """
    Merlin.SubtractAndRefsetFasteners - work layer 96; each fastener (arriving on the reference set it is
    subtracted with) is linked and subtracted from bottom_face's body, stamped with the subtract attribute, then put
    on Empty (layer 98) or on BODY and added to body_refset (None leaves it out). Per-fastener try/except.
    """
    nx.display_part().Layers.WorkLayer = 96
    for fastener in fasteners:
        try:
            # The fastener arrives on the reference set it is subtracted with (CBORE, SHORT-TAP, ...).
            subtract_refset = fastener.ReferenceSet
            link = nx.create_linked_body(fastener)
            # Part.__SubtractLinkedBody builds in the display part; it is also the work part here.
            nx.subtract(bottom_face.GetBody(), link.GetBodies())
            drawdie._stamp_fastener_subtract(fastener, subtract_refset)
            if fastener.Layer == 98:
                nx.set_reference_set(fastener, nx.RefsetEmpty)
                continue
            nx.set_reference_set(fastener, "BODY")
            # None leaves the fastener out of the part's BODY reference set.
            if body_refset is not None:
                body_refset.AddObjectsToReferenceSet([fastener])
        except Exception as ex:
            nx.print_exception(ex)


def _subtract_components(get_target: Callable[[], NXOpen.Body],
                         components: Iterable[NXOpen.Assemblies.Component], refset: str) -> None:
    """
    Merlin.SubtractComponents - per component: skip with a print unless its part has refset; switch to refset,
    skip with a print when that holds no solid bodies, link and subtract from get_target() (re-fetched each time,
    since a boolean can replace the body); NXException 3520001 prints its own line; BODY restored in a finally.
    """
    for comp in components:
        if not nx.has_reference_set(nx.prototype(comp), refset):
            nx.warn("Component {} does not have reference set {}, skipping boolean".format(comp.DisplayName, refset))
            continue

        try:
            nx.set_reference_set(comp, refset)

            # Only solid bodies are linked - a reference set holding nothing but sheets (a binder surface, say) would
            # otherwise fail in the boolean with an error that does not say why.
            if len(nx.solid_body_members(comp)) == 0:
                nx.warn("Component {}: reference set {} has no solid bodies, skipping boolean".format(
                    comp.DisplayName, refset))
                continue

            linked = nx.create_linked_body(comp)
            nx.subtract(get_target(), linked.GetBodies())
        except NXOpen.NXException as ex:
            if ex.ErrorCode == merlin.ErrorBooleanFailed:
                nx.print_("Failed to boolean {} with reference set {}".format(comp.DisplayName, refset))
            nx.print_exception(ex)
        except Exception as ex:
            nx.print_exception(ex)
        finally:
            nx.set_reference_set(comp, "BODY")


def _place_key(origin: NXOpen.Point3d, orientation: Optional[NXOpen.Matrix3x3] = None, layer: int = 1,
               reference_set: str = "BODY", is_gm: bool = True) -> NXOpen.Assemblies.Component:
    """Merlin.PlaceKey - a Smart GM Key (or the CTS Smart Key Metric) into the display part."""
    return nx.add_component(nx.display_part(), _gmKeyPath if is_gm else _ctsSmartKeyMetric, reference_set, None,
                            origin, orientation, layer)


def _place_gm_cast_post_upper_keys(is_upper: bool, xlength: float, ywidth: float, block_origin: NXOpen.Point3d,
                                   body_reference_set: NXOpen.ReferenceSet, orientation: NXOpen.Matrix3x3,
                                   is_gm: bool) -> Tuple[NXOpen.Matrix3x3, NXOpen.Assemblies.Component]:
    """
    Merlin.PlaceGmCastPostUpperKeys - the +X / -X keys at orientation (into BODY), then the display part's WCS set to
    orientation and turned 90 degrees about Z, and the +Y key (into BODY) and -Y key at that WCS orientation. Returns
    the WCS orientation from before (the caller restores it) and the -Y key (the caller adds it to BODY).
    """
    path = _gmKeyPath if is_gm else _ctsSmartKeyMetric
    z = 8.0 if is_upper else 0.0
    display = nx.display_part()

    def at(x: float, y: float) -> NXOpen.Point3d:
        return NXOpen.Point3d(block_origin.X + x, block_origin.Y + y, block_origin.Z + z)

    keys = [
        # +X edge (right): Y-centered, sitting near MaxX
        nx.add_component(display, path, "BODY", None, at(xlength + (1.5 - .625) - 1.9 / 25.4 - .125, ywidth / 2),
                         orientation, 99),
        # -X edge (left): Y-centered, sitting near MinX
        nx.add_component(display, path, "BODY", None, at(-(1.5 - .625) + 1.9 / 25.4 + .125, ywidth / 2),
                         orientation, 99),
    ]

    body_reference_set.AddObjectsToReferenceSet(keys)

    wcs = nx.display_part().WCS
    current_wcs = wcs.CoordinateSystem.Orientation.Element
    wcs.SetOriginAndMatrix(NXOpen.Point3d(0.0, 0.0, 0.0), orientation)
    wcs.Rotate(NXOpen.WCS.Axis.ZAxis, 90.0)

    # +Y edge (back): X-centered, sitting near MaxY
    key = nx.add_component(display, path, "BODY", None, at(xlength / 2, ywidth - 1.5 - 1.9 / 25.4),
                           wcs.CoordinateSystem.Orientation.Element, 99)
    body_reference_set.AddObjectsToReferenceSet([key])
    # -Y edge (front): X-centered, sitting near MinY
    key = nx.add_component(display, path, "BODY", None, at(xlength / 2, 1.5 + 1.9 / 25.4),
                           wcs.CoordinateSystem.Orientation.Element, 99)
    return current_wcs, key


def _extrude_foot_from_edge(ywidth: float, solid_body: NXOpen.Body, x_offset: float, src_max_x: bool,
                            src_max_z: bool, extrude_dir: NXOpen.Vector3d, edge_name: str,
                            foot_height: float = FootHeight) -> None:
    """
    Merlin.ExtrudeFootFromEdge - the display part's layer-1 solid body's ywidth-long edge at max/min X then max/min Z
    is named edge_name and turned into a curve; a closed 4-line profile x_offset out in X is extruded foot_height
    along extrude_dir, united onto solid_body (color 181), and the foot's outer ywidth-long edge blended .3".
    """
    display = nx.display_part()
    layer1 = _solid_body_layer1_or_null(display)
    if layer1 is None:
        raise RuntimeError("{} has no single solid body on layer 1".format(display.Leaf))

    all_edges = [e for e in layer1.GetEdges() if nx.doubles_equal(e.GetLength(), ywidth)]
    edge = _first(_order(all_edges, descending_x=src_max_x, descending_z=src_max_z))

    edge.SetName(edge_name)
    curve = nx.edge_to_curve(edge)
    start = wirestart._curve_start_point(curve)
    end = _curve_end_point(curve)
    lines: List[NXOpen.Curve] = [
        _create_line(display, _add_x(start, x_offset), start),
        _create_line(display, _add_x(end, x_offset), end),
        _create_line(display, _add_x(end, x_offset), _add_x(start, x_offset)),
        cast(NXOpen.Line, curve),
    ]
    foot = wirestart._create_extrude(display, lines, extrude_dir, 0.0, foot_height)
    united = nx.create_boolean(solid_body, [foot.GetBodies()[0]], NXOpen.Features.Feature.BooleanType.Unite)
    nx.set_color(united.GetBodies()[0], PostColor)
    target_edges = [e for e in foot.GetEdges() if nx.doubles_equal(e.GetLength(), ywidth)]
    # -X foot: its outer edge is the max-X, max-Z one; +X foot: min-X, max-Z.
    target_edge = _first(_order(target_edges, descending_x=x_offset < 0, descending_z=True))
    _create_edge_blend(FootBlendRadius, target_edge)


def _create_edge_blend(radius_inches: float, edge: NXOpen.Edge) -> NXOpen.Features.Feature:
    """
    Snap.Create.EdgeBlend(".3in", edge), as an NXOpen EdgeBlendBuilder in the work part with the option set of
    Globals.cs __CreateEdgeBlend (SNAP's): a multiple-seed-tangent edge rule at the angle tolerance, roll over smooth
    edges / onto edges, convex first, setback separate from corner. The radius is written in the part's units. The
    stubs have no EdgeBlendBuilder, so the builder is Any.
    """
    part = nx.work_part()
    radius = radius_inches * 25.4 if part.PartUnits == NXOpen.BasePart.Units.Millimeters else radius_inches
    features = cast(Any, part.Features)
    builder = features.CreateEdgeBlendBuilder(None)
    try:
        _ = builder.LimitsListData
        collector = part.ScCollectors.CreateCollector()
        modeling = cast(Any, part.Preferences).Modeling
        rule = cast(Any, part.ScRuleFactory).CreateRuleEdgeMultipleSeedTangent([edge], modeling.AngleToleranceData,
                                                                                 True)
        collector.ReplaceRules([rule], False)
        builder.Tolerance = nx.distance_tolerance()
        builder.AllInstancesOption = False
        builder.RemoveSelfIntersection = True
        builder.ConvexConcaveY = False
        builder.RollOverSmoothEdge = True
        builder.RollOntoEdge = True
        builder.MoveSharpEdge = True
        builder.TrimmingOption = False
        edge_blend_builder = cast(Any, NXOpen.Features).EdgeBlendBuilder
        builder.OverlapOption = edge_blend_builder.Overlap.AnyConvexityRollOver
        builder.BlendOrder = edge_blend_builder.OrderOfBlending.ConvexFirst
        builder.SetbackOption = edge_blend_builder.Setback.SeparateFromCorner
        builder.AddChainset(collector, nx.cs_double_str(radius))
        return cast(NXOpen.Features.Feature, builder.CommitFeature())
    finally:
        builder.Destroy()


# ---------------------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------------------

def _same_component(a: Optional[NXOpen.Assemblies.Component], b: Optional[NXOpen.Assemblies.Component]) -> bool:
    """HashSet<Component> equality - by tag, with null equal only to null."""
    if a is None or b is None:
        return a is None and b is None
    return a.Tag == b.Tag


def _solid_body_layer1_or_null(part: NXOpen.Part) -> Optional[NXOpen.Body]:
    """BasePart.__SolidBodyLayer1OrNull - the only non-occurrence solid body on layer 1, else None."""
    bodies = [b for b in part.Bodies if not b.IsOccurrence and b.IsSolidBody and b.Layer == 1]
    return bodies[0] if len(bodies) == 1 else None


def _order(edges: List[NXOpen.Edge], descending_x: bool, descending_z: bool) -> List[NXOpen.Edge]:
    """OrderBy[Descending](StartPoint.X).ThenBy[Descending](StartPoint.Z) - stable, like LINQ."""
    def key(edge: NXOpen.Edge) -> Tuple[float, float]:
        point = nx.edge_start_point(edge)
        return (-point.X if descending_x else point.X, -point.Z if descending_z else point.Z)

    return sorted(edges, key=key)


def _first(edges: List[NXOpen.Edge]) -> NXOpen.Edge:
    """Enumerable.First - throws on an empty sequence."""
    if len(edges) == 0:
        raise RuntimeError("Sequence contains no elements")
    return edges[0]


def _curve_end_point(curve: NXOpen.Curve) -> NXOpen.Point3d:
    """Curve.__EndPoint - the point at the end of the parameter range (__MaxU/__Position)."""
    evaluator = nx.ufsession_.Eval.Initialize2(curve.Tag)
    limits = nx.ufsession_.Eval.AskLimits(evaluator)
    point = nx.ufsession_.Eval.EvaluateUnitVectors(evaluator, limits[1])[0]
    return NXOpen.Point3d(point[0], point[1], point[2])


def _create_line(part: NXOpen.Part, start: NXOpen.Point3d, end: NXOpen.Point3d) -> NXOpen.Line:
    """BasePart.__CreateLine(Point3d, Point3d) - a visible line, redisplayed."""
    line = part.Curves.CreateLine(start, end)
    # SmartObject.SetVisibility / VisibilityOption are not stubbed.
    cast(Any, line).SetVisibility(cast(Any, NXOpen.SmartObject).VisibilityOption.Visible)
    line.RedisplayObject()
    return line


def _add_x(point: NXOpen.Point3d, x: float) -> NXOpen.Point3d:
    """Point3d.__AddX"""
    return NXOpen.Point3d(point.X + x, point.Y, point.Z)


def main() -> None:
    """The cast-post UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db
    from tsg_dialog import ask_is_gm

    with usage_db.run("cast-post"):
        try:
            # The Customer dialog stands in for the "Are you sure" box: GM builds with the GM parts, TSG throws.
            is_gm = ask_is_gm("Cast Post")
            if is_gm is not None:
                CastPost.execute(is_gm)
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
