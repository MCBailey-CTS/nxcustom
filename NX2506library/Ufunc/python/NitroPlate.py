"""
Python port of the nitro-plate-upper / nitro-plate-lower UFuncs (Merlin.StaticNitroPlateUpper /
Merlin.StaticNitroPlateLower, both over Merlin.BuildNitroPlate, src\\UFuncs\\Merlin.cs, region "Nitrogen Plate -
Upper & Lower").
The C# wrappers were deleted 2026-10-22 (in git at 1cb53d8): the UFuncs' menu buttons run this file's main()
(nitro-plate-upper) and NitroPlateLower.py.

Select the nitrogen cylinders (components; 4 expected, any count is built over with a print). The plate is sized off
every loaded solid body of the cylinders, children included: span rounded up to 1/8", centred, plus the spec's
overhang on every side. Its height comes from the cylinders' own layer-1 solid bodies (children left out - the SHCS
that hold a cylinder together stick out its top):
  - upper: bottom face on their highest point, 25 mm thick, extending +Z;
  - lower: top face on their lowest point, 50 mm thick, hanging under them.
The eight corners are mapped ROOT -> WORK, since the station is not at identity in the -000 (it is flipped upside
down), and the block is built from the box they span in the work part. Body color 13, top and bottom faces 42.
Promoted to {gm|cts}-nitro-plate-{upper|lower}, re-based onto the block (the opposite corner for the upper), then:
  - BODY refset, DYNAMIC BLOCK, the AutoSize update switched off BEFORE DESCRIPTION / DETAIL NAME "NITROGEN PLATE
    SYSTEM" and MATERIAL "DADCO" are stamped (the subtracts below would otherwise rewrite DESCRIPTION as a size);
  - SUBTOOL on hidden layer 15, its "top" face offset 3" and its sides 30 mm outward, recolored 2 with the "bottom"
    face 42, then each of its "bottom" face edges extruded 8 mm as a sheet, each sheet's face extruded 25 mm toward
    the subtool's centre and united onto it (all walls built before any unite). The lower reverses every Z face and
    direction;
  - 1" edge blends on the four vertical corner edges;
  - SHCS round the edge (corners, then ceil(span / 11.5") equal gaps per edge), CBORE subtracted from the body of the
    bottom face found once before any subtract, then put on BODY. Upper heads from the bottom pointing +Z, lower
    heads from the top pointing -Z;
  - 4 GM hoist rings on the top face (+Z, 12" in) and 4 on the bottom (-Z, 10" in), subtracted on
    NITRO_PLATE_HANDLING and kept out of BODY;
  - the Dadco control panel, turned 180 degrees in the upper's part (to cancel its upper-detail frame), moved flush
    into the plate's -Y / +X corner as seen in the -000, BODY refset when it has one, and added to BODY;
then BODY is set (and the plate added to BODY) in every loaded ancestor assembly.

Entry points:
  - Session.Execute("NitroPlate.py", "NitroPlateUpper", "execute", is_gm) / ("NitroPlate.py", "NitroPlateLower",
    "execute", is_gm) from C#: the units gate, WCS to absolute and the cylinder pick, then the build.
  - build_nitro_plate_upper(is_gm, cylinders) / build_nitro_plate_lower(is_gm, cylinders) - the build over cylinders
    already picked (Merlin.BuildNitroPlateUpper / BuildNitroPlateLower). The caller brings the units gate.
  - File -> Execute -> NX Open on this file runs main(): the upper plate with is_gm = True.

Differences from the C#:
  - Snap.Create.EdgeBlend / Snap.Create.OffsetFace (SNAP is .NET-only) become an NXOpen EdgeBlendBuilder (one
    chainset, the part's distance tolerance, the builder's other defaults) and an OffsetFaceBuilder (face-dumb rule,
    Direction False - the C# passes false straight through). The C# hands Snap "{value}in" strings; here the
    distances are written as plain numbers in the part's units (inches, x 25.4 in a metric part), as
    GmCastTrimPad.py does for its chamfer.
  - The SUBTOOL faces come from Body.GetFaces() rather than Snap.NX.Body.Faces - read once, before the offsets, as
    the C# reads them.
  - ExactBoundingBox's identity matrix and temporary csys are made with ufsession_.Mtx3.Initialize /
    ufsession_.Csys.CreateMatrix / CreateTempCsys, and the box with ufsession_.ModlGeneral.AskBoundingBoxExact
    (not Modl - see the README). Mtx3.Initialize and Csys.CreateMatrix are not in the stubs, so they are reached
    through Any; their signatures were read from NXOpen_UF.pyd.
  - Part.SubtractLinkedBody builds the boolean in the display part, nx.subtract in the work part. They are the same
    part here: the re-base leaves the new plate as both.
  - The AutoSize UDO class can only be registered from C# (see tsg_nx.create_auto_size_udo). Run standalone in a
    session where TSG_Library never registered it, the plate gets no UDO and there is nothing to switch off.
  - GFolder.create_or_null (print-only, result unused) is not ported.

The Merlin helpers DrawDie.py, PointComponent.py and GmCastTrimPad.py already port are imported from them rather than
copied.
"""

from __future__ import annotations

import math
import os
import sys
from typing import Any, Iterable, List, Optional, Sequence, Tuple, cast

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

import tsg_nx as nx  # noqa: E402
import PointComponent as merlin  # noqa: E402
import DrawDie as drawdie  # noqa: E402
import GmCastTrimPad as trimpad  # noqa: E402

# ---------------------------------------------------------------------------------------------------
# Constants (Merlin's, inches unless the name says otherwise)
# ---------------------------------------------------------------------------------------------------

_shcs16mm050Path = "G:\\0Library\\Fasteners\\Metric\\SocketHeadCapScrews-2X\\016-2x\\16mm-shcs-050-2x.prt"
_shcs20mm070Path = "G:\\0Library\\Fasteners\\Metric\\SocketHeadCapScrews-2X\\020-2x\\20mm-shcs-070-2x.prt"
_gmHoistRingPath = "G:\\0Library\\0Customer\\GM\\GM 16MM DIA PLDW Hoist Ring.prt"
_dadcoControlPanelPath = ("G:\\0Library\\0Customer\\GM\\Fittings - GM EO24 (Dadco D-24)\\"
                          "90.406V.P2N Control Panel.prt")

# The most the SHCS pitch along an edge may be: each edge's corner-to-corner span is divided into ceil(span / this)
# equal gaps.
NitroPlateMaxShcsPitch = 11.5

# The four +Z hoist rings sit this far in from each side, on the top face; the four -Z ones this far, on the bottom.
NitroPlateTopHoistRingInset = 12.0
NitroPlateBottomHoistRingInset = 10.0

NitroPlateColor = 13

# The hoist-ring reference set wave-linked and subtracted from the nitrogen plate.
NitroPlateHandlingRefset = "NITRO_PLATE_HANDLING"

# How far each SUBTOOL "bottom" face edge is extruded (part -Z for the upper - up in the main assembly).
NitroSubtoolEdgeExtrudeHeight = 8 / 25.4

# Color of every face the SUBTOOL edge extrudes create - the sheets and the walls united onto SUBTOOL.
NitroSubtoolExtrudeColor = 2

# How far each SUBTOOL edge sheet's face is extruded toward the centre of SUBTOOL.
NitroSubtoolWallThickness = 25 / 25.4

_UF_CSYS_ROOT_COORDS = 1
_UF_CSYS_WORK_COORDS = 2

_VectorZ = NXOpen.Vector3d(0.0, 0.0, 1.0)
_VectorZN = NXOpen.Vector3d(0.0, 0.0, -1.0)


def _rotated_about_z_180() -> NXOpen.Matrix3x3:
    """Merlin.RotatedAboutZ180 - the absolute orientation turned 180 degrees about Z: X and Y reversed, Z unchanged."""
    matrix = NXOpen.Matrix3x3()
    matrix.Xx, matrix.Xy, matrix.Xz = -1.0, 0.0, 0.0
    matrix.Yx, matrix.Yy, matrix.Yz = 0.0, -1.0, 0.0
    matrix.Zx, matrix.Zy, matrix.Zz = 0.0, 0.0, 1.0
    return matrix


class NitroPlateSpec(object):
    """Merlin.NitroPlateSpec - the values that differ between the upper and lower nitrogen plates."""

    def __init__(self, label: str, name_prefix: str, overhang: float, thickness: float, shcs_path: str,
                 shcs_inset: float, shcs_z: float, opposite_corner: bool, corner_blend_radius: float,
                 hoist_rings_in_body: bool, control_panel_at_corner: bool, below_blue: bool, shcs_from_top: bool,
                 subtool_top_offset: float, subtool_side_offset: float, z_offset: float,
                 subtool_flipped: bool) -> None:
        # Cue, undo-mark and title text, e.g. "Nitro Plate Upper".
        self.Label = label
        # The part name after the gm-/cts- prefix, e.g. "nitro-plate-upper".
        self.NamePrefix = name_prefix
        # How far the plate runs past the cylinders' bounding box on each of +X, -X, +Y and -Y.
        self.Overhang = overhang
        self.Thickness = thickness
        self.ShcsPath = shcs_path
        # SHCS centrelines in from the plate edges.
        self.ShcsInset = shcs_inset
        # SHCS origin (the head seat) above the bottom face - below the top face when ShcsFromTop.
        self.ShcsZ = shcs_z
        # RebaseBlockToPartOrigin's oppositeCorner: true for the upper (the upper-detail frame).
        self.OppositeCorner = opposite_corner
        # Edge-blend radius on the four vertical corner edges; 0 leaves them sharp.
        self.CornerBlendRadius = corner_blend_radius
        # Whether the hoist rings are members of the plate's BODY reference set.
        self.HoistRingsInBody = hoist_rings_in_body
        # True: the control panel goes in the plate's -Y / +X corner (as seen in the -000). False: the part origin.
        self.ControlPanelAtCorner = control_panel_at_corner
        # False: the plate sits on top of the layer-1 bodies. True: it hangs under them (name predates layer 1).
        self.BelowBlue = below_blue
        # False: SHCS heads from the bottom, pointing +Z. True: heads from the top, pointing -Z.
        self.ShcsFromTop = shcs_from_top
        # How far the SUBTOOL's "top" face (+Z, or -Z when SubtoolFlipped) and its four sides are offset outward.
        self.SubtoolTopOffset = subtool_top_offset
        self.SubtoolSideOffset = subtool_side_offset
        # Moves the whole plate in Z after it is seated; negative is down.
        self.ZOffset = z_offset
        # False (upper): grows in +Z, walled from its -Z face edges in -Z. True (lower): every Z reversed.
        self.SubtoolFlipped = subtool_flipped


# Upper: 25 mm plate, +2" overhang, 16mm-shcs-050-2x 1.125" in. The SHCS start 8 mm above the bottom and move down
# (1.0236" - 8 mm) in -Z, which puts the head seat 10 mm below the bottom face.
NitroPlateUpperSpec = NitroPlateSpec(
    label="Nitro Plate Upper",
    name_prefix="nitro-plate-upper",
    overhang=2.0,
    thickness=25 / 25.4,
    shcs_path=_shcs16mm050Path,
    shcs_inset=1.125,
    shcs_z=8 / 25.4 - (1.0236 - 8 / 25.4),
    opposite_corner=True,
    corner_blend_radius=1.0,
    hoist_rings_in_body=False,
    control_panel_at_corner=True,
    below_blue=False,
    shcs_from_top=False,
    subtool_top_offset=3.0,
    subtool_side_offset=30 / 25.4,
    z_offset=0,
    subtool_flipped=False)

# Lower: 50 mm plate, +2.75" overhang, 20mm-shcs-070-2x 1.375" in, hanging under the cylinders. SHCS flipped - heads
# from the top, pointing -Z; measured down from the top, so moving down adds and moving up subtracts.
NitroPlateLowerSpec = NitroPlateSpec(
    label="Nitro Plate Lower",
    name_prefix="nitro-plate-lower",
    overhang=2.75,
    thickness=50 / 25.4,
    shcs_path=_shcs20mm070Path,
    shcs_inset=1.375,
    shcs_z=28 / 25.4 - (1.0236 - 28 / 25.4) - 2.3622 + 28 / 25.4,
    opposite_corner=False,
    corner_blend_radius=1.0,
    hoist_rings_in_body=False,
    control_panel_at_corner=True,
    below_blue=True,
    shcs_from_top=True,
    subtool_top_offset=3.0,
    subtool_side_offset=30 / 25.4,
    z_offset=0,
    subtool_flipped=True)


class NitroPlateUpper(object):

    @staticmethod
    def execute(is_gm: bool = True) -> None:
        """Merlin.StaticNitroPlateUpper(is_gm) - the nitro-plate-upper UFunc passes is_gm = True."""
        _static_nitro_plate(is_gm, NitroPlateUpperSpec)


class NitroPlateLower(object):

    @staticmethod
    def execute(is_gm: bool = True) -> None:
        """Merlin.StaticNitroPlateLower(is_gm) - the nitro-plate-lower UFunc passes is_gm = True."""
        _static_nitro_plate(is_gm, NitroPlateLowerSpec)


def build_nitro_plate_upper(is_gm: bool, cylinders: Sequence[NXOpen.Assemblies.Component]) -> None:
    """Merlin.BuildNitroPlateUpper - the upper plate over cylinders already picked. The caller brings the units gate."""
    _build_nitro_plate(is_gm, NitroPlateUpperSpec, cylinders)


def build_nitro_plate_lower(is_gm: bool, cylinders: Sequence[NXOpen.Assemblies.Component]) -> None:
    """Merlin.BuildNitroPlateLower - see build_nitro_plate_upper."""
    _build_nitro_plate(is_gm, NitroPlateLowerSpec, cylinders)


def _static_nitro_plate(is_gm: bool, spec: NitroPlateSpec) -> None:
    """Merlin.BuildNitroPlate(is_gm, spec) - the units gate, WCS to absolute and the cylinder pick, then the build."""
    ok, message = drawdie._check_info_units()
    if not ok:
        nx.show_error(message)
        return

    drawdie._set_wcs_to_absolute(nx.display_part())

    title = "{}: {}".format(spec.Label, nx.assembly_file_version())
    picked = nx.select_many_components("Select the nitrogen cylinders for {}".format(title))

    if len(picked) == 0:
        return

    _build_nitro_plate(is_gm, spec, picked)


def _build_nitro_plate(is_gm: bool, spec: NitroPlateSpec, picked: Sequence[NXOpen.Assemblies.Component]) -> None:
    """Merlin.BuildNitroPlate(is_gm, spec, picked) - the shared nitrogen-plate build over cylinders already picked."""
    drawdie._set_wcs_to_absolute(nx.display_part())

    # Session.Execute hands a TaggedObject[] over as a sequence of NXOpen objects.
    cylinders = [cast(NXOpen.Assemblies.Component, c) for c in picked if c is not None]

    if len(cylinders) == 0:
        return

    if len(cylinders) != 4:
        nx.print_("{} cylinders selected - the plate is laid out for 4, building over what was picked.".format(
            len(cylinders)))

    bodies = _nitro_cylinder_bodies(cylinders)

    if len(bodies) == 0:
        nx.show_error("The selected cylinders have no loaded solid bodies.")
        return

    # Both are set against the cylinders' own layer-1 solid bodies - not their children, whose SHCS stick out the
    # top. Upper: the plate's bottom sits on their highest point. Lower: it hangs under them.
    layer1_bodies = _nitro_cylinder_layer1_bodies(cylinders)

    if len(layer1_bodies) == 0:
        nx.show_error("None of the selected cylinders has a solid body on layer 1, so the plate height cannot be found.")
        return

    layer1_min, layer1_max = _exact_bounding_box(layer1_bodies)
    if spec.BelowBlue:
        base_z = layer1_min.Z - spec.Thickness
        nx.print_("Lowest layer-1 solid body on the selected cylinders at Z {}.".format(_f4(layer1_min.Z)))
    else:
        base_z = layer1_max.Z
        nx.print_("Highest layer-1 solid body on the selected cylinders at Z {}.".format(_f4(base_z)))

    bottom_z = base_z + spec.ZOffset

    nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, spec.Label)
    starting_display = nx.display_part()
    starting_work = nx.work_part()

    try:
        _build(is_gm, spec, bodies, bottom_z, starting_display)
    except Exception as ex:
        nx.print_exception(ex)
    finally:
        # CreateCtsComponent leaves the new detail as the display/work part - put the session back.
        nx.set_display_part(starting_display)
        nx.set_work_part(starting_work)


def _build(is_gm: bool, spec: NitroPlateSpec, bodies: List[NXOpen.Body], bottom_z: float,
           starting_display: NXOpen.Part) -> None:
    """The try block of Merlin.BuildNitroPlate(is_gm, spec, picked)."""
    box_min, box_max = _exact_bounding_box(bodies)
    span_x = box_max.X - box_min.X
    span_y = box_max.Y - box_min.Y

    # Rounded up to the next 1/8" and centred on the cylinders, then the overhang added on every side.
    xlength = nx.round_to_125(span_x) + 2 * spec.Overhang
    ywidth = nx.round_to_125(span_y) + 2 * spec.Overhang
    block_origin = NXOpen.Point3d(box_min.X - (xlength - span_x) / 2,
                                  box_min.Y - (ywidth - span_y) / 2,
                                  bottom_z)

    # Everything above is in the display part's coordinates, but the block is built in the work part: map the
    # plate's eight corners into work coordinates and build the box they span there. Lengths are re-read too: a
    # 90 degree turn about Z swaps X and Y.
    work_corners = [list(nx.ufsession_.Csys.MapPoint(_UF_CSYS_ROOT_COORDS, [x, y, z], _UF_CSYS_WORK_COORDS))
                    for x in (block_origin.X, block_origin.X + xlength)
                    for y in (block_origin.Y, block_origin.Y + ywidth)
                    for z in (block_origin.Z, block_origin.Z + spec.Thickness)]
    work_min = NXOpen.Point3d(min(c[0] for c in work_corners), min(c[1] for c in work_corners),
                              min(c[2] for c in work_corners))
    work_max = NXOpen.Point3d(max(c[0] for c in work_corners), max(c[1] for c in work_corners),
                              max(c[2] for c in work_corners))
    work_x = work_max.X - work_min.X
    work_y = work_max.Y - work_min.Y
    work_z = work_max.Z - work_min.Z

    # Only a work part turned by multiples of 90 degrees keeps the plate a box with the same three lengths.
    expected = sorted([xlength, ywidth, spec.Thickness])
    actual = sorted([work_x, work_y, work_z])
    if any(abs(e - a) > .001 for e, a in zip(expected, actual)):
        nx.print_("{} is not square to the display part - the plate is built as the box {} x {} x {} around where it "
                  "belongs, not {} x {} x {}.".format(nx.work_part().Leaf, _f3(work_x), _f3(work_y), _f3(work_z),
                                                      _f3(xlength), _f3(ywidth), _f3(spec.Thickness)))

    if (not nx.doubles_equal(work_min.X, block_origin.X) or not nx.doubles_equal(work_min.Y, block_origin.Y)
            or not nx.doubles_equal(work_min.Z, block_origin.Z)):
        nx.print_("{} is not at identity in {} - plate corner mapped from ({}, {}, {}) to ({}, {}, {}) in the work "
                  "part.".format(nx.work_part().Leaf, nx.display_part().Leaf,
                                 _f4(block_origin.X), _f4(block_origin.Y), _f4(block_origin.Z),
                                 _f4(work_min.X), _f4(work_min.Y), _f4(work_min.Z)))

    xlength = work_x
    ywidth = work_y

    # (GFolder.create_or_null(disp) - print-only in the C#, not ported.)
    nx.work_part().Layers.WorkLayer = 1
    block = drawdie._create_block_origin_and_lengths(work_min, xlength, ywidth, work_z)

    # Color the whole body first - it colors every face, so the yellow faces have to come after.
    block_body = block.GetBodies()[0]
    nx.set_color(block_body, NitroPlateColor)
    for normal in (_VectorZ, _VectorZN):
        face = nx.planar_face_with_normal_or_null(block_body, normal)
        if face is not None:
            nx.set_color(face, 42)

    new_component = drawdie._create_new_component_core(
        ("gm-" if is_gm else "cts-") + spec.NamePrefix,
        [block_body],
        NXOpen.Assemblies.CreateNewComponentBuilder.ComponentOriginType.Absolute,
        NXOpen.Assemblies.CreateNewComponentBuilder.ComponentLayerOptionType.AsSpecified,
        layer_number=1, original_objects_deleted=True, auto_size_udo=True)

    # The upper is an upper detail: csys on the opposite corner; the lower keeps the block's own corner. Either way
    # the block fills X 0..L, Y 0..W, Z 0..H, and everything below is symmetric about the block centre.
    drawdie._rebase_block_to_part_origin(new_component, cast(NXOpen.Part, new_component.OwningPart),
                                         opposite_corner=spec.OppositeCorner)
    nx.find_or_create_reference_set(new_component.OwningPart, "BODY").AddObjectsToReferenceSet([new_component])

    new_part = nx.work_part()
    nx.setup_station_expressions(new_part)
    body_refset = nx.find_or_create_reference_set(new_part, "BODY")
    body_refset.AddObjectsToReferenceSet(list(new_part.Bodies))
    first_block = nx.first_block_feature(new_part)
    if first_block is None:
        raise RuntimeError("Sequence contains no elements")
    first_block.SetName("DYNAMIC BLOCK")

    # The DESCRIPTION is fixed text, not a size. Switch the AutoSize update off before stamping it: the SHCS and
    # hoist-ring subtracts below modify the body, and the UDO's update callback would rewrite DESCRIPTION.
    drawdie._switch_auto_size_off(new_part)

    nx.set_attribute(new_part, "DESCRIPTION", "NITROGEN PLATE SYSTEM")
    nx.set_attribute(new_part, "MATERIAL", "DADCO")
    nx.set_attribute(new_part, "DETAIL NAME", "NITROGEN PLATE SYSTEM")

    # Extract onto layer 15 (after BODY is populated so it is not added to BODY), grown and walled when the spec
    # says so.
    new_part.Layers.WorkLayer = 15
    if spec.SubtoolTopOffset > 0 or spec.SubtoolSideOffset > 0:
        subtool_up = _VectorZN if spec.SubtoolFlipped else _VectorZ
        subtool_body = merlin._create_subtool(new_part).GetBodies()[0]
        _grow_nitro_subtool(subtool_body, spec.SubtoolTopOffset, spec.SubtoolSideOffset, subtool_up)
        _extrude_nitro_subtool_bottom_edges(subtool_body, subtool_up)
    else:
        merlin._create_subtool(new_part)
    new_part.Layers.WorkLayer = 1
    new_part.Layers.SetState(15, NXOpen.Layer.State.Hidden)

    # Corner blends go on after the subtool, so the subtool keeps the square corners, and before every subtract,
    # while the block's only vertical edges are its four corners.
    if spec.CornerBlendRadius > 0:
        for edge in [e for e in nx.dynamic_block(new_part).GetBodies()[0].GetEdges() if trimpad._is_vertical(e)]:
            _edge_blend(spec.CornerBlendRadius, edge)

    # Found once, before any subtract: the counterbores cut from the bottom have -Z floors too.
    plate_bottom = _find_bottom_face()

    # Upper: heads from the bottom, origin ShcsZ above the bottom face, pointing +Z. Lower: flipped - origin ShcsZ
    # below the top face, pointing -Z. Dropped on CBORE so the subtract cuts the counterbore, then switched to BODY.
    shcs_orientation = drawdie._z_matrix(_VectorZN if spec.ShcsFromTop else _VectorZ)
    shcs_z = spec.Thickness - spec.ShcsZ if spec.ShcsFromTop else spec.ShcsZ
    shcs = [nx.add_component(nx.display_part(), spec.ShcsPath, "CBORE", None,
                             NXOpen.Point3d(point.X, point.Y, shcs_z), shcs_orientation, 99)
            for point in _nitro_plate_shcs_positions(xlength, ywidth, spec.ShcsInset)]
    _subtract_and_refset_fasteners(shcs, plate_bottom, body_refset)
    new_part.Layers.WorkLayer = 1

    if xlength < 2 * NitroPlateTopHoistRingInset or ywidth < 2 * NitroPlateTopHoistRingInset:
        nx.print_("The plate ({} x {}) is narrower than twice the {}\" hoist-ring inset - the +Z rings cross "
                  "over.".format(_f3(xlength), _f3(ywidth), nx.cs_double_str(NitroPlateTopHoistRingInset)))

    up = drawdie._z_matrix(_VectorZ)
    down = drawdie._z_matrix(_VectorZN)
    hoist_rings = ([nx.add_component(nx.display_part(), _gmHoistRingPath, "BODY", None,
                                     NXOpen.Point3d(point.X, point.Y, spec.Thickness), up, 99)
                    for point in drawdie._inset_corners(xlength, ywidth, NitroPlateTopHoistRingInset)]
                   + [nx.add_component(nx.display_part(), _gmHoistRingPath, "BODY", None,
                                       NXOpen.Point3d(point.X, point.Y, 0.0), down, 99)
                      for point in drawdie._inset_corners(xlength, ywidth, NitroPlateBottomHoistRingInset)])

    # Wave-link each ring on NITRO_PLATE_HANDLING and subtract it from the plate; the helper then puts it back on
    # BODY. The rings share one prototype, so a part without that refset skips all eight (with a print).
    ring_refset = body_refset if spec.HoistRingsInBody else None
    if len(hoist_rings) > 0 and _component_has_reference_set(hoist_rings[0], NitroPlateHandlingRefset):
        for ring in hoist_rings:
            nx.set_reference_set(ring, NitroPlateHandlingRefset)

        _subtract_and_refset_fasteners(hoist_rings, plate_bottom, ring_refset)
        new_part.Layers.WorkLayer = 1
    else:
        nx.print_("{} has no {} reference set - hoist rings not subtracted.".format(
            os.path.basename(_gmHoistRingPath), NitroPlateHandlingRefset))
        if ring_refset is not None:
            ring_refset.AddObjectsToReferenceSet(hoist_rings)

    # A reference set can be set to pick up new components automatically, so take the rings out explicitly.
    if not spec.HoistRingsInBody:
        drawdie._keep_out_of_reference_set(body_refset, hoist_rings)

    # Added on Entire Part, then switched to BODY when the library part publishes one. The upper's part is itself
    # turned 180 degrees about Z, so the panel is turned 180 degrees in that part to cancel it.
    control_panel = nx.add_component(nx.display_part(), _dadcoControlPanelPath, "Entire Part", None,
                                     NXOpen.Point3d(0.0, 0.0, 0.0),
                                     _rotated_about_z_180() if spec.OppositeCorner else nx.identity_matrix(), 99)

    # Component_.TrySetReferenceSet
    if _component_has_reference_set(control_panel, "BODY"):
        nx.set_reference_set(control_panel, "BODY")

    if spec.ControlPanelAtCorner:
        _move_nitro_control_panel_to_corner(control_panel, xlength, ywidth, spec.OppositeCorner)

    body_refset.AddObjectsToReferenceSet([control_panel])

    nx.set_display_part(starting_display)
    new_comp = nx.first_occurrence_in(new_part, nx.display_part())
    new_comp.Unblank()
    nx.set_reference_set(new_comp, "BODY")
    merlin._set_reference_set_in_ancestor_assemblies(new_comp, add_to_reference_set=True)

    nx.print_("{}: {} x {} nitrogen plate at Z {}, {} SHCS, {} hoist rings.".format(
        new_part.Leaf, _f3(xlength), _f3(ywidth), _f4(bottom_z), len(shcs), len(hoist_rings)))


# ---------------------------------------------------------------------------------------------------
# SUBTOOL
# ---------------------------------------------------------------------------------------------------

def _grow_nitro_subtool(subtool: NXOpen.Body, top_offset: float, side_offset: float, up: NXOpen.Vector3d) -> None:
    """
    Merlin.GrowNitroSubtool - the SUBTOOL's face along up offset outward top_offset and its four side faces outward
    side_offset, recolored 2 with its face along -up 42. up is +Z for the upper and -Z for the lower.
    """
    faces = subtool.GetFaces()
    down = nx.negate(up)

    def is_planar_with_normal(face: NXOpen.Face, normal: NXOpen.Vector3d) -> bool:
        return face.SolidFaceType == NXOpen.Face.FaceType.Planar and nx.vectors_equal(nx.face_normal(face), normal)

    if top_offset > 0:
        top = [face for face in faces if is_planar_with_normal(face, up)]
        if len(top) == 0:
            nx.print_("SUBTOOL has no {} face - not offset.".format("+Z" if up.Z > 0 else "-Z"))
        else:
            _offset_face(top_offset, top)

    if side_offset > 0:
        sides = [face for face in faces
                 if face.SolidFaceType == NXOpen.Face.FaceType.Planar
                 and not nx.vectors_equal(nx.face_normal(face), _VectorZ)
                 and not nx.vectors_equal(nx.face_normal(face), _VectorZN)]
        if len(sides) == 0:
            nx.print_("SUBTOOL has no side faces - sides not offset.")
        else:
            _offset_face(side_offset, sides)

    # Body first - it colors every face - then the bottom face over it.
    nx.set_color(subtool, 2)

    # Re-read after the offsets: the bottom face's edges have moved out with the side faces.
    bottom = nx.planar_face_with_normal_or_null(subtool, down)
    if bottom is None:
        nx.print_("SUBTOOL has no {} face - not colored.".format("+Z" if down.Z > 0 else "-Z"))
        return

    nx.set_color(bottom, 42)


def _extrude_nitro_subtool_bottom_edges(subtool: NXOpen.Body, up: NXOpen.Vector3d) -> None:
    """
    Merlin.ExtrudeNitroSubtoolBottomEdges - each edge of the SUBTOOL's face along -up extruded
    NitroSubtoolEdgeExtrudeHeight in -up as a sheet; each sheet's face extruded NitroSubtoolWallThickness along its
    normal toward the centre of SUBTOOL; every wall built before any unite, then each united onto SUBTOOL.
    """
    down = nx.negate(up)
    bottom = nx.planar_face_with_normal_or_null(subtool, down)
    if bottom is None:
        nx.print_("SUBTOOL has no {} face - edges not extruded.".format("+Z" if down.Z > 0 else "-Z"))
        return

    part = cast(NXOpen.Part, subtool.OwningPart)
    other_min, other_max = _exact_bounding_box([subtool])
    centre = NXOpen.Point3d((other_min.X + other_max.X) / 2,
                            (other_min.Y + other_max.Y) / 2,
                            (other_min.Z + other_max.Z) / 2)

    def extrude_section(rule: NXOpen.SelectionIntentRule, seed: NXOpen.NXObject, at: NXOpen.Point3d,
                        direction: NXOpen.Vector3d, distance: float) -> NXOpen.Features.Extrude:
        builder = part.Features.CreateExtrudeBuilder(None)
        try:
            # SectionCollection.CreateSection() - the no-argument overload is not in the stubs.
            builder.Section = cast(Any, part.Sections).CreateSection()
            builder.Section.AddToSection([rule], seed, None, None, NXOpen.Point3d(0.0, 0.0, 0.0),
                                         NXOpen.Section.Mode.Create, False)
            builder.Limits.StartExtend.Value.Value = 0
            builder.Limits.EndExtend.Value.Value = distance
            builder.Direction = part.Directions.CreateDirection(at, direction,
                                                                NXOpen.SmartObject.UpdateOption.WithinModeling)
            return cast(NXOpen.Features.Extrude, builder.Commit())
        finally:
            builder.Destroy()

    # Every wall is built before any unite: a unite rebuilds SUBTOOL, which would invalidate the face edges the
    # later extrudes still need.
    walls: List[NXOpen.Features.Extrude] = []
    for edge in bottom.GetEdges():
        try:
            sheet = extrude_section(part.ScRuleFactory.CreateRuleEdgeDumb([edge]), edge,
                                    nx.edge_start_point(edge), down, NitroSubtoolEdgeExtrudeHeight)
            for body in sheet.GetBodies():
                nx.set_color(body, NitroSubtoolExtrudeColor)

            # A sheet from one straight edge is a single planar face. Its normal can come out either way, so turn
            # it to the side the centre of SUBTOOL is on.
            for face in [f for body in sheet.GetBodies() for f in body.GetFaces()]:
                face_min, face_max = _exact_bounding_box([face])
                face_centre = NXOpen.Point3d((face_min.X + face_max.X) / 2,
                                             (face_min.Y + face_max.Y) / 2,
                                             (face_min.Z + face_max.Z) / 2)
                normal = nx.face_normal(face)
                to_centre = NXOpen.Vector3d(centre.X - face_centre.X, centre.Y - face_centre.Y,
                                            centre.Z - face_centre.Z)
                if normal.X * to_centre.X + normal.Y * to_centre.Y + normal.Z * to_centre.Z < 0:
                    normal = nx.negate(normal)

                # ScRuleFactory.CreateRuleEdgeFace is not in the stubs.
                wall = extrude_section(cast(Any, part.ScRuleFactory).CreateRuleEdgeFace([face]), face,
                                       face_centre, normal, NitroSubtoolWallThickness)

                # Colored before the unite, so the wall's faces carry the color onto SUBTOOL.
                for body in wall.GetBodies():
                    nx.set_color(body, NitroSubtoolExtrudeColor)
                walls.append(wall)
        except Exception as ex:
            nx.print_exception(ex)

    # One unite per wall, each onto the SUBTOOL solid. The edge sheets are not united - they are not solids.
    for wall in walls:
        try:
            nx.create_boolean(subtool, wall.GetBodies(), NXOpen.Features.Feature.BooleanType.Unite)
        except Exception as ex:
            nx.print_exception(ex)


# ---------------------------------------------------------------------------------------------------
# Snap.Create replacements
# ---------------------------------------------------------------------------------------------------

def _inches_in_part_units(part: NXOpen.BasePart, inches: float) -> str:
    """The C#'s "{value}in" Snap expression, as a number in the part's units."""
    return nx.cs_double_str(inches * 25.4 if part.PartUnits == NXOpen.BasePart.Units.Millimeters else inches)


def _edge_blend(radius: float, edge: NXOpen.Edge) -> NXOpen.Features.Feature:
    """Snap.Create.EdgeBlend($"{radius}in", edge) - a constant-radius blend on one edge, in the work part."""
    part = nx.work_part()
    # Features.CreateEdgeBlendBuilder / EdgeBlendBuilder are not in the stubs.
    builder = cast(Any, part.Features).CreateEdgeBlendBuilder(None)
    try:
        builder.Tolerance = nx.distance_tolerance()
        collector = part.ScCollectors.CreateCollector()
        collector.ReplaceRules([part.ScRuleFactory.CreateRuleEdgeDumb([edge])], False)
        builder.AddChainset(collector, _inches_in_part_units(part, radius))
        return cast(NXOpen.Features.Feature, builder.CommitFeature())
    finally:
        builder.Destroy()


def _offset_face(distance: float, faces: Sequence[NXOpen.Face]) -> NXOpen.Features.Feature:
    """Snap.Create.OffsetFace($"{distance}in", false, faces) - one offset-face feature, in the work part."""
    part = nx.work_part()
    builder = part.Features.CreateOffsetFaceBuilder(None)
    try:
        builder.Distance.RightHandSide = _inches_in_part_units(part, distance)
        builder.Direction = False
        builder.FaceCollector.ReplaceRules([part.ScRuleFactory.CreateRuleFaceDumb(list(faces))], False)
        return builder.CommitFeature()
    finally:
        builder.Destroy()


# ---------------------------------------------------------------------------------------------------
# Fasteners / control panel
# ---------------------------------------------------------------------------------------------------

def _find_bottom_face() -> NXOpen.Face:
    """Merlin.FindBottomFace - the -Z planar face of the display part's single layer-1 solid body, colored 42."""
    bottom_face = nx.planar_face_with_normal_or_null(trimpad._single_solid_body_on_layer1(nx.display_part()),
                                                     _VectorZN)
    if bottom_face is None:
        raise RuntimeError("{} has no -Z planar face".format(nx.display_part().Leaf))
    nx.set_color(bottom_face, 42)
    return bottom_face


def _subtract_and_refset_fasteners(fasteners: Sequence[NXOpen.Assemblies.Component], bottom_face: NXOpen.Face,
                                   body_refset: Optional[NXOpen.ReferenceSet]) -> None:
    """
    Merlin.SubtractAndRefsetFasteners - work layer 96; per fastener: link it on the reference set it arrived on,
    subtract that from bottom_face's body, stamp the subtract attribute, then layer-98 fasteners go to Empty and the
    rest to BODY (added to body_refset unless it is None).
    """
    nx.display_part().Layers.WorkLayer = 96
    for fastener in fasteners:
        try:
            # The fastener arrives on the reference set it is subtracted with (CBORE, SHORT-TAP, ...).
            subtract_refset = fastener.ReferenceSet
            link = nx.create_linked_body(fastener)
            nx.subtract(bottom_face.GetBody(), link.GetBodies())
            drawdie._stamp_fastener_subtract(fastener, subtract_refset)
            if fastener.Layer == 98:
                nx.set_reference_set(fastener, "Empty")
                continue
            nx.set_reference_set(fastener, "BODY")
            # None leaves the fastener out of the part's BODY reference set.
            if body_refset is not None:
                body_refset.AddObjectsToReferenceSet([fastener])
        except Exception as ex:
            nx.print_exception(ex)


def _move_nitro_control_panel_to_corner(control_panel: NXOpen.Assemblies.Component, xlength: float, ywidth: float,
                                        upper_frame: bool) -> None:
    """
    Merlin.MoveNitroControlPanelToCorner - translates the panel (in the plate part) so its box is flush against the
    -Y and +X faces as seen in the -000; with upper_frame that is the part's +Y / -X corner. Z untouched.
    """
    bodies = nx.solid_body_members(control_panel)

    if len(bodies) == 0:
        nx.print_("{} has no solid bodies to measure - left at the part origin.".format(control_panel.DisplayName))
        return

    min_point, max_point = _exact_bounding_box(bodies)

    if upper_frame:
        delta = NXOpen.Vector3d(0 - min_point.X, ywidth - max_point.Y, 0.0)
    else:
        delta = NXOpen.Vector3d(xlength - max_point.X, 0 - min_point.Y, 0.0)

    # Component_.Move
    control_panel.OwningPart.ComponentAssembly.MoveComponent(control_panel, delta, nx.identity_matrix())


def _component_has_reference_set(component: NXOpen.Assemblies.Component, name: str) -> bool:
    """Component_.HasReferenceSet - loaded, and the prototype publishes name."""
    return nx.is_loaded(component) and nx.has_reference_set(nx.prototype(component), name)


# ---------------------------------------------------------------------------------------------------
# Cylinders / boxes / stations
# ---------------------------------------------------------------------------------------------------

def _nitro_cylinder_bodies(cylinders: Iterable[NXOpen.Assemblies.Component]) -> List[NXOpen.Body]:
    """Merlin.NitroCylinderBodies - every loaded solid body of the cylinders, their children included."""
    return [body
            for cylinder in cylinders
            for component in nx.descendants(cylinder, include_root=True, include_suppressed=True,
                                            include_unloaded=True)
            if nx.is_loaded(component)
            for body in nx.solid_body_members(component)]


def _nitro_cylinder_layer1_bodies(cylinders: Iterable[NXOpen.Assemblies.Component]) -> List[NXOpen.Body]:
    """
    Merlin.NitroCylinderLayer1Bodies - the solid bodies on layer 1 of each cylinder's own part (children left out),
    the layer read off the prototype body. Prints each cylinder that has none.
    """
    result: List[NXOpen.Body] = []

    for cylinder in [c for c in cylinders if nx.is_loaded(c)]:
        layer1 = [body for body in nx.solid_body_members(cylinder)
                  if cast(NXOpen.Body, body.Prototype if body.IsOccurrence else body).Layer == 1]

        if len(layer1) == 0:
            nx.print_("{}: no solid body on layer 1 - not used for the plate height.".format(cylinder.DisplayName))

        result.extend(layer1)

    return result


def _exact_bounding_box(objects: Iterable[NXOpen.TaggedObject]) -> Tuple[NXOpen.Point3d, NXOpen.Point3d]:
    """
    Merlin.ExactBoundingBox - the exact box of objects against a temporary csys at (0,0,0) with the identity
    orientation, so it does not need an absolute datum csys in the part.
    """
    ufs = cast(Any, nx.ufsession_)
    matrix = ufs.Mtx3.Initialize([1.0, 0.0, 0.0], [0.0, 1.0, 0.0])
    matrix_tag = ufs.Csys.CreateMatrix(matrix)
    csys = nx.ufsession_.Csys.CreateTempCsys([0.0, 0.0, 0.0], matrix_tag)
    min_x = min_y = min_z = sys.float_info.max
    max_x = max_y = max_z = -sys.float_info.max

    for obj in objects:
        origin, _directions, distances = nx.ufsession_.ModlGeneral.AskBoundingBoxExact(obj.Tag, csys)
        min_x = min(min_x, origin[0])
        min_y = min(min_y, origin[1])
        min_z = min(min_z, origin[2])
        max_x = max(max_x, origin[0] + distances[0])
        max_y = max(max_y, origin[1] + distances[1])
        max_z = max(max_z, origin[2] + distances[2])

    return NXOpen.Point3d(min_x, min_y, min_z), NXOpen.Point3d(max_x, max_y, max_z)


def _nitro_plate_shcs_positions(xlength: float, ywidth: float, inset: float) -> List[NXOpen.Point3d]:
    """
    Merlin.NitroPlateShcsPositions - the plate's SHCS centres (Z 0), inset in from the edges: the four corners, then
    along each edge the stations from _nitro_plate_edge_stations.
    """
    x0 = inset
    x1 = xlength - inset
    y0 = inset
    y1 = ywidth - inset

    points = [NXOpen.Point3d(x0, y0, 0.0), NXOpen.Point3d(x1, y0, 0.0),
              NXOpen.Point3d(x1, y1, 0.0), NXOpen.Point3d(x0, y1, 0.0)]

    for x in _nitro_plate_edge_stations(x0, x1):
        points.append(NXOpen.Point3d(x, y0, 0.0))
        points.append(NXOpen.Point3d(x, y1, 0.0))

    for y in _nitro_plate_edge_stations(y0, y1):
        points.append(NXOpen.Point3d(x0, y, 0.0))
        points.append(NXOpen.Point3d(x1, y, 0.0))

    return points


def _nitro_plate_edge_stations(start: float, end: float) -> List[float]:
    """
    Merlin.NitroPlateEdgeStations - the stations strictly between two corner screws: ceil(span / max pitch) equal
    gaps, the quotient rounded to 6 places first so an exact multiple does not gain a gap from noise.
    """
    span = end - start

    if span <= 0:
        return []

    gaps = int(math.ceil(round(span / NitroPlateMaxShcsPitch, 6)))

    return [start + span * i / gaps for i in range(1, gaps)]


# ---------------------------------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------------------------------

def _f3(value: float) -> str:
    """C#'s value.ToString("0.###")."""
    return merlin._format_0_000(value)


def _f4(value: float) -> str:
    """C#'s value.ToString("0.####")."""
    text = "{:.4f}".format(value).rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def main() -> None:
    """The nitro-plate-upper UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db
    from tsg_dialog import ask_is_gm

    with usage_db.run("nitro-plate-upper"):
        try:
            # The Customer dialog stands in for the "Are you sure" box: GM builds with the GM parts, TSG throws.
            is_gm = ask_is_gm("Nitro Plate Upper")
            if is_gm is not None:
                NitroPlateUpper.execute(is_gm)
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
