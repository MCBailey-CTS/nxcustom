"""
Python port of the draw-die UFunc (Merlin.StaticDrawDie, src\\UFuncs\\MerlinDrawDie.cs).
The C# wrapper was deleted 2026-10-22 (in git at 1cb53d8): the UFunc's menu button runs this file's main().

The Merlin builder for a full draw station minus the nitrogen, from the "DRAW DIE PROGRAM" spec. Run from the
-000; one run builds both halves:
  - LAD02: the lower cast binder (BINDER-3D), eight post form steels (LWR-3D) and the lower cast riser under them.
  - UAD02: eight cavity form steels (UPR-3D) and the mounting plate on top of them.
All sizes are measured off the selected part bodies' box in the -000, mapped into each station's coordinates.

Two ways in:
  - File -> Execute -> NX Open on this file runs main(), which does the body pick itself (the C# entry point
    picks inside StaticDrawDie, so this is the like-for-like entry) with is_gm = True, as the draw-die UFunc does.
  - Session.Execute("DrawDie.py", "DrawDie", "execute", is_gm) from C#.
  - Session.Execute("DrawDie.py", "DrawDie", "build", is_gm, bodies) - the build half only (Merlin.BuildDrawDie,
    build_draw_die): no units / -000 gates and no pick; the stations are looked up again. AutoDesign calls this.

Differences from the C#:
  - The DrawDieDialog stage picker is not ported. It is commented out in StaticDrawDie (every stage is built), and
    SNAP dialogs are .NET-only anyway. The stage flags are kept as plain booleans so the gating reads the same.
  - OffsetDrawDieCurves is not ported - nothing calls it.
  - GFolder.create_or_null (print-only, result discarded) is not ported, as in PointComponent.py.
  - The AutoSize UDO class can only be registered from C# (see tsg_nx.create_auto_size_udo). Run standalone in a
    session where TSG_Library never registered it, the blocks get no UDO and "fixed description" has nothing to
    switch off - both print and carry on.
  - BlockFeatureBuilder.Length/Width/Height come back None in Python (README "Known differences"), so the re-base
    reads the block's size expressions through UF_MODL_ask_block_parms instead.

The Merlin helpers PointComponent.py already ports (subtool, SubtractComponents, SetReferenceSetInAncestorAssemblies,
RandomFileToken, the split palette) are imported from it rather than copied.
"""

from __future__ import annotations

import datetime
import math
import os
import random
import sys
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, TypeVar, cast

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
import NXOpen.Layer  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
import PointComponent as merlin  # noqa: E402

_T = TypeVar("_T")

Placement = Tuple[NXOpen.Point3d, Optional[NXOpen.Matrix3x3]]

# ---------------------------------------------------------------------------------------------------
# Constants (Draw Die - Constants region, plus the Merlin ones it uses). All lengths in inches; the spec's
# millimetre values are converted where they are declared.
# ---------------------------------------------------------------------------------------------------

# Cast details (binder, riser) - dark red.
CastColor = 13

BinderOverhangX = 3.75
BinderOverhangY = 4.50
BinderMinThickness = 4.00

BinderJackInsetX = 1.50
BinderJackInsetY = 3.00

BinderHoistRingInsetY = 10.00
BinderHoistRingAboveBottom = 2.00
BinderHoistRingStandoff = 5 / 25.4

BinderNitroInset = 4.00
BinderPadBalancerInset = 5.00
BinderPadBalancerOffBottom = 4.00
BinderGuidedRetainerInset = 55 / 25.4
BinderGuidedRetainerOffBottom = 1 / 25.4

# The stations the two halves are built into, matched (lower case) in the -000's display names.
DrawDieLowerStation = "lad02"
DrawDieUpperStation = "uad02"

# The subtract reference sets the selected part must carry, matched ignoring case.
DrawDieBinderRefset = "BINDER-3D"
DrawDieLowerRefset = "LWR-3D"
DrawDieUpperRefset = "UPR-3D"

FormSteelColumns = 2
FormSteelRows = 4
PostMinThickness = 2.50
CavityMinThickness = 2.75

PostShcsInset = .625
PostJackInset = .500

CavityOverhang = 1.00
CavityShcsInset = 1.00
CavityJackInset = 1.50

RiserOffset = .25

# How far the linked BINDER-3D bottom face is extruded each way along the riser's Z.
BinderFaceExtrudeDistance = 50.0

# Body color of that extrude.
BinderFaceExtrudeColor = 186

# How far every face of that extrude is offset inward (the body gets smaller).
BinderFaceOffset = .25
RiserThickness = 4.00

PlateOverhangX = 1.75
PlateOverhangY = 2.50
PlateThickness = 2.00
PlateShcsInsetX = 1.00
PlateShcsInsetY = 3.00
PlateHoistRingInset = 1.00

NitroPlateHandlingRefset = "NITRO_PLATE_HANDLING"
_castPadLocatorInset = 1.5748031496062991

_shcs12mm100Path = "G:\\0Library\\Fasteners\\Metric\\SocketHeadCapScrews-2X\\012-2x\\12mm-shcs-100-2x.prt"
_shcs16mm060Path = "G:\\0Library\\Fasteners\\Metric\\SocketHeadCapScrews-2X\\016-2x\\16mm-shcs-060-2x.prt"
_shcs20mm060Path = "G:\\0Library\\Fasteners\\Metric\\SocketHeadCapScrews-2X\\020-2x\\20mm-shcs-060-2x.prt"
_jck12mmScrewTsgPath = "G:\\0Library\\Fasteners\\Metric\\JackScrews\\12mm-jck-screw-tsg.prt"
_tsgNitroExtensionPath = "G:\\0Library\\TsgComponents\\NitroExtensions\\Smart TSG Nitro Extension.prt"
_tsgPadBalancerPath = "G:\\0Library\\TsgComponents\\PadBalancers\\Smart TSG Pad Balancers.prt"
_gmKeyPath = "G:\\0Library\\0Customer\\GM\\Smart GM Key.prt"
_gmGuidedRetainerPath = "G:\\0Library\\0Customer\\GM\\Smart GM Guided Retainer.prt"
_gmHoistRingPath = "G:\\0Library\\0Customer\\GM\\GM 16MM DIA PLDW Hoist Ring.prt"
_gmCastPadLocatorPath = "G:\\CTS\\junk\\blank-station-data\\GM CAST PAD LOCATOR.prt"
_ctsSmartKeyMetric = "G:\\0Library\\Keys\\Smart Key Metric.prt"
_ctsSmartSlGuidedKeeper = "G:\\0Library\\StandardLifters\\GuidedKeepers\\Smart SL Guided Keepers.prt"

# Smart GM Key sizes: (Main!I3 radio value = the Data sheet's column B row number, the Label the sheet gives it).
PostKeySize = (6, "25mm - 50mm")        # Jolico J-996457
CavityKeySize = (7, "25mm - 80mm")      # Jolico J-996443 - the seed's own setting
RiserKeySize = (8, "25mm - 100mm")      # Jolico J-996444
PlateKeySize = (8, "25mm - 100mm")      # Jolico J-996444

# Smart GM Key sheet cells (1-based row, column). Main!I3 is the hidden cell the size radio buttons write.
_keySizeCell = (3, 9)
# Exp-Attr: expression name in B / value in C on rows 3-30 (UG_ACTIVE_RNG), attribute "Title" (str) in E / value
# in F on rows 3-6 (UG_ATTR_RNG).
_keyExpressionRows = (3, 30)
_keyAttributeRows = (3, 6)

# Smart GM Guided Retainer, as the spec pictures it: GRS.50.HD with the Plate Adapter Cap, 105 mm stroke, 75 mm travel.
GuidedRetainerModel = 1                 # Main!J4 model radio: 1 = GRS.50.HD, 2 = GRS.65.HD (the seed's)
GuidedRetainerStroke = 105.0            # mm - must be in the sheet's GRS_50_HD list (55-155 by 10)
GuidedRetainerTravel = 75.0             # mm
GuidedRetainerDescription = "GRS.50.HD.J.1050.FH.AC Guided Retainer"

# Smart GM Guided Retainer sheet cells (1-based row, column), all on Main's hidden columns J-L but G.
_retainerModelCell = (4, 10)            # J4
_retainerStrokeCell = (9, 7)            # G9
_retainerTravelCell = (12, 7)           # G12
# Exp-Attr: expression name in B / value in C on rows 3-37 (UG_ACTIVE_RNG), attribute title in E / value in F on
# rows 3-7 (UG_ATTR_RNG: Description, Material, LABEL, LIBRARY, REVISION).
_retainerExpressionRows = (3, 37)
_retainerAttributeRows = (3, 7)

# uf_csys.h: UF_CSYS_ROOT_COORDS 1, UF_CSYS_WORK_COORDS 2.
_UF_CSYS_ROOT_COORDS = 1
_UF_CSYS_WORK_COORDS = 2

# NXException.ErrorCode when a subtract from a dynamic block fails (SubtractRefsetFromDynamicBlock prints it).
_ErrorCouldNotSubtract = 670030

# The AutoSize UDO's status attribute (Extensions.AutoUpdateAttribute).
_AutoUpdateAttribute = "AUTO UPDATE"

_VectorX = NXOpen.Vector3d(1.0, 0.0, 0.0)
_VectorY = NXOpen.Vector3d(0.0, 1.0, 0.0)
_VectorZ = NXOpen.Vector3d(0.0, 0.0, 1.0)
_VectorXN = NXOpen.Vector3d(-1.0, 0.0, 0.0)
_VectorYN = NXOpen.Vector3d(0.0, -1.0, 0.0)
_VectorZN = NXOpen.Vector3d(0.0, 0.0, -1.0)


class DrawDie(object):

    @staticmethod
    def execute(is_gm: bool = True) -> None:
        """Merlin.StaticDrawDie(is_gm) - the draw-die UFunc passes is_gm = true."""
        try:
            static_draw_die(bool(is_gm))
        except Exception as ex:
            nx.print_exception(ex)

    @staticmethod
    def build(is_gm: bool, bodies: Sequence[NXOpen.TaggedObject], quiet: bool = False,
              skip_spreadsheets: bool = False) -> None:
        """
        Merlin.BuildDrawDie(is_gm, bodies) - the build half, on part bodies the caller already picked (AutoDesign).
        No units / -000 gates and no pick: run with the -000 as the display part. quiet leaves out the elapsed time
        and "Created reference set" lines; skip_spreadsheets leaves every key's and guided retainer's sheet unopened
        (AutoDesign's Edit Spreadsheets off).
        """
        DrawDie._build_halves(is_gm, bodies, quiet, skip_spreadsheets, lower=True, upper=True)

    @staticmethod
    def build_upper(is_gm: bool, bodies: Sequence[NXOpen.TaggedObject], quiet: bool = False,
                    skip_spreadsheets: bool = False) -> None:
        """
        build, the upper half only: the cavity form steels and the mounting plate in UAD02, subtracting UPR-3D.
        Dead Strike's upper (and so Auto Design's DEADHIT upper) is exactly this.
        """
        DrawDie._build_halves(is_gm, bodies, quiet, skip_spreadsheets, lower=False, upper=True)

    @staticmethod
    def _build_halves(is_gm: bool, bodies: Sequence[NXOpen.TaggedObject], quiet: bool, skip_spreadsheets: bool,
                      lower: bool, upper: bool) -> None:
        global _skip_spreadsheets
        _skip_spreadsheets = bool(skip_spreadsheets)
        try:
            with nx.quiet_listing(quiet):
                build_draw_die(bool(is_gm), [cast(NXOpen.Body, body) for body in bodies], build_lower_half=lower,
                               build_upper_half=upper)
        except Exception as ex:
            nx.print_exception(ex)
        finally:
            _skip_spreadsheets = False


# ---------------------------------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------------------------------

class DrawDieJob(object):
    """Merlin.DrawDieJob - everything every Draw Die stage needs from the entry point."""

    def __init__(self, is_gm: bool, is_upper: bool, top_level: NXOpen.Part, station: NXOpen.Part,
                 components: Sequence[NXOpen.Assemblies.Component], part_box: nx.Box3d) -> None:
        self.is_gm = is_gm
        self.is_upper = is_upper
        # The -000 - the selected components are occurrences in its tree.
        self.top_level = top_level
        # LAD02 or UAD02 - every detail of this half is built into it.
        self.station = station
        # The selected bodies' components - the subtract sources.
        self.components = components
        # The selected bodies' combined box, mapped into the station's coordinates.
        self.part_box = part_box
        # BINDER-3D as the selected components spell it - subtracted from the binder (lower only).
        self.binder_refset: Optional[str] = None
        # LWR-3D (posts) or UPR-3D (cavity) as the selected components spell it.
        self.form_steel_refset: Optional[str] = None

    @property
    def prefix(self) -> str:
        """"gm" or "cts" - the component-name prefix."""
        return "gm" if self.is_gm else "cts"

    @property
    def dir(self) -> str:
        """Where the Save As'd library parts go - the station's folder."""
        return os.path.dirname(self.station.FullPath)


def static_draw_die(is_gm: bool) -> None:
    """
    Merlin.StaticDrawDie - run from the -000: the units and -000 gates, the station check (before the pick, so a job
    missing a station fails before the user selects anything), the body pick, then build_draw_die.
    """
    ok, message = _check_info_units()
    if not ok:
        nx.show_error(message)
        return

    if not nx.display_part().Leaf.endswith("-000"):
        nx.show_error("Draw Die must be run from the 000.")
        return

    # Checked before the pick so a job missing a station fails before the user selects anything.
    if _try_find_draw_die_stations() is None:
        return

    label = "Draw Die"
    version = nx.assembly_file_version()
    bodies = _select_bodies("Select solid bodies for {}: {}".format(label, version), "{}: {}".format(label, version))

    if not bodies:
        return

    build_draw_die(is_gm, bodies)


# The C# stage dialog is commented out - every stage is built, as if all its boxes were ticked.
_BuildBinder = _BuildPosts = _BuildRiser = True
_BuildCavity = _BuildMountingPlate = True
_BuildLower = _BuildBinder or _BuildPosts or _BuildRiser
_BuildUpper = _BuildCavity or _BuildMountingPlate


def _try_find_draw_die_stations(lower: bool = True, upper: bool = True
                                ) -> Optional[Tuple[Optional[NXOpen.Assemblies.Component],
                                                    Optional[NXOpen.Assemblies.Component]]]:
    """
    Merlin.TryFindDrawDieStations - LAD02 / UAD02 under the display part, each looked up only when its half has a
    stage and is wanted (lower / upper; None otherwise). Shows an error naming the missing ones and returns None when
    any is missing.
    """
    root = nx.root_component(nx.display_part())
    descendants = list(nx.descendants(root)) if root is not None else []

    def find_station(name: str) -> Optional[NXOpen.Assemblies.Component]:
        return next((c for c in descendants if name in c.DisplayName.lower()), None)

    want_lower = _BuildLower and lower
    want_upper = _BuildUpper and upper
    station_lad = find_station(DrawDieLowerStation) if want_lower else None
    station_uad = find_station(DrawDieUpperStation) if want_upper else None
    missing = [name.upper() for station, name, wanted in ((station_lad, DrawDieLowerStation, want_lower),
                                                           (station_uad, DrawDieUpperStation, want_upper))
               if wanted and station is None]

    if missing:
        nx.show_error("Draw Die could not find {} under {}.".format(" or ".join(missing), nx.display_part().Leaf))
        return None

    return station_lad, station_uad


def build_draw_die(is_gm: bool, bodies: Sequence[NXOpen.Body], build_lower_half: bool = True,
                   build_upper_half: bool = True) -> None:
    """
    Merlin.BuildDrawDie - the build half of static_draw_die, on part bodies the caller already has, so AutoDesign
    can drive it. Run from the -000; the caller brings the units and -000 gates. Builds the lower stages (binder,
    posts, riser) into LAD02 and the upper ones (cavity, mounting plate) into UAD02 - only the halves asked for
    (Dead Strike builds the upper alone). Each stage is caught on its own, so a failed binder still leaves the posts
    and riser to be built, and a failed lower half the upper one.
    """
    stations = _try_find_draw_die_stations(build_lower_half, build_upper_half)
    if stations is None:
        return

    station_lad, station_uad = stations
    build_binder = _BuildBinder and build_lower_half
    build_posts = _BuildPosts and build_lower_half
    build_riser = _BuildRiser and build_lower_half
    build_cavity = _BuildCavity and build_upper_half
    build_mounting_plate = _BuildMountingPlate and build_upper_half
    build_lower = station_lad is not None
    build_upper = station_uad is not None

    components: List[NXOpen.Assemblies.Component] = []
    for body in bodies:
        owner = body.OwningComponent
        if owner is not None and all(c.Tag != owner.Tag for c in components):
            components.append(owner)

    if not components:
        nx.show_error("Select the part's bodies as component occurrences - their components carry the "
                      "BINDER-3D / LWR-3D / UPR-3D reference sets.")
        return

    # The subtract reference sets the stages use, found on the selected components up front (ignoring case, so a
    # BINDER-3d still counts) - nothing is built when one is missing, rather than a die with an uncut detail. The
    # riser and mounting plate subtract nothing.
    wanted_refsets: List[str] = []
    if build_binder:
        wanted_refsets.append(DrawDieBinderRefset)
    if build_posts:
        wanted_refsets.append(DrawDieLowerRefset)
    if build_cavity:
        wanted_refsets.append(DrawDieUpperRefset)

    refsets: Dict[str, Optional[str]] = {name: _find_draw_die_refset(components, name) for name in wanted_refsets}
    missing_refsets = [name for name, found in refsets.items() if found is None]

    if missing_refsets:
        nx.show_error("None of the selected bodies' components ({}) has a {} reference set. Draw Die subtracts "
                      "BINDER-3D from the binder, LWR-3D from the posts and UPR-3D from the cavity - select the "
                      "part that carries them.".format(", ".join(c.DisplayName for c in components),
                                                       " / ".join(missing_refsets)))
        return

    nx.info("Draw Die: subtracting {} from {}.".format(
        ", ".join(cast(str, r) for r in refsets.values()), ", ".join(c.DisplayName for c in components)))

    top_level = nx.display_part()
    starting_work = nx.work_part()
    _set_wcs_to_absolute(top_level)

    nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Draw Die")

    try:
        # In the -000, then into each station - neither has to sit at identity in the -000.
        part_box = nx.combine_boxes([nx.body_box(b) for b in bodies])
        span_x = part_box.MaxX - part_box.MinX
        span_y = part_box.MaxY - part_box.MinY

        if span_x > span_y:
            nx.print_("Draw Die: the part is longer in X ({}) than in Y ({}). The spec lays the die out long along "
                      "Y, so the hoist rings and long-side placements will land on the short sides."
                      .format(_f3(span_x), _f3(span_y)))

        # Only the halves with a stage - the other station was not looked up.
        lower: Optional[DrawDieJob] = None
        if build_lower and station_lad is not None:
            lower = DrawDieJob(is_gm, False, top_level, cast(NXOpen.Part, nx.prototype(station_lad)), components,
                               _map_box_to_station(part_box, station_lad, top_level, starting_work))
            lower.binder_refset = refsets.get(DrawDieBinderRefset)
            lower.form_steel_refset = refsets.get(DrawDieLowerRefset)

        upper: Optional[DrawDieJob] = None
        if build_upper and station_uad is not None:
            upper = DrawDieJob(is_gm, True, top_level, cast(NXOpen.Part, nx.prototype(station_uad)), components,
                               _map_box_to_station(part_box, station_uad, top_level, starting_work))
            upper.form_steel_refset = refsets.get(DrawDieUpperRefset)

        start = datetime.datetime.now()
        try:
            with nx.suppress_display():
                # The riser and mounting plate are sized off the posts / cavity boxes, so a failed posts or
                # cavity stage skips its dependant.
                if build_binder and lower is not None:
                    _run_draw_die_stage("binder", lambda: _build_draw_die_binder(cast(DrawDieJob, lower)))

                posts = (_run_draw_die_stage("posts", lambda: _build_draw_die_posts(cast(DrawDieJob, lower)))
                         if build_posts and lower is not None else None)

                if posts is not None and build_riser:
                    _run_draw_die_stage("riser", lambda: _build_draw_die_riser(cast(DrawDieJob, lower),
                                                                              cast(nx.Box3d, posts)))

                cavity = (_run_draw_die_stage("cavity", lambda: _build_draw_die_cavity(cast(DrawDieJob, upper)))
                          if build_cavity and upper is not None else None)

                if cavity is not None and build_mounting_plate:
                    _run_draw_die_stage("mounting plate",
                                        lambda: _build_draw_die_mounting_plate(cast(DrawDieJob, upper),
                                                                               cast(nx.Box3d, cavity)))
        finally:
            # Session.__UsingTimer prints the elapsed TimeSpan.
            if not nx.quiet:
                nx.print_(_time_span(datetime.datetime.now() - start))
    except Exception as ex:
        nx.print_exception(ex)
    finally:
        nx.set_display_part(top_level)
        nx.set_work_part(starting_work)


def _find_draw_die_refset(components: Iterable[NXOpen.Assemblies.Component], refset: str) -> Optional[str]:
    """
    Merlin.FindDrawDieRefset - the name of the refset reference set as the selected components' parts spell it,
    matched ignoring case (BINDER-3d finds BINDER-3D); None when none of them has it.
    """
    for component in components:
        for reference_set in nx.prototype(component).GetAllReferenceSets():
            if reference_set.Name.lower() == refset.lower():
                return reference_set.Name
    return None


def _map_box_to_station(root_box: nx.Box3d, station: NXOpen.Assemblies.Component, top_level: NXOpen.Part,
                        starting_work: NXOpen.Part) -> nx.Box3d:
    """
    Merlin.MapBoxToStation - root_box (in the -000) in station's coordinates: its eight corners mapped ROOT -> WORK
    with the station as the work component. Prints when the station is not at identity, and warns when it is turned
    - the builders put the lower details under the part and the upper ones over it in station Z.
    """
    def map_point(x: float, y: float, z: float) -> List[float]:
        return list(nx.ufsession_.Csys.MapPoint(_UF_CSYS_ROOT_COORDS, [float(x), float(y), float(z)], _UF_CSYS_WORK_COORDS))

    try:
        nx.set_display_part(top_level)
        nx.set_work_component(station)

        corners = [map_point(x, y, z)
                   for x in (root_box.MinX, root_box.MaxX)
                   for y in (root_box.MinY, root_box.MaxY)
                   for z in (root_box.MinZ, root_box.MaxZ)]

        origin = map_point(0, 0, 0)
        x_axis = map_point(1, 0, 0)
        z_axis = map_point(0, 0, 1)
        upright = abs(x_axis[0] - origin[0] - 1) < 1e-6 and abs(z_axis[2] - origin[2] - 1) < 1e-6

        if not upright:
            nx.print_("Draw Die: {} is turned in {}. The draw die is laid out in its coordinates, so check that the "
                      "details are not upside down.".format(station.DisplayName, top_level.Leaf))
        elif any(abs(c) > 1e-6 for c in origin):
            nx.print_("Draw Die: {} is not at the origin of {} - the part box was mapped into it.".format(
                station.DisplayName, top_level.Leaf))

        return nx.Box3d(min(c[0] for c in corners), min(c[1] for c in corners), min(c[2] for c in corners),
                        max(c[0] for c in corners), max(c[1] for c in corners), max(c[2] for c in corners))
    finally:
        nx.set_display_part(top_level)
        nx.set_work_part(starting_work)


def _run_draw_die_stage(label: str, stage: Callable[[], nx.Box3d]) -> Optional[nx.Box3d]:
    """Merlin.RunDrawDieStage - runs one stage and returns the box it built (None on failure)."""
    nx.prompt("Draw Die -> {}".format(label))
    try:
        return stage()
    except Exception as ex:
        nx.print_("Draw Die: the {} failed.".format(label))
        nx.print_exception(ex)
        return None


# ---------------------------------------------------------------------------------------------------
# Binder (lower)
# ---------------------------------------------------------------------------------------------------

def _build_draw_die_binder(job: DrawDieJob) -> nx.Box3d:
    """
    Merlin.BuildDrawDieBinder - the part's box + 3.75" per side in X and + 4.50" per side in Y, at least 4" thick
    under the part's lowest point, BINDER-3D subtracted. Children: 8 jack screws, 4 side hoist rings, 4 cast pad
    locators, 6 nitro extensions, 4 pad balancers and 6 guided retainers.
    """
    box = job.part_box
    xlength = nx.round_to_125(box.MaxX - box.MinX) + 2 * BinderOverhangX
    ywidth = nx.round_to_125(box.MaxY - box.MinY) + 2 * BinderOverhangY
    height = nx.round_to_125(box.MaxZ - box.MinZ + BinderMinThickness)
    min_point = _centered_min(box, xlength, ywidth, box.MaxZ - height)

    new_part, component = _promote_draw_die_block(
        job, min_point, xlength, ywidth, height,
        name="{}-draw-die-binder".format(job.prefix),
        color=CastColor,
        description="LOWER CAST BINDER",
        material="GM190/S0050A",
        detail_name="LOWER CAST BINDER",
        fixed_description=True)

    body_refset = nx.find_or_create_reference_set(new_part, "BODY")
    up = nx.identity_matrix()
    upside_down = nx.matrix_from_axes(_VectorX, _VectorYN)

    # Jack screws: two rows of four, symmetric about both centrelines, from the bottom.
    def jack_screws() -> None:
        jack_xs = [BinderJackInsetX, xlength - BinderJackInsetX]
        jack_ys = _even_stations(BinderJackInsetY, ywidth - BinderJackInsetY, 4)
        _place_draw_die_children("binder jack screw", _jck12mmScrewTsgPath,
                                 [(NXOpen.Point3d(x, y, 0.0), up) for x in jack_xs for y in jack_ys],
                                 layer=99, subtract_refset="CBORE_BLIND", body_refset=body_refset)

    _draw_die_step("binder jack screws", jack_screws)

    # Hoist rings: sideways on the two long (X) faces, 10" in from each end, 2" up, 5 mm off the face.
    def hoist_rings() -> List[NXOpen.Assemblies.Component]:
        ring_z = BinderHoistRingAboveBottom
        return _place_draw_die_children("binder hoist ring", _gmHoistRingPath, [
            (NXOpen.Point3d(xlength + BinderHoistRingStandoff, BinderHoistRingInsetY, ring_z), _z_matrix(_VectorX)),
            (NXOpen.Point3d(xlength + BinderHoistRingStandoff, ywidth - BinderHoistRingInsetY, ring_z),
             _z_matrix(_VectorX)),
            (NXOpen.Point3d(-BinderHoistRingStandoff, BinderHoistRingInsetY, ring_z), _z_matrix(_VectorXN)),
            (NXOpen.Point3d(-BinderHoistRingStandoff, ywidth - BinderHoistRingInsetY, ring_z), _z_matrix(_VectorXN)),
        ], layer=98, subtract_refset=NitroPlateHandlingRefset, body_refset=None)

    rings: List[NXOpen.Assemblies.Component] = _draw_die_step_result("binder hoist rings", hoist_rings, [])

    # Cast pad locators: on the bottom, on both centrelines, one in from each edge.
    def cast_pad_locators() -> List[NXOpen.Assemblies.Component]:
        locator_path = _gmCastPadLocatorPath if job.is_gm else _ctsSmartKeyMetric
        front_back = _lower_key_front_back_orientation()
        return _place_draw_die_children("binder cast pad locator", locator_path, [
            (NXOpen.Point3d(xlength / 2, _castPadLocatorInset, 0.0), front_back),
            (NXOpen.Point3d(xlength / 2, ywidth - _castPadLocatorInset, 0.0), front_back),
            (NXOpen.Point3d(_castPadLocatorInset, ywidth / 2, 0.0), up),
            (NXOpen.Point3d(xlength - _castPadLocatorInset, ywidth / 2, 0.0), up),
        ], layer=98, subtract_refset=None, body_refset=None)

    locators: List[NXOpen.Assemblies.Component] = _draw_die_step_result("binder cast pad locators",
                                                                        cast_pad_locators, [])

    # Half in the block, half out of it: centre each locator's body on the bottom face (Z 0).
    _draw_die_step("binder cast pad locators - straddle the bottom face",
                   lambda: _center_draw_die_children_on_z(new_part, locators, 0.0))

    _draw_die_step("binder BODY reference set (hoist rings and locators)",
                   lambda: _keep_out_of_reference_set(body_refset, rings + locators))

    # Nitro extensions: upside down on the bottom face - four 4" in from the corners, two at mid-length.
    def nitro_extensions() -> None:
        nitros = _place_draw_die_children(
            "binder nitro extension", _tsgNitroExtensionPath,
            [(p, upside_down) for p in _corners_and_mid_length(xlength, ywidth, BinderNitroInset, 0.0)],
            layer=99, subtract_refset=None, body_refset=body_refset)
        # TODO(draw-die): set the nitro extensions once their expression names are known.
        _save_as_draw_die_part(nitros, job, "draw-die-binder-nitro-extension")

    _draw_die_step("binder nitro extensions", nitro_extensions)

    # Pad balancers: 5" in from the corners, 4" off the bottom.
    def pad_balancers() -> None:
        balancers = _place_draw_die_children(
            "binder pad balancer", _tsgPadBalancerPath,
            [(NXOpen.Point3d(p.X, p.Y, -BinderPadBalancerOffBottom), up)
             for p in _inset_corners(xlength, ywidth, BinderPadBalancerInset)],
            layer=99, subtract_refset=None, body_refset=body_refset)
        _save_as_draw_die_part(balancers, job, "draw-die-binder-pad-balancer")

    _draw_die_step("binder pad balancers", pad_balancers)

    # Guided retainers: 55 mm in from the corners plus two at mid-length, 1 mm off the bottom.
    def guided_retainers() -> None:
        retainer_path = _gmGuidedRetainerPath if job.is_gm else _ctsSmartSlGuidedKeeper
        # Upside down (a 180 degree roll about X), like the nitro extensions - +Z put them in the wrong way up.
        retainers = _place_draw_die_children(
            "binder guided retainer", retainer_path,
            [(p, upside_down) for p in _corners_and_mid_length(xlength, ywidth, BinderGuidedRetainerInset,
                                                               -BinderGuidedRetainerOffBottom)],
            layer=99, subtract_refset=None, body_refset=body_refset)
        _set_draw_die_guided_retainer(retainers, job)
        _save_as_draw_die_part(retainers, job, "draw-die-binder-guided-retainer")

    _draw_die_step("binder guided retainers", guided_retainers)

    # TODO(draw-die): the cast text import fails in the C# - commented out there until it is fixed, so not ported.

    _finish_draw_die_block(job, new_part, component, job.binder_refset)
    return _box_from(min_point, xlength, ywidth, height)


# ---------------------------------------------------------------------------------------------------
# Posts and riser (lower)
# ---------------------------------------------------------------------------------------------------

def _build_draw_die_posts(job: DrawDieJob) -> nx.Box3d:
    """
    Merlin.BuildDrawDiePosts - eight post form steels: the part's box (rounded up to 1/8") split down its centre in
    X and into four along Y, .004" apart, at least 2.5" thick under the part's lowest point, LWR-3D subtracted.
    Returns the overall box.
    """
    box = job.part_box
    xlength = nx.round_to_125(box.MaxX - box.MinX)
    ywidth = nx.round_to_125(box.MaxY - box.MinY)
    height = nx.round_to_125(box.MaxZ - box.MinZ + PostMinThickness)
    min_point = _centered_min(box, xlength, ywidth, box.MaxZ - height)

    _build_draw_die_form_steels(job, min_point, xlength, ywidth, height,
                                name="{}-draw-die-post".format(job.prefix),
                                subtract_refset=job.form_steel_refset,
                                shcs_path=_shcs12mm100Path,
                                shcs_inset=PostShcsInset,
                                jack_inset=PostJackInset,
                                key_save_name="draw-die-post-key",
                                key_size=PostKeySize,
                                keys_both_ways=True)

    return _box_from(min_point, xlength, ywidth, height)


def _build_draw_die_riser(job: DrawDieJob, posts: nx.Box3d) -> nx.Box3d:
    """
    Merlin.BuildDrawDieRiser - lower cast riser under the posts: their overall box + .25" per side, 4" thick, with
    4 keys on the bottom. Built from the posts' box rather than a wave link of them, so it is not associative.
    """
    xlength = posts.MaxX - posts.MinX + 2 * RiserOffset
    ywidth = posts.MaxY - posts.MinY + 2 * RiserOffset
    min_point = NXOpen.Point3d(posts.MinX - RiserOffset, posts.MinY - RiserOffset, posts.MinZ - RiserThickness)

    new_part, component = _promote_draw_die_block(
        job, min_point, xlength, ywidth, RiserThickness,
        name="{}-draw-die-riser".format(job.prefix),
        color=CastColor,
        description="LOWER CAST RISER",
        material="GM241/G3500",
        detail_name="LOWER CAST RISER",
        fixed_description=True)

    def riser_keys() -> None:
        keys = _place_draw_die_edge_keys(job, xlength, ywidth, RiserThickness)
        nx.find_or_create_reference_set(new_part, "BODY").AddObjectsToReferenceSet(keys)
        _set_draw_die_key_size(keys, job, RiserKeySize)
        _save_as_draw_die_part(keys, job, "draw-die-riser-key")

    _draw_die_step("riser keys", riser_keys)

    _finish_draw_die_block(job, new_part, component, subtract_refset=None)

    _draw_die_step("riser BINDER-3D bottom face link", lambda: _link_lowest_binder_face(job, new_part))

    return _box_from(min_point, xlength, ywidth, RiserThickness)


def _link_lowest_binder_face(job: DrawDieJob, new_part: NXOpen.Part) -> None:
    """
    Merlin.LinkLowestBinderFace - for each selected component with the binder reference set: switch it to
    BINDER-3D, make new_part the work part (in the -000), find the lowest planar face of the component's solid
    bodies, name it HELLO and wave-link it into the riser on layer 96, remove the link's parameters, extrude its one
    face 50" up and down, offset that solid's faces .25" inward (printing the offset's expression), intersect the
    riser with it and color the riser's top and bottom faces 42, then put the component back on the reference set
    it had.
    """
    binder_refset = job.binder_refset

    try:
        nx.set_display_part(job.top_level)

        if binder_refset is None:
            return

        for comp in job.components:
            if not nx.has_reference_set(nx.prototype(comp), binder_refset):
                continue

            original_refset = comp.ReferenceSet

            try:
                nx.set_reference_set(comp, binder_refset)

                # Lowest in the -000: the planar face whose highest point is lowest.
                planar = [f for b in nx.solid_body_members(comp) for f in b.GetFaces()
                          if f.SolidFaceType == NXOpen.Face.FaceType.Planar]

                if not planar:
                    nx.print_("Draw Die: did NOT find the bottom face of {} ({} has no planar solid face).".format(
                        comp.DisplayName, binder_refset))
                    continue

                face = min(planar, key=lambda f: _exact_box(f).MaxZ)
                face_box = _exact_box(face)
                nx.info("Draw Die: found the bottom face of {} ({}) at Z {} .. {}, {} edges.".format(
                    comp.DisplayName, binder_refset, _f3(face_box.MinZ), _f3(face_box.MaxZ), len(face.GetEdges())))

                # Named on the occurrence, so it shows as HELLO in the -000.
                face.SetName("HELLO")

                nx.set_work_part(new_part)
                new_part.Layers.WorkLayer = 96

                # Wave-link the bottom face into the riser (the work part) on layer 96.
                linked_face = _create_linked_face([face])
                nx.info("Draw Die: linked the lowest {} face of {} into {}, layer 96 ({}).".format(
                    binder_refset, comp.DisplayName, new_part.Leaf, linked_face.JournalIdentifier))

                # Remove its parameters: what is left is a plain sheet body with the one face.
                sheets = linked_face.GetBodies()
                if len(sheets) != 1:
                    raise RuntimeError("The linked face {} has {} bodies, expected 1.".format(
                        linked_face.JournalIdentifier, len(sheets)))
                sheet = sheets[0]
                _remove_parameters([sheet])
                sheet_faces = sheet.GetFaces()
                if len(sheet_faces) != 1:
                    raise RuntimeError("The linked sheet has {} faces, expected 1.".format(len(sheet_faces)))

                extrude = _extrude_binder_face(new_part, sheet_faces[0], BinderFaceExtrudeDistance)
                solid = extrude.GetBodies()[0]
                nx.set_color(solid, BinderFaceExtrudeColor)
                nx.info("Draw Die: extruded the linked face {} up and down in {} ({}).".format(
                    _f3(BinderFaceExtrudeDistance), new_part.Leaf, extrude.JournalIdentifier))

                expression = _offset_binder_face_body_inward(new_part, solid, BinderFaceOffset)
                nx.info("Draw Die: offset {} inward {} - expression {} = {}.".format(
                    extrude.JournalIdentifier, _f3(BinderFaceOffset), expression.Name, expression.RightHandSide))

                # Intersect the riser with the offset body, then color the result's top and bottom faces.
                riser_body = nx.dynamic_block(new_part).GetBodies()[0]
                nx.create_boolean(riser_body, [solid], NXOpen.Features.Feature.BooleanType.Intersect)
                for normal in (_VectorZ, _VectorZN):
                    riser_face = nx.planar_face_with_normal_or_null(riser_body, normal)
                    if riser_face is not None:
                        nx.set_color(riser_face, 42)
                nx.info("Draw Die: intersected the riser in {} with the offset body.".format(new_part.Leaf))

                # The linked face's sheet stays in the riser on layer 96, but not in its BODY reference set.
                body_refset = nx.find_reference_set_or_null(new_part, "BODY")
                if body_refset is not None:
                    _keep_out_of_reference_set(body_refset, [sheet])
            finally:
                new_part.Layers.WorkLayer = 1
                nx.set_reference_set(comp, original_refset)
    finally:
        nx.set_display_part(job.station)
        nx.set_work_part(job.station)


# ---------------------------------------------------------------------------------------------------
# Cavity and mounting plate (upper)
# ---------------------------------------------------------------------------------------------------

def _build_draw_die_cavity(job: DrawDieJob) -> nx.Box3d:
    """
    Merlin.BuildDrawDieCavity - eight cavity form steels: the part's box + 1" per side, split like the posts, at
    least 2.75" thick over the part's highest point, UPR-3D subtracted. Returns the overall box.
    """
    min_point, xlength, ywidth, height = _cavity_size(job.part_box)

    _build_draw_die_form_steels(job, min_point, xlength, ywidth, height,
                                name="{}-draw-die-cavity".format(job.prefix),
                                subtract_refset=job.form_steel_refset,
                                shcs_path=_shcs16mm060Path,
                                shcs_inset=CavityShcsInset,
                                jack_inset=CavityJackInset,
                                key_save_name="draw-die-cavity-key",
                                key_size=CavityKeySize,
                                keys_both_ways=True)

    return _box_from(min_point, xlength, ywidth, height)


def _cavity_size(box: nx.Box3d) -> Tuple[NXOpen.Point3d, float, float, float]:
    """(min corner, xlength, ywidth, height) of the cavity steels over the part's box, in station coordinates."""
    xlength = nx.round_to_125(box.MaxX - box.MinX) + 2 * CavityOverhang
    ywidth = nx.round_to_125(box.MaxY - box.MinY) + 2 * CavityOverhang
    height = nx.round_to_125(box.MaxZ - box.MinZ + CavityMinThickness)
    return _centered_min(box, xlength, ywidth, box.MinZ), xlength, ywidth, height


def _mounting_plate_size(cavity: nx.Box3d) -> Tuple[NXOpen.Point3d, float, float, float]:
    """(min corner, xlength, ywidth, thickness) of the mounting plate on top of the cavity steels."""
    xlength = cavity.MaxX - cavity.MinX + 2 * PlateOverhangX
    ywidth = cavity.MaxY - cavity.MinY + 2 * PlateOverhangY
    min_point = NXOpen.Point3d(cavity.MinX - PlateOverhangX, cavity.MinY - PlateOverhangY, cavity.MaxZ)
    return min_point, xlength, ywidth, PlateThickness


def upper_preview_boxes(part_box: nx.Box3d) -> List[Tuple[NXOpen.Point3d, float, float, float]]:
    """
    The (origin, x, y, z) boxes the upper half builds over part_box (in UAD02's coordinates): the FormSteelColumns x
    FormSteelRows cavity steels, then the mounting plate last. Empty when the box is too small to split.
    """
    min_point, xlength, ywidth, height = _cavity_size(part_box)
    column_width = (xlength - (FormSteelColumns - 1) * merlin.SplitGap) / FormSteelColumns
    row_length = (ywidth - (FormSteelRows - 1) * merlin.SplitGap) / FormSteelRows
    if column_width <= 0 or row_length <= 0:
        return []
    boxes = [(NXOpen.Point3d(min_point.X + column * (column_width + merlin.SplitGap),
                             min_point.Y + row * (row_length + merlin.SplitGap), min_point.Z),
              column_width, row_length, height)
             for column in range(FormSteelColumns) for row in range(FormSteelRows)]
    boxes.append(_mounting_plate_size(_box_from(min_point, xlength, ywidth, height)))
    return boxes


def _build_draw_die_mounting_plate(job: DrawDieJob, cavity: nx.Box3d) -> nx.Box3d:
    """
    Merlin.BuildDrawDieMountingPlate - on top of the cavity steels: 1.75" per side wider and 2.50" per end longer,
    2" thick. Children: 10 x 20mm-shcs-060-2x (5 per long side), 8 jack screws, 4 corner hoist rings, 4 keys.
    """
    min_point, xlength, ywidth, thickness = _mounting_plate_size(cavity)

    new_part, component = _promote_draw_die_block(
        job, min_point, xlength, ywidth, thickness,
        name="{}-draw-die-mounting-plate".format(job.prefix),
        color=None,
        description="{:.3f} GRIND +.005/-.000 X {:.2f} X {:.2f}".format(thickness, xlength, ywidth),
        material="HRS",
        detail_name="RISER",
        fixed_description=True,
        # Both ground faces yellow: the top is the upper mounting face _promote_draw_die_block colors already, the
        # bottom (against the cavity steels) is added here.
        joint_normals=[_VectorZ, _VectorZN])

    body_refset = nx.find_or_create_reference_set(new_part, "BODY")

    # Upper detail: fasteners come in from the top (the shoe side), pointing -Z.
    down = _z_matrix(_VectorZN)

    # SHCS: 1" in from each long side, 5 per side - 3" from each end, one on the centreline, two between.
    xs = [PlateShcsInsetX, xlength - PlateShcsInsetX]
    shcs_ys = _even_stations(PlateShcsInsetY, ywidth - PlateShcsInsetY, 5)
    _draw_die_step("mounting plate SHCS", lambda: _place_draw_die_children(
        "mounting plate SHCS", _shcs20mm060Path,
        [(NXOpen.Point3d(x, y, thickness), down) for x in xs for y in shcs_ys],
        layer=99, subtract_refset="CBORE", body_refset=body_refset))

    # Jack screws: 8, aimed midway between neighbouring screws on the SHCS lines, then put on a 1" grid: the first
    # stays put and every other one is pulled back to whole inches from it in X and Y.
    def jack_screws() -> None:
        jack_ys = [(a + b) / 2 for a, b in zip(shcs_ys, shcs_ys[1:])]
        aimed = [NXOpen.Point3d(x, y, thickness) for x in xs for y in jack_ys]
        anchor = aimed[0]
        _place_draw_die_children("mounting plate jack screw", _jck12mmScrewTsgPath,
                                 [(_snap_to_inch_grid_from(anchor, p), down) for p in aimed],
                                 layer=99, subtract_refset="CBORE_BLIND", body_refset=body_refset)

    _draw_die_step("mounting plate jack screws", jack_screws)

    # Hoist rings: 1" in from each corner, on the bottom face, as the backside backing plate places them.
    def hoist_rings() -> None:
        rings = _place_draw_die_children(
            "mounting plate hoist ring", _gmHoistRingPath,
            [(NXOpen.Point3d(p.X, p.Y, 0.0), down) for p in _inset_corners(xlength, ywidth, PlateHoistRingInset)],
            layer=98, subtract_refset="SHORT-TAP", body_refset=None)
        _keep_out_of_reference_set(body_refset, rings)

    _draw_die_step("mounting plate hoist rings", hoist_rings)

    def plate_keys() -> None:
        keys = _place_draw_die_edge_keys(job, xlength, ywidth, thickness)
        body_refset.AddObjectsToReferenceSet(keys)
        _set_draw_die_key_size(keys, job, PlateKeySize)
        _save_as_draw_die_part(keys, job, "draw-die-mounting-plate-key")

    _draw_die_step("mounting plate keys", plate_keys)

    _finish_draw_die_block(job, new_part, component, subtract_refset=None)
    return _box_from(min_point, xlength, ywidth, thickness)


# ---------------------------------------------------------------------------------------------------
# Shared builders
# ---------------------------------------------------------------------------------------------------

def _build_draw_die_form_steels(job: DrawDieJob, min_point: NXOpen.Point3d, xlength: float, ywidth: float,
                                height: float, name: str, subtract_refset: Optional[str], shcs_path: str,
                                shcs_inset: float, jack_inset: float, key_save_name: str,
                                key_size: Tuple[int, str], keys_both_ways: bool = False) -> None:
    """
    Merlin.BuildDrawDieFormSteels - two columns either side of the X centreline, four rows along Y, .004" apart,
    each a different random color with its joint faces and mounting face yellow. Per block: 4 backside SHCS
    (SHORT-TAP), 2 TSG jack screws (CBORE_BLIND) - the second snapped to whole inches from the first - and 2 keys
    (4 with keys_both_ways). The keys are sized (key_size) and Save As'd once, after every block, so all eight share
    one job copy.
    """
    column_width = (xlength - (FormSteelColumns - 1) * merlin.SplitGap) / FormSteelColumns
    row_length = (ywidth - (FormSteelRows - 1) * merlin.SplitGap) / FormSteelRows

    if column_width <= 0 or row_length <= 0:
        raise RuntimeError("{} x {} is too small to split {} x {}.".format(
            _f3(xlength), _f3(ywidth), FormSteelColumns, FormSteelRows))

    # Without replacement, so all eight come out different.
    colors = random.sample(merlin.SplitComponentColors, len(merlin.SplitComponentColors))
    keys: List[NXOpen.Assemblies.Component] = []
    index = 0

    for column in range(FormSteelColumns):
        for row in range(FormSteelRows):
            try:
                _build_one_form_steel(job, min_point, column, row, index, column_width, row_length, height, name,
                                      colors[index % len(colors)], subtract_refset, shcs_path, shcs_inset,
                                      jack_inset, keys_both_ways, keys)
            except Exception as ex:
                nx.print_("Draw Die: {} block {} of {} failed.".format(name, index + 1,
                                                                     FormSteelColumns * FormSteelRows))
                nx.print_exception(ex)
            index += 1

    _set_draw_die_key_size(keys, job, key_size)
    _save_as_draw_die_part(keys, job, key_save_name)


def _build_one_form_steel(job: DrawDieJob, min_point: NXOpen.Point3d, column: int, row: int, index: int,
                          column_width: float, row_length: float, height: float, name: str, color: int,
                          subtract_refset: Optional[str], shcs_path: str, shcs_inset: float, jack_inset: float,
                          keys_both_ways: bool, keys: List[NXOpen.Assemblies.Component]) -> None:
    """The body of BuildDrawDieFormSteels' per-block loop."""
    block_min = NXOpen.Point3d(min_point.X + column * (column_width + merlin.SplitGap),
                               min_point.Y + row * (row_length + merlin.SplitGap),
                               min_point.Z)
    joints: List[NXOpen.Vector3d] = []
    if column < FormSteelColumns - 1:
        joints.append(_VectorX)
    if column > 0:
        joints.append(_VectorXN)
    if row < FormSteelRows - 1:
        joints.append(_VectorY)
    if row > 0:
        joints.append(_VectorYN)

    new_part, component = _promote_draw_die_block(
        job, block_min, column_width, row_length, height,
        name=name,
        color=color,
        description="{} X {} X {}".format(_f3(column_width), _f3(row_length), _f3(height)),
        material="D2",
        detail_name="FORM STEEL",
        fixed_description=False,
        joint_normals=joints)

    body_refset = nx.find_or_create_reference_set(new_part, "BODY")

    # Lower: the mounting face is the bottom (Z 0); upper: the top (Z height). CBORE parts point into the block from
    # it; backside SHCS point out of it, their heads in the part behind.
    mount_z = height if job.is_upper else 0.0
    into = _z_matrix(_VectorZN if job.is_upper else _VectorZ)
    out_of = _z_matrix(_VectorZ if job.is_upper else _VectorZN)

    block_label = "{} block {}".format(name, index + 1)

    _draw_die_step("{} SHCS".format(block_label), lambda: _place_draw_die_children(
        "form steel SHCS", shcs_path,
        [(NXOpen.Point3d(p.X, p.Y, mount_z), out_of) for p in _inset_corners(column_width, row_length, shcs_inset)],
        layer=99, subtract_refset="SHORT-TAP", body_refset=body_refset))

    def jack_screws() -> None:
        jack_first = NXOpen.Point3d(column_width - jack_inset, jack_inset, mount_z)
        jack_second = _snap_to_inch_grid_from(jack_first, NXOpen.Point3d(jack_inset, row_length - jack_inset, mount_z))
        _place_draw_die_children("form steel jack screw", _jck12mmScrewTsgPath,
                                 [(jack_first, into), (jack_second, into)],
                                 layer=99, subtract_refset="CBORE_BLIND", body_refset=body_refset)

    _draw_die_step("{} jack screws".format(block_label), jack_screws)

    def block_keys() -> None:
        placed = (_place_draw_die_edge_keys(job, column_width, row_length, height) if keys_both_ways
                  else _place_draw_die_front_back_keys(job, column_width, row_length, height))
        body_refset.AddObjectsToReferenceSet(placed)
        keys.extend(placed)

    _draw_die_step("{} keys".format(block_label), block_keys)

    _finish_draw_die_block(job, new_part, component, subtract_refset)


def _promote_draw_die_block(job: DrawDieJob, min_point: NXOpen.Point3d, xlength: float, ywidth: float,
                            height: float, name: str, color: Optional[int], description: str, material: str,
                            detail_name: str, fixed_description: bool,
                            joint_normals: Sequence[NXOpen.Vector3d] = ()
                            ) -> Tuple[NXOpen.Part, NXOpen.Assemblies.Component]:
    """
    Merlin.PromoteDrawDieBlock - builds a block into the station at min_point, colors it (mounting face and
    joint_normals faces yellow), promotes it and re-bases the new part onto it (upper details on the opposite
    corner), names it DYNAMIC BLOCK, stamps DESCRIPTION / MATERIAL / DETAIL NAME and extracts the SUBTOOL on
    hidden layer 15. Leaves the new detail as the display and work part. fixed_description switches the AutoSize
    update off before DESCRIPTION is stamped, so the subtracts that follow do not rewrite it as a size.
    """
    nx.set_display_part(job.station)
    nx.set_work_part(job.station)
    nx.work_part().Layers.WorkLayer = 1

    block = _create_block_origin_and_lengths(min_point, xlength, ywidth, height)

    # The whole body first - it colors every face - then the yellow faces.
    body = block.GetBodies()[0]
    if color is not None:
        nx.set_color(body, color)
    mounting_face = nx.planar_face_with_normal_or_null(body, _VectorZ if job.is_upper else _VectorZN)
    if mounting_face is not None:
        nx.set_color(mounting_face, 42)
    for normal in joint_normals:
        face = nx.planar_face_with_normal_or_null(body, normal)
        if face is not None:
            nx.set_color(face, 42)

    # (GFolder.create_or_null(disp) - print-only in the C#, not ported.)
    component = _create_new_component_core(
        name, [body],
        NXOpen.Assemblies.CreateNewComponentBuilder.ComponentOriginType.Absolute,
        NXOpen.Assemblies.CreateNewComponentBuilder.ComponentLayerOptionType.AsSpecified,
        layer_number=1, original_objects_deleted=True, auto_size_udo=True)

    _rebase_block_to_part_origin(component, cast(NXOpen.Part, component.OwningPart), opposite_corner=job.is_upper)

    new_part = nx.work_part()
    nx.setup_station_expressions(new_part)
    nx.find_or_create_reference_set(new_part, "BODY").AddObjectsToReferenceSet(list(new_part.Bodies))
    first_block = nx.first_block_feature(new_part)
    if first_block is None:
        raise RuntimeError("{} has no block feature to name DYNAMIC BLOCK.".format(new_part.Leaf))
    first_block.SetName("DYNAMIC BLOCK")

    if fixed_description:
        _switch_auto_size_off(new_part)

    nx.set_attribute(new_part, "DESCRIPTION", description)
    nx.set_attribute(new_part, "MATERIAL", material)
    nx.set_attribute(new_part, "DETAIL NAME", detail_name)

    new_part.Layers.WorkLayer = 15
    merlin._create_subtool(new_part)
    new_part.Layers.WorkLayer = 1
    new_part.Layers.SetState(15, NXOpen.Layer.State.Hidden)

    return new_part, component


def _finish_draw_die_block(job: DrawDieJob, new_part: NXOpen.Part, component: NXOpen.Assemblies.Component,
                           subtract_refset: Optional[str]) -> None:
    """
    Merlin.FinishDrawDieBlock - back in the launch display part: makes the detail BODY and a member of its station's
    BODY, subtracts subtract_refset of the selected components from it (when not None), sets BODY in every loaded
    ancestor assembly, then puts the session back on the station for the next block.
    """
    try:
        new_part.Layers.WorkLayer = 1
        nx.set_display_part(job.top_level)

        def body_reference_set() -> None:
            nx.set_reference_set(component, "BODY")
            nx.find_or_create_reference_set(component.OwningPart, "BODY").AddObjectsToReferenceSet([component])

        _draw_die_step("{} BODY reference set".format(new_part.Leaf), body_reference_set)

        if subtract_refset is not None:
            def subtract() -> None:
                nx.set_work_part(new_part)
                merlin._subtract_components(lambda: nx.dynamic_block(nx.work_part()).GetBodies()[0],
                                            job.components, cast(str, subtract_refset))

            _draw_die_step("{} {} subtract".format(new_part.Leaf, subtract_refset), subtract)

        def ancestor_reference_sets() -> None:
            nx.set_display_part(job.top_level)
            merlin._set_reference_set_in_ancestor_assemblies(nx.first_occurrence_in(new_part, job.top_level),
                                                             add_to_reference_set=True)

        _draw_die_step("{} ancestor reference sets".format(new_part.Leaf), ancestor_reference_sets)

        _draw_die_step("{} unblank".format(new_part.Leaf), lambda: component.Unblank())
    finally:
        # Back on the station for the next block, whatever failed above.
        nx.set_display_part(job.station)
        nx.set_work_part(job.station)


def _draw_die_step(label: str, step: Callable[[], object]) -> None:
    """Merlin.DrawDieStep(string, Action) - a step that throws is printed and skipped."""
    nx.prompt("Draw Die -> {}".format(label))
    try:
        step()
    except Exception as ex:
        nx.print_("Draw Die: {} failed.".format(label))
        nx.print_exception(ex)


def _draw_die_step_result(label: str, step: Callable[[], _T], fallback: _T) -> _T:
    """Merlin.DrawDieStep<T> - for a step with a result; fallback when it throws."""
    nx.prompt("Draw Die -> {}".format(label))
    try:
        return step()
    except Exception as ex:
        nx.print_("Draw Die: {} failed.".format(label))
        nx.print_exception(ex)
        return fallback


def _place_draw_die_children(label: str, path: str, placements: Iterable[Placement], layer: int,
                             subtract_refset: Optional[str],
                             body_refset: Optional[NXOpen.ReferenceSet]) -> List[NXOpen.Assemblies.Component]:
    """
    Merlin.PlaceDrawDieChildren - adds one path per placement to the display part on layer (BODY reference set),
    subtracting subtract_refset from the dynamic block when it is not None and adding each to body_refset when that
    is not None. One at a time, so a part that fails costs only itself. Returns what was placed.
    """
    placed: List[NXOpen.Assemblies.Component] = []

    for origin, orientation in placements:
        try:
            if subtract_refset is None:
                child = nx.add_component(nx.display_part(), path, "BODY", None, origin, orientation, layer)
            else:
                child = _drop_and_subtract(path, origin, orientation, subtract_refset, layer=layer)

            if body_refset is not None:
                body_refset.AddObjectsToReferenceSet([child])
            placed.append(child)
        except Exception as ex:
            nx.print_("Draw Die: could not place {} ({}) in {}".format(
                label, os.path.splitext(os.path.basename(path))[0], nx.display_part().Leaf))
            nx.print_exception(ex)

    return placed


def _center_draw_die_children_on_z(part: NXOpen.Part, components: Iterable[NXOpen.Assemblies.Component],
                                   z: float) -> None:
    """
    Merlin.CenterDrawDieChildrenOnZ - moves each component in Z so the middle of its solid bodies' box sits at z,
    whatever the library part's own origin. A component with no solid body is printed and left where it is.
    """
    for component in components:
        try:
            bodies = nx.solid_body_members(component)

            if not bodies:
                nx.print_("Draw Die: {} has no solid body to centre on Z {} - left where it is.".format(
                    component.DisplayName, _f3(z)))
                continue

            box = nx.combine_boxes([nx.body_box(b) for b in bodies])
            shift = z - (box.MinZ + box.MaxZ) / 2

            if abs(shift) > 1e-6:
                part.ComponentAssembly.MoveComponent(component, NXOpen.Vector3d(0.0, 0.0, shift),
                                                     nx.identity_matrix())
        except Exception as ex:
            nx.print_("Draw Die: could not centre {} on Z {}.".format(component.DisplayName, _f3(z)))
            nx.print_exception(ex)


def _keep_out_of_reference_set(refset: NXOpen.ReferenceSet,
                               components: Iterable[NXOpen.NXObject]) -> None:
    """Merlin.KeepOutOfReferenceSet - takes components (or any members, e.g. a body) out of refset if anything put
    them there."""
    members = {member.Tag for member in refset.AskAllDirectMembers()}
    strays = [c for c in components if c.Tag in members]
    if strays:
        refset.RemoveObjectsFromReferenceSet(strays)


def _save_as_draw_die_part(placed: Sequence[NXOpen.Assemblies.Component], job: DrawDieJob, name: str) -> None:
    """
    Merlin.SaveAsDrawDiePart - Save As's the library part behind placed into the station's folder as
    {gm|cts}-{name}-{token}.prt, so its settings can be changed without touching the library.
    """
    if not placed:
        nx.print_("Draw Die: nothing placed for {} - no Save As.".format(name))
        return

    try:
        status = cast(NXOpen.Part, nx.prototype(placed[0])).SaveAs(
            "{}\\{}-{}-{}.prt".format(job.dir, job.prefix, name, merlin._random_file_token()))
        if status is not None:
            status.Dispose()
    except Exception as ex:
        nx.print_("Draw Die: could not Save As {}.".format(name))
        nx.print_exception(ex)


# True while a DrawDie.build(..., skip_spreadsheets=True) runs - no key's or guided retainer's sheet is opened.
_skip_spreadsheets = False


def _set_draw_die_key_size(placed: Sequence[NXOpen.Assemblies.Component], job: DrawDieJob,
                           size: Tuple[int, str]) -> bool:
    """
    Merlin.WriteDrawDieKeySpreadsheet (a stub in the C#) - sets the Smart GM Key behind placed to size: its size radio
    (Main!I3) through _apply_draw_die_sheet, then checks the Label came out as the size's. CTS keys (Smart Key Metric)
    have a different sheet and are left alone. False, printed, when anything failed.
    """
    if not placed:
        return False

    if not job.is_gm:
        nx.print_("Draw Die: CTS key sheet not mapped - {} left at its seed size.".format(placed[0].DisplayName))
        return False

    selection, label = size
    return _apply_draw_die_sheet(
        placed[0], "key ({})".format(label),
        numbers=[(_keySizeCell, float(selection))],
        expression_rows=_keyExpressionRows, attribute_rows=_keyAttributeRows,
        checks=[(("Exp-Attr", 5, 6), label)])


def _set_draw_die_guided_retainer(placed: Sequence[NXOpen.Assemblies.Component], job: DrawDieJob) -> bool:
    """
    Merlin.WriteGuidedRetainerSpreadsheet (a stub in the C#) - sets the Smart GM Guided Retainer behind placed to the
    spec's GRS.50.HD, stroke 105 mm, travel 75 mm, with the Plate Adapter Cap. The cap's checkbox (Main!L14, a
    logical) is not written - the seed has it on - but the checks fail the edit when it is off, or when the sheet
    calls the stroke or travel invalid. CTS keepers (Smart SL Guided Keepers) are left alone.
    """
    if not placed:
        return False

    if not job.is_gm:
        nx.print_("Draw Die: CTS guided keeper sheet not mapped - {} left at its seed settings.".format(
            placed[0].DisplayName))
        return False

    return _apply_draw_die_sheet(
        placed[0], "guided retainer ({})".format(GuidedRetainerDescription),
        numbers=[(_retainerModelCell, GuidedRetainerModel),
                 (_retainerStrokeCell, GuidedRetainerStroke),
                 (_retainerTravelCell, GuidedRetainerTravel)],
        expression_rows=_retainerExpressionRows, attribute_rows=_retainerAttributeRows,
        # J10 is a logical, but EvaluateCell hands it back as a double: TRUE -1, FALSE 0.
        checks=[(("Main", 10, 10), "-1"),                      # J10 valid stroke for the model
                (("Main", 7, 10), "1"),                        # J7 valid travel (available travel >= 0)
                (("Main", 15, 12), "1"),                       # L15 Plate Adapter Cap on
                (("Exp-Attr", 3, 6), GuidedRetainerDescription)])


def _apply_draw_die_sheet(placed: NXOpen.Assemblies.Component, label: str,
                          numbers: Sequence[Tuple[Tuple[int, int], float]],
                          expression_rows: Tuple[int, int], attribute_rows: Tuple[int, int],
                          checks: Sequence[Tuple[Tuple[str, int, int], str]]) -> bool:
    """
    The draw-die twin of PierceMerlin.ApplySheetExpressions, for a smart part with an embedded Main / Exp-Attr sheet:
    writes numbers into Main ((row, col) 1-based), recalculates, copies Exp-Attr's expressions (name in B, value in C
    on expression_rows) and attributes (title in E, value in F on attribute_rows) into the part, then saves and
    terminates the sheet so the sheet and the part agree. checks are ((sheet, row, col), expected text) read after the
    recalculation; a miss is printed and makes the result False, but the part is still written.
    Call it before _save_as_draw_die_part: the edit changes the library part in session only, and the Save As writes
    it to the job copy. The prototype is made the display part for the edit and the display and work parts are put
    back. False, printed, when anything failed. With _skip_spreadsheets the sheet is not opened and False is returned.
    """
    if _skip_spreadsheets:
        nx.info("Draw Die: spreadsheets skipped - {} {} keeps its seed settings.".format(placed.DisplayName, label))
        return False

    display = nx.display_part()
    work = nx.work_part()
    part = cast(NXOpen.Part, nx.prototype(placed))
    ok = True

    try:
        nx.set_display_part(part)
        nx.set_work_part(part)

        manager = cast(Any, nx.session_).SpreadsheetManager
        sheet = manager.Open(cast(Any, NXOpen).SpreadsheetManager.Sheettype.Modeling, part.FullPath)
        types = cast(Any, NXOpen).SpreadsheetCellData.Types

        def text(cell: Any) -> str:
            if cell.Type == types.String:
                return cell.StringValue
            if cell.Type == types.Int:
                return str(cell.IntValue)
            if cell.Type == types.Logical:
                return str(bool(cell.LogicalValue))
            return nx.cs_double_str(cell.DoubleValue)

        try:
            main = sheet.GetSheetNumberOfName("Main")
            for (row, col), value in numbers:
                data = manager.CreateCellData()
                data.DoubleValue = float(value)
                sheet.SetNumber(row, col, data, main)
            sheet.Recalculate()

            # EvaluateCell, not GetValue: GetValue hands back an empty string for a formula cell (every Exp-Attr
            # value is one) and reads Main whatever sheet it is given.
            for (sheet_name, row, col), expected in checks:
                got = text(sheet.EvaluateCell(row, col, sheet.GetSheetNumberOfName(sheet_name)))
                if got != expected:
                    ok = False
                    nx.print_("Draw Die: {} {} {}!R{}C{} is {}, expected {}.".format(
                        part.Leaf, label, sheet_name, row, col, got, expected))

            exp_attr = sheet.GetSheetNumberOfName("Exp-Attr")

            for row in range(expression_rows[0], expression_rows[1] + 1):
                name = text(sheet.EvaluateCell(row, 2, exp_attr))
                try:
                    part.Expressions.FindObject(name).SetFormula(text(sheet.EvaluateCell(row, 3, exp_attr)))
                except Exception as ex:
                    ok = False
                    nx.print_exception(ex, "{} Exp-Attr row {}, expression {}".format(label, row, name))

            for row in range(attribute_rows[0], attribute_rows[1] + 1):
                title = text(sheet.EvaluateCell(row, 5, exp_attr))
                if '"' in title:
                    title = title.split('"')[1]                 # the key's '"Description" (str)'
                part.SetUserAttribute(title.strip(), -1, text(sheet.EvaluateCell(row, 6, exp_attr)),
                                      NXOpen.Update.Option.Now)
        finally:
            sheet.Save()
            sheet.Terminate()

        nx.ufsession_.Modeling.Update()
    except Exception as ex:
        ok = False
        nx.print_("Draw Die: could not set {} to {}.".format(part.Leaf, label))
        nx.print_exception(ex)
    finally:
        nx.set_display_part(display)
        nx.set_work_part(work)

    return ok


def _place_draw_die_front_back_keys(job: DrawDieJob, xlength: float, ywidth: float,
                                    height: float) -> List[NXOpen.Assemblies.Component]:
    """Merlin.PlaceDrawDieFrontBackKeys - two keys on the mounting face, X-centred, 1.5" in from each Y end."""
    path = _gmKeyPath if job.is_gm else _ctsSmartKeyMetric
    nudge = 0.0748 if job.is_gm else 0.0
    z = height if job.is_upper else 0.0
    orientation = _compute_upper_key_orientation() if job.is_upper else _lower_key_front_back_orientation()

    return [
        nx.add_component(nx.display_part(), path, "BODY", None,
                         NXOpen.Point3d(xlength / 2, 1.5 + nudge, z), orientation, 99),
        nx.add_component(nx.display_part(), path, "BODY", None,
                         NXOpen.Point3d(xlength / 2, ywidth - 1.5 - nudge, z), orientation, 99),
    ]


def _place_draw_die_edge_keys(job: DrawDieJob, xlength: float, ywidth: float,
                              height: float) -> List[NXOpen.Assemblies.Component]:
    """
    Merlin.PlaceDrawDieEdgeKeys - four keys on the mounting face, one in from each edge on the centrelines, through
    PlaceEdgeItems (which assumes an 8" block for the upper, hence the Z shift). Saves and restores the WCS.
    """
    wcs = nx.display_part().WCS
    current_wcs = wcs.CoordinateSystem.Orientation.Element

    try:
        return _place_edge_items(_gmKeyPath if job.is_gm else _ctsSmartKeyMetric, NXOpen.Point3d(0.0, 0.0, 0.0),
                                 xlength, ywidth, job.is_upper,
                                 front_back_nudge=0.0748 if job.is_gm else 0.0, x_edge_inset=2.4498,
                                 extra_z=height - 8 if job.is_upper else 0.0, layer=99)
    finally:
        wcs.SetOriginAndMatrix(NXOpen.Point3d(0.0, 0.0, 0.0), current_wcs)


# ---------------------------------------------------------------------------------------------------
# Merlin helpers not in PointComponent.py
# ---------------------------------------------------------------------------------------------------

def _check_info_units() -> Tuple[bool, str]:
    """Merlin.CheckInfoUnits - (False, message) unless the display and work parts are in english info units."""
    english = NXOpen.UnitCollection.UnitDefaults.LbmInLbfDegF

    if nx.display_part().UnitCollection.GetDefaultDataEntryUnits() != english:
        return False, "The display part must be in english info units."

    if nx.work_part().UnitCollection.GetDefaultDataEntryUnits() != english:
        return False, "The work part must be in english info units."

    return True, ""


def _select_bodies(cue: str, title: str) -> List[NXOpen.Body]:
    """
    Selection.select_bodies(cue, title) - many bodies, any in assembly; [] on cancel. The C# is a SNAP picker
    filtered to bodies; this is the NXOpen SelectionManager with a body mask.
    """
    mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type, 0,
                                       NXOpen.UF.UFConstants.UF_UI_SEL_FEATURE_BODY)
    response, objects = NXOpen.UI.GetUI().SelectionManager.SelectTaggedObjects(
        cue,
        title,
        NXOpen.Selection.SelectionScope.AnyInAssembly,
        NXOpen.Selection.SelectionAction.ClearAndEnableSpecific,
        False,
        False,
        [mask])
    if response not in (NXOpen.Selection.Response.Ok, NXOpen.Selection.Response.ObjectSelected):
        return []
    bodies = [obj for obj in objects if isinstance(obj, NXOpen.Body)]
    for body in bodies:
        body.Unhighlight()
    return bodies


def _set_wcs_to_absolute(part: NXOpen.Part) -> None:
    """Part.SetWcsToAbsolute"""
    part.WCS.SetOriginAndMatrix(NXOpen.Point3d(0.0, 0.0, 0.0), nx.identity_matrix())


def _create_block_origin_and_lengths(origin: NXOpen.Point3d, xlength: float, ywidth: float,
                                     height: float) -> NXOpen.Features.Block:
    """
    BasePart.__CreateBlock(Point3d, Matrix3x3, double, double, double) with the absolute orientation - an
    origin-and-edge-lengths block in the work part. The block takes its orientation from the WCS, so the display
    part's WCS is turned to absolute for the commit and put back afterwards.
    """
    csys = nx.display_part().WCS.CoordinateSystem
    original = csys.Orientation.Element
    csys.SetDirections(_VectorX, _VectorY)
    builder = nx.work_part().Features.CreateBlockFeatureBuilder(None)
    try:
        builder.Type = NXOpen.Features.BlockFeatureBuilder.Types.OriginAndEdgeLengths
        builder.BooleanOption.Type = NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Create
        builder.SetOriginAndLengths(origin, nx.cs_double_str(xlength), nx.cs_double_str(ywidth),
                                    nx.cs_double_str(height))
        csys.SetDirections(nx.axis_x(original), nx.axis_y(original))
        return cast(NXOpen.Features.Block, builder.Commit())
    finally:
        builder.Destroy()


def _create_new_component_core(name_prefix: str, objects: Sequence[NXOpen.DisplayableObject],
                               origin: NXOpen.Assemblies.CreateNewComponentBuilder.ComponentOriginType,
                               layer_option: NXOpen.Assemblies.CreateNewComponentBuilder.ComponentLayerOptionType,
                               layer_number: int = 1, original_objects_deleted: bool = False,
                               auto_size_udo: bool = True) -> NXOpen.Assemblies.Component:
    """
    Merlin.CreateNewComponentCore (through CreateCtsComponent) - promotes objects into a new blank part
    {name_prefix}-{token}.prt next to the display part, stamps CSPC / GM Tool Number "X" on it and (optionally)
    adds the AutoSize UDO. PointComponent._create_cts_component is the same with the WCS / Work defaults fixed.
    """
    work = nx.work_part()
    builder = work.AssemblyManager.CreateNewComponentBuilder()
    try:
        file_new = nx.session_.Parts.FileNew()
        file_new.Units = (NXOpen.Part.Units.Millimeters if work.PartUnits == NXOpen.BasePart.Units.Millimeters
                          else NXOpen.Part.Units.Inches)
        file_new.NewFileName = "{}\\{}-{}.prt".format(
            os.path.dirname(nx.display_part().FullPath), name_prefix, merlin._random_file_token())
        file_new.UseBlankTemplate = True
        builder.ReferenceSet = NXOpen.Assemblies.CreateNewComponentBuilder.ComponentReferenceSetType.Other
        builder.LayerOption = layer_option
        builder.NewComponentName = os.path.splitext(os.path.basename(file_new.NewFileName))[0]
        builder.LayerNumber = layer_number
        builder.ComponentOrigin = origin
        builder.OriginalObjectsDeleted = original_objects_deleted
        for obj in objects:
            builder.ObjectForNewComponent.Add(obj)
        builder.NewFile = file_new
        builder.Commit()
        new_component = cast(NXOpen.Assemblies.Component, builder.GetObject())
        # Every component Merlin makes gets these placeholder GM job attributes on its prototype part.
        new_prototype = nx.prototype(new_component)
        nx.set_attribute(new_prototype, "CSPC", "X")
        nx.set_attribute(new_prototype, "GM Tool Number", "X")
        if auto_size_udo:
            nx.create_auto_size_udo(nx.work_part())
        return new_component
    finally:
        builder.Destroy()


def _rebase_block_to_part_origin(component: NXOpen.Assemblies.Component, parent: NXOpen.Part,
                                 opposite_corner: bool = False, apply_orientation: bool = True) -> None:
    """
    Merlin.RebaseBlockToPartOrigin(component, parent, applyOrientation, oppositeCorner) - the block's corner
    becomes the part's (0,0,0) and its orientation the part's absolute orientation, edited parametrically on the
    block feature; the component is then moved by the inverse, rotate first and translate second. With
    opposite_corner (upper details) the csys goes on the corner diagonally opposite in X and Y, staying on the
    bottom face, oriented -X / -Y - a 180 degree roll about Z; the block still fills X 0..L, Y 0..W, Z 0..H. Leaves
    the new detail as the display and work part. apply_orientation=False (the cast trim pad) only translates: the
    block keeps its orientation in the part and the component is not rotated.
    """
    new_part = cast(NXOpen.Part, nx.prototype(component))
    block = nx.first_block_feature(new_part)

    if block is None:
        nx.print_("{} has no block feature - leaving its origin alone".format(new_part.Leaf))
        return

    nx.set_display_part(new_part)
    nx.set_work_part(new_part)

    # The builder's Length/Width/Height come back None in Python, so the size expressions come from
    # UF_MODL_ask_block_parms ("name=value" strings, length / width / height).
    length_exp, width_exp, height_exp = (new_part.Expressions.FindObject(parm.split("=", 1)[0].strip())
                                         for parm in nx.ufsession_.ModlFeatures.AskBlockParms(block.Tag, 0))

    builder = new_part.Features.CreateBlockFeatureBuilder(block)
    try:
        # The block's own origin and orientation, read in assembly coordinates - they become the component's
        # position after the reset below.
        block_origin = builder.Origin
        x_axis, y_axis = builder.GetOrientation()
        block_orientation = nx.matrix_from_axes(x_axis, y_axis)

        if opposite_corner:
            length = length_exp.Value
            width = width_exp.Value

            # The opposite corner in X and Y, staying on the bottom face, in assembly coordinates - the component
            # moves here - plus the -X/-Y orientation that goes with it.
            block_origin = nx.add_along(nx.add_along(block_origin, nx.axis_x(block_orientation), length),
                                        nx.axis_y(block_orientation), width)
            block_orientation = nx.matrix_from_axes(nx.negate(nx.axis_x(block_orientation)),
                                                    nx.negate(nx.axis_y(block_orientation)))

            # In that frame the block's own corner sits at (L, W, 0) with its local axes reading -X / -Y / +Z.
            builder.SetOrientation(_VectorXN, _VectorYN)
            builder.SetOriginAndLengths(NXOpen.Point3d(length, width, 0.0), length_exp.RightHandSide,
                                        width_exp.RightHandSide, height_exp.RightHandSide)
        else:
            # Orientation before origin, so the origin is written against the axes the block keeps.
            if apply_orientation:
                builder.SetOrientation(_VectorX, _VectorY)
            builder.SetOriginAndLengths(NXOpen.Point3d(0.0, 0.0, 0.0), length_exp.RightHandSide,
                                        width_exp.RightHandSide, height_exp.RightHandSide)
        builder.Commit()
    finally:
        builder.Destroy()

    # The component move needs its owning assembly as the work part...
    nx.set_display_part(parent)
    nx.set_work_part(parent)

    # Rotate first, while the geometry is still on the origin and therefore spins in place...
    if apply_orientation or opposite_corner:
        parent.ComponentAssembly.MoveComponent(component, NXOpen.Vector3d(0.0, 0.0, 0.0), block_orientation)
    # ...then carry it out to where the block was.
    parent.ComponentAssembly.MoveComponent(
        component, NXOpen.Vector3d(block_origin.X, block_origin.Y, block_origin.Z), nx.identity_matrix())

    # ...but the caller picks up with the new detail as the display and work part.
    nx.set_display_part(new_part)
    nx.set_work_part(new_part)


def _switch_auto_size_off(part: NXOpen.BasePart) -> None:
    """
    `if (part.IsUdoAutoSize) part.AutoSizeUpdateStatus = false;` - the UDO's integer to 0 and the AUTO UPDATE
    attribute to OFF (__UdoAutoSizeUpdateStatus writes both). Nothing to do when the part has no AutoSize UDO.
    """
    try:
        udo_class = nx.session_.UserDefinedClassManager.GetUserDefinedClassFromClassName("UdoAutoSizeComponent")
    except NXOpen.NXException as ex:
        if ex.ErrorCode != nx.ErrorUdoClassNotRegistered:
            raise
        return

    if udo_class is None:
        return

    udos = part.UserDefinedObjectManager.GetUdosOfClass(udo_class)

    if len(udos) == 0:
        return

    udos[0].SetIntegers([0])
    nx.set_attribute(part, _AutoUpdateAttribute, "OFF")


def _drop_and_subtract(path: str, origin: NXOpen.Point3d, orientation: Optional[NXOpen.Matrix3x3],
                       subtract_refset: str, restore_refset: str = "BODY",
                       layer: int = 99) -> NXOpen.Assemblies.Component:
    """
    Merlin.DropAndSubtract - drops a library part at origin (BODY refset, layer), switches it to subtract_refset,
    subtracts its linked body from the display part's dynamic block, restores restore_refset, and stamps a fastener
    with the subtract instance attribute.
    """
    display = nx.display_part()
    component = nx.add_component(display, path, "BODY", None, origin, orientation, layer)
    _subtract_refset_from_dynamic_block(display, component, subtract_refset, restore_refset)

    # The subtract prints and skips a part without the reference set - nothing to stamp then.
    if nx.has_reference_set(nx.prototype(component), subtract_refset):
        _stamp_fastener_subtract(component, subtract_refset)

    return component


def _subtract_refset_from_dynamic_block(target_part: NXOpen.Part, component: NXOpen.Assemblies.Component,
                                        subtract_refset: str, restore_refset: str = "BODY") -> None:
    """
    Part.__SubtractRefsetFromDynamicBlock - switches component to subtract_refset, subtracts its linked body from
    target_part's dynamic block, then restores restore_refset. NXException 670030 is swallowed with a print.
    """
    if not nx.has_reference_set(nx.prototype(component), subtract_refset):
        nx.print_("Component {} doesn't containt a reference set {}".format(component.DisplayName, subtract_refset))
        return

    nx.set_reference_set(component, subtract_refset)
    try:
        link = nx.create_linked_body(component)
        nx.subtract(nx.dynamic_block(target_part).GetBodies()[0], link.GetBodies())
    except NXOpen.NXException as ex:
        if ex.ErrorCode != _ErrorCouldNotSubtract:
            raise
        nx.print_("Could not subtract {} from {}".format(component.DisplayName, component.OwningPart.Leaf))
    nx.set_reference_set(component, restore_refset)


def _stamp_fastener_subtract(fastener: NXOpen.Assemblies.Component, subtract_refset: str) -> None:
    """
    Merlin.StampFastenerSubtract - stamps a fastener (SHCS, dowel, jack screw or TSG jack screw) with the subtract
    instance attribute AddFasteners writes. Anything else (keys, hoist rings) is left alone.
    """
    leaf = nx.prototype(fastener).Leaf
    lower = leaf.lower()

    # BasePart.__IsJckScrew / __IsJckScrewTsg test EndsWith; tsg_nx.is_jck_screw (the string._IsJckScrew_ port)
    # wants "-jck-screw-" and so misses a plain "12mm-jck-screw" leaf.
    if not (nx.is_shcs(leaf) or nx.is_dwl(leaf)
            or lower.endswith("-jck-screw") or lower.endswith("-jck-screw-tsg")):
        return

    fastener.SetInstanceUserAttribute("subtract", -1, subtract_refset, NXOpen.Update.Option.Now)


def _place_edge_items(path: str, origin: NXOpen.Point3d, xlength: float, y_extent: float, is_upper: bool,
                      front_back_nudge: float, x_edge_inset: float, extra_z: float = 0.0,
                      layer: int = 99) -> List[NXOpen.Assemblies.Component]:
    """
    Merlin.PlaceEdgeItems - X-centered front (-Y) and back (+Y) at inset 1.5 (+/- front_back_nudge), Y-centered
    right (+X) and left (-X) at x_edge_inset +/- (1.5 - .625). Upper sits them on top of an 8" block (+Z 8),
    rotates the WCS 90 degrees about Z, and orients front/back with the upper-key matrix and right/left with the
    rotated WCS; lower uses the side-key matrix front/back and identity right/left. Returns [front, back, right,
    left]. The caller saves and restores the WCS.
    """
    z_top = 8.0 if is_upper else 0.0
    lr_orient: Optional[NXOpen.Matrix3x3]
    if is_upper:
        key_orientation = _compute_upper_key_orientation()
        wcs = nx.display_part().WCS
        wcs.SetOriginAndMatrix(NXOpen.Point3d(0.0, 0.0, 0.0), key_orientation)
        wcs.Rotate(NXOpen.WCS.Axis.ZAxis, 90.0)
        fb_orient = key_orientation
        lr_orient = wcs.CoordinateSystem.Orientation.Element
    else:
        fb_orient = _lower_key_front_back_orientation()
        lr_orient = None

    z = z_top + extra_z
    display = nx.display_part()

    def at(x: float, y: float) -> NXOpen.Point3d:
        return NXOpen.Point3d(origin.X + x, origin.Y + y, origin.Z + z)

    # -Y edge (front): X-centered near MinY
    front = nx.add_component(display, path, "BODY", None, at(xlength / 2, 1.5 + front_back_nudge), fb_orient, layer)
    # +Y edge (back): X-centered near MaxY
    back = nx.add_component(display, path, "BODY", None, at(xlength / 2, y_extent - 1.5 - front_back_nudge),
                            fb_orient, layer)
    # +X edge (right): Y-centered near MaxX
    right = nx.add_component(display, path, "BODY", None, at(-x_edge_inset + xlength + (1.5 - .625), y_extent / 2),
                             lr_orient, layer)
    # -X edge (left): Y-centered near MinX
    left = nx.add_component(display, path, "BODY", None, at(x_edge_inset - (1.5 - .625), y_extent / 2),
                            lr_orient, layer)
    return [front, back, right, left]


def _create_linked_face(faces: Sequence[NXOpen.Face]) -> NXOpen.Features.Feature:
    """Face[].__CreateLinkedFace - wave-links faces into the work part as one associative face-link feature."""
    part = nx.work_part()
    builder = part.BaseFeatures.CreateWaveLinkBuilder(None)
    try:
        builder.Type = NXOpen.Features.WaveLinkBuilder.Types.FaceLink
        extract = builder.ExtractFaceBuilder
        extract.ParentPart = NXOpen.Features.ExtractFaceBuilder.ParentPartType.OtherPart
        extract.Associative = True
        extract.FaceOption = NXOpen.Features.ExtractFaceBuilder.FaceOptionType.FaceChain
        extract.FaceChain.ReplaceRules([part.ScRuleFactory.CreateRuleFaceDumb(list(faces))], False)
        extract.FixAtCurrentTimestamp = False
        return cast(NXOpen.Features.Feature, builder.Commit())
    finally:
        builder.Destroy()


def _remove_parameters(bodies: Sequence[NXOpen.Body]) -> None:
    """Body.__RemoveParameters - a RemoveParametersBuilder in the work part over bodies."""
    builder = nx.work_part().Features.CreateRemoveParametersBuilder()
    try:
        builder.Objects.Add(list(bodies))
        builder.Commit()
    finally:
        builder.Destroy()


def _extrude_binder_face(part: NXOpen.Part, face: NXOpen.Face, distance: float) -> NXOpen.Features.Extrude:
    """
    Merlin.ExtrudeBinderFace - extrudes the edges of face in part (the work part) along part Z, distance down and
    distance up, as a new solid.
    """
    modeling: Any = cast(Any, part.Preferences).Modeling
    distance_tolerance = modeling.DistanceToleranceData
    section = part.Sections.CreateSection(0.95 * distance_tolerance, distance_tolerance, modeling.AngleToleranceData)
    rule_factory: Any = part.ScRuleFactory
    section.AddToSection([rule_factory.CreateRuleEdgeFace([face])], face, None, None,
                         NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Section.Mode.Create, False)

    builder: Any = part.Features.CreateExtrudeBuilder(None)
    try:
        builder.Section = section
        builder.Limits.StartExtend.Value.RightHandSide = nx.cs_double_str(-distance)
        builder.Limits.EndExtend.Value.RightHandSide = nx.cs_double_str(distance)
        builder.Direction = part.Directions.CreateDirection(NXOpen.Point3d(0.0, 0.0, 0.0), _VectorZ,
                                                            NXOpen.SmartObject.UpdateOption.WithinModeling)
        return cast(NXOpen.Features.Extrude, builder.CommitFeature())
    finally:
        builder.Destroy()


def _offset_binder_face_body_inward(part: NXOpen.Part, body: NXOpen.Body, distance: float) -> NXOpen.Expression:
    """
    Merlin.OffsetBinderFaceBodyInward - Insert -> Offset/Scale -> Offset Face on every face of body (a face-body
    rule, as the recorded journal does), distance so the body gets smaller, and returns the distance expression.
    The journal's Direction = True is tried first; if the body came out bigger the feature is edited with the
    direction flipped, since which way the flag points depends on the face normals.
    """
    def box_volume() -> float:
        box = _exact_box(body)
        return (box.MaxX - box.MinX) * (box.MaxY - box.MinY) * (box.MaxZ - box.MinZ)

    before = box_volume()

    builder = part.Features.CreateOffsetFaceBuilder(None)
    try:
        builder.FaceCollector.ReplaceRules([part.ScRuleFactory.CreateRuleFaceBody(body)], False)
        builder.Direction = True
        builder.Distance.SetFormula(nx.cs_double_str(distance))
        offset = cast(NXOpen.Features.Feature, builder.CommitFeature())
        expression = builder.Distance
    finally:
        builder.Destroy()

    if box_volume() > before:
        edit = part.Features.CreateOffsetFaceBuilder(offset)
        try:
            edit.Direction = not edit.Direction
            edit.CommitFeature()
            expression = edit.Distance
        finally:
            edit.Destroy()

        nx.info("Draw Die: the offset grew {} - flipped its direction.".format(offset.JournalIdentifier))

    return expression


# ---------------------------------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------------------------------

def _cross(a: NXOpen.Vector3d, b: NXOpen.Vector3d) -> NXOpen.Vector3d:
    return NXOpen.Vector3d(a.Y * b.Z - a.Z * b.Y, a.Z * b.X - a.X * b.Z, a.X * b.Y - a.Y * b.X)


def _z_matrix(axis_z: NXOpen.Vector3d) -> NXOpen.Matrix3x3:
    """Vector3d.__ToMatrix3x3() - a matrix whose Z axis is axis_z (X and Y picked the way the C# picks them)."""
    u = _VectorY if not abs(axis_z.X) < abs(axis_z.Y) else _VectorX
    z = nx.unit(axis_z)
    v = nx.unit(_cross(u, z))
    y = nx.unit(_cross(z, v))
    return nx.matrix_from_axes(v, y)


def _compute_upper_key_orientation() -> NXOpen.Matrix3x3:
    """Merlin.ComputeUpperKeyOrientation - a 90 degree rotation of the -Z matrix."""
    km = _z_matrix(_VectorZN)
    matrix = NXOpen.Matrix3x3()
    matrix.Xx, matrix.Xy, matrix.Xz = -km.Xy, km.Xx, km.Xz
    matrix.Yx, matrix.Yy, matrix.Yz = -km.Yy, km.Yx, km.Yz
    matrix.Zx, matrix.Zy, matrix.Zz = -km.Zy, km.Zx, km.Zz
    return matrix


def _lower_key_front_back_orientation() -> NXOpen.Matrix3x3:
    """Merlin.LowerKeyFrontBackOrientation - the lower keys' front/back orientation, as PlaceEdgeItems uses it."""
    return nx.matrix_from_axes(_VectorYN, _VectorX)


def _snap_to_inch_grid_from(anchor: NXOpen.Point3d, target: NXOpen.Point3d) -> NXOpen.Point3d:
    """
    Merlin.SnapToInchGridFrom - target's X and Y offsets from anchor become whole inches, truncated toward the
    anchor (so the point only moves inboard). Rounded to a micro-inch first so 3.9999999 counts as 4. Z is kept.
    """
    def snap(offset: float) -> float:
        return float(math.trunc(round(offset, 6)))

    return NXOpen.Point3d(anchor.X + snap(target.X - anchor.X), anchor.Y + snap(target.Y - anchor.Y), target.Z)


def _inset_corners(xlength: float, ywidth: float, inset: float) -> List[NXOpen.Point3d]:
    """Merlin.InsetCorners - the four points inset in from each side of an X 0..L, Y 0..W plate (Z 0)."""
    return [NXOpen.Point3d(inset, inset, 0.0),
            NXOpen.Point3d(xlength - inset, inset, 0.0),
            NXOpen.Point3d(xlength - inset, ywidth - inset, 0.0),
            NXOpen.Point3d(inset, ywidth - inset, 0.0)]


def _centered_min(box: nx.Box3d, xlength: float, ywidth: float, z: float) -> NXOpen.Point3d:
    """Merlin.CenteredMin - the min corner of an xlength x ywidth box centred on box in XY, at z."""
    return NXOpen.Point3d((box.MinX + box.MaxX - xlength) / 2, (box.MinY + box.MaxY - ywidth) / 2, z)


def _even_stations(start: float, end: float, count: int) -> List[float]:
    """Merlin.EvenStations - count evenly spaced values from start to end, both included."""
    return [(start + end) / 2 if count == 1 else start + (end - start) * i / (count - 1) for i in range(count)]


def _corners_and_mid_length(xlength: float, ywidth: float, inset: float, z: float) -> List[NXOpen.Point3d]:
    """Merlin.CornersAndMidLength - the four corners inset in, plus the two mid-length (Y) points, at z."""
    return ([NXOpen.Point3d(p.X, p.Y, z) for p in _inset_corners(xlength, ywidth, inset)]
            + [NXOpen.Point3d(inset, ywidth / 2, z), NXOpen.Point3d(xlength - inset, ywidth / 2, z)])


def _box_from(min_point: NXOpen.Point3d, xlength: float, ywidth: float, height: float) -> nx.Box3d:
    """new Box3d(min, min.__Add(xlength, ywidth, height))"""
    return nx.Box3d(min_point.X, min_point.Y, min_point.Z,
                    min_point.X + xlength, min_point.Y + ywidth, min_point.Z + height)


def _exact_box(obj: NXOpen.DisplayableObject) -> nx.Box3d:
    """new OrientedBox(obj.Tag, Tag.Null) as an absolute box - tsg_nx.body_box only reads the tag."""
    return nx.body_box(cast(NXOpen.Body, obj))


def _f3(value: float) -> str:
    """C#'s value.ToString("0.###")."""
    return merlin._format_0_000(value)


def _time_span(elapsed: datetime.timedelta) -> str:
    """TimeSpan.ToString() - hh:mm:ss.fffffff (the .NET default, as Timer prints it)."""
    ticks = elapsed.days * 864000000000 + elapsed.seconds * 10000000 + elapsed.microseconds * 10
    seconds, fraction = divmod(ticks, 10000000)
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return "{:02d}:{:02d}:{:02d}.{:07d}".format(hours, minutes, seconds, fraction)


def main() -> None:
    """The draw-die UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("draw-die"):
        try:
            # No dialog of its own: ask before doing anything (a logged Question box).
            if nx.confirm_execute("draw-die"):
                DrawDie.execute(True)
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
