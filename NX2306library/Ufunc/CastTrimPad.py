"""
Python port of the cast-trim-pad UFunc (Merlin.StaticGmCastTrimPad, src\\UFuncs\\Merlin.cs, region
"GM Trim Pad - Builder & Cast Inserts").
The C# wrapper was deleted 2026-10-22 (in git at 1cb53d8): the UFunc's menu button runs this file's main().

Run from an upper station (uad/upd/ush/usp as the work part; upper only since 2026-11-07). When the work part is not
one, the dialog adds a "Build in" radio of the display assembly's loaded upper stations ({job}-{op}-{station}[NN],
2026-10-30) and the picked one is made the work component (and left so) before the build; with none in the assembly it is the
old error box. Select the bodies to pad;
their combined box, +6" in X and +12" in Y (rounded up to 1/8"), becomes a 75 mm block sitting 10 mm above their
highest point (its bottom there, upper or lower; it used to hang down from there, wrapping the bodies, 2026-11-07). It is promoted to [cts-]cast-trim-pad, its origin re-based onto the block (translation only),
its vertical edges chamfered 3.25", hollowed into a bath tub (the top face's edges offset 40 mm in, extruded 45 mm
down and subtracted, its faces colored 13 like the pad, 2026-11-07, never run in NX), and it gets:
  - 5 guided retainers (four 90 mm in from the corners, one in the centre), the first one Save As'd as a job part;
  - 4 cast-in inserts, 255 mm / 55 mm in from the corners, on layer 96;
  - 4 ISO nitros on the box corners, .7874" above the top face (GM-only, as in the C#);
  - 4 cast pad locators, one centred on each edge, .25" up (upper) or down (lower);
  - the GM PAD CAST TEXT part imported at the centre, on layer 20.
DESCRIPTION / DETAIL NAME CAST TRIM PAD, MATERIAL GM338/D6510, the AutoSize UDO switched off, and BODY set up in
every loaded ancestor assembly.

Two ways in:
  - File -> Execute -> NX Open on this file runs main() with is_gm = True, as the cast-trim-pad UFunc does.
  - Session.Execute("CastTrimPad.py", "CastTrimPad", "execute", is_gm) from C#.

Differences from the C#:
  - The chamfer is an NXOpen ChamferBuilder per vertical edge (symmetric offset) instead of Snap.Create.Chamfer,
    written in part units rather than as the "3.25in" string.
  - The AutoSize UDO class can only be registered from C# (see tsg_nx.create_auto_size_udo). Run standalone in a
    session where TSG_Library never registered it, the pad gets no UDO and there is nothing to switch off - both print
    and carry on.
  - The re-base reads the block size through UF_MODL_ask_block_parms (DrawDie._rebase_block_to_part_origin), since
    BlockFeatureBuilder.Length/Width/Height come back None in Python.

The Merlin helpers DrawDie.py and PointComponent.py already port are imported from them rather than copied.
"""

from __future__ import annotations

import datetime
import os
import re
import sys
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, cast

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
import NXOpen.GeometricUtilities  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
import PointComponent as merlin  # noqa: E402
import DrawDie as drawdie  # noqa: E402
from tsg_dialog import CustomerBodiesDialog, is_gm_customer, title_with_version  # noqa: E402

# ---------------------------------------------------------------------------------------------------
# Constants (Merlin's, inches unless the name says otherwise)
# ---------------------------------------------------------------------------------------------------

# Block: the bodies' box plus this much in X / Y (half on each side), 75 mm deep, its bottom 10 mm above their top.
TrimPadGrowX = 6.0
TrimPadGrowY = 12.0
TrimPadHeight = 75.0 / 25.4
TrimPadAboveTop = 10 / 25.4
TrimPadColor = 13
TrimPadChamfer = 3.25

# The bath tub: the top face's edges offset this far in, extruded this far down and subtracted (2026-11-07).
TrimPadPocketInsetMm = 40.0
TrimPadPocketDepthMm = 45.0
# The pocket's extrude starts this far above the top face, so its cap is not coplanar with it.
_TrimPadPocketStartAboveMm = 5.0

# Cast-in inserts sit in from each corner of the trim pad: 255mm in X, 55mm in Y.
CastInInsertInsetX = 255 / 25.4
CastInInsertInsetY = 55 / 25.4

# Corner guided retainers sit 90mm in from each corner, in both X and Y.
GuidedRetainerCornerInset = 90 / 25.4

# ISO nitros sit this far above the pad's top face.
IsoNitroAboveTop = .7874

_guidedRetainerZ = 2.9528 + 11 / 25.4
_castPadLocatorZ = 2.9528 + 10 / 25.4
_castInInsertZ = 1.6535
_castPadLocatorInset = 1.5748031496062991
_castPadLocatorZAdjust = -0.50004409503937008

_gmGuidedRetainerPath = "G:\\0Library\\0Customer\\GM\\Smart GM Guided Retainer.prt"
_gmCastInInsertPath = "G:\\0Library\\0Customer\\GM\\GM M16 Cast-In Insert.prt"
_gmCastPadLocatorPath = "G:\\CTS\\junk\\blank-station-data\\GM CAST PAD LOCATOR.prt"
_gmIsoNitroPath = "G:\\0Library\\0Customer\\GM\\Smart GM ISO Nitro.prt"
_gmPadCastTextPath = "G:\\CTS\\junk\\blank-station-data\\GM PAD CAST TEXT.prt"
_ctsSmartKeyMetric = "G:\\0Library\\Keys\\Smart Key Metric.prt"
_ctsLiftLugMetric = "G:\\0Library\\LiftLugs\\Metric\\CastIn\\M16-J-449253.prt"
_ctsSmartSlGuidedKeeper = "G:\\0Library\\StandardLifters\\GuidedKeepers\\Smart SL Guided Keepers.prt"

# The layer __ImportCastText imports onto.
_CastTextLayer = 20

# Merlin.TryDetectIsUpper's work-part tests (substrings of the leaf), and the stricter
# {job}-{op}-{station}[NN] the assembly search offers in the "Build in" radio - a bare substring would also match
# library parts (a "cushion" holds "ush").
_UpperTokens = ("uad", "upd", "ush", "usp")
_LowerTokens = ("lad", "lsh", "lsp")
_StationLeaf = re.compile(r"^\d+-\d+-(uad|upd|ush|usp|lad|lsh|lsp)\d*$", re.IGNORECASE)
_StationError = "Must be run from LAD, UAD, UPD, USH, USP, LSP or LSH"
# The cast trim pad goes in upper stations only (2026-11-07).
_UpperStationError = ("The cast trim pad goes in an upper station: run it from a UAD, UPD, USH or USP, or from an "
                      "assembly holding one")

_VectorY = NXOpen.Vector3d(0.0, 1.0, 0.0)
_VectorXN = NXOpen.Vector3d(-1.0, 0.0, 0.0)
_VectorZN = NXOpen.Vector3d(0.0, 0.0, -1.0)


class CastTrimPad(object):

    @staticmethod
    def execute(is_gm: bool = True) -> None:
        """
        Merlin.StaticGmCastTrimPad(is_gm). The Cast Trim Pad dialog's Customer radio decides is_gm (TSG uses the CTS parts); the argument
        is not used.
        """
        static_gm_cast_trim_pad(is_gm)


def static_gm_cast_trim_pad(is_gm: bool) -> None:
    """
    Merlin.StaticGmCastTrimPad - the Cast Trim Pad dialog (CastTrimPad.dlx: customer + bodies, plus the "Build in"
    station radio when the work part is not a station), then build a trim pad (block + guided retainers + cast-in
    inserts + ISO nitros + locators + cast text) around them in the work part.
    """
    ok, message = drawdie._check_info_units()
    if not ok:
        nx.show_error(message)
        return

    try:
        # Upper stations only (2026-11-07): a lower work part, or none, offers the assembly's upper stations instead.
        is_upper = _station_is_upper(nx.work_part().Leaf)
        stations = [] if is_upper else [c for c in _station_components()
                                         if _station_is_upper(nx.prototype(c).Leaf)]
        if not is_upper and not stations:
            nx.show_error(_UpperStationError)
            return

        dialog = BuildInDialog(title_with_version("Cast Trim Pad"), [nx.prototype(c).Leaf for c in stations])
        if not dialog.run():
            return
        is_gm = is_gm_customer(dialog.customer_choice)
        bodies = dialog.bodies
        for body in bodies:
            body.Unhighlight()

        if stations:
            station = next(c for c in stations if nx.prototype(c).Leaf == dialog.station)
            nx.set_work_component(station)
            is_upper = _station_is_upper(dialog.station)
        assert is_upper

        # sess.SetWcs() - the display part's WCS back to absolute.
        drawdie._set_wcs_to_absolute(nx.display_part())

        start = datetime.datetime.now()
        try:
            _build_trim_pad(is_gm, is_upper, bodies)
        finally:
            # Session.__UsingTimer prints the elapsed TimeSpan.
            nx.warn(drawdie._time_span(datetime.datetime.now() - start))
    except Exception as ex:
        nx.print_exception(ex)


@nx.traced("Cast Trim Pad")
def _build_trim_pad(is_gm: bool, is_upper: bool, bodies: List[NXOpen.Body]) -> None:
    # The bodies are measured in the display part, but the block is built in the work part (the station): map the box
    # into the station's own coordinates, or a station that is not at the display part's origin gets its pad that far
    # off (2026-11-07: pads landing at the wrong Z and off to the side when run from the -000).
    # Then the station is displayed for the build, as Cast Form Pad / Cast Post / Component do: a builder in a work
    # component under a displayed assembly takes the assembly's coordinates and maps them itself, so the mapped box
    # was moved by the station's offset twice (2026-11-07, still off after the WorkFrame fix).
    top_level = nx.display_part()
    station_occurrence = nx.session_.Parts.WorkComponent
    combined = nx.combine_boxes(nx.body_box(body) for body in bodies)
    frame = nx.WorkFrame()
    combined = frame.box(combined)
    frame.warn_if_turned("Cast Trim Pad")
    if top_level.Tag != nx.work_part().Tag:
        nx.set_display_part(nx.work_part())
        drawdie._set_wcs_to_absolute(nx.display_part())
    xlength = nx.round_to_125(combined.MaxX - combined.MinX + TrimPadGrowX)
    ywidth = nx.round_to_125(combined.MaxY - combined.MinY + TrimPadGrowY)

    # Origin at top of block, 75 mm over its bottom, which is 10 mm above the bodies' top (2026-11-07: the pad sits
    # above the bodies; the top used to be at MaxZ + 10mm). Block is oriented -Z so it extends downward. The -Z matrix
    # (Vector3d.__ToMatrix3x3) has X = -X and Y = +Y, so the block runs from the origin towards -X: the origin is the
    # +X corner. It used to be the -X corner (as in the C#), which put the whole pad its length to -X of the bodies
    # (seen in NX 2026-11-07: bodies X 1.64..50.65, pad X -56.49..-1.36).
    origin = NXOpen.Point3d(combined.MinX - TrimPadGrowX / 2 + xlength,
                            combined.MinY - TrimPadGrowY / 2,
                            combined.MaxZ + TrimPadAboveTop + TrimPadHeight)

    block = _create_block(origin, drawdie._z_matrix(_VectorZN), xlength, ywidth, TrimPadHeight)

    block_body = block.GetBodies()[0]
    nx.set_layer(block_body, 1)
    block.SetName("DYNAMIC BLOCK")
    nx.set_color(block_body, TrimPadColor)
    current_work = nx.work_part()
    current_display = nx.display_part()
    pad = drawdie._create_new_component_core(
        "cast-trim-pad" if is_gm else "cts-cast-trim-pad",
        [block_body],
        NXOpen.Assemblies.CreateNewComponentBuilder.ComponentOriginType.Absolute,
        NXOpen.Assemblies.CreateNewComponentBuilder.ComponentLayerOptionType.AsSpecified,
        original_objects_deleted=True,
        auto_size_udo=True)

    # Origin only, deliberately. This block is built rotated (-Z, so it extends downward from its top), and
    # everything below places off the box's min corner with hard-coded orientation matrices. Axis-aligning the block
    # would make that corner a different physical corner and would spin every one of those matrices through the
    # block rotation. A pure translation leaves all of it intact - `bounding` is re-read below and self-corrects.
    drawdie._rebase_block_to_part_origin(pad, cast(NXOpen.Part, pad.OwningPart), apply_orientation=False)

    nx.setup_station_expressions(nx.work_part())
    pad.SetName("PAD")
    new_part = nx.display_part()
    new_part.Layers.WorkLayer = merlin.DetailWorkLayer
    _chamfer_vertical_edges(nx.dynamic_block(new_part), TrimPadChamfer)
    solid_body = _single_solid_body_on_layer1(new_part)
    # After the chamfers, so the pocket follows the chamfered outline and its own walls are not chamfered.
    _pad_step("pocket", lambda: _cut_pocket(solid_body))
    bounding = nx.body_box(solid_body)

    _pad_step("guided retainers", lambda: _add_guided_retainers(bounding, is_gm))
    _pad_step("cast-in inserts", lambda: _add_cast_in_inserts(bounding, is_gm))
    _pad_step("ISO nitros", lambda: _add_iso_nitros(bounding))
    matrix = nx.matrix_from_axes(_VectorXN, _VectorY)
    mat = nx.matrix_from_axes(nx.negate(nx.axis_y(matrix)), nx.axis_x(matrix))
    _pad_step("cast pad locators",
              lambda: _add_cast_pad_locators(xlength, ywidth, bounding, matrix, mat, is_upper, is_gm))
    _import_cast_text(nx.work_part(), _gmPadCastTextPath, xlength, ywidth,
                      NXOpen.Point3d(bounding.MinX, bounding.MinY, bounding.MinZ))

    body_refset = nx.find_or_create_reference_set(nx.display_part(), "BODY")
    body_refset.AddObjectsToReferenceSet([solid_body])
    # Cast details are not resized - force the AutoSize UDO off (UDO + AUTO UPDATE attribute).
    drawdie._switch_auto_size_off(new_part)
    display = nx.display_part()
    nx.set_attribute(display, "DESCRIPTION", "CAST TRIM PAD")
    nx.set_attribute(display, "DETAIL NAME", "CAST TRIM PAD")
    nx.set_attribute(display, "MATERIAL", "GM338/D6510")
    nx.set_attribute(display, "CSPC", "XXXX")
    nx.set_attribute(display, "GM Tool Number", "XX-XXXXX")
    root = nx.root_component(display)
    if root is not None:
        for child in root.GetChildren():
            body_refset.AddObjectsToReferenceSet([child])

    nx.set_display_part(current_display)
    nx.find_or_create_reference_set(current_work, "BODY").AddObjectsToReferenceSet([pad])

    # Back on the assembly the run started from, with the station the work component again.
    if top_level.Tag != current_display.Tag:
        nx.set_display_part(top_level)
        if station_occurrence is not None:
            nx.set_work_component(station_occurrence)
    merlin._set_reference_set_in_ancestor_assemblies(nx.first_occurrence_in(new_part, top_level))


# ---------------------------------------------------------------------------------------------------
# Placements
# ---------------------------------------------------------------------------------------------------

@nx.traced("Cast Trim Pad")
def _add_cast_pad_locators(xlength: float, ywidth: float, bounding: nx.Box3d, matrix: NXOpen.Matrix3x3,
                           mat: NXOpen.Matrix3x3, is_upper: bool, is_gm: bool) -> None:
    """Merlin.AddCastPadLocators - locator 1 on the -Y edge, 2 on +Y, 3 on +X, 4 on -X; into the display part."""
    z_shift = .25 if is_upper else -.25
    path = _gmCastPadLocatorPath if is_gm else _ctsSmartKeyMetric
    z = _castPadLocatorZAdjust + _castPadLocatorZ + z_shift

    for dx, dy, orientation in (
            (xlength / 2, _castPadLocatorInset, mat),             # -Y edge (front): X-centered, near MinY
            (xlength / 2, ywidth - _castPadLocatorInset, mat),    # +Y edge (back): X-centered, near MaxY
            (xlength - _castPadLocatorInset, ywidth / 2, matrix),  # +X edge (right): Y-centered, near MaxX
            (_castPadLocatorInset, ywidth / 2, matrix)):          # -X edge (left): Y-centered, near MinX
        nx.add_component(nx.display_part(), path, reference_set="BODY",
                         origin=_from_min(bounding, dx, dy, z), orientation=orientation, layer=99)


@nx.traced("Cast Trim Pad")
def _add_iso_nitros(bounding: nx.Box3d) -> None:
    """Merlin.AddIsoNitros - one on each corner of the pad's box (no inset), pointing +Z. GM-only like the hoist rings."""
    x, y, height = _distances(bounding)
    z = height + IsoNitroAboveTop

    for dx, dy in ((0.0, 0.0), (x, 0.0), (x, y), (0.0, y)):
        nx.add_component(nx.work_part(), _gmIsoNitroPath, reference_set="BODY",
                         origin=_from_min(bounding, dx, dy, z), orientation=nx.identity_matrix(), layer=99)


@nx.traced("Cast Trim Pad")
def _add_cast_in_inserts(bounding: nx.Box3d, is_gm: bool) -> None:
    """Merlin.AddCastInInserts - 255 mm / 55 mm in from each corner, pointing -Z, on layer 96."""
    path = _gmCastInInsertPath if is_gm else _ctsLiftLugMetric
    x, y, _height = _distances(bounding)

    for dx, dy in ((CastInInsertInsetX, CastInInsertInsetY),
                   (x - CastInInsertInsetX, CastInInsertInsetY),
                   (x - CastInInsertInsetX, y - CastInInsertInsetY),
                   (CastInInsertInsetX, y - CastInInsertInsetY)):
        nx.add_component(nx.work_part(), path, reference_set="BODY",
                         origin=_from_min(bounding, dx, dy, _castInInsertZ),
                         orientation=drawdie._z_matrix(_VectorZN), layer=96)


@nx.traced("Cast Trim Pad")
def _add_guided_retainers(bounding: nx.Box3d, is_gm: bool) -> None:
    """
    Merlin.AddGuidedRetainers - four 90 mm in from the corners plus one in the centre, then the first one's
    prototype Save As'd next to the display part as [cts-]cast-trim-pad-guided-retainer-{n}.prt.
    """
    path = _gmGuidedRetainerPath if is_gm else _ctsSmartSlGuidedKeeper
    x, y, _height = _distances(bounding)
    inset = GuidedRetainerCornerInset
    z = _guidedRetainerZ + -.00112 / 25.4

    placed = [nx.add_component(nx.work_part(), path, reference_set="BODY",
                               origin=_from_min(bounding, dx, dy, z), layer=99)
              for dx, dy in ((inset, inset), (x - inset, inset), (x - inset, y - inset), (inset, y - inset),
                             (x / 2, y / 2))]

    nx.prototype(placed[0]).SaveAs(merlin._next_part_path(
        os.path.dirname(nx.display_part().FullPath), "{}cast-trim-pad-guided-retainer".format("" if is_gm else "cts-")))


@nx.traced("Cast Trim Pad")
def _import_cast_text(part: NXOpen.Part, path: str, xlength: float, ywidth: float,
                      block_origin: NXOpen.Point3d) -> None:
    """
    Part.__ImportCastText - imports the cast-text part at the centre of the block footprint (block_origin + xlength/2,
    ywidth/2), on layer 20 with its original layers. part must be the work part.
    """
    if part.Tag != nx.work_part().Tag:
        raise RuntimeError("{} is not the work part".format(part.Leaf))

    work_layer = part.Layers.WorkLayer
    part.Layers.WorkLayer = _CastTextLayer
    try:
        importer = part.ImportManager.CreatePartImporter()
        try:
            importer.FileName = path
            importer.LayerOption = NXOpen.PartImporter.LayerOptionType.Original
            importer.DestinationCoordinateSystemSpecification = \
                NXOpen.PartImporter.DestinationCoordinateSystemSpecificationType.Work
            importer.DestinationCoordinateSystem = part.NXMatrices.Create(nx.identity_matrix())
            importer.DestinationPoint = NXOpen.Point3d(block_origin.X + xlength / 2, block_origin.Y + ywidth / 2,
                                                       block_origin.Z)
            with nx.display_unsuppressed():
                importer.Commit()
        finally:
            importer.Destroy()
    finally:
        part.Layers.WorkLayer = work_layer


# ---------------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------------

def _try_detect_is_upper() -> Optional[bool]:
    """
    Merlin.TryDetectIsUpper - True for a uad/upd/ush/usp work part, False for lad/lsh/lsp, otherwise an error box and
    None.
    """
    is_upper = _station_is_upper(nx.work_part().Leaf)
    if is_upper is None:
        nx.show_error(_StationError)
    return is_upper


def _station_is_upper(leaf: str) -> Optional[bool]:
    """True for a uad/upd/ush/usp leaf, False for lad/lsh/lsp, otherwise None."""
    if any(token in leaf for token in _UpperTokens):
        return True
    if any(token in leaf for token in _LowerTokens):
        return False
    return None


def _station_components() -> List[NXOpen.Assemblies.Component]:
    """
    The display assembly's loaded, unsuppressed {job}-{op}-{station}[NN] components (upper and lower), one per part
    (its first occurrence), sorted by name - the "Build in" radio's choices.
    """
    root = nx.root_component(nx.display_part())
    if root is None:
        return []
    found: Dict[str, NXOpen.Assemblies.Component] = {}
    for comp in nx.descendants(root, include_root=False):
        leaf = nx.prototype(comp).Leaf
        if _StationLeaf.match(leaf) and leaf not in found:
            found[leaf] = comp
    return [found[leaf] for leaf in sorted(found)]


class BuildInDialog(CustomerBodiesDialog):
    """
    CastTrimPad.dlx / Component.dlx: the Customer radio, the bodies, and a "station" radio ("Build in") filled from
    stations - the assembly's station names - and shown only when there are any (the work part is not a station). The
    .dlx holds a placeholder member.
    """

    def __init__(self, title: str, stations: Sequence[str], dlx_name: str = "CastTrimPad.dlx",
                 solid_only: bool = False) -> None:
        self.stations = list(stations)
        super().__init__(dlx_name, title, solid_only=solid_only)
        # Captured in ok(): the blocks are gone once Launch returns.
        self.station = self.stations[0] if self.stations else ""

    def initialize(self) -> None:
        super().initialize()
        if self.stations:
            self.block("station").SetEnumMembers(self.stations)
        else:
            self.block("station").Show = False

    def shown(self) -> None:
        super().shown()
        if self.stations:
            # Not remembered: the dialog memory could hold a station from another assembly.
            self.block("station").ValueAsString = self.stations[0]

    def ok(self) -> bool:
        if not super().ok():
            return False
        if self.stations:
            self.station = str(self.block("station").ValueAsString)
        return True


def _create_block(origin: NXOpen.Point3d, orientation: NXOpen.Matrix3x3, xlength: float, ywidth: float,
                  height: float) -> NXOpen.Features.Block:
    """
    BasePart.__CreateBlock(Point3d, Matrix3x3, double, double, double) - an origin-and-edge-lengths block in the work
    part, oriented by orientation whatever the WCS is (nx.wcs_turned_to).
    """
    with nx.wcs_turned_to(nx.axis_x(orientation), nx.axis_y(orientation)):
        builder = nx.work_part().Features.CreateBlockFeatureBuilder(None)
        try:
            builder.Type = NXOpen.Features.BlockFeatureBuilder.Types.OriginAndEdgeLengths
            builder.BooleanOption.Type = NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Create
            builder.SetOriginAndLengths(origin, nx.cs_double_str(xlength), nx.cs_double_str(ywidth),
                                        nx.cs_double_str(height))
            return cast(NXOpen.Features.Block, builder.Commit())
        finally:
            builder.Destroy()


def _chamfer_vertical_edges(block: NXOpen.Features.Block, chamfer: float) -> None:
    """
    Merlin.ChamferVerticalEdges - a symmetric-offset chamfer on every vertical edge of the block's body, one feature
    per edge as Snap.Create.Chamfer makes them. chamfer is in inches and written in the part's units.
    """
    part = nx.work_part()
    offset = chamfer * 25.4 if part.PartUnits == NXOpen.BasePart.Units.Millimeters else chamfer
    edges = [edge for edge in block.GetBodies()[0].GetEdges() if _is_vertical(edge)]

    for edge in edges:
        builder = part.Features.CreateChamferBuilder(None)
        try:
            builder.Option = NXOpen.Features.ChamferBuilder.ChamferOption.SymmetricOffsets
            builder.Method = NXOpen.Features.ChamferBuilder.OffsetMethod.EdgesAlongFaces
            builder.FirstOffset = nx.cs_double_str(offset)
            collector = part.ScCollectors.CreateCollector()
            collector.ReplaceRules([part.ScRuleFactory.CreateRuleEdgeDumb([edge])], False)
            builder.SmartCollector = collector
            builder.CommitFeature()
        finally:
            builder.Destroy()


@nx.traced("Cast Trim Pad")
def _cut_pocket(body: NXOpen.Body) -> None:
    """
    The bath tub: the top face's edges copied to curves, offset TrimPadPocketInsetMm inside, extruded
    TrimPadPocketDepthMm down from the top face and subtracted from body, its faces colored TrimPadColor like the
    pad. The curves stay on the work layer, behind the extrude.
    """
    from Boss import _snap_extrude
    from ProfileSubtract import _offset_outward

    part = cast(NXOpen.Part, body.OwningPart)
    per_mm = 1.0 if part.PartUnits == NXOpen.BasePart.Units.Millimeters else 1 / 25.4
    top_z = nx.body_box(body).MaxZ
    tops = [face for face in body.GetFaces()
            if face.SolidFaceType == NXOpen.Face.FaceType.Planar
            and nx.doubles_equal(nx.body_box(cast(Any, face)).MinZ, top_z)
            and nx.doubles_equal(nx.body_box(cast(Any, face)).MaxZ, top_z)]
    if len(tops) != 1:
        raise RuntimeError("{} has {} flat top faces, expected 1".format(part.Leaf, len(tops)))

    curves = [nx.edge_to_curve(edge) for edge in tops[0].GetEdges()]
    profile = _offset_outward(curves, -TrimPadPocketInsetMm * per_mm)
    start = -_TrimPadPocketStartAboveMm * per_mm
    # Lifted off the top face: start is measured along -Z, so a negative start is above it.
    extrude = _snap_extrude(profile, _VectorZN, TrimPadPocketDepthMm * per_mm, start=start)
    faces_before = {face.Tag for face in body.GetFaces()}
    subtract = nx.subtract(body, list(extrude.GetBodies()))
    # The pocket's walls and floor come from the extrude and would keep its color: they get the pad's (2026-11-07).
    new_faces = list(subtract.GetFaces()) or [face for face in body.GetFaces() if face.Tag not in faces_before]
    for face in new_faces:
        nx.set_color(face, TrimPadColor)


def _is_vertical(edge: NXOpen.Edge) -> bool:
    """Body.__VerticalEdges' test - the edge's two ends at different Z (.001 tolerance)."""
    start, end = edge.GetVertices()
    return not nx.doubles_equal(start.Z, end.Z)


def _single_solid_body_on_layer1(part: NXOpen.Part) -> NXOpen.Body:
    """BasePart.__SingleSolidBodyOnLayer1 - throws unless exactly one solid body sits on layer 1."""
    bodies = [body for body in part.Bodies if body.IsSolidBody and body.Layer == 1]
    if len(bodies) != 1:
        raise RuntimeError("{} has {} solid bodies on layer 1, expected 1".format(part.Leaf, len(bodies)))
    return bodies[0]


def _distances(box: nx.Box3d) -> Tuple[float, float, float]:
    """Box3d.Distances"""
    return box.MaxX - box.MinX, box.MaxY - box.MinY, box.MaxZ - box.MinZ


def _from_min(box: nx.Box3d, dx: float, dy: float, dz: float) -> NXOpen.Point3d:
    """bounding.MinXyz.__Add(dx, dy, dz)"""
    return NXOpen.Point3d(box.MinX + dx, box.MinY + dy, box.MinZ + dz)


def _pad_step(label: str, step: Callable[[], None]) -> None:
    """
    One placement group. The C# has no try/catch here, so a failed group ends the build - kept: the exception goes
    up to static_gm_cast_trim_pad's handler after naming the group.
    """
    try:
        step()
    except Exception:
        nx.print_("Cast trim pad: {} failed".format(label))
        raise


def main() -> None:
    """The cast-trim-pad UFunc - its menu button runs this file. An escaping exception is printed."""
    with nx.merlin_run("cast-trim-pad"):
        try:
            # The Cast Trim Pad dialog (customer + bodies) stands in for the "Are you sure" box.
            CastTrimPad.execute(True)
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
