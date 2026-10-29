"""
The Blank Station / Secondary Trim Station UFuncs (blank-station / secondary-trim-station): a port of
Merlin.RunTimMagic, Merlin.BuildBlankStations and Merlin.TryFindBlankStations (src\\UFuncs\\Merlin.cs, region
"Automated Blank Stations - TimMagic"), plus every stage builder and helper they use that no other port had yet.

Python only since 2026-10-23: the blank-station menu button runs this file's main(), the secondary-trim-station
one SecondaryTrimStation.py's. Both call BlankStation.execute(is3d) - RunTimMagic's front end: the units / -000 /
station gates, then BlankStationDialog (slug bodies + D2 / S7 trim-steel material, in place of the SNAP
BlankStationDialog), then the build. The C# UFunc classes, RunTimMagic and BlankStationDialog are in git at 41f2a7b.

    Session.Execute("BlankStation.py", "BlankStation", "execute", is3d)      # gates + dialog + build
    PythonLibrary.Execute("BlankStation.py", "BlankStation", "build",
                          is3d, material, bodies.Cast<TaggedObject>().ToArray());  # Auto Design: the build alone

build re-runs the gates BuildBlankStations has (english info units, a -000 display part, the uad/upd/lad stations),
so it is also safe for a caller that never showed the dialog (Merlin.StaticAutoDesign).

Run at the -000. For each picked slug body (its box and owning component are captured up front), with
station = "01" for the Blank Station (is3d False) and "02" for the Secondary Trim Station (is3d True):
  1. backing plate BP1 into uad{station} - slug box +2" (1/8" up), Z 2.86..3.10 (3D: .24" thick, sitting on the
     retainer, whose bottom is 20 mm over the window's top), chamfered .25", color 130, faces
     +-Z 42, chamfers 211, O1 GS, 2x 8mm-shcs-020-2x on the diagonal (CBORE);
  2. retainer Retainer1 into uad{station} - 1.25" below the backing plate's bottom, chamfered, color 200, 4140,
     4x 12mm-shcs-050-2x (CBORE), dowels + jack screws .5" in from X, jacks .25" lower; UPR-PROFILE subtracted;
  3. punch Punch1 into uad{station} - 3.625" (2D) / 7" (3D) below the backing plate, color 60, FILL IN, 2 Unikix pins
     (SUB_TOOL), 2x 10mm-shcs-020-2x (SHORT-TAP), 1x 8mm-shcs-065-2x from the bottom on layer 98 kept out of BODY;
     UPR-PROFILE INTERSECTED;
  4. window Window1 into upd{station} - slug box +6", 25 mm thick on top of the slug (3D: grown 4" in -Z), built
     upside down (flipZ re-base), chamfered, color 136, 4140 PH, 4x 12mm-shcs-030-2x, dowels + jacks, 2 extra SHCS;
     3D subtracts UPR-3D, and its top is at least 1" over the highest point of the component's UPR-3D bodies;
  5. lower trim steel lts into lad{station} - slug box +2.5", Z -50 mm (2D) / 1.875" under the LWR-3D bodies' lowest
     point (3D) up to the slug's underside (3D: +3"), chamfered, color 11, FILL IN, 4x 12mm-shcs-050-2x, dowels +
     jacks, 2 extra SHCS; LWR-PROFILE subtracted, and 3D also LWR-3D;
  6. the window named WINDOW gets PAD-PROFILE subtracted; the backing plate gets CLR_HOLE for the retainer's SHCS and
     the punch's non-8mm SHCS;
  7. the retainer gets SHORT-TAP for the backing plate's SHCS;
  8. the taper (a 2 degree drafted extrude off the layout link's top tangent edge) is cut in the lower trim steel;
  9. the lower trim steel's first extrude is colored 211;
 10. every view of the five new parts is regenerated.
After every slug, MATERIAL = the picked material (D2 / S7) goes on every punch and lower trim steel, and the session
is put back on the -000 (work part = display part). Each new detail is set to BODY in every assembly on its path.

Secondary Trim Station heights: before any slug is built, each picked component is switched to UPR-3D and LWR-3D
in turn (and put back) to measure those bodies. A component missing either gets one Question box for the whole
run - Yes uses the picked body (its current reference set) for the missing side, No cancels before anything is
built. This is Python-only; the commented-out C# measured the picked body.

Kept from the C#, quirks included:
  - Every stage is its own try/except + print_exception, so a failed stage does not stop the next one; a later stage
    that needs an earlier detail then fails in turn and prints (stage 6 assumes stages 1-5 succeeded).
  - A slug with no layout-link taper edge, or a lower trim steel with no Extrude, skips EVERYTHING after it for that
    slug (including the view regeneration) - the C# `continue`s the per-slug loop there, so this returns.
  - The 3D LWR-3D guard skips only the boolean.
  - The "out" components of the retainer, punch and lower trim steel are seen by the caller as soon as the builder
    writes them (C# out parameters), even when the builder throws later - emulated with a small holder.
  - The SetReferenceSetInAncestorAssemblies calls in stage 6 are commented out in the C#, so they are not made here.
  - No undo mark: BuildBlankStations sets none.
  - Listing-window messages and cue lines are the C#'s, "doesn't containt" included.

Differences from the C#:
  - Merlin.ChamferVerticalEdges uses Snap.Create.Chamfer(edge, ".25in", false); this is CastTrimPad's NXOpen
    ChamferBuilder (symmetric offset, edges along faces), one feature per vertical edge as SNAP makes them, with
    .25" written in part units.
  - Blocks: BasePart.__CreateBlock(Matrix3x3, Point3d, Point3d) restores the WCS with its original X axis but the
    BLOCK's Y axis (a latent bug); tsg_nx.create_block restores both original axes. The orientation is the identity
    rather than the part's AbsoluteCsys orientation, which is the identity by definition.
  - RebaseBlockToPartOrigin(flipZ: true) (the window) is ported here (_rebase_block_flip_z); the other modes reuse
    DrawDie._rebase_block_to_part_origin. Both read the block size through UF_MODL_ask_block_parms, since
    BlockFeatureBuilder.Length/Width/Height come back None in Python.
  - Merlin.StampFastenerSubtract is re-ported (_stamp_fastener_subtract) rather than imported from DrawDie, because
    DrawDie's version tests jack screws with tsg_nx.is_jck_screw ("-jck-screw-" substring), which misses the
    "12mm-jck-screw" leaf that BasePart.__IsJckScrew (EndsWith "-jck-screw") matches. DropAndSubtract is re-ported
    for the same reason.
  - The taper's ExtrudeBuilder, Views.Regenerate and the null NXOpen objects are reached through `Any`: the
    hand-written stubs do not cover them (stubs not edited).
  - Booleans go through tsg_nx.create_boolean (tool-body collector) where Body.__CreateBoolean uses the obsolete
    BooleanBuilder.Tools - same result.
  - The obsolete NXObject.GetStringAttribute (CopyAssemblyAttributes) is GetUserAttributeAsString(String).
  - A hard C# cast of the wave-link source to Body is an explicit isinstance check that raises TypeError.
  - The AutoSize UDO class can only be registered from C# (see tsg_nx.create_auto_size_udo): AutoSizeComponent.Startup
    registers it at NX startup (and Merlin.BuildBlankStations before Auto Design calls build). Run where it was never
    registered, the details get no UDO, with a print.
  - BlankStation.build and execute catch and print anything that escapes, so nothing crosses Session.Execute.

The Merlin helpers PointComponent.py, DrawDie.py and CastTrimPad.py already port are imported from them rather than
copied.
"""

from __future__ import annotations

import math
import os
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple, cast

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
import DrawDie as drawdie  # noqa: E402
import CastTrimPad as trimpad  # noqa: E402

# The NXOpen members the stubs do not cover (the taper's ExtrudeBuilder, the .Null objects, SmartVolumeProfile).
_NXOpen: Any = NXOpen

# ---------------------------------------------------------------------------------------------------
# Constants (Merlin's, inches unless the name says otherwise)
# ---------------------------------------------------------------------------------------------------

_defaultShcsPath = "G:\\0Library\\Fasteners\\Metric\\SocketHeadCapScrews-2X\\012-2x\\12mm-shcs-050-2x.prt"
_dwl12mm050Path = "G:\\0Library\\Fasteners\\Metric\\Dowels\\12mm-dwl-050.prt"
_jck12mmScrewPath = "G:\\0Library\\Fasteners\\Metric\\JackScrews\\12mm-jck-screw.prt"
_jck12mmScrewTsgPath = "G:\\0Library\\Fasteners\\Metric\\JackScrews\\12mm-jck-screw-tsg.prt"

# Literal paths in the stage builders.
_shcs8mm020Path = "G:\\0Library\\Fasteners\\Metric\\SocketHeadCapScrews-2X\\008-2x\\8mm-shcs-020-2x.prt"
_shcs8mm065Path = "G:\\0Library\\Fasteners\\Metric\\SocketHeadCapScrews-2X\\008-2x\\8mm-shcs-065-2x.prt"
_shcs10mm020Path = "G:\\0Library\\Fasteners\\Metric\\SocketHeadCapScrews-2X\\010-2x\\10mm-shcs-020-2x.prt"
_shcs12mm030Path = "G:\\0Library\\Fasteners\\Metric\\SocketHeadCapScrews-2X\\012-2x\\12mm-shcs-030-2x.prt"
_dwl12mm025Path = "G:\\0Library\\Fasteners\\Metric\\Dowels\\12mm-dwl-025.prt"
_unikixPinsPath = "G:\\0Library\\Unikix\\Smart Unikix Pins.prt"

# ChamferVerticalEdges' default ".25in".
TrimDetailChamfer = .25

# Dowel / jack-screw layout shared by the lower trim steel, window and retainer (AddDowelsAndJackScrews). All
# distances are physical, as seen in the -000 - the upper details mirror them into their own frame.
TrimDetailFastenerInsetX = .625
TrimDetailDowelInsetNegY = 1.5
TrimDetailDowelInsetPosY = 1.75
TrimDetailJackInsetPosY = 2.50
TrimDetailJackInsetNegY = 2.25
TrimDetailTsgJackInsetY = 1.75
TrimDetailTsgJackShiftX = .625 - .1875
RetainerFastenerInsetX = .5
RetainerJackZOffset = -.25
# Secondary Trim Station window: minimum thickness above the part's highest point (inches).
WindowMinThickness3d = 1.0
# Secondary Trim Station lower trim steel: its block origin (bottom) this far below the part's lowest point (inches).
LowerTrimSteelBelowPart3d = 1.875
# Secondary Trim Station window: its top face this far above the UPR-3D / LWR-3D intersect's highest point (inches,
# in the -000).
WindowAboveIntersect3d = .875
# Name of the same-size block the Secondary Trim Station builds in lad02 ahead of the real lower trim steel (deleted
# once the station is built).
TempLowerTrimSteelName = "TEMP LOWER TRIM STEEL"
# The second same-size temp block, which gets UPR-3D and LWR-3D linked in together.
TempLowerTrimSteelName2 = "TEMP LOWER TRIM STEEL 2"
# Secondary Trim Station retainer: its bottom face this far above the window's top face (20 mm).
RetainerAboveWindow3d = 20 / 25.4
# The reference sets the Secondary Trim Station measures the window / lower trim steel heights from.
UpperZRefset = "UPR-3D"
LowerZRefset = "LWR-3D"

# NXException.ErrorCode values handled by the stages.
_ErrorCouldNotSubtract = 670030
_ErrorTaperNoSolidBody = 671468
_ErrorTaperIncompatibleDirection = 671443

_VectorX = NXOpen.Vector3d(1.0, 0.0, 0.0)
_VectorY = NXOpen.Vector3d(0.0, 1.0, 0.0)
_VectorZ = NXOpen.Vector3d(0.0, 0.0, 1.0)
_VectorYN = NXOpen.Vector3d(0.0, -1.0, 0.0)
_VectorZN = NXOpen.Vector3d(0.0, 0.0, -1.0)

_Origin = NXOpen.Point3d(0.0, 0.0, 0.0)

# Environment.NewLine in the missing-station message.
_NewLine = "\r\n"

# The dialog titles (RunTimMagic's, with the version in front as the Python dialogs put it).
BlankStationTitle = "Blank Station"
SecondaryTrimStationTitle = "Secondary Trim Station"


class BlankStation(object):

    @staticmethod
    def build(is3d: bool, material: str, bodies: Sequence[NXOpen.Body], quiet: bool = False) -> None:
        """
        Session.Execute entry for the blank-station (is3d False) / secondary-trim-station (is3d True) UFuncs:
        Merlin.BuildBlankStations(is3d, bodies, material) with the arguments in the order the C# passes them.
        bodies are the picked slug solid bodies (occurrences, so OwningComponent is the slug component); material is
        "D2" or "S7". quiet leaves out the "Created reference set" lines (AutoDesign).
        """
        try:
            with nx.quiet_listing(quiet):
                build_blank_stations(bool(is3d), [body for body in bodies], str(material))
        except Exception as ex:
            nx.print_exception(ex)

    @staticmethod
    def execute(is3d: bool) -> None:
        """
        Merlin.RunTimMagic - the blank-station (is3d False, -01 stations) / secondary-trim-station (is3d True,
        -02 stations) front end: the units and -000 gates and the station lookup before anything is picked, so a job
        missing a station fails first; then BlankStationDialog for the slug bodies and the material; then build.
        """
        try:
            ok, message = drawdie._check_info_units()
            if not ok:
                nx.show_error(message)
                return

            if not nx.display_part().Leaf.endswith("-000"):
                nx.show_error("This must be ran at the 000")
                return

            if try_find_blank_stations(bool(is3d)) is None:
                return

            from BlankStationDialog import ask
            from tsg_dialog import title_with_version

            result = ask(title_with_version(SecondaryTrimStationTitle if is3d else BlankStationTitle))
            if result is None:
                return
            bodies, material = result
        except Exception as ex:
            nx.print_exception(ex)
            return

        BlankStation.build(bool(is3d), material, bodies)


# ---------------------------------------------------------------------------------------------------
# BuildBlankStations / TryFindBlankStations
# ---------------------------------------------------------------------------------------------------

class _Stations(object):
    """TryFindBlankStations' three out parts."""

    def __init__(self, part_uad: NXOpen.Part, part_upd: NXOpen.Part, part_lad: NXOpen.Part) -> None:
        self.part_uad = part_uad
        self.part_upd = part_upd
        self.part_lad = part_lad


class _Out(object):
    """A C# `out Component` - the caller sees the value as soon as the callee writes it, even if it throws later."""

    def __init__(self) -> None:
        self.value: Optional[NXOpen.Assemblies.Component] = None


class _TempGeometry(object):
    """
    What the Secondary Trim Station's temp lower trim steel blocks leave in lad02 - the two blocks, the UPR-3D link,
    the brep links and the intersects - deleted once every slug is built.
    """

    def __init__(self, part: NXOpen.Part) -> None:
        self.part = part
        self.features: List[NXOpen.Features.Feature] = []
        self.body_tags: Set[int] = set()


def build_blank_stations(is3d: bool, bodies1: Sequence[NXOpen.Body], material: str) -> None:
    """
    Merlin.BuildBlankStations - one blank station per slug body, with material (D2 / S7) stamped on every punch and
    lower trim steel. Gates on the units, the -000 and the stations like the dialog front end.
    """
    ok, message = drawdie._check_info_units()
    if not ok:
        nx.show_error(message)
        return

    if not nx.display_part().Leaf.endswith("-000"):
        nx.show_error("This must be ran at the 000")
        return

    stations = try_find_blank_stations(is3d)
    if stations is None:
        return

    starting_display = nx.display_part()

    # The punch and lower trim steel of every slug, for the MATERIAL pass after the loop.
    trim_steels: List[NXOpen.Assemblies.Component] = []

    drawdie._set_wcs_to_absolute(nx.display_part())
    body_data: List[Tuple[nx.Box3d, NXOpen.Assemblies.Component]] = []

    for b in bodies1:
        body_data.append((nx.body_box(b), b.OwningComponent))

    # Secondary Trim Station: the window height comes off each component's UPR-3D bodies and the lower trim steel's
    # off its LWR-3D bodies. Measured after the boxes above, since switching a reference set kills the picked
    # body occurrences.
    z_boxes: List[Tuple[nx.Box3d, nx.Box3d]] = [(box, box) for box, _ in body_data]
    if is3d:
        measured = _measure_3d_refset_boxes(body_data)
        # No at the missing reference set question (it marked the run cancelled).
        if measured is None:
            return
        z_boxes = measured

    temp = _TempGeometry(stations.part_lad)
    with nx.suppress_display():
        for i in range(len(body_data)):
            try:
                _build_one_slug(i, len(bodies1), is3d, body_data[i][0], body_data[i][1], stations, trim_steels,
                                upper_box=z_boxes[i][0], lower_box=z_boxes[i][1], temp=temp)
            except Exception as ex:
                nx.print_exception(ex)

    # The temp blocks only set the heights; nothing built from them refers back to them.
    try:
        _delete_temp_geometry(temp)
    except Exception as ex:
        nx.print_exception(ex)

    # The trim-steel material picked in the selection dialog goes on last, over the "FILL IN" the punch and lower
    # trim steel builders stamp. Done after the loop rather than at the end of each iteration because the taper and
    # extrude-coloring stages can skip the end of it.
    nx.prompt("Setting MATERIAL = {} on {} trim steel(s)".format(material, len(trim_steels)))
    for trim_steel in trim_steels:
        try:
            nx.set_attribute(nx.prototype(trim_steel), "MATERIAL", material)
        except Exception as ex:
            nx.print_exception(ex)

    # The stages leave the work part pointed at whichever detail component they last built; put the session back on
    # the -000 with the work part matching the display part.
    nx.set_display_part(starting_display)
    nx.set_work_part(nx.display_part())


def try_find_blank_stations(is3d: bool) -> Optional[_Stations]:
    """
    Merlin.TryFindBlankStations - the uad/upd/lad station assemblies under the display part (-01 for the Blank
    Station, -02 for the Secondary Trim Station; usp/lsp are the legacy fallbacks). Shows an error naming every
    missing one and returns None when any is missing.
    """
    station = "02" if is3d else "01"

    root = nx.root_component(nx.display_part())
    descendants: List[NXOpen.Assemblies.Component] = list(nx.descendants(root)) if root is not None else []

    def find_station(station_name: str, fallback: str) -> Optional[NXOpen.Assemblies.Component]:
        for c in descendants:
            if station_name in c.DisplayName:
                return c
        for c in descendants:
            if fallback in c.DisplayName:
                return c
        return None

    component_uad = find_station("uad" + station, "usp")
    component_upd = find_station("upd" + station, "usp")
    component_lad = find_station("lad" + station, "lsp")

    missing_stations: List[str] = []

    if component_uad is None:
        missing_stations.append("uad{} (or usp)".format(station))
    if component_upd is None:
        missing_stations.append("upd{} (or usp)".format(station))
    if component_lad is None:
        missing_stations.append("lad{} (or lsp)".format(station))

    if component_uad is None or component_upd is None or component_lad is None:
        nx.show_error("The following station {} not found under {}:{}{}{}".format(
            "assembly was" if len(missing_stations) == 1 else "assemblies were",
            nx.display_part().Leaf, _NewLine, _NewLine, _NewLine.join(missing_stations)))
        return None

    return _Stations(cast(NXOpen.Part, nx.prototype(component_uad)),
                     cast(NXOpen.Part, nx.prototype(component_upd)),
                     cast(NXOpen.Part, nx.prototype(component_lad)))


def _measure_3d_refset_boxes(
        body_data: Sequence[Tuple[nx.Box3d, NXOpen.Assemblies.Component]]
) -> Optional[List[Tuple[nx.Box3d, nx.Box3d]]]:
    """
    The (upper, lower) Z boxes of each slug for the Secondary Trim Station: its component's UPR-3D / LWR-3D solid
    bodies, with the component switched to that reference set to measure and put back after. A component missing
    one is listed in one warning; Yes carries on with the picked body's box (its current reference set) for the
    missing side, No cancels the run (None).
    """
    components: List[NXOpen.Assemblies.Component] = []
    for _, comp in body_data:
        if all(c.Tag != comp.Tag for c in components):
            components.append(comp)

    if not nx.confirm_missing_reference_sets(
            "Secondary Trim Station", "The window height is taken from UPR-3D and the lower trim steel's from LWR-3D",
            components, (UpperZRefset, LowerZRefset)):
        return None

    boxes: Dict[Tuple[int, str], Optional[nx.Box3d]] = {}
    for comp in components:
        for name in (UpperZRefset, LowerZRefset):
            boxes[(comp.Tag, name)] = nx.reference_set_box(comp, name, "Secondary Trim Station")

    result: List[Tuple[nx.Box3d, nx.Box3d]] = []
    for box, comp in body_data:
        result.append((boxes[(comp.Tag, UpperZRefset)] or box, boxes[(comp.Tag, LowerZRefset)] or box))
    return result


def _build_one_slug(i: int, count: int, is3d: bool, box: nx.Box3d, owning_comp: NXOpen.Assemblies.Component,
                    stations: _Stations, trim_steels: List[NXOpen.Assemblies.Component],
                    upper_box: Optional[nx.Box3d] = None, lower_box: Optional[nx.Box3d] = None,
                    temp: Optional[_TempGeometry] = None) -> None:
    """
    The body of BuildBlankStations' per-slug loop. A `return` here is the C#'s `continue` of the outer loop (the
    taper and extrude-coloring stages); everything else is per-stage try/except. upper_box / lower_box set the 3D
    window top and lower trim steel bottom (the UPR-3D / LWR-3D bodies); both default to box. temp collects the 3D
    temp blocks and their links / intersects for the caller to delete.
    """
    upper_box = upper_box or box
    lower_box = lower_box or box
    nx.prompt("{} of {} -> backing plate".format(i + 1, count))
    drawdie._set_wcs_to_absolute(nx.display_part())
    nx.display_part().Layers.WorkLayer = 1
    current = nx.display_part()
    material_thickness = box.MaxZ - box.MinZ
    bp_cx = (box.MinX + box.MaxX) / 2
    bp_cy = (box.MinY + box.MaxY) / 2
    bp_x = nx.round_to_125(box.MaxX - box.MinX + 2)
    bp_y = nx.round_to_125(box.MaxY - box.MinY + 2)
    min_bp = NXOpen.Point3d(bp_cx - bp_x / 2, bp_cy - bp_y / 2, 3.10 - .24)
    max_bp = NXOpen.Point3d(bp_cx + bp_x / 2, bp_cy + bp_y / 2, 3.10)
    slug_thickness = box.MaxZ - box.MinZ

    # Secondary Trim Station: the two temp blocks in lad02 and their intersects come first, since the window top
    # (and with it the retainer, backing plate and punch) and the lower trim steel bottom are set from them.
    # station_box is the second intersect's box in lad02's coordinates, assembly_box the same body in the -000's.
    lts_min_z = -50 / 25.4
    station_box: Optional[nx.Box3d] = None
    assembly_box: Optional[nx.Box3d] = None
    if is3d:
        lts_min_z = lower_box.MinZ - LowerTrimSteelBelowPart3d
        nx.prompt("{} of {} -> temp lower trim steel blocks".format(i + 1, count))
        try:
            first_box, station_box, assembly_box = _build_temp_lower_blocks(
                current, box, owning_comp, stations.part_lad, lts_min_z, 3.0,
                temp if temp is not None else _TempGeometry(stations.part_lad))
            if station_box is not None:
                lts_min_z = station_box.MinZ - LowerTrimSteelBelowPart3d
                nx.info("{}: lower trim steel bottom at Z {:.4f} ({}\" under the {} / {} intersect's lowest "
                          "point)".format(owning_comp.DisplayName, lts_min_z, LowerTrimSteelBelowPart3d,
                                          UpperZRefset, LowerZRefset))
            elif first_box is not None:
                lts_min_z = first_box.MinZ - LowerTrimSteelBelowPart3d
                nx.info("{}: lower trim steel bottom at Z {:.4f} ({}\" under the {} intersect's lowest "
                          "point)".format(owning_comp.DisplayName, lts_min_z, LowerTrimSteelBelowPart3d,
                                          UpperZRefset))
        except Exception as ex:
            nx.print_exception(ex)
        finally:
            nx.set_display_part(current)
            nx.display_part().Layers.WorkLayer = 1

    win_x = nx.round_to_125(box.MaxX - box.MinX + 6)
    win_y = nx.round_to_125(box.MaxY - box.MinY + 6)
    win_cx = (box.MinX + box.MaxX) / 2
    win_cy = (box.MinY + box.MaxY) / 2
    window_min = NXOpen.Point3d(win_cx - win_x / 2, win_cy - win_y / 2, slug_thickness)
    window_top_z = slug_thickness + 25 / 25.4
    if is3d and assembly_box is not None:
        # Secondary Trim Station: the window's top face goes WindowAboveIntersect3d over the highest point of the
        # UPR-3D / LWR-3D intersect, measured in the -000.
        window_top_z = assembly_box.MaxZ + WindowAboveIntersect3d
        nx.info("{}: window top at Z {:.4f} ({}\" over the {} / {} intersect's highest point)".format(
            owning_comp.DisplayName, window_top_z, WindowAboveIntersect3d, UpperZRefset, LowerZRefset))
    elif is3d:
        # Secondary Trim Station without that intersect: the window must be at least WindowMinThickness3d thick at
        # its thinnest section, taken (conservatively) as above the part's highest point (its UPR-3D bodies), the
        # way the draw die measures it. Raised tops are rounded up to 1/8".
        min_top_z = upper_box.MaxZ + WindowMinThickness3d
        if window_top_z < min_top_z:
            window_top_z = math.ceil(min_top_z * 8 - 1e-9) / 8
    window_max = NXOpen.Point3d(win_cx + win_x / 2, win_cy + win_y / 2, window_top_z)
    if is3d:
        # Secondary Trim Station: the retainer's bottom sits RetainerAboveWindow3d over the window's top. min_bp.Z
        # is the retainer's top (1.25" up), which is also the backing plate's bottom and the punch's top, so the
        # backing plate sits on the retainer and the punch is flush with that face.
        bp_bottom_z = window_top_z + RetainerAboveWindow3d + 1.25
        min_bp = NXOpen.Point3d(min_bp.X, min_bp.Y, bp_bottom_z)
        max_bp = NXOpen.Point3d(max_bp.X, max_bp.Y, bp_bottom_z + .24)
    # Any so the stages below can hand a None to the next stage the way the C# hands it a null - they then throw
    # and print, exactly as the C# NREs and prints.
    component_backing: Any = None
    component_window: Any = None
    retainer = _Out()
    punch = _Out()
    lower_trim_steel = _Out()

    # Backing plate
    try:
        component_backing = _create_backing_plate(current, min_bp, max_bp, stations.part_uad)
        component_backing = _first_descendant_named(current, component_backing.DisplayName)
        _set_body_up_assembly_path(component_backing)
    except Exception as ex:
        nx.print_exception(ex)
    finally:
        nx.set_display_part(current)

    nx.prompt("{} of {} -> retainer".format(i + 1, count))

    # Retainer
    try:
        _create_retainer(current, owning_comp, min_bp, max_bp, stations.part_uad, retainer)
        retainer.value = _first_descendant_named(current, _require(retainer.value).DisplayName)
        _set_body_up_assembly_path(retainer.value)
    except Exception as ex:
        nx.print_exception(ex)

    nx.set_display_part(current)

    nx.prompt("{} of {} -> punch".format(i + 1, count))

    # Punch
    try:
        _create_punch(current, owning_comp, min_bp, max_bp, stations.part_uad, 7.0 if is3d else 3.625, punch)
        if punch.value is not None:
            trim_steels.append(punch.value)

        punch.value = _first_descendant_named(current, _require(punch.value).DisplayName)
        _set_body_up_assembly_path(punch.value)
    except Exception as ex:
        nx.print_exception(ex)
    nx.set_display_part(current)

    nx.prompt("{} of {} -> window".format(i + 1, count))

    # Window - 3D grows the block 4" in the -Z direction (lowers the bottom corner)
    try:
        window_min_for_block = nx.add_z(window_min, -4) if is3d else window_min
        component_window = _create_window(current, window_min_for_block, window_max, stations.part_upd,
                                          add_extra_shcs=True)
        component_window = _first_descendant_named(current, component_window.DisplayName)
        _set_body_up_assembly_path(component_window)
    except Exception as ex:
        nx.print_exception(ex)

    nx.set_display_part(current)

    # 3D: link and subtract UPR-3D out of the newly created window
    if is3d:
        try:
            component_window = _first_occurrence_of(component_window, nx.display_part())
            nx.set_work_component(component_window)

            drawdie._subtract_refset_from_dynamic_block(nx.work_part(), owning_comp, "UPR-3D")
            nx.set_display_part(current)
        except Exception as ex:
            nx.print_exception(ex)

    nx.prompt("{} of {} -> lower trim steel".format(i + 1, count))

    # Lower trim steel - 2D puts the block bottom at -50 mm and leaves the top at the default (window_min.Z -
    # material_thickness). 3D puts the bottom (the block origin) LowerTrimSteelBelowPart3d under the UPR-3D / LWR-3D
    # intersect's lowest point (lts_min_z, set before the window) and pins the top to +3.
    try:
        _create_lower_trim_steel(current, box, owning_comp, material_thickness, window_min, stations.part_lad,
                                 lower_trim_steel,
                                 override_min_z=lts_min_z,
                                 override_max_z=3.0 if is3d else None,
                                 add_extra_shcs=True)
        if lower_trim_steel.value is not None:
            trim_steels.append(lower_trim_steel.value)

        lower_trim_steel.value = _first_descendant_named(current, _require(lower_trim_steel.value).DisplayName)
        _set_body_up_assembly_path(lower_trim_steel.value)
    except Exception as ex:
        nx.print_exception(ex)

    # 3D: subtract LWR-3D into the lower trim steel. A slug whose component has no LWR-3D reference set skips *only*
    # this boolean - the remaining stages still have to run for this slug.
    if is3d:
        try:
            if not nx.has_reference_set(nx.prototype(owning_comp), "LWR-3D"):
                nx.print_("Component {} does not have reference set LWR-3D, skipping boolean".format(
                    owning_comp.DisplayName))
            else:
                nx.set_reference_set(owning_comp, "LWR-3D")
                _subtract_from_dynamic_block(nx.work_part(), owning_comp)
                nx.set_reference_set(owning_comp, "BODY")
        except Exception as ex:
            nx.print_exception(ex)

    nx.set_display_part(current)

    nx.prompt("{} of {} -> backing plate pad profile".format(i + 1, count))

    # Clearance holes and final BODY reference sets
    try:
        component_window = _first_occurrence_of(component_window, nx.display_part())
        component_window.SetName("WINDOW")
        nx.set_work_component(component_window)
        # Switching a component to a reference set it does not publish throws. Unguarded it would take the whole of
        # stage 6 with it.
        if nx.has_reference_set(nx.prototype(owning_comp), "PAD-PROFILE"):
            drawdie._subtract_refset_from_dynamic_block(nx.work_part(), owning_comp, "PAD-PROFILE")
        else:
            nx.print_("Component {} does not have reference set PAD-PROFILE, skipping the window boolean".format(
                owning_comp.DisplayName))
        nx.set_display_part(current)

        component_backing = _first_occurrence_of(component_backing, nx.display_part())
        component_backing.SetName("UPPER PUNCH BACKING PLATE")
        nx.set_work_component(component_backing)
        for child in _require(retainer.value).GetChildren():
            drawdie._subtract_refset_from_dynamic_block(nx.work_part(), child, "CLR_HOLE")
        nx.set_display_part(current)

        nx.set_work_component(component_backing)
        for child in _require(punch.value).GetChildren():
            if "shcs" not in child.DisplayName:
                continue
            if "8mm" in child.DisplayName:
                continue
            drawdie._subtract_refset_from_dynamic_block(nx.work_part(), child, "CLR_HOLE")

        # (The C#'s SetReferenceSetInAncestorAssemblies calls for the five details are commented out here.)
    except Exception as ex:
        nx.print_exception(ex)

    nx.set_display_part(current)
    nx.prompt("{} of {} -> retainer fasteners".format(i + 1, count))

    try:
        nx.set_work_component(retainer.value)
        for child in component_backing.GetChildren():
            if "shcs" in child.DisplayName:
                drawdie._subtract_refset_from_dynamic_block(nx.work_part(), child, "SHORT-TAP")
    except Exception as ex:
        nx.print_exception(ex)

    # Taper runs for both the 2D and 3D variants.
    try:
        nx.prompt("{} of {} -> taper".format(i + 1, count))
        nx.set_display_part(nx.prototype(_require(lower_trim_steel.value)))
        dynamicblock = nx.dynamic_block(nx.display_part())
        body1 = dynamicblock.GetBodies()[0]
        tangent_edge = _find_taper_edge(nx.display_part())

        if tangent_edge is None:
            nx.print_("Couldn't find edge for taper in {}".format(nx.display_part().Leaf))
            nx.set_display_part(current)
            return  # the C# `continue`s the per-slug loop

        try:
            taper = _create_taper(nx.work_part(), body1, tangent_edge)
            taper.SetName("TAPER")
        except NXOpen.NXException as ex:
            if ex.ErrorCode == _ErrorTaperNoSolidBody:
                nx.print_("Could not find solid body for taper in {}".format(nx.display_part().Leaf))
            elif ex.ErrorCode == _ErrorTaperIncompatibleDirection:
                nx.print_("Section and direction for taper were incompatible {}".format(nx.display_part().Leaf))
            else:
                raise
    except Exception as ex:
        nx.print_exception(ex)

    nx.set_display_part(current)

    try:
        nx.set_display_part(nx.prototype(_require(lower_trim_steel.value)))

        extrude: Optional[NXOpen.Features.Feature] = None
        for feature in nx.display_part().Features.GetFeatures():
            if isinstance(feature, NXOpen.Features.Extrude):
                extrude = feature
                break

        if extrude is None:
            nx.print_("Could not find extrude to color for {}".format(nx.display_part().Leaf))
            nx.set_display_part(current)
            return  # the C# `continue`s the per-slug loop

        for face in extrude.GetFaces():
            nx.set_color(face, 211)
    except Exception as ex:
        nx.print_exception(ex)

    nx.set_display_part(current)

    # Regenerate every view in each newly created detail part so the blank/secondary-trim station geometry displays
    # correctly.
    nx.prompt("{} of {} -> regenerate views".format(i + 1, count))
    for new_comp in (component_backing, retainer.value, punch.value, component_window, lower_trim_steel.value):
        try:
            if new_comp is None:
                continue
            nx.set_display_part(nx.prototype(new_comp))
            cast(Any, nx.display_part().Views).Regenerate()
        except Exception as ex:
            nx.print_exception(ex)

    nx.set_display_part(current)


def _require(component: Optional[NXOpen.Assemblies.Component]) -> NXOpen.Assemblies.Component:
    """Dereferencing a C# null component - the NullReferenceException the stage's catch prints."""
    if component is None:
        raise AttributeError("Object reference not set to an instance of an object.")
    return component


def _first_occurrence_of(component: Optional[NXOpen.Assemblies.Component],
                         assembly: NXOpen.BasePart) -> NXOpen.Assemblies.Component:
    """Component.__FirstOccurrenceIn(Part) - the first occurrence of component's prototype in assembly."""
    return nx.first_occurrence_in(nx.prototype(_require(component)), assembly)


def _first_descendant_named(current: NXOpen.Part, display_name: str) -> NXOpen.Assemblies.Component:
    """current.ComponentAssembly.RootComponent.__Descendants().First(c => c.DisplayName == display_name)"""
    root = current.ComponentAssembly.RootComponent
    if root is None:
        raise AttributeError("Object reference not set to an instance of an object.")
    for c in nx.descendants(root):
        if c.DisplayName == display_name:
            return c
    raise RuntimeError("Sequence contains no matching element")


def _set_body_up_assembly_path(component: NXOpen.Assemblies.Component) -> None:
    """
    BuildBlankStations' per-stage loop over component._AssemblyPath(): in the prototype of every assembly on the
    path (the component itself excluded by name), the descendant with the component's display name is set to BODY.
    """
    t: Optional[NXOpen.Assemblies.Component] = component
    while t is not None:
        if t.DisplayName != component.DisplayName:
            nx.set_reference_set(_first_descendant_named(cast(NXOpen.Part, nx.prototype(t)), component.DisplayName),
                                 "BODY")
        t = t.Parent


# ---------------------------------------------------------------------------------------------------
# Stage builders
# ---------------------------------------------------------------------------------------------------

def _create_backing_plate(current: NXOpen.Part, min_bp: NXOpen.Point3d, max_bp: NXOpen.Point3d,
                          station_uad: NXOpen.Part) -> NXOpen.Assemblies.Component:
    """Merlin.CreateBackingPlate - the upper-punch backing plate into station_uad, two diagonal-corner SHCS."""
    nx.set_display_part(station_uad)
    nx.display_part().Layers.WorkLayer = 1
    block_backing = nx.create_block(min_bp, max_bp)
    nx.set_layer(block_backing.GetBodies()[0], 1)
    block_backing.SetName("DYNAMIC BLOCK")
    owning_backing = nx.display_part()
    component_backing = merlin._create_cts_component(block_backing, "BP1")

    # Origin on the block's corner rather than the station's, before the subtool below. uad station - upper, so the
    # csys goes on the block's far vertex.
    drawdie._rebase_block_to_part_origin(component_backing, owning_backing, opposite_corner=True)
    nx.setup_station_expressions(nx.prototype(component_backing))

    # The two diagonal SHCS below are the only things placed from assembly coordinates; the far-corner frame keeps
    # the block in the all-positive octant.
    bp_size = NXOpen.Point3d(max_bp.X - min_bp.X, max_bp.Y - min_bp.Y, max_bp.Z - min_bp.Z)
    min_bp = _Origin
    max_bp = bp_size

    nx.display_part().Layers.WorkLayer = 15
    merlin._create_subtool(nx.prototype(component_backing))
    _chamfer_vertical_edges(nx.dynamic_block(nx.prototype(component_backing)))
    nx.display_part().Layers.WorkLayer = 1
    nx.display_part().Layers.SetState(15, NXOpen.Layer.State.Hidden)
    nx.find_or_create_reference_set(owning_backing, "BODY").AddObjectsToReferenceSet([component_backing])
    _color_non_yellow_faces(130)
    _color_face(42, _VectorZ)
    _color_face(42, _VectorZN)
    _color_chamfer_faces(211)
    component_backing.SetName("BP1")
    nx.set_attribute(nx.display_part(), "DETAIL NAME", "UPPER PUNCH BACKING PLATE")
    nx.set_attribute(nx.display_part(), "MATERIAL", "O1 GS")
    _copy_assembly_attributes(current)
    bp_shcs_orientation = drawdie._z_matrix(_VectorZ)
    _subtract_fasteners_from_block([
        nx.add_component(nx.display_part(), _shcs8mm020Path, reference_set="BODY",
                         origin=NXOpen.Point3d(o.X, o.Y, o.Z - 4 / 25.4), orientation=bp_shcs_orientation, layer=99)
        for o in (NXOpen.Point3d(min_bp.X + 1.125, min_bp.Y + 1.125, max_bp.Z),
                  NXOpen.Point3d(max_bp.X - 1.125, max_bp.Y - 1.125, max_bp.Z))])
    _create_body_reference_set()
    nx.create_auto_size_udo(nx.work_part())
    # Nothing to restore - the station's WCS is not moved. This only resets the display part (the new detail by
    # now) to absolute, as every other stage does.
    drawdie._set_wcs_to_absolute(nx.display_part())
    return component_backing


def _create_retainer(current: NXOpen.Part, owning_comp: NXOpen.Assemblies.Component, min_bp: NXOpen.Point3d,
                     max_bp: NXOpen.Point3d, station_uad: NXOpen.Part, component_retainer: _Out) -> None:
    """Merlin.CreateRetainer - the upper trim retainer into station_uad, then UPR-PROFILE subtracted."""
    nx.set_display_part(station_uad)

    block_retainer = nx.create_block(nx.add_z(min_bp, -1.25), nx.add_z(max_bp, -.24))
    # uad station - upper, so the csys goes on the block's far vertex.
    component_retainer.value = _promote_detail_block(block_retainer, "Retainer1", rebase_to_block=True,
                                                     opposite_corner=True)

    # The block runs from min_bp lowered by 1.25, so that lowered corner is the part's origin in Z.
    retainer_span = NXOpen.Point3d(max_bp.X - min_bp.X, max_bp.Y - min_bp.Y, max_bp.Z - min_bp.Z)
    min_bp = NXOpen.Point3d(0.0, 0.0, 1.25)
    max_bp = NXOpen.Point3d(retainer_span.X, retainer_span.Y, retainer_span.Z + 1.25)

    _chamfer_vertical_edges(nx.dynamic_block(nx.prototype(component_retainer.value)))
    _color_non_yellow_faces(200)
    _color_face(42, _VectorZ)
    _color_chamfer_faces(211)
    _stamp_detail(component_retainer.value, "Retainer1", "UPPER TRIM RETAINER", "4140", current)
    _subtract_fasteners_from_block(_add_corner_fasteners(nx.add_z(min_bp, -1.25), nx.add_z(max_bp, .01), _VectorZN,
                                                         max_bp.Z + .01, _defaultShcsPath, .625))
    retainer_dwl_orientation = drawdie._z_matrix(_VectorZN)
    # Dowels on CBORE; dowels and jack screws .5" in from the X faces, jack screws .25" lower in the block.
    _add_dowels_and_jack_screws(min_bp, max_bp, max_bp.Z + .01, retainer_dwl_orientation, _dwl12mm050Path, "CBORE",
                                upper_frame=True, inset_x=RetainerFastenerInsetX, jack_z_offset=RetainerJackZOffset)
    _create_body_reference_set()
    nx.create_auto_size_udo(nx.work_part())
    component_retainer.value = _finalize_detail_occurrence(component_retainer.value, current, "UPPER TRIM RETAINER")
    # Switching a component to a reference set it does not publish throws, and this is the last statement in the
    # stage - guard and print.
    if nx.has_reference_set(nx.prototype(owning_comp), "UPR-PROFILE"):
        drawdie._subtract_refset_from_dynamic_block(nx.work_part(), owning_comp, "UPR-PROFILE")
    else:
        nx.print_("Component {} does not have reference set UPR-PROFILE, skipping the retainer boolean".format(
            owning_comp.DisplayName))


def _create_punch(current: NXOpen.Part, owning_comp: NXOpen.Assemblies.Component, min_bp: NXOpen.Point3d,
                  max_bp: NXOpen.Point3d, station_uad: NXOpen.Part, punch_depth: float,
                  component_punch: _Out) -> None:
    """
    Merlin.CreatePunch - the WB trim punch into station_uad, punch_depth below the backing plate's bottom (3D 7",
    2D 3.625"), Unikix pins and SHCS, then UPR-PROFILE INTERSECTED.
    """
    nx.set_display_part(station_uad)
    block_punch = nx.create_block(nx.add_z(min_bp, -punch_depth), nx.add_z(max_bp, -.24))
    # uad station - upper, so the csys goes on the block's far vertex.
    component_punch.value = _promote_detail_block(block_punch, "Punch1", rebase_to_block=True, opposite_corner=True)

    # The lowered corner is the part's origin in Z - min_bp itself sits punch_depth above it.
    punch_span = NXOpen.Point3d(max_bp.X - min_bp.X, max_bp.Y - min_bp.Y, max_bp.Z - min_bp.Z)
    min_bp = NXOpen.Point3d(0.0, 0.0, punch_depth)
    max_bp = NXOpen.Point3d(punch_span.X, punch_span.Y, punch_span.Z + punch_depth)

    _color_non_yellow_faces(60)
    _color_face(42, _VectorZ)
    _color_chamfer_faces(211)
    _stamp_detail(component_punch.value, "Punch1", "UPPER WB TRIM PUNCH", "FILL IN", current)
    punch_center_x = (min_bp.X + max_bp.X) / 2
    punch_center_y = (min_bp.Y + max_bp.Y) / 2
    punch_top_z = max_bp.Z - .24
    unikix_orientation = drawdie._z_matrix(_VectorZ)
    for pin_origin in (NXOpen.Point3d(punch_center_x, punch_center_y - .5, punch_top_z),
                       NXOpen.Point3d(punch_center_x, punch_center_y + .5, punch_top_z)):
        _drop_and_subtract(_unikixPinsPath, pin_origin, unikix_orientation, "SUB_TOOL", "Empty", layer=99)
    # .01" down toward the block's centre from .25 above the pin plane.
    punch_shcs_z = punch_top_z + .25 - .01
    for shcs_origin in (NXOpen.Point3d(punch_center_x, punch_center_y - 1, punch_shcs_z),
                        NXOpen.Point3d(punch_center_x, punch_center_y + 1, punch_shcs_z)):
        _drop_and_subtract(_shcs10mm020Path, shcs_origin, unikix_orientation, "SHORT-TAP")
    punch_bottom_z = min_bp.Z - punch_depth
    # 10 mm up from the bottom face, on layer 98 and left out of the punch's BODY reference set.
    punch_shcs_8mm = _drop_and_subtract(_shcs8mm065Path,
                                        NXOpen.Point3d(punch_center_x, punch_center_y, punch_bottom_z + 10 / 25.4),
                                        drawdie._z_matrix(_VectorZN), "SHORT-TAP", layer=98)
    _create_body_reference_set(punch_shcs_8mm)
    nx.create_auto_size_udo(nx.work_part())
    component_punch.value = _finalize_detail_occurrence(component_punch.value, current, "UPPER WB TRIM PUNCH")
    # The restore to BODY goes in a finally because the switch happens before the intersect.
    if nx.has_reference_set(nx.prototype(owning_comp), "UPR-PROFILE"):
        try:
            nx.set_reference_set(owning_comp, "UPR-PROFILE")
            nx.create_boolean(nx.dynamic_block(nx.work_part()).GetBodies()[0],
                              nx.create_linked_body(owning_comp).GetBodies(),
                              NXOpen.Features.Feature.BooleanType.Intersect)
        finally:
            nx.set_reference_set(owning_comp, "BODY")
    else:
        nx.print_("Component {} does not have reference set UPR-PROFILE, skipping the punch intersect".format(
            owning_comp.DisplayName))


def _create_window(current: NXOpen.Part, window_min: NXOpen.Point3d, window_max: NXOpen.Point3d,
                   station_upd: NXOpen.Part, add_extra_shcs: bool = False) -> NXOpen.Assemblies.Component:
    """
    Merlin.CreateWindow - the window into station_upd, built upside down (flipZ), corner SHCS and blind-ream dowels;
    add_extra_shcs drops two extra SHCS at the dowel locations offset +/-1" in Y.
    """
    nx.set_display_part(station_upd)
    block_window = nx.create_block(window_min, window_max)
    # The window part is built upside down (a roll about X).
    component_window = _promote_detail_block(block_window, "Window1", rebase_to_block=True, flip_z=True)

    # The station's top face is now part Z 0 and the station's +Z is part -Z, so the fasteners go in at window_min.Z
    # pointing +Z, and the station's -Y edge is part Y = width.
    window_max = NXOpen.Point3d(window_max.X - window_min.X, window_max.Y - window_min.Y,
                                window_max.Z - window_min.Z)
    window_min = _Origin

    _chamfer_vertical_edges(nx.dynamic_block(nx.prototype(component_window)))
    body = trimpad._single_solid_body_on_layer1(nx.display_part())
    _color_non_yellow_faces(136)
    _color_face(42, _VectorZ)
    _color_face(42, _VectorZN)
    _color_chamfer_faces(211)
    # The "top-window" name is cosmetic, so a missing face must not throw out of the window stage. The station's top
    # face, which is part -Z in the flipped frame.
    face = nx.planar_face_with_normal_or_null(body, _VectorZN)
    if face is None:
        nx.print_('Could not find the top planar face to name "top-window" in {}'.format(nx.display_part().Leaf))
    else:
        face.SetName("top-window")
    _stamp_detail(component_window, "Window1", "WINDOW", "4140 PH", current)
    _subtract_fasteners_from_block(_add_corner_fasteners(window_min, window_max, _VectorZ, window_min.Z,
                                                         _shcs12mm030Path, .625))
    window_center_y = (window_min.Y + window_max.Y) / 2
    window_dwl_orientation = drawdie._z_matrix(_VectorZ)
    _add_dowels_and_jack_screws(window_min, window_max, window_min.Z, window_dwl_orientation, _dwl12mm025Path,
                                "CBORE", upper_frame=False, flipped_frame=True)
    if add_extra_shcs:
        # Two extra SHCS at the dowel locations, one shifted +1" in Y, the other -1", on the same physical spots as
        # before the flip (the min/max ends swap; Y counts from the station's +Y edge in both frames).
        _drop_and_subtract(_shcs12mm030Path, NXOpen.Point3d(window_max.X - .625, window_center_y + 1, window_min.Z),
                           window_dwl_orientation, "CBORE")
        _drop_and_subtract(_shcs12mm030Path, NXOpen.Point3d(window_min.X + .625, window_center_y - 1, window_min.Z),
                           window_dwl_orientation, "CBORE")
    _create_body_reference_set()
    nx.create_auto_size_udo(nx.work_part())
    return component_window


def _intersect_temp_block_with_upper(current: NXOpen.Part, station_lad: NXOpen.Part,
                                     owning_comp: NXOpen.Assemblies.Component,
                                     block_temp: NXOpen.Features.Feature) -> Optional[nx.Box3d]:
    """
    Secondary Trim Station (Python-only): wave-links the slug component's UPR-3D bodies into station_lad and
    intersects the temp block (target) with them (tool). Done from the -000 with station_lad as the work component,
    the way the other stages link across the assembly. The component's reference set is put back afterwards.
    Returns the intersected body's box in station_lad's coordinates (the frame the lower trim steel is built in), or
    None when the component has no UPR-3D or NX refuses the intersect - both print and leave the temp block whole.
    """
    if not nx.has_reference_set(nx.prototype(owning_comp), UpperZRefset):
        nx.print_("Component {} does not have reference set {}, skipping the temp block intersect".format(
            owning_comp.DisplayName, UpperZRefset))
        return None

    nx.set_display_part(current)
    nx.set_work_component(nx.first_occurrence_in(station_lad, current))
    previous_refset = owning_comp.ReferenceSet
    nx.set_reference_set(owning_comp, UpperZRefset)
    try:
        link = nx.create_linked_body(owning_comp)
        intersect = nx.create_boolean(block_temp.GetBodies()[0], link.GetBodies(),
                                      NXOpen.Features.Feature.BooleanType.Intersect)
        # The prototype body in station_lad, so the box is in station_lad's coordinates.
        return nx.combine_boxes(nx.body_box(body) for body in intersect.GetBodies())
    except NXOpen.NXException as ex:
        nx.print_("Could not intersect {} with the {} of {}: {}".format(
            TempLowerTrimSteelName, UpperZRefset, owning_comp.DisplayName, ex))
        return None
    finally:
        if previous_refset != UpperZRefset:
            nx.set_reference_set(owning_comp, previous_refset)


def _link_upper_and_lower_into_station(current: NXOpen.Part, station_lad: NXOpen.Part,
                                       owning_comp: NXOpen.Assemblies.Component) -> Optional[NXOpen.Body]:
    """
    Secondary Trim Station (Python-only): links the solid bodies of the slug component's UPR-3D and LWR-3D into
    station_lad with Associative off, so they come in as plain (brep) bodies, then intersects them - the UPR-3D body
    is the target and the LWR-3D bodies the tools. Done from the -000 with station_lad as the work component. A
    component shows one reference set at a time, so it is put on Entire Part while the members of each set are
    picked out and linked, then it goes back to the reference set it had. Returns the intersected body, or None
    (printed) when either set is missing or empty, or NX refuses the intersect.
    """
    proto = nx.prototype(owning_comp)
    wanted: Dict[str, set] = {}
    for name in (UpperZRefset, LowerZRefset):
        refset = nx.find_reference_set_or_null(proto, name)
        members = set() if refset is None else {
            m.Tag for m in refset.AskAllDirectMembers() if isinstance(m, NXOpen.Body) and m.IsSolidBody}
        if not members:
            nx.print_("Component {} has no {} solid bodies, skipping the {} / {} intersect".format(
                owning_comp.DisplayName, name, UpperZRefset, LowerZRefset))
            return None
        wanted[name] = members

    nx.set_display_part(current)
    nx.set_work_component(nx.first_occurrence_in(station_lad, current))
    previous_refset = owning_comp.ReferenceSet
    nx.set_reference_set(owning_comp, nx.RefsetEntirePart)
    try:
        # Each occurrence's prototype body tag, to match against the reference set members.
        occurrences = [(b, b.Prototype.Tag) for b in nx.solid_body_members(owning_comp) if b.Prototype is not None]
        upper = _link_bodies_as_breps([b for b, tag in occurrences if tag in wanted[UpperZRefset]])
        lower = _link_bodies_as_breps([b for b, tag in occurrences if tag in wanted[LowerZRefset]])
    finally:
        if previous_refset != nx.RefsetEntirePart:
            nx.set_reference_set(owning_comp, previous_refset)

    if not upper or not lower:
        nx.print_("Component {}: the {} / {} link brought in no body, skipping the intersect".format(
            owning_comp.DisplayName, UpperZRefset, LowerZRefset))
        return None
    if len(upper) > 1:
        nx.info("Component {}: {} has {} solid bodies - intersecting the first with {}".format(
            owning_comp.DisplayName, UpperZRefset, len(upper), LowerZRefset))

    try:
        intersect = nx.create_boolean(upper[0], lower, NXOpen.Features.Feature.BooleanType.Intersect)
        return intersect.GetBodies()[0]
    except NXOpen.NXException as ex:
        nx.print_("Could not intersect the {} and {} of {}: {}".format(
            UpperZRefset, LowerZRefset, owning_comp.DisplayName, ex))
        return None


def _link_bodies_as_breps(bodies: Sequence[NXOpen.Body]) -> List[NXOpen.Body]:
    """
    Wave-links bodies (occurrences) into the work part with Associative off, and returns the new solid bodies. A
    non-associative link leaves no feature to ask, so the new bodies are the ones the work part did not have before.
    """
    if not bodies:
        return []
    part = nx.work_part()
    before = {b.Tag for b in part.Bodies}
    builder = part.BaseFeatures.CreateWaveLinkBuilder(None)
    try:
        extract = builder.ExtractFaceBuilder
        extract.ParentPart = NXOpen.Features.ExtractFaceBuilder.ParentPartType.OtherPart
        builder.Type = NXOpen.Features.WaveLinkBuilder.Types.BodyLink
        extract.Associative = False
        extract.FeatureOption = NXOpen.Features.ExtractFaceBuilder.FeatureOptionType.OneFeatureForAllBodies
        rule = part.ScRuleFactory.CreateRuleBodyDumb(list(bodies), False)
        extract.ExtractBodyCollector.ReplaceRules([rule], False)
        extract.FixAtCurrentTimestamp = False
        builder.Commit()
    finally:
        builder.Destroy()
    return [b for b in part.Bodies if b.Tag not in before and b.IsSolidBody]


def _build_temp_lower_blocks(current: NXOpen.Part, box: nx.Box3d, owning_comp: NXOpen.Assemblies.Component,
                             station_lad: NXOpen.Part, min_z: float, max_z: float, temp: _TempGeometry
                             ) -> Tuple[Optional[nx.Box3d], Optional[nx.Box3d], Optional[nx.Box3d]]:
    """
    Secondary Trim Station (Python-only): two same-size blocks where the lower trim steel would go (slug box +2.5",
    1/8" up, min_z..max_z), both in station_lad's BODY reference set until the run deletes them, built with the
    slug's component on LWR-3D (put back after):
      - TempLowerTrimSteelName, intersected with the component's UPR-3D (associative link);
      - TempLowerTrimSteelName2, intersected with the UPR-3D x LWR-3D brep intersect.
    Returns (the first intersect's box, the second's box in station_lad's coordinates, the second's box in the
    -000's); each is None when its intersect did not happen (printed). Every feature and body this adds to
    station_lad goes into temp, even when it throws part-way.
    """
    nx.set_display_part(station_lad)
    features_before = {f.Tag for f in station_lad.Features.GetFeatures()}
    bodies_before = {b.Tag for b in station_lad.Bodies}
    cx = (box.MinX + box.MaxX) / 2
    cy = (box.MinY + box.MaxY) / 2
    x = nx.round_to_125(box.MaxX - box.MinX + 2.5)
    y = nx.round_to_125(box.MaxY - box.MinY + 2.5)
    temp_min = NXOpen.Point3d(cx - x / 2, cy - y / 2, min_z)
    temp_max = NXOpen.Point3d(cx + x / 2, cy + y / 2, max_z)
    nx.display_part().Layers.WorkLayer = 1

    first_box: Optional[nx.Box3d] = None
    station_box: Optional[nx.Box3d] = None
    assembly_box: Optional[nx.Box3d] = None
    original_refset: Optional[str] = None
    if nx.has_reference_set(nx.prototype(owning_comp), LowerZRefset):
        original_refset = owning_comp.ReferenceSet
        nx.set_reference_set(owning_comp, LowerZRefset)
    try:
        block_temp = nx.create_block(temp_min, temp_max)
        block_temp.SetName(TempLowerTrimSteelName)
        nx.find_or_create_reference_set(station_lad, "BODY").AddObjectsToReferenceSet(block_temp.GetBodies())
        first_box = _intersect_temp_block_with_upper(current, station_lad, owning_comp, block_temp)
        nx.set_display_part(station_lad)
        nx.display_part().Layers.WorkLayer = 1

        block_temp2 = nx.create_block(temp_min, temp_max)
        block_temp2.SetName(TempLowerTrimSteelName2)
        nx.find_or_create_reference_set(station_lad, "BODY").AddObjectsToReferenceSet(block_temp2.GetBodies())
        upper_lower = _link_upper_and_lower_into_station(current, station_lad, owning_comp)
        # The second temp block (target) intersected with that result (tool). Both are bodies of station_lad,
        # which is still the work part.
        if upper_lower is not None:
            try:
                intersect = nx.create_boolean(block_temp2.GetBodies()[0], [upper_lower],
                                              NXOpen.Features.Feature.BooleanType.Intersect)
                bodies = list(intersect.GetBodies())
                station_box = nx.combine_boxes(nx.body_box(b) for b in bodies)
                assembly_box = _station_box_in_assembly(current, station_lad, station_box)
            except NXOpen.NXException as ex:
                nx.print_("Could not intersect {} with the {} / {} result of {}: {}".format(
                    TempLowerTrimSteelName2, UpperZRefset, LowerZRefset, owning_comp.DisplayName, ex))
    finally:
        if original_refset is not None and original_refset != LowerZRefset:
            nx.set_reference_set(owning_comp, original_refset)
        temp.features.extend(f for f in station_lad.Features.GetFeatures() if f.Tag not in features_before)
        temp.body_tags.update(b.Tag for b in station_lad.Bodies if b.Tag not in bodies_before)

    return first_box, station_box, assembly_box


def _delete_temp_geometry(temp: _TempGeometry) -> None:
    """
    Deletes what _build_temp_lower_blocks left in lad02: its features first (a block takes its intersect with it),
    then any of its bodies still there - the non-associative links have no feature to delete them by.
    """
    if not temp.features and not temp.body_tags:
        return
    nx.prompt("Deleting the temp lower trim steel blocks")
    if temp.features:
        with nx.do_update("Delete temp lower trim steel"):
            nx.session_.UpdateManager.AddObjectsToDeleteList(list(temp.features))
    leftovers = [b for b in temp.part.Bodies if b.Tag in temp.body_tags]
    if leftovers:
        with nx.do_update("Delete temp lower trim steel bodies"):
            nx.session_.UpdateManager.AddObjectsToDeleteList(leftovers)
    nx.info("Deleted {} temp feature(s) and {} leftover bodies from {}".format(
        len(temp.features), len(leftovers), temp.part.Leaf))


def _station_box_in_assembly(current: NXOpen.Part, station: NXOpen.Part, station_box: nx.Box3d) -> nx.Box3d:
    """
    station_box (in station's coordinates) in current's (the -000's): its eight corners mapped WORK -> ROOT with
    station's occurrence as the work component - DrawDie._map_box_to_station the other way round.
    """
    nx.set_display_part(current)
    nx.set_work_component(nx.first_occurrence_in(station, current))
    corners = [list(nx.ufsession_.Csys.MapPoint(drawdie._UF_CSYS_WORK_COORDS, [float(px), float(py), float(pz)],
                                                drawdie._UF_CSYS_ROOT_COORDS))
               for px in (station_box.MinX, station_box.MaxX)
               for py in (station_box.MinY, station_box.MaxY)
               for pz in (station_box.MinZ, station_box.MaxZ)]
    return nx.Box3d(min(c[0] for c in corners), min(c[1] for c in corners), min(c[2] for c in corners),
                    max(c[0] for c in corners), max(c[1] for c in corners), max(c[2] for c in corners))


def _create_lower_trim_steel(current: NXOpen.Part, box: nx.Box3d, owning_comp: NXOpen.Assemblies.Component,
                             material_thickness: float, window_min: NXOpen.Point3d, station_lad: NXOpen.Part,
                             component_lower_trim_steel: _Out, override_min_z: Optional[float] = None,
                             override_max_z: Optional[float] = None, add_extra_shcs: bool = False) -> None:
    """
    Merlin.CreateLowerTrimSteel - the lower blank steel into station_lad, corner SHCS and dowels, then LWR-PROFILE
    subtracted. (The Secondary Trim Station's temp blocks are built ahead of it - _build_temp_lower_blocks.)
    """
    nx.set_display_part(station_lad)
    lts_cx = (box.MinX + box.MaxX) / 2
    lts_cy = (box.MinY + box.MaxY) / 2
    lts_x = nx.round_to_125(box.MaxX - box.MinX + 2.5)
    lts_y = nx.round_to_125(box.MaxY - box.MinY + 2.5)
    lts_min = NXOpen.Point3d(lts_cx - lts_x / 2, lts_cy - lts_y / 2,
                             override_min_z if override_min_z is not None else window_min.Z - 1.969)
    lts_max = NXOpen.Point3d(lts_cx + lts_x / 2, lts_cy + lts_y / 2,
                             override_max_z if override_max_z is not None else window_min.Z - material_thickness)
    nx.display_part().Layers.WorkLayer = 1
    block_lower_trim_steel = nx.create_block(lts_min, lts_max)
    component_lower_trim_steel.value = _promote_detail_block(block_lower_trim_steel, "lts", hide_subtool_layer=False,
                                                             rebase_to_block=True)

    # Everything below places inside the new part, and the block's lts_min corner is now that part's origin.
    lts_max = NXOpen.Point3d(lts_max.X - lts_min.X, lts_max.Y - lts_min.Y, lts_max.Z - lts_min.Z)
    lts_min = _Origin

    _chamfer_vertical_edges(nx.dynamic_block(nx.prototype(component_lower_trim_steel.value)))
    _color_non_yellow_faces(11)
    _color_face(42, _VectorZN)
    _color_face(42, _VectorZ)
    _stamp_detail(component_lower_trim_steel.value, "Lower Blank Steel", "LOWER BLANK STEEL", "FILL IN", current)
    _subtract_fasteners_from_block(_add_corner_fasteners(lts_min, lts_max, _VectorZ, lts_min.Z, _defaultShcsPath,
                                                         .625))
    lts_center_y = (lts_min.Y + lts_max.Y) / 2
    lts_dwl_orientation = drawdie._z_matrix(_VectorZ)
    _add_dowels_and_jack_screws(lts_min, lts_max, lts_min.Z, lts_dwl_orientation, _dwl12mm050Path, "CBORE",
                                upper_frame=False)

    if add_extra_shcs:
        # Two extra SHCS at the dowel locations, one shifted +1" in Y, the other -1".
        _drop_and_subtract(_defaultShcsPath, NXOpen.Point3d(lts_min.X + .625, lts_center_y + 1, lts_min.Z),
                           lts_dwl_orientation, "CBORE")
        _drop_and_subtract(_defaultShcsPath, NXOpen.Point3d(lts_max.X - .625, lts_center_y - 1, lts_min.Z),
                           lts_dwl_orientation, "CBORE")
    _create_body_reference_set()
    nx.create_auto_size_udo(nx.work_part())
    nx.work_part().Layers.SetState(15, NXOpen.Layer.State.Hidden)

    _color_chamfer_faces(211)

    component_lower_trim_steel.value = _finalize_detail_occurrence(component_lower_trim_steel.value, current,
                                                                   "LOWER BLANK STEEL")
    # Switching a component to a reference set it does not publish throws, and this is the last statement in the
    # stage - guard and print.
    if nx.has_reference_set(nx.prototype(owning_comp), "LWR-PROFILE"):
        drawdie._subtract_refset_from_dynamic_block(nx.work_part(), owning_comp, "LWR-PROFILE")
    else:
        nx.print_("Component {} does not have reference set LWR-PROFILE, skipping the lower trim steel boolean".format(
            owning_comp.DisplayName))


# ---------------------------------------------------------------------------------------------------
# Detail scaffolding
# ---------------------------------------------------------------------------------------------------

def _promote_detail_block(block: NXOpen.Features.Block, name: str, hide_subtool_layer: bool = True,
                          rebase_to_block: bool = False, opposite_corner: bool = False,
                          flip_z: bool = False) -> NXOpen.Assemblies.Component:
    """
    Merlin.PromoteDetailBlock - names the block DYNAMIC BLOCK, promotes it (CreateCtsComponent), optionally re-bases
    the new part onto it, station expressions, SUBTOOL on layer 15, and the new component into the owning part's
    BODY reference set.
    """
    block.SetName("DYNAMIC BLOCK")
    owning = nx.display_part()
    component = merlin._create_cts_component(block, name)
    if rebase_to_block:
        if flip_z:
            _rebase_block_flip_z(component, owning)
        else:
            drawdie._rebase_block_to_part_origin(component, owning, opposite_corner=opposite_corner)
    nx.setup_station_expressions(nx.work_part())
    nx.display_part().Layers.WorkLayer = 15
    merlin._create_subtool(nx.prototype(component))
    nx.display_part().Layers.WorkLayer = 1
    if hide_subtool_layer:
        nx.display_part().Layers.SetState(15, NXOpen.Layer.State.Hidden)
    nx.find_or_create_reference_set(owning, "BODY").AddObjectsToReferenceSet([component])
    return component


def _rebase_block_flip_z(component: NXOpen.Assemblies.Component, parent: NXOpen.Part) -> None:
    """
    Merlin.RebaseBlockToPartOrigin(component, parent, flipZ: true) - the part turned upside down: a 180 degree roll
    about the block's X, so it reads +X / -Y / -Z of the block, with its csys on the block's top face at the far Y
    edge. The block still fills X 0..L, Y 0..W, Z 0..H. Rotate, then translate; leaves the new detail as the display
    and work part.
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
        # The block's own origin and orientation, read in assembly coordinates.
        block_origin = builder.Origin
        x_axis, y_axis = builder.GetOrientation()
        block_orientation = nx.matrix_from_axes(x_axis, y_axis)

        width = width_exp.Value
        height = height_exp.Value

        # The corner on the top face at the far Y edge, in assembly coordinates - the component moves here - plus the
        # +X/-Y (so -Z) orientation of a roll about X.
        block_origin = nx.add_along(nx.add_along(block_origin, nx.axis_y(block_orientation), width),
                                    nx.axis_z(block_orientation), height)
        block_orientation = nx.matrix_from_axes(nx.axis_x(block_orientation), nx.negate(nx.axis_y(block_orientation)))

        # In that frame the block's own corner sits at (0, W, H) with its local axes reading +X / -Y / -Z.
        builder.SetOrientation(_VectorX, _VectorYN)
        builder.SetOriginAndLengths(NXOpen.Point3d(0.0, width, height), length_exp.RightHandSide,
                                    width_exp.RightHandSide, height_exp.RightHandSide)
        builder.Commit()
    finally:
        builder.Destroy()

    # The component move needs its owning assembly as the work part...
    nx.set_display_part(parent)
    nx.set_work_part(parent)

    # Rotate first, while the geometry is still on the origin and therefore spins in place...
    parent.ComponentAssembly.MoveComponent(component, NXOpen.Vector3d(0.0, 0.0, 0.0), block_orientation)
    # ...then carry it out to where the block was.
    parent.ComponentAssembly.MoveComponent(
        component, NXOpen.Vector3d(block_origin.X, block_origin.Y, block_origin.Z), nx.identity_matrix())

    # ...but the caller picks up with the new detail as the display and work part.
    nx.set_display_part(new_part)
    nx.set_work_part(new_part)


def _stamp_detail(component: NXOpen.Assemblies.Component, name: str, detail_name: str, material: str,
                  current: NXOpen.Part) -> None:
    """Merlin.StampDetail - names the component, DETAIL NAME / MATERIAL on the display part, assembly attributes."""
    component.SetName(name)
    nx.set_attribute(nx.display_part(), "DETAIL NAME", detail_name)
    nx.set_attribute(nx.display_part(), "MATERIAL", material)
    _copy_assembly_attributes(current)


def _finalize_detail_occurrence(component: NXOpen.Assemblies.Component, current: NXOpen.Part,
                                detail_name: str) -> NXOpen.Assemblies.Component:
    """
    Merlin.FinalizeDetailOccurrence - back to current, the detail's occurrence there renamed detail_name and made the
    work component.
    """
    nx.set_display_part(current)
    component = _first_occurrence_of(component, nx.display_part())
    component.SetName(detail_name)
    nx.set_work_component(component)
    return component


def _copy_assembly_attributes(source: NXOpen.Part) -> None:
    """Merlin.CopyAssemblyAttributes - GM CSPC and GM TOOL NUMBER from source onto the display part, if present."""
    for name in ("GM CSPC", "GM TOOL NUMBER"):
        try:
            nx.set_attribute(nx.display_part(), name, nx.get_attribute(source, name))
        except Exception:
            pass


def _create_body_reference_set(*exclude: NXOpen.Assemblies.Component) -> None:
    """
    Merlin.CreateBodyReferenceSet - BODY on the display part: the dynamic block's bodies plus every root child, each
    switched to BODY. Children in exclude are left out and keep their own reference set. Part_.FindOrCreateReferenceSet
    does not print, unlike Merlin.FindOrCreateReferenceSet.
    """
    display = nx.display_part()
    refset = nx.find_reference_set_or_null(display, "BODY")
    if refset is None:
        refset = display.CreateReferenceSet()
        refset.SetName("BODY")
    refset.AddObjectsToReferenceSet(list(nx.dynamic_block(display).GetBodies()))
    root = nx.root_component(display)
    if root is not None:
        for child in root.GetChildren():
            if any(skip.Tag == child.Tag for skip in exclude):
                continue
            nx.set_reference_set(child, "BODY")
            refset.AddObjectsToReferenceSet([child])


# ---------------------------------------------------------------------------------------------------
# Fasteners
# ---------------------------------------------------------------------------------------------------

def _add_corner_fasteners(block_min: NXOpen.Point3d, block_max: NXOpen.Point3d, normal_z: NXOpen.Vector3d, z: float,
                          path: str = _defaultShcsPath, corner_offset: float = 1.125,
                          z_adjust: float = 0.0) -> List[NXOpen.Assemblies.Component]:
    """Merlin.AddCornerFasteners - 4 fasteners corner_offset in from each corner at z, BODY, layer 99."""
    orientation = drawdie._z_matrix(normal_z)
    fasteners: List[NXOpen.Assemblies.Component] = []
    for x, y in ((block_min.X + corner_offset, block_min.Y + corner_offset),
                 (block_max.X - corner_offset, block_min.Y + corner_offset),
                 (block_max.X - corner_offset, block_max.Y - corner_offset),
                 (block_min.X + corner_offset, block_max.Y - corner_offset)):
        fasteners.append(nx.add_component(nx.display_part(), path, reference_set="BODY",
                                          origin=NXOpen.Point3d(x, y, z + z_adjust), orientation=orientation,
                                          layer=99))
    return fasteners


def _subtract_fasteners_from_block(fasteners: Iterable[NXOpen.Assemblies.Component]) -> None:
    """
    Merlin.SubtractFastenersFromBlock - each fastener's CBORE linked in and subtracted from the display part's dynamic
    block (670030 printed and skipped), stamped, then back on BODY. One catch around the lot, as in the C#.
    """
    try:
        for f in fasteners:
            nx.set_reference_set(f, "CBORE")
            link = nx.create_linked_body(f)
            try:
                nx.subtract(nx.dynamic_block(nx.display_part()).GetBodies()[0], link.GetBodies())
                _stamp_fastener_subtract(f, "CBORE")
            except NXOpen.NXException as ex:
                if ex.ErrorCode != _ErrorCouldNotSubtract:
                    raise
                nx.print_("Could not subtract {} from {}".format(f.DisplayName, f.OwningPart.Leaf))
            nx.set_reference_set(f, "BODY")
    except Exception as ex:
        nx.print_exception(ex)


def _add_dowels_and_jack_screws(min_point: NXOpen.Point3d, max_point: NXOpen.Point3d, z: float,
                                orientation: NXOpen.Matrix3x3, dowel_path: str, dowel_refset: str, upper_frame: bool,
                                inset_x: float = TrimDetailFastenerInsetX, jack_z_offset: float = 0.0,
                                flipped_frame: bool = False) -> None:
    """
    Merlin.AddDowelsAndJackScrews - 2 dowels, 2x 12mm-jck-screw (CBORE) and 2x 12mm-jck-screw-tsg (CBORE_BLIND), laid
    out as seen in the -000 and mirrored into the part's frame (upper_frame: through the block centre; flipped_frame:
    Y only). Each one dropped and subtracted on its own, so one failure does not cost the rest.
    """
    length = max_point.X - min_point.X
    width = max_point.Y - min_point.Y

    def at(physical: NXOpen.Point3d) -> NXOpen.Point3d:
        if flipped_frame:
            return NXOpen.Point3d(min_point.X + physical.X, max_point.Y - physical.Y, z + physical.Z)
        if upper_frame:
            return NXOpen.Point3d(max_point.X - physical.X, max_point.Y - physical.Y, z + physical.Z)
        return NXOpen.Point3d(min_point.X + physical.X, min_point.Y + physical.Y, z + physical.Z)

    default_inset = abs(inset_x - TrimDetailFastenerInsetX) < 1e-9

    tsg_first = NXOpen.Point3d(length - inset_x, TrimDetailTsgJackInsetY, jack_z_offset)
    tsg_target = NXOpen.Point3d(inset_x, width - TrimDetailTsgJackInsetY, jack_z_offset)
    # Snapped in the physical frame, so the 1" grid and the -X shift mean the same thing on every detail.
    tsg_snapped = drawdie._snap_to_inch_grid_from(tsg_first, tsg_target)
    if default_inset:
        tsg_second = NXOpen.Point3d(tsg_snapped.X - TrimDetailTsgJackShiftX, tsg_snapped.Y, tsg_snapped.Z)
    else:
        tsg_second = NXOpen.Point3d(inset_x, tsg_snapped.Y, tsg_snapped.Z)

    placements = (
        (dowel_path, NXOpen.Point3d(inset_x, TrimDetailDowelInsetNegY, 0.0), dowel_refset),
        (dowel_path, NXOpen.Point3d(length - inset_x, width - TrimDetailDowelInsetPosY, 0.0), dowel_refset),
        (_jck12mmScrewPath, NXOpen.Point3d(inset_x, TrimDetailJackInsetNegY, jack_z_offset), "CBORE"),
        (_jck12mmScrewPath, NXOpen.Point3d(length - inset_x, width - TrimDetailJackInsetPosY, jack_z_offset),
         "CBORE"),
        (_jck12mmScrewTsgPath, tsg_first, "CBORE_BLIND"),
        (_jck12mmScrewTsgPath, tsg_second, "CBORE_BLIND"),
    )

    for path, physical, refset in placements:
        try:
            _drop_and_subtract(path, at(physical), orientation, refset)
        except Exception as ex:
            nx.print_("Could not place {} ({}) in {}".format(os.path.splitext(os.path.basename(path))[0], refset,
                                                             nx.display_part().Leaf))
            nx.print_exception(ex)


def _drop_and_subtract(path: str, origin: NXOpen.Point3d, orientation: Optional[NXOpen.Matrix3x3],
                       subtract_refset: str, restore_refset: str = "BODY",
                       layer: int = 99) -> NXOpen.Assemblies.Component:
    """
    Merlin.DropAndSubtract - drops a library part at origin (BODY refset, layer) into the display part, subtracts its
    subtract_refset from the dynamic block, restores restore_refset, and stamps a fastener's subtract attribute.
    """
    display = nx.display_part()
    component = nx.add_component(display, path, "BODY", None, origin, orientation, layer)
    drawdie._subtract_refset_from_dynamic_block(display, component, subtract_refset, restore_refset)

    # The subtract prints and skips a part without the reference set - nothing to stamp then.
    if nx.has_reference_set(nx.prototype(component), subtract_refset):
        _stamp_fastener_subtract(component, subtract_refset)

    return component


def _stamp_fastener_subtract(fastener: NXOpen.Assemblies.Component, subtract_refset: str) -> None:
    """
    Merlin.StampFastenerSubtract - the subtract instance attribute on a fastener (BasePart.__IsFastener: -dwl-,
    EndsWith -jck-screw, EndsWith -jck-screw-tsg, -shcs-); anything else is left alone.
    """
    leaf = nx.prototype(fastener).Leaf.lower()

    if not ("-dwl-" in leaf or leaf.endswith("-jck-screw") or leaf.endswith("-jck-screw-tsg") or "-shcs-" in leaf):
        return

    fastener.SetInstanceUserAttribute("subtract", -1, subtract_refset, NXOpen.Update.Option.Now)


def _subtract_from_dynamic_block(part: NXOpen.Part, component: NXOpen.Assemblies.Component) -> None:
    """Part.__SubtractFromDynamicBlock - the component's current reference set linked in and subtracted."""
    link = nx.create_linked_body(component)
    nx.subtract(nx.dynamic_block(part).GetBodies()[0], link.GetBodies())


# ---------------------------------------------------------------------------------------------------
# Colors / chamfers
# ---------------------------------------------------------------------------------------------------

def _chamfer_vertical_edges(block: NXOpen.Features.Block) -> None:
    """Merlin.ChamferVerticalEdges(block) - .25" on every vertical edge (CastTrimPad's ChamferBuilder version)."""
    trimpad._chamfer_vertical_edges(block, TrimDetailChamfer)


def _color_non_yellow_faces(color: int) -> None:
    """Merlin.ColorNonYellowFaces - colors the display part's single layer-1 solid body (every face, despite the name)."""
    nx.set_color(trimpad._single_solid_body_on_layer1(nx.display_part()), color)


def _color_face(color: int, normal: NXOpen.Vector3d) -> None:
    """Merlin.ColorFace - the layer-1 body's planar face with that normal, if any (no redisplay, as in the C#)."""
    face = nx.planar_face_with_normal_or_null(trimpad._single_solid_body_on_layer1(nx.display_part()), normal)
    if face is not None:
        face.Color = color


def _color_chamfer_faces(color: int) -> None:
    """foreach (var face in disp.Features.OfType<Chamfer>().SelectMany(c => c.GetFaces())) face.__Color(color)"""
    for feature in nx.display_part().Features.GetFeatures():
        if isinstance(feature, NXOpen.Features.Chamfer):
            for face in feature.GetFaces():
                nx.set_color(face, color)


# ---------------------------------------------------------------------------------------------------
# Taper
# ---------------------------------------------------------------------------------------------------

def _edge_ends(edge: NXOpen.Edge) -> Tuple[NXOpen.Point3d, NXOpen.Point3d]:
    """Edge_.StartPoint / EndPoint (the two vertices)."""
    start, end = edge.GetVertices()
    return start, end


def _is_horizontal(edge: NXOpen.Edge) -> bool:
    """Edge_.IsHorizontal - both vertices at the same Z (.001 tolerance)."""
    start, end = _edge_ends(edge)
    return nx.doubles_equal(start.Z, end.Z)


def _find_taper_edge(part: NXOpen.Part) -> Optional[NXOpen.Edge]:
    """
    The taper stage's edge search: in the first LINKED_BODY whose wave source lives in a part whose leaf contains
    "layout", a vertical edge's higher Z, then the horizontal edge starting at exactly that Z.
    """
    for feature in part.Features.GetFeatures():
        if not isinstance(feature, NXOpen.Features.ExtractFace):
            continue
        if feature.FeatureType != "LINKED_BODY":
            continue
        source = nx.ufsession_.Wave.AskLinkSource(feature.Tag, True)
        temp = nx.tagged_object(source)
        if not isinstance(temp, NXOpen.Body):
            # The C#'s hard (Body) cast.
            raise TypeError("Unable to cast object of type '{}' to type 'NXOpen.Body'.".format(type(temp).__name__))
        if "layout" not in temp.OwningPart.Leaf.lower():
            continue
        edges = feature.GetEdges()
        vertical_edge = next((e for e in edges if not _is_horizontal(e)), None)
        if vertical_edge is None:
            continue
        start, end = _edge_ends(vertical_edge)
        zlevel = max(start.Z, end.Z)
        edge11 = next((e for e in edges if _is_horizontal(e) and _edge_ends(e)[0].Z == zlevel), None)
        if edge11 is None:
            continue
        return edge11
    return None


def _create_taper(work_part: NXOpen.Part, body1: NXOpen.Body, tangent_edge: NXOpen.Edge) -> NXOpen.Features.Feature:
    """
    Part.__CreateTaper (Globals.cs) - a recorded-journal extrude: the tangent chain from tangent_edge, -Z, 10 mm to
    60 mm, a 2 degree simple draft from the start and a 0..2 offset, subtracted from body1. work_part must be the
    work part. The builder is Any: the stubs do not cover ExtrudeBuilder's draft / offset / smart-volume members.
    """
    if work_part.Tag != nx.work_part().Tag:
        raise RuntimeError("{} is not the work part".format(work_part.Leaf))
    part: Any = nx.session_.Parts.Work
    extrude_builder: Any = part.Features.CreateExtrudeBuilder(None)
    try:
        section1 = part.Sections.CreateSection(0.00038000000000000002, 0.00040000000000000002, 0.5)
        extrude_builder.Section = section1
        extrude_builder.AllowSelfIntersectingSection(True)
        extrude_builder.DistanceTolerance = 0.00040000000000000002
        extrude_builder.BooleanOperation.Type = NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Create
        extrude_builder.BooleanOperation.SetTargetBodies([_NXOpen.Body.Null])
        extrude_builder.Limits.StartExtend.Value.SetFormula("0.393700787401575")
        extrude_builder.Limits.EndExtend.Value.SetFormula("1.5748031496063")
        extrude_builder.BooleanOperation.Type = NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Subtract
        extrude_builder.BooleanOperation.SetTargetBodies([body1])
        extrude_builder.Draft.FrontDraftAngle.SetFormula("-2")
        extrude_builder.Draft.BackDraftAngle.SetFormula("2")
        extrude_builder.Offset.StartOffset.SetFormula("0")
        extrude_builder.Offset.EndOffset.SetFormula("2")
        smart_volume_profile_builder1 = extrude_builder.SmartVolumeProfile
        smart_volume_profile_builder1.OpenProfileSmartVolumeOption = False
        smart_volume_profile_builder1.CloseProfileRule = \
            _NXOpen.GeometricUtilities.SmartVolumeProfileBuilder.CloseProfileRuleType.Fci
        section1.DistanceTolerance = 0.00040000000000000002
        section1.ChainingTolerance = 0.00038000000000000002
        section1.SetAllowedEntityTypes(NXOpen.Section.AllowTypes.OnlyCurves)
        selection_intent_rule_options1 = part.ScRuleFactory.CreateRuleOptions()
        selection_intent_rule_options1.SetSelectedFromInactive(False)
        edge_tangent_rule1 = part.ScRuleFactory.CreateRuleEdgeTangent(
            tangent_edge, _NXOpen.Edge.Null, True, 0.5, False, False, selection_intent_rule_options1)
        selection_intent_rule_options1.Dispose()
        section1.AllowSelfIntersection(True)
        section1.AllowDegenerateCurves(False)
        help_point1 = NXOpen.Point3d(22.203733205592865, 11.9449495757104, 0.031496062992122514)
        section1.AddToSection([edge_tangent_rule1], tangent_edge, _NXOpen.NXObject.Null, _NXOpen.NXObject.Null,
                              help_point1, NXOpen.Section.Mode.Create, False)
        origin1 = NXOpen.Point3d(21.811023622046278, 14.695517477602802, 0.03149606299212411)
        direction1 = part.Directions.CreateDirection(origin1, NXOpen.Vector3d(0.0, 0.0, 1.0),
                                                     _NXOpen.SmartObject.UpdateOption.WithinModeling)
        extrude_builder.Direction = direction1
        direction2 = part.Directions.CreateDirection(NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Vector3d(-0.0, -0.0, -1.0),
                                                     _NXOpen.SmartObject.UpdateOption.WithinModeling)
        extrude_builder.Direction = direction2
        extrude_builder.Limits.EndExtend.Value.SetFormula("60mm")
        extrude_builder.Draft.DraftOption = _NXOpen.GeometricUtilities.SimpleDraft.SimpleDraftType.SimpleFromStart
        extrude_builder.ParentFeatureInternal = False

        return cast(NXOpen.Features.Feature, extrude_builder.CommitFeature())
    finally:
        extrude_builder.Destroy()


def main() -> None:
    """The blank-station UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("blank-station"):
        BlankStation.execute(False)


if __name__ == "__main__":
    main()
