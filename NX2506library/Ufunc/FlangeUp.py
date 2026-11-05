"""
The flange-up UFunc: a standalone Python UFunc (no C# class); its menu button runs this file's main().

The Merlin builder for a flange up station, from the "FLANGE UP STATION" spec (2026-11-02). Run from the -000; one run
builds into the op picked in the dialog:
  - LADnn (Lower):
      1. CAST LOWER HOLDING PAD - the part's box + .375" a side in X and + 5" a side in Y, at least 3.5" under the
         part's lowest point, LWR-3D subtracted, then intersected with PAD-PROFILE. Its SUB_TOOL (layer 15, color 138,
         reference set SUB_TOOL) is its bottom face's outline offset 10 mm outward, extruded from 30 mm below the
         bottom face to 10" over its top. Children: 8 TSG jack screws (CBORE_BLIND) on the bottom on a balanced 1"
         grid, 4 Jolico bottoming blocks, 4 cast pad locators on the centrelines, 4 hoist rings on the top face 1" in,
         4 guided retainers 55 mm in from the corners, 1 mm off the bottom (GRS.50.HD, stroke 105, travel 75, Save As'd),
         and the GM PAD CAST TEXT part.
      2. CAST LOWER FLANGE RISER - from 3.25" under the pad's bottom, 9" tall; the part's box + 3" a side in X and
         + .375" a side in Y. The pad's SUB_TOOL is wave-linked in and subtracted (the pad's pocket). Children: 8 jack
         screws midway between the SHCS on a balanced 1" grid, 4 hoist rings on the top face 1" in, 10 x
         20mm-shcs-150-2x from the backside (5 per X side, SHORT-TAP), 4 keys on the bottom centrelines (25mm-100mm),
         the left / right ones 2" along Y off the centreline to miss the SHCS, and the cast text.
      3. LOWER FLANGE UP STEELS - the part's box + 1" a side in X and + .375" a side in Y, at least 2" under the part,
         split down the X centre; the dialog's "Flange is located where?" keeps both halves, the -X (left) or the +X
         (right) one, each split into Rows along Y. LWR-PROFILE and LWR-3D subtracted. Per steel: 2 jack screws on
         the bottom (balanced on a 1" grid), 3 x 16mm-shcs-070-2x in from the outer side face (SHORT-TAP), 1.625" up
         and evenly along the steel, and one key on the bottom running along X (25mm-80mm). Bottom and SHCS face
         yellow.
  - UADnn (Upper):
      4. CAST UPPER HOLDING PAD - the part's box + .375" a side in X and + 8" a side in Y, 3.5" over the part's
         highest point, UPR-3D subtracted. Children: 8 jack screws, 8 bottoming blocks, 4 cast pad locators, 4 hoist
         rings 2" in, 4 guided retainers 90 mm in, 1 mm off the mounting face (GRS.65.HD, stroke 95, travel 60, Save
         As'd), the cast text.
      5. UPPER FLANGE UP STEELS - Dead Hit's upper grid: the part's box + .375" all round, at least 2.75" over the
         part, Rows (x) blocks along X by Cols (y) along Y, UPR-3D subtracted. Per steel: 2 jack screws, 4 x
         16mm-shcs-070-2x from the backside 1" in (SHORT-TAP), 3 keys (25mm-80mm): one along X, two along Y.

"Bottom" in the spec is read as each detail's mounting face (the yellow one): the underside of a lower detail, the
top of an upper one - the upper pad's spec is the lower's with the numbers changed, "bottom of pad to be yellow"
included. "Top face" (the hoist rings) is the face opposite it.

The dialog (FlangeUp.dlx, tools\\make-dlx.py): the Customer radio (None / TSG / GM; TSG uses the CTS keys and guided
keepers, as Draw Die does), the part's solid bodies, the op (ops with both a ladNN and a uadNN), Lower with its Rows
(y) and the flange side, and Upper with Rows (x) / Cols (y). OK stays greyed out until TSG or GM is
checked, a body is picked and a side is checked. LWR-3D / UPR-3D must be on the picked bodies' components for the
side being built; a missing PAD-PROFILE or LWR-PROFILE asks one Question box (Yes builds without that boolean).

Each detail is caught on its own (a failed pad skips only the riser that needs it), and each child group inside a
detail too. Never run in NX: the child orientations follow DrawDie's (keys: identity runs along X on a lower detail;
the upper key matrix along Y) and need checking on a real job.

Run standalone: File -> Execute -> NX Open on this file runs main().
"""

from __future__ import annotations

import datetime
import math
import os
import random
import re
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple, cast

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
import NXOpen.BlockStyler  # noqa: E402
import NXOpen.Features  # noqa: E402
import NXOpen.GeometricUtilities  # noqa: E402
import NXOpen.Layer  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
import PointComponent as merlin  # noqa: E402
import DrawDie as drawdie  # noqa: E402
from CastTrimPad import _import_cast_text  # noqa: E402
from DrawDie import DrawDieJob, Placement  # noqa: E402
from tsg_dialog import CustomerNone, Dialog, is_gm_customer, title_with_version  # noqa: E402

ufunc_name = "flange-up"

# ---------------------------------------------------------------------------------------------------
# Constants (inches; the spec's millimetres converted where declared)
# ---------------------------------------------------------------------------------------------------

FlangeBoth = "Both Sides"
FlangeLeft = "Left Side"
FlangeRight = "Right Side"
FlangeSides = [FlangeBoth, FlangeLeft, FlangeRight]

CastColor = 138                         # strong leaf
CastMaterial = "GM68M/S0030"
SteelMaterial = "D2"
Yellow = 42

# Cast lower holding pad.
LowerPadOverhangX = .375
LowerPadOverhangY = 5.00
LowerPadMinThickness = 3.50
LowerPadHoistRingInset = 1.00
LowerPadRetainerInset = 55 / 25.4
LowerPadBottomingBlocks = 4

# Its SUB_TOOL: the bottom face's outline offset 10 mm, from 30 mm under the bottom face to SubToolAboveTop over the top.
SubToolOffset = 10 / 25.4
SubToolBelowBottom = 30 / 25.4
SubToolAboveTop = 10.0
SubToolName = "SUB_TOOL"

# Cast lower flange riser.
RiserBelowPad = 3.25
RiserHeight = 9.00
RiserOverhangX = 3.00
RiserOverhangY = .375
RiserHoistRingInset = 1.00
RiserShcsPerSide = 5
RiserShcsInsetY = 1.50
# The SHCS go up the middle of the walls either side of the pad's pocket.
RiserShcsInsetX = (RiserOverhangX - LowerPadOverhangX) / 2
RiserKeyShiftY = 2.00

# Lower flange up steels.
LowerSteelOverhangX = 1.00
LowerSteelOverhangY = .375
LowerSteelMinHeight = 2.00
LowerSteelShcsAboveBottom = 1.625
LowerSteelShcsCount = 3
LowerSteelJackInset = 1.00

# Cast upper holding pad.
UpperPadOverhangX = .375
UpperPadOverhangY = 8.00
UpperPadThickness = 3.50
UpperPadHoistRingInset = 2.00
UpperPadRetainerInset = 90 / 25.4
UpperPadBottomingBlocks = 8

# Upper flange up steels (Dead Hit's upper: 3/8" all round, 2.75" over the part).
UpperSteelOverhang = .375
UpperSteelMinThickness = 2.75
UpperSteelShcsInset = 1.00
UpperSteelJackInset = 1.50

# Shared by the pads.
PadJackInsetX = 1.00
PadJackInsetY = 2.00
PadBottomingInset = 2.00
RetainerOffMountingFace = 1 / 25.4

# Smart GM Guided Retainer presets (already set, no spreadsheet opened): the spec pictures GRS.50.HD 105 / 75 on the
# lower pad and GRS.65.HD 95 / 60 on the upper.
LowerRetainerPath = drawdie._gmGuidedRetainer50Path
UpperRetainerPath = drawdie._gmGuidedRetainer65Path

# Smart GM Key presets ({width}-{length} mm, DrawDie._key_path).
RiserKeySize = drawdie.RiserKeySize      # 25-100, J-996444
SteelKeySize = drawdie.CavityKeySize     # 25-80, J-996443

# The reference sets the details subtract / intersect, matched ignoring case, spaces, hyphens and underscores.
Lower3d = "LWR-3D"
Upper3d = "UPR-3D"
PadProfile = "PAD-PROFILE"
LowerProfile = "LWR-PROFILE"
_RefsetCandidates: Dict[str, Sequence[str]] = {
    Lower3d: ("LWR-3D",),
    Upper3d: ("UPR-3D",),
    PadProfile: ("PAD-PROFILE",),
    # The spec's "Profile" tool: ProfileTrimAndForm's LWR-PROFILE, else a plain PROFILE.
    LowerProfile: ("LWR-PROFILE", "PROFILE"),
}

_shcs16mm070Path = "G:\\0Library\\Fasteners\\Metric\\SocketHeadCapScrews-2X\\016-2x\\16mm-shcs-070-2x.prt"
_shcs20mm150Path = "G:\\0Library\\Fasteners\\Metric\\SocketHeadCapScrews-2X\\020-2x\\20mm-shcs-150-2x.prt"
_gmBottomingBlockPath = "G:\\0Library\\0Customer\\GM\\Smart Jolico GM Bottoming Block.prt"
_gmPadCastTextPath = "G:\\CTS\\junk\\blank-station-data\\GM PAD CAST TEXT.prt"

# UF_UI_SEL_FEATURE_SOLID_BODY - not in every UFConstants build, so the number Perfect.py uses too.
_SolidBodyDetail = 36

_VectorX = NXOpen.Vector3d(1.0, 0.0, 0.0)
_VectorY = NXOpen.Vector3d(0.0, 1.0, 0.0)
_VectorZ = NXOpen.Vector3d(0.0, 0.0, 1.0)
_VectorXN = NXOpen.Vector3d(-1.0, 0.0, 0.0)
_VectorYN = NXOpen.Vector3d(0.0, -1.0, 0.0)
_VectorZN = NXOpen.Vector3d(0.0, 0.0, -1.0)


class FlangeUp(object):

    @staticmethod
    def execute(is_gm: bool = True) -> None:
        """
        The units / -000 gates, the dialog, the reference-set check, then the build. The dialog's Customer radio
        decides is_gm (TSG uses the CTS parts); the argument is not used.
        """
        ok, message = drawdie._check_info_units()
        if not ok:
            nx.show_error(message)
            return

        if not nx.display_part().Leaf.endswith("-000"):
            nx.show_error("Flange Up must be run from the 000.")
            return

        numbers = sorted(drawdie.find_op_stations())
        if len(numbers) == 0:
            nx.show_error("Flange Up could not find an op with both a LADnn and a UADnn under {}.".format(
                nx.display_part().Leaf))
            return

        dialog = _FlangeUpDialog(title_with_version("Flange Up"), numbers)
        if not dialog.run():
            return

        options = FlangeUpOptions(dialog.station, dialog.lower, dialog.upper, dialog.lower_rows, dialog.flange,
                                  dialog.upper_rows, dialog.upper_cols)

        refsets = _resolve_reference_sets(_components_of(dialog.bodies), options)
        if refsets is None:
            nx.mark_cancelled("the missing reference set question")
            return

        build(is_gm_customer(dialog.customer_choice), dialog.bodies, options, refsets)


class FlangeUpOptions(object):
    """What the dialog picked."""

    def __init__(self, station: str = drawdie.DefaultStation, lower: bool = True, upper: bool = True,
                 lower_rows: int = 2, flange: str = FlangeBoth, upper_rows: int = 2, upper_cols: int = 1) -> None:
        self.station = station
        self.lower = lower
        self.upper = upper
        # Lower steels along Y on each flange side.
        self.lower_rows = max(1, lower_rows)
        self.flange = flange
        # Upper steels: rows along X by cols along Y (Dead Hit's Rows (x) / Cols (y)).
        self.upper_rows = max(1, upper_rows)
        self.upper_cols = max(1, upper_cols)


# ---------------------------------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------------------------------

def build(is_gm: bool, bodies: Sequence[NXOpen.Body], options: FlangeUpOptions,
          refsets: Optional[Dict[str, Optional[str]]] = None) -> None:
    """
    The build half, on part bodies already picked, run from the -000: the lower details in LADnn, the upper ones in
    UADnn (nn = options.station). refsets maps Lower3d / Upper3d / PadProfile / LowerProfile to the name the bodies'
    components spell it (None = skip that boolean); looked up (without the question) when not given.
    """
    components = _components_of(bodies)
    if not components:
        nx.show_error("Select the part's bodies as component occurrences - their components carry the LWR-3D / "
                      "UPR-3D reference sets.")
        return

    if refsets is None:
        refsets = {name: _find_refset(components, name) for name in _RefsetCandidates}

    stations = drawdie.find_op_stations().get(options.station)
    if stations is None:
        nx.show_error("Flange Up could not find LAD{0} and UAD{0} under {1}.".format(options.station,
                                                                                    nx.display_part().Leaf))
        return

    top_level = nx.display_part()
    starting_work = nx.work_part()
    drawdie._set_wcs_to_absolute(top_level)
    nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Flange Up")

    try:
        part_box = nx.combine_boxes([nx.body_box(b) for b in bodies])
        nx.info("Flange Up: part box {} x {} x {}, from {}.".format(
            _f3(part_box.MaxX - part_box.MinX), _f3(part_box.MaxY - part_box.MinY), _f3(part_box.MaxZ - part_box.MinZ),
            ", ".join(c.DisplayName for c in components)))

        def job_for(kind: str, is_upper: bool) -> DrawDieJob:
            station = stations[kind]
            return DrawDieJob(is_gm, is_upper, top_level, cast(NXOpen.Part, nx.prototype(station)), components,
                              drawdie._map_box_to_station(part_box, station, top_level, starting_work))

        start = datetime.datetime.now()
        try:
            with nx.suppress_display():
                if options.lower:
                    lower = job_for("lad", False)
                    pad = _run_stage("cast lower holding pad", lambda: _build_lower_pad(lower, refsets))
                    if pad is not None:
                        _run_stage("cast lower flange riser", lambda: _build_riser(lower, pad[0], pad[1]))
                    else:
                        nx.print_("Flange Up: no lower holding pad, so no riser (it is placed off the pad).")
                    _run_stage("lower flange up steels", lambda: _build_lower_steels(lower, options, refsets))

                if options.upper:
                    upper = job_for("uad", True)
                    _run_stage("cast upper holding pad", lambda: _build_upper_pad(upper, refsets))
                    _run_stage("upper flange up steels", lambda: _build_upper_steels(upper, options, refsets))
        finally:
            nx.warn(drawdie._time_span(datetime.datetime.now() - start))
    except Exception as ex:
        nx.print_exception(ex)
    finally:
        nx.set_display_part(top_level)
        nx.set_work_part(starting_work)


def _components_of(bodies: Sequence[NXOpen.Body]) -> List[NXOpen.Assemblies.Component]:
    """The bodies' owning components, each once."""
    components: List[NXOpen.Assemblies.Component] = []
    for body in bodies:
        owner = body.OwningComponent
        if owner is not None and all(c.Tag != owner.Tag for c in components):
            components.append(owner)
    return components


def _normalized(name: str) -> str:
    return re.sub(r"[\s_\-]", "", name).lower()


def _find_refset(components: Sequence[NXOpen.Assemblies.Component], key: str) -> Optional[str]:
    """The first of key's candidate reference sets any component's part has, as the part spells it; None if none."""
    for candidate in _RefsetCandidates[key]:
        for component in components:
            for reference_set in nx.prototype(component).GetAllReferenceSets():
                if _normalized(reference_set.Name) == _normalized(candidate):
                    return reference_set.Name
    return None


def _resolve_reference_sets(components: Sequence[NXOpen.Assemblies.Component],
                            options: FlangeUpOptions) -> Optional[Dict[str, Optional[str]]]:
    """
    The reference sets the sides being built use. A missing LWR-3D / UPR-3D is an error box (None); a missing
    PAD-PROFILE / LWR-PROFILE asks one Question box - Yes builds without that boolean, No is None.
    """
    found = {name: _find_refset(components, name) for name in _RefsetCandidates}
    required = ([Lower3d] if options.lower else []) + ([Upper3d] if options.upper else [])
    missing_required = [name for name in required if found[name] is None]
    if missing_required:
        nx.show_error("None of the selected bodies' components ({}) has a {} reference set. Flange Up subtracts "
                      "LWR-3D from the lower pad and steels and UPR-3D from the upper ones - select the part that "
                      "carries them.".format(", ".join(c.DisplayName for c in components),
                                             " / ".join(missing_required)))
        return None

    optional = ([(PadProfile, "the lower holding pad is not intersected with it"),
                 (LowerProfile, "the lower flange up steels do not have it subtracted")] if options.lower else [])
    missing = ["{} - {}".format(name, why) for name, why in optional if found[name] is None]
    if missing:
        response = nx.message_box(
            "Flange Up", NXOpen.NXMessageBox.DialogType.Question,
            "None of the selected bodies' components has:\n" + "\n".join(missing) + "\n\nBuild anyway?")
        if response != nx.MessageBoxYes:
            return None
        for line in missing:
            nx.warn("Flange Up: no {}.".format(line))

    nx.info("Flange Up: reference sets {}.".format(
        ", ".join("{}={}".format(k, v) for k, v in found.items() if v is not None)))
    return found


def _run_stage(label: str, stage: Any) -> Any:
    """One detail (or group of steels): its result, or None, printed, when it throws."""
    nx.prompt("Flange Up -> {}".format(label))
    try:
        return stage()
    except Exception as ex:
        nx.print_("Flange Up: the {} failed.".format(label))
        nx.print_exception(ex)
        return None


def _step(label: str, step: Any) -> Any:
    """One child group inside a detail (DrawDie's step): printed and skipped when it throws."""
    return drawdie._draw_die_step_result(label, step, None)


# ---------------------------------------------------------------------------------------------------
# Holding pads
# ---------------------------------------------------------------------------------------------------

def _build_lower_pad(job: DrawDieJob, refsets: Dict[str, Optional[str]]) -> Tuple[nx.Box3d, NXOpen.Part]:
    """CAST LOWER HOLDING PAD - see the module docstring. Returns its box (station coordinates) and its part."""
    box = job.part_box
    xlength = nx.round_to_125(box.MaxX - box.MinX) + 2 * LowerPadOverhangX
    ywidth = nx.round_to_125(box.MaxY - box.MinY) + 2 * LowerPadOverhangY
    height = nx.round_to_125(box.MaxZ - box.MinZ + LowerPadMinThickness)
    min_point = drawdie._centered_min(box, xlength, ywidth, box.MaxZ - height)

    new_part = _build_pad(job, min_point, xlength, ywidth, height, "flange-up-lower-pad", "CAST LOWER HOLDING PAD",
                          LowerPadBottomingBlocks, LowerPadHoistRingInset, LowerPadRetainerInset, LowerRetainerPath,
                          refsets.get(Lower3d))

    pad_profile = refsets.get(PadProfile)
    if pad_profile is not None:
        _step("{} {} intersect".format(new_part.Leaf, pad_profile),
              lambda: _boolean_components(job, new_part, pad_profile, NXOpen.Features.Feature.BooleanType.Intersect))

    _step("{} {}".format(new_part.Leaf, SubToolName), lambda: _create_offset_sub_tool(job, new_part))
    return drawdie._box_from(min_point, xlength, ywidth, height), new_part


def _build_upper_pad(job: DrawDieJob, refsets: Dict[str, Optional[str]]) -> nx.Box3d:
    """CAST UPPER HOLDING PAD - see the module docstring."""
    box = job.part_box
    xlength = nx.round_to_125(box.MaxX - box.MinX) + 2 * UpperPadOverhangX
    ywidth = nx.round_to_125(box.MaxY - box.MinY) + 2 * UpperPadOverhangY
    height = nx.round_to_125(box.MaxZ - box.MinZ + UpperPadThickness)
    min_point = drawdie._centered_min(box, xlength, ywidth, box.MinZ)

    _build_pad(job, min_point, xlength, ywidth, height, "flange-up-upper-pad", "CAST UPPER HOLDING PAD",
               UpperPadBottomingBlocks, UpperPadHoistRingInset, UpperPadRetainerInset, UpperRetainerPath,
               refsets.get(Upper3d))
    return drawdie._box_from(min_point, xlength, ywidth, height)


def _build_pad(job: DrawDieJob, min_point: NXOpen.Point3d, xlength: float, ywidth: float, height: float,
               name: str, title: str, bottoming_blocks: int, hoist_ring_inset: float, retainer_inset: float,
               retainer_path: str, subtract_refset: Optional[str]) -> NXOpen.Part:
    """
    The block, its children and cast text, then BODY / subtract / ancestor reference sets. The mounting face (lower:
    Z 0, upper: Z height) is yellow and holds the jack screws, bottoming blocks, locators and guided retainers; the
    hoist rings go on the face opposite it.
    """
    new_part, component = drawdie._promote_draw_die_block(
        job, min_point, xlength, ywidth, height,
        name="{}{}".format(job.prefix, name),
        color=CastColor,
        description=title,
        material=CastMaterial,
        detail_name=title,
        fixed_description=True)

    body_refset = nx.find_or_create_reference_set(new_part, "BODY")
    mount_z, into, out_of, top_z, up_from_top = _faces(job.is_upper, height)

    def jack_screws() -> None:
        xs = _balanced(xlength / 2, 2, xlength - 2 * PadJackInsetX)
        ys = _balanced(ywidth / 2, 4, (ywidth - 2 * PadJackInsetY) / 3)
        drawdie._place_draw_die_children("pad jack screw", drawdie._jck12mmScrewTsgPath,
                                         [(NXOpen.Point3d(x, y, mount_z), into) for x in xs for y in ys],
                                         layer=99, subtract_refset="CBORE_BLIND", body_refset=body_refset)

    _step("{} jack screws".format(title), jack_screws)

    def bottoming() -> None:
        points = drawdie._inset_corners(xlength, ywidth, PadBottomingInset)
        if bottoming_blocks > 4:
            points += [NXOpen.Point3d(xlength / 2, PadBottomingInset, 0.0),
                       NXOpen.Point3d(xlength / 2, ywidth - PadBottomingInset, 0.0),
                       NXOpen.Point3d(PadBottomingInset, ywidth / 2, 0.0),
                       NXOpen.Point3d(xlength - PadBottomingInset, ywidth / 2, 0.0)]
        drawdie._place_draw_die_children("pad bottoming block", _gmBottomingBlockPath,
                                         [(NXOpen.Point3d(p.X, p.Y, mount_z), out_of) for p in points],
                                         layer=99, subtract_refset=None, body_refset=body_refset)

    _step("{} bottoming blocks".format(title), bottoming)

    def locators() -> List[NXOpen.Assemblies.Component]:
        path = drawdie._gmCastPadLocatorPath if job.is_gm else drawdie._ctsSmartKeyMetric
        inset = drawdie._castPadLocatorInset
        front_back = drawdie._lower_key_front_back_orientation()
        up = nx.identity_matrix()
        placed = drawdie._place_draw_die_children("pad cast pad locator", path, [
            (NXOpen.Point3d(xlength / 2, inset, mount_z), front_back),
            (NXOpen.Point3d(xlength / 2, ywidth - inset, mount_z), front_back),
            (NXOpen.Point3d(inset, ywidth / 2, mount_z), up),
            (NXOpen.Point3d(xlength - inset, ywidth / 2, mount_z), up),
        ], layer=98, subtract_refset=None, body_refset=None)
        # Half in the pad, half out of it, as the draw die's binder has them.
        drawdie._center_draw_die_children_on_z(new_part, placed, mount_z)
        return placed

    placed_locators = _step("{} cast pad locators".format(title), locators) or []

    def hoist_rings() -> List[NXOpen.Assemblies.Component]:
        return drawdie._place_draw_die_children(
            "pad hoist ring", drawdie._gmHoistRingPath,
            [(NXOpen.Point3d(p.X, p.Y, top_z), up_from_top)
             for p in drawdie._inset_corners(xlength, ywidth, hoist_ring_inset)],
            layer=98, subtract_refset="SHORT-TAP", body_refset=None)

    placed_rings = _step("{} hoist rings".format(title), hoist_rings) or []
    _step("{} BODY reference set (hoist rings and locators)".format(title),
          lambda: drawdie._keep_out_of_reference_set(body_refset, placed_rings + placed_locators))

    def guided_retainers() -> None:
        path = retainer_path if job.is_gm else drawdie._ctsSmartSlGuidedKeeper
        # Pointing out of the mounting face, 1 mm off it: upside down under a lower pad (as the binder's).
        z = height + RetainerOffMountingFace if job.is_upper else -RetainerOffMountingFace
        placed = drawdie._place_draw_die_children(
            "pad guided retainer", path,
            [(NXOpen.Point3d(p.X, p.Y, z), out_of) for p in drawdie._inset_corners(xlength, ywidth, retainer_inset)],
            layer=99, subtract_refset=None, body_refset=body_refset)
        drawdie._save_as_draw_die_part(placed, job, "{}-guided-retainer".format(name))

    _step("{} guided retainers".format(title), guided_retainers)
    _step("{} cast text".format(title), lambda: _cast_text(new_part, xlength, ywidth, mount_z))

    drawdie._finish_draw_die_block(job, new_part, component, subtract_refset)
    return new_part


def _create_offset_sub_tool(job: DrawDieJob, pad_part: NXOpen.Part) -> None:
    """
    The lower pad's SUB_TOOL: its lowest -Z planar face's edges extruded from SubToolBelowBottom under it to
    SubToolAboveTop over the pad, offset SubToolOffset outward, on hidden layer 15, color 138, in its own SUB_TOOL
    reference set and kept out of BODY. Built after the LWR-3D subtract and PAD-PROFILE intersect, so the outline is
    the finished pad's.
    """
    try:
        nx.set_display_part(pad_part)
        nx.set_work_part(pad_part)
        body = nx.dynamic_block(pad_part).GetBodies()[0]
        bottoms = [f for f in body.GetFaces()
                   if f.SolidFaceType == NXOpen.Face.FaceType.Planar and nx.vectors_equal(nx.face_normal(f), _VectorZN)]
        if not bottoms:
            raise RuntimeError("{} has no bottom face to offset into a {}.".format(pad_part.Leaf, SubToolName))
        bottom = min(bottoms, key=lambda f: drawdie._exact_box(f).MinZ)
        face_box = drawdie._exact_box(bottom)
        pad_box = drawdie._exact_box(body)

        pad_part.Layers.WorkLayer = 15
        try:
            extrude = _extrude_face_with_offset(pad_part, bottom, -SubToolBelowBottom,
                                                pad_box.MaxZ - face_box.MinZ + SubToolAboveTop, SubToolOffset)
        finally:
            pad_part.Layers.WorkLayer = 1

        extrude.SetName(SubToolName)
        tool = extrude.GetBodies()[0]
        nx.set_color(tool, CastColor)
        nx.find_or_create_reference_set(pad_part, SubToolName).AddObjectsToReferenceSet([tool])
        body_refset = nx.find_reference_set_or_null(pad_part, "BODY")
        if body_refset is not None:
            drawdie._keep_out_of_reference_set(body_refset, [tool])
        pad_part.Layers.SetState(15, NXOpen.Layer.State.Hidden)
        nx.info("Flange Up: {} in {} ({}).".format(SubToolName, pad_part.Leaf, extrude.JournalIdentifier))
    finally:
        nx.set_display_part(job.station)
        nx.set_work_part(job.station)


def _extrude_face_with_offset(part: NXOpen.Part, face: NXOpen.Face, start: float, end: float,
                              offset: float) -> NXOpen.Features.Extrude:
    """
    face's edges extruded along +Z from start to end as a new solid, with a single-sided offset. The side the offset
    goes depends on the loop direction, so when the result came out narrower than the face it is edited to the other
    side.
    """
    modeling: Any = cast(Any, part.Preferences).Modeling
    distance_tolerance = modeling.DistanceToleranceData
    section = part.Sections.CreateSection(0.95 * distance_tolerance, distance_tolerance, modeling.AngleToleranceData)
    rule_factory: Any = part.ScRuleFactory
    section.AddToSection([rule_factory.CreateRuleEdgeFace([face])], face, None, None,
                         NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Section.Mode.Create, False)
    geometric: Any = NXOpen.GeometricUtilities

    builder: Any = part.Features.CreateExtrudeBuilder(None)
    try:
        builder.Section = section
        builder.BooleanOperation.Type = geometric.BooleanOperation.BooleanType.Create
        builder.Limits.StartExtend.Value.RightHandSide = nx.cs_double_str(start)
        builder.Limits.EndExtend.Value.RightHandSide = nx.cs_double_str(end)
        builder.Offset.Option = geometric.Type.SingleOffset
        builder.Offset.StartOffset.RightHandSide = "0"
        builder.Offset.EndOffset.RightHandSide = nx.cs_double_str(offset)
        builder.Direction = part.Directions.CreateDirection(NXOpen.Point3d(0.0, 0.0, 0.0), _VectorZ,
                                                            NXOpen.SmartObject.UpdateOption.WithinModeling)
        extrude = cast(NXOpen.Features.Extrude, builder.CommitFeature())
    finally:
        builder.Destroy()

    face_box = drawdie._exact_box(face)
    tool_box = drawdie._exact_box(extrude.GetBodies()[0])
    if tool_box.MaxX - tool_box.MinX < face_box.MaxX - face_box.MinX:
        edit: Any = part.Features.CreateExtrudeBuilder(extrude)
        try:
            edit.Offset.EndOffset.RightHandSide = nx.cs_double_str(-offset)
            edit.CommitFeature()
        finally:
            edit.Destroy()
        nx.info("Flange Up: the {} offset went inward - flipped it.".format(SubToolName))
    return extrude


# ---------------------------------------------------------------------------------------------------
# Riser
# ---------------------------------------------------------------------------------------------------

def _build_riser(job: DrawDieJob, pad_box: nx.Box3d, pad_part: NXOpen.Part) -> nx.Box3d:
    """CAST LOWER FLANGE RISER - see the module docstring."""
    box = job.part_box
    xlength = nx.round_to_125(box.MaxX - box.MinX) + 2 * RiserOverhangX
    ywidth = nx.round_to_125(box.MaxY - box.MinY) + 2 * RiserOverhangY
    min_point = drawdie._centered_min(box, xlength, ywidth, pad_box.MinZ - RiserBelowPad)
    title = "CAST LOWER FLANGE RISER"

    new_part, component = drawdie._promote_draw_die_block(
        job, min_point, xlength, ywidth, RiserHeight,
        name="{}flange-up-riser".format(job.prefix),
        color=CastColor,
        description=title,
        material=CastMaterial,
        detail_name=title,
        fixed_description=True)

    body_refset = nx.find_or_create_reference_set(new_part, "BODY")
    mount_z, into, out_of, top_z, up_from_top = _faces(False, RiserHeight)

    # SHCS from the backside, five up each X wall.
    shcs_xs = [RiserShcsInsetX, xlength - RiserShcsInsetX]
    shcs_ys = drawdie._even_stations(RiserShcsInsetY, ywidth - RiserShcsInsetY, RiserShcsPerSide)
    _step("riser SHCS", lambda: drawdie._place_draw_die_children(
        "riser SHCS", _shcs20mm150Path,
        [(NXOpen.Point3d(x, y, mount_z), out_of) for x in shcs_xs for y in shcs_ys],
        layer=99, subtract_refset="SHORT-TAP", body_refset=body_refset))

    # Jack screws: four up each wall, aimed midway between the SHCS, balanced about the centre on a 1" grid.
    def jack_screws() -> None:
        spacing = shcs_ys[1] - shcs_ys[0] if len(shcs_ys) > 1 else ywidth
        xs = _balanced(xlength / 2, 2, xlength - 2 * RiserShcsInsetX)
        ys = _balanced(ywidth / 2, RiserShcsPerSide - 1, spacing)
        drawdie._place_draw_die_children("riser jack screw", drawdie._jck12mmScrewTsgPath,
                                         [(NXOpen.Point3d(x, y, mount_z), into) for x in xs for y in ys],
                                         layer=99, subtract_refset="CBORE_BLIND", body_refset=body_refset)

    _step("riser jack screws", jack_screws)

    def hoist_rings() -> None:
        rings = drawdie._place_draw_die_children(
            "riser hoist ring", drawdie._gmHoistRingPath,
            [(NXOpen.Point3d(p.X, p.Y, top_z), up_from_top)
             for p in drawdie._inset_corners(xlength, ywidth, RiserHoistRingInset)],
            layer=98, subtract_refset="SHORT-TAP", body_refset=None)
        drawdie._keep_out_of_reference_set(body_refset, rings)

    _step("riser hoist rings", hoist_rings)

    # Keys on the bottom centrelines, the left / right ones moved 2" along Y to miss the middle SHCS.
    def riser_keys() -> None:
        keys = drawdie._place_draw_die_edge_keys(job, xlength, ywidth, RiserHeight, RiserKeySize,
                                                 (0.0, RiserKeyShiftY))
        body_refset.AddObjectsToReferenceSet(keys)
        drawdie._save_as_draw_die_part(keys, job, "flange-up-riser-key")

    _step("riser keys", riser_keys)
    _step("riser cast text", lambda: _cast_text(new_part, xlength, ywidth, mount_z))

    drawdie._finish_draw_die_block(job, new_part, component, subtract_refset=None)

    # The pad's pocket: its SUB_TOOL wave-linked in and subtracted.
    def pocket() -> None:
        nx.set_display_part(job.top_level)
        pad_occurrence = nx.first_occurrence_in(pad_part, job.top_level)
        if not nx.has_reference_set(pad_part, SubToolName):
            raise RuntimeError("{} has no {} reference set - the riser has no pocket.".format(pad_part.Leaf,
                                                                                            SubToolName))
        nx.set_work_part(new_part)
        merlin._subtract_components(lambda: nx.dynamic_block(nx.work_part()).GetBodies()[0], [pad_occurrence],
                                    SubToolName)

    try:
        _step("riser {} pocket".format(SubToolName), pocket)
    finally:
        nx.set_display_part(job.station)
        nx.set_work_part(job.station)

    return drawdie._box_from(min_point, xlength, ywidth, RiserHeight)


# ---------------------------------------------------------------------------------------------------
# Flange up steels
# ---------------------------------------------------------------------------------------------------

def _build_lower_steels(job: DrawDieJob, options: FlangeUpOptions, refsets: Dict[str, Optional[str]]) -> None:
    """LOWER FLANGE UP STEELS - see the module docstring. One key job copy for all of them."""
    box = job.part_box
    xlength = nx.round_to_125(box.MaxX - box.MinX) + 2 * LowerSteelOverhangX
    ywidth = nx.round_to_125(box.MaxY - box.MinY) + 2 * LowerSteelOverhangY
    height = nx.round_to_125(box.MaxZ - box.MinZ + LowerSteelMinHeight)
    min_point = drawdie._centered_min(box, xlength, ywidth, box.MaxZ - height)

    rows = options.lower_rows
    column_width = (xlength - merlin.SplitGap) / 2
    row_length = (ywidth - (rows - 1) * merlin.SplitGap) / rows
    if column_width <= 0 or row_length <= 0:
        raise RuntimeError("{} x {} is too small to split into {} rows a side.".format(_f3(xlength), _f3(ywidth),
                                                                                      rows))

    columns = {FlangeBoth: [0, 1], FlangeLeft: [0], FlangeRight: [1]}.get(options.flange, [0, 1])
    colors = random.sample(merlin.SplitComponentColors, len(merlin.SplitComponentColors))
    keys: List[NXOpen.Assemblies.Component] = []
    index = 0
    for column in columns:
        for row in range(rows):
            block_min = NXOpen.Point3d(min_point.X + column * (column_width + merlin.SplitGap),
                                       min_point.Y + row * (row_length + merlin.SplitGap), min_point.Z)
            try:
                _build_one_lower_steel(job, block_min, column, row, column_width, row_length, height,
                                       colors[index % len(colors)], refsets, keys)
            except Exception as ex:
                nx.print_("Flange Up: lower flange up steel {} of {} failed.".format(index + 1, len(columns) * rows))
                nx.print_exception(ex)
            index += 1

    drawdie._save_as_draw_die_part(keys, job, "flange-up-lower-steel-key")


def _build_one_lower_steel(job: DrawDieJob, block_min: NXOpen.Point3d, column: int, row: int, width: float,
                           length: float, height: float, color: int, refsets: Dict[str, Optional[str]],
                           keys: List[NXOpen.Assemblies.Component]) -> None:
    """One lower steel: column 0 is the -X (left) flange side, 1 the +X (right)."""
    outer = _VectorXN if column == 0 else _VectorX
    outer_x = 0.0 if column == 0 else width
    label = "lower flange up steel {}{}".format("L" if column == 0 else "R", row + 1)

    new_part, component = drawdie._promote_draw_die_block(
        job, block_min, width, length, height,
        name="{}flange-up-lower-steel".format(job.prefix),
        color=color,
        description="{} X {} X {}".format(_f3(width), _f3(length), _f3(height)),
        material=SteelMaterial,
        detail_name="LOWER FLANGE UP STEELS",
        fixed_description=False,
        # The bottom is yellow already (the mounting face); the side the SHCS come in from too.
        joint_normals=[outer])

    body_refset = nx.find_or_create_reference_set(new_part, "BODY")
    shift = drawdie.KeyShiftStep * row

    # SHCS in from the outer side: heads outside, threads in the steel.
    ys = [length * (2 * i + 1) / (2 * LowerSteelShcsCount) for i in range(LowerSteelShcsCount)]
    _step("{} SHCS".format(label), lambda: drawdie._place_draw_die_children(
        "lower steel SHCS", _shcs16mm070Path,
        [(NXOpen.Point3d(outer_x, y + (shift if i == 0 else 0.0), LowerSteelShcsAboveBottom), drawdie._z_matrix(outer))
         for i, y in enumerate(ys)],
        layer=99, subtract_refset="SHORT-TAP", body_refset=body_refset))

    _step("{} jack screws".format(label),
          lambda: _place_jack_pair(width, length, 0.0, drawdie._z_matrix(_VectorZ), LowerSteelJackInset, body_refset))

    # One key on the bottom, running along X (a lower key's identity orientation), moved along Y by the row.
    def key() -> None:
        path = drawdie._key_path(job, SteelKeySize)
        placed = nx.add_component(nx.display_part(), path, "BODY", None,
                                  NXOpen.Point3d(width / 2, length / 2 + shift, 0.0), nx.identity_matrix(), 99)
        body_refset.AddObjectsToReferenceSet([placed])
        keys.append(placed)

    _step("{} key".format(label), key)

    drawdie._finish_draw_die_block(job, new_part, component, refsets.get(Lower3d))
    profile = refsets.get(LowerProfile)
    if profile is not None:
        _step("{} {} subtract".format(new_part.Leaf, profile),
              lambda: _boolean_components(job, new_part, profile, NXOpen.Features.Feature.BooleanType.Subtract))


def _build_upper_steels(job: DrawDieJob, options: FlangeUpOptions, refsets: Dict[str, Optional[str]]) -> None:
    """UPPER FLANGE UP STEELS - see the module docstring. One key job copy for all of them."""
    box = job.part_box
    xlength = nx.round_to_125(box.MaxX - box.MinX) + 2 * UpperSteelOverhang
    ywidth = nx.round_to_125(box.MaxY - box.MinY) + 2 * UpperSteelOverhang
    height = nx.round_to_125(box.MaxZ - box.MinZ + UpperSteelMinThickness)
    min_point = drawdie._centered_min(box, xlength, ywidth, box.MinZ)

    columns, rows = options.upper_rows, options.upper_cols
    column_width = (xlength - (columns - 1) * merlin.SplitGap) / columns
    row_length = (ywidth - (rows - 1) * merlin.SplitGap) / rows
    if column_width <= 0 or row_length <= 0:
        raise RuntimeError("{} x {} is too small to split {} x {}.".format(_f3(xlength), _f3(ywidth), columns, rows))

    colors = random.sample(merlin.SplitComponentColors, len(merlin.SplitComponentColors))
    keys: List[NXOpen.Assemblies.Component] = []
    index = 0
    for column in range(columns):
        for row in range(rows):
            block_min = NXOpen.Point3d(min_point.X + column * (column_width + merlin.SplitGap),
                                       min_point.Y + row * (row_length + merlin.SplitGap), min_point.Z)
            try:
                _build_one_upper_steel(job, block_min, column, row, columns, column_width, row_length, height,
                                       colors[index % len(colors)], refsets, keys)
            except Exception as ex:
                nx.print_("Flange Up: upper flange up steel {} of {} failed.".format(index + 1, columns * rows))
                nx.print_exception(ex)
            index += 1

    drawdie._save_as_draw_die_part(keys, job, "flange-up-upper-steel-key")


def _build_one_upper_steel(job: DrawDieJob, block_min: NXOpen.Point3d, column: int, row: int, columns: int,
                           width: float, length: float, height: float, color: int,
                           refsets: Dict[str, Optional[str]], keys: List[NXOpen.Assemblies.Component]) -> None:
    label = "upper flange up steel {}".format(row * columns + column + 1)
    new_part, component = drawdie._promote_draw_die_block(
        job, block_min, width, length, height,
        name="{}flange-up-upper-steel".format(job.prefix),
        color=color,
        description="{} X {} X {}".format(_f3(width), _f3(length), _f3(height)),
        material=SteelMaterial,
        detail_name="UPPER FLANGE UP STEELS",
        fixed_description=False)

    body_refset = nx.find_or_create_reference_set(new_part, "BODY")
    mount_z, into, out_of, _top_z, _up = _faces(True, height)
    shift = drawdie.key_shift_for(column, row, columns)

    _step("{} SHCS".format(label), lambda: drawdie._place_draw_die_children(
        "upper steel SHCS", _shcs16mm070Path,
        [(NXOpen.Point3d(p.X, p.Y, mount_z), out_of)
         for p in drawdie.shift_first_corner(drawdie._inset_corners(width, length, UpperSteelShcsInset), shift)],
        layer=99, subtract_refset="SHORT-TAP", body_refset=body_refset))

    _step("{} jack screws".format(label),
          lambda: _place_jack_pair(width, length, mount_z, into, UpperSteelJackInset, body_refset))

    # Two keys along Y (front / back, the upper key matrix) and one along X (right, that matrix turned 90 degrees),
    # where Draw Die's upper edge keys go.
    def steel_keys() -> None:
        path = drawdie._key_path(job, SteelKeySize)
        nudge = 0.0748 if job.is_gm else 0.0
        along_y = drawdie._compute_upper_key_orientation()
        along_x = nx.matrix_from_axes(nx.axis_y(along_y), nx.negate(nx.axis_x(along_y)))
        placements: List[Placement] = [
            (NXOpen.Point3d(width / 2 + shift[0], 1.5 + nudge, height), along_y),
            (NXOpen.Point3d(width / 2 + shift[0], length - 1.5 - nudge, height), along_y),
            (NXOpen.Point3d(width - drawdie._UpperXKeyEdgeInset + (1.5 - .625), length / 2 + shift[1], height),
             along_x),
        ]
        placed = [nx.add_component(nx.display_part(), path, "BODY", None, origin, orientation, 99)
                  for origin, orientation in placements]
        body_refset.AddObjectsToReferenceSet(placed)
        keys.extend(placed)

    _step("{} keys".format(label), steel_keys)

    drawdie._finish_draw_die_block(job, new_part, component, refsets.get(Upper3d))


# ---------------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------------

def _faces(is_upper: bool, height: float) -> Tuple[float, NXOpen.Matrix3x3, NXOpen.Matrix3x3, float,
                                                     NXOpen.Matrix3x3]:
    """
    (mount_z, into, out_of, top_z, up_from_top) of a detail height tall: its mounting face's Z, the orientations
    pointing into the detail from it and out of it, the opposite face's Z and the orientation pointing out of that.
    """
    if is_upper:
        return height, drawdie._z_matrix(_VectorZN), drawdie._z_matrix(_VectorZ), 0.0, drawdie._z_matrix(_VectorZN)
    return 0.0, drawdie._z_matrix(_VectorZ), drawdie._z_matrix(_VectorZN), height, drawdie._z_matrix(_VectorZ)


def _balanced(center: float, count: int, target_spacing: float) -> List[float]:
    """count values balanced about center, a whole number of inches apart (at least 1"): target_spacing rounded
    down."""
    spacing = max(1.0, float(math.floor(round(target_spacing, 6))))
    return [center + (i - (count - 1) / 2) * spacing for i in range(count)]


def _place_jack_pair(width: float, length: float, z: float, orientation: NXOpen.Matrix3x3, inset: float,
                     body_refset: NXOpen.ReferenceSet) -> None:
    """Two TSG jack screws (CBORE_BLIND) on diagonal corners, balanced about the centre on a 1" grid."""
    xs = _balanced(width / 2, 2, width - 2 * inset)
    ys = _balanced(length / 2, 2, length - 2 * inset)
    drawdie._place_draw_die_children("steel jack screw", drawdie._jck12mmScrewTsgPath,
                                     [(NXOpen.Point3d(xs[1], ys[0], z), orientation),
                                      (NXOpen.Point3d(xs[0], ys[1], z), orientation)],
                                     layer=99, subtract_refset="CBORE_BLIND", body_refset=body_refset)


def _cast_text(part: NXOpen.Part, xlength: float, ywidth: float, z: float) -> None:
    """The GM PAD CAST TEXT part imported at the centre of the mounting face (layer 20). part is the work part."""
    _import_cast_text(part, _gmPadCastTextPath, xlength, ywidth, NXOpen.Point3d(0.0, 0.0, z))


def _boolean_components(job: DrawDieJob, new_part: NXOpen.Part, refset: str,
                        boolean_type: NXOpen.Features.Feature.BooleanType) -> None:
    """
    refset of the picked components wave-linked into new_part and booleaned with its dynamic block (in the -000, as
    _finish_draw_die_block subtracts). A component without it is skipped; a failed boolean is printed.
    """
    try:
        nx.set_display_part(job.top_level)
        nx.set_work_part(new_part)
        if boolean_type == NXOpen.Features.Feature.BooleanType.Subtract:
            merlin._subtract_components(lambda: nx.dynamic_block(nx.work_part()).GetBodies()[0], job.components,
                                        refset)
            return
        for component in job.components:
            if not nx.has_reference_set(nx.prototype(component), refset):
                continue
            try:
                nx.set_reference_set(component, refset)
                linked = nx.create_linked_body(component)
                nx.create_boolean(nx.dynamic_block(nx.work_part()).GetBodies()[0], linked.GetBodies(), boolean_type)
            except Exception as ex:
                nx.print_("Flange Up: could not intersect {} with {} of {}.".format(new_part.Leaf, refset,
                                                                                   component.DisplayName))
                nx.print_exception(ex)
            finally:
                nx.set_reference_set(component, "BODY")
    finally:
        nx.set_display_part(job.station)
        nx.set_work_part(job.station)


def _f3(value: float) -> str:
    return drawdie._f3(value)


# ---------------------------------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------------------------------

class _FlangeUpDialog(Dialog):
    """FlangeUp.dlx: Customer, the bodies, the op, Lower (Rows (y), flange side), Upper (Rows (x), Cols (y)).
    GM keys and guided retainers are placed from DrawDie's preset parts, so no spreadsheet is opened."""

    dlx_name = "FlangeUp.dlx"

    def __init__(self, title: str, numbers: Sequence[str]) -> None:
        self.title = title
        self.numbers = list(numbers)
        super().__init__()
        # Captured in ok(): the blocks are gone once Launch returns.
        self.customer_choice = CustomerNone
        self.bodies: List[NXOpen.Body] = []
        self.station = self.numbers[0]
        self.lower = True
        self.upper = True
        self.lower_rows = 2
        self.flange = FlangeBoth
        self.upper_rows = 2
        self.upper_cols = 1

    def initialize(self) -> None:
        mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type, 0, _SolidBodyDetail)
        self.block("bodies").SetSelectionFilter(NXOpen.Selection.SelectionAction.ClearAndEnableSpecific, [mask])
        self.assembly_scope(self.block("bodies"))
        self.block("station").SetEnumMembers(self.numbers)

    def shown(self) -> None:
        self.reset_customer()
        match = drawdie._OpStationPattern.search(nx.work_part().Leaf.lower())
        self.block("station").ValueAsString = (match.group(2) if match is not None and match.group(2) in self.numbers
                                               else self.numbers[0])
        # Not remembered: both sides every time, as Dead Strike.
        self.block("lower").Value = True
        self.block("upper").Value = True
        self._enable_sides()

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        self._enable_sides()

    def _enable_sides(self) -> None:
        lower = bool(self.block("lower").Value)
        upper = bool(self.block("upper").Value)
        self.block("lower_rows").Enable = lower
        self.block("flange").Enable = lower
        self.block("upper_rows").Enable = upper
        self.block("upper_cols").Enable = upper

    def enable_ok(self) -> bool:
        return (self.customer_picked() and (bool(self.block("lower").Value) or bool(self.block("upper").Value))
                and len(self._picked_bodies()) > 0)

    def ok(self) -> bool:
        self.bodies = self._picked_bodies()
        self.lower = bool(self.block("lower").Value)
        self.upper = bool(self.block("upper").Value)
        # enable_ok greys OK out for these; they are a backstop.
        if not self.customer_picked():
            self.message("Check TSG or GM.")
            return False
        if not self.lower and not self.upper:
            self.message("Check Lower, Upper or both.")
            return False
        if not self.bodies:
            self.message("Select the part's solid bodies.")
            return False
        self.customer_choice = self.customer()
        self.station = str(self.block("station").ValueAsString)
        self.lower_rows = int(self.block("lower_rows").Value)
        self.flange = str(self.block("flange").ValueAsString)
        self.upper_rows = int(self.block("upper_rows").Value)
        self.upper_cols = int(self.block("upper_cols").Value)
        return True

    def _picked_bodies(self) -> List[NXOpen.Body]:
        return [cast(NXOpen.Body, o) for o in self.selected(self.block("bodies"))
                if isinstance(o, NXOpen.Body) and cast(NXOpen.Body, o).IsSolidBody]


def main() -> None:
    """The flange-up UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            # The Flange Up dialog asks for the customer and stands in for the "Are you sure" box.
            FlangeUp.execute(True)
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
