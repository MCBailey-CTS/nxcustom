"""
Python port of the split-form UFunc (Merlin.StaticGmSplitForm / Merlin.BuildGmSplitForm -> Merlin.CreateSplitForm,
src\\UFuncs\\Merlin.cs, regions "Static Entry Points - GM Component / Split / Form Pad" and "Builders - Form Pad,
Component & Split").

The split-form UFunc is this file: its NX menu button runs main(), which opens SplitFormDialog.py (Upper /
Lower, Rows, Cols, one solid body), which calls SplitForm.execute_with. There is no C# UFunc around it (the
MerlinUFuncs\\GmSplitForm.cs wrapper was deleted 2026-10-22; in git at 07dcca8), so main() records the run in
tblUFuncsExe itself through usage_db.py. The AutoSize UDO class is registered at NX startup. execute() still asks with
menus - the station from the work part (uad/upd/ush/usp or lad/lsh/lsp), the bodies, then a split count (2/3/4/5). The box, +.375" on every
side (each span rounded up to 1/8"), is cut along Y into Rows blocks and along X into Cols, .004" apart both ways.
The blocks are sized off each picked body's component's UPR-3D (upper) / LWR-3D (lower) solids rather than the picked
bodies, with their Z off the part: at least 2.75" over its highest point (upper) or under its lowest (lower)
(_compute_refset_block_dimensions; the C# built 8" blocks from Z -4). Each block is a different random split color
(Merlin's SplitComponentColors, without replacement; the C# colored them all 140).
Each block, in turn:
  - its mounting face (+Z upper / -Z lower) and the faces bounding a gap colored 42;
  - promoted to [cts-]split-form, re-based onto the block (the opposite corner for an upper);
  - station expressions, BODY reference set, DYNAMIC BLOCK, DESCRIPTION (the whole box's X x Y x the bodies' height)
    and MATERIAL ##, a SUBTOOL on layer 15 (hidden);
  - 4 16mm-shcs-060-2x .75" in from the corners (CBORE), linked and subtracted from the block, its bottom face 42;
  - 4 keys around its edges (Merlin.PlaceSplitKeys) on layer 99, added to BODY;
  - the AutoSize UDO, BODY in the station, the UPR-3D / LWR-3D reference set of each picked body's component linked
    and subtracted, DETAIL NAME FORM STEEL / MATERIAL D2, BODY in every loaded ancestor assembly.
After the loop the library key part is Save As'd as [cts-]split-form-key-{token}.prt (a debug copy, kept).

The dialog's two boxes make it the old split-form-with-plate and split-form-with-plate-backside too (combined
2026-10-22; those UFunc names stay, as legacy entries opening this dialog pre-checked - SplitFormWithPlate.py /
SplitFormWithPlateBackside.py and their C# wrappers):
  - Backing Plate: first the sub plate (_create_backside_backing_plate), [cts-]split-form-backing-plate; the
    corner SHCS are 16mm-shcs-050-2x; each block's first key is Save As'd in the loop instead of the library key after.
  - SHCS From Backside (only with the plate): the corner SHCS 1" in, SHORT-TAP, from the mounting face up into the
    plate instead of down through the block.
The with-plate port's GM-post keys and identity block orientation were dropped for the split keys and the absolute
csys; every mode names its blocks [cts-]split-form and prints "complete -> {elapsed}".

Two ways in:
  - The split-form menu button (or File -> Execute -> NX Open) on this file runs main(): the SplitFormDialog
    with is_gm = True, recorded as a split-form run.
  - Session.Execute("SplitForm.py", "SplitForm", "execute_with", is_gm, is_upper, rows, cols, bodies) - what
    the dialog calls once it is accepted.
  - Session.Execute("SplitForm.py", "SplitForm", "execute", is_gm) from C#.

This module also holds the Merlin helpers the four split / component ports share (Component.py,
SplitFormWithPlateBackside.py and SplitFormWithPlate.py import them from here): TryBeginGmEntry,
TryPickSplitCount / TryMenuIndex, ComputeBlockDimensions, PromoteToComponent, SubtractAndRefsetFasteners,
SubtractComponents, ParseBooleanOperation, PlaceSplitKeys, FindBottomFace, ColorFace, AddCornerFasteners and
CreateBacksideBackingPlate.

Differences from the C#:
  - The body pick is the NXOpen SelectionManager with a body mask (DrawDie._select_bodies) instead of the SNAP
    picker. The solid-only pick (Component) drops sheet bodies after the pick instead of refusing them in the
    dialog; a pick left empty returns, as a cancelled one does.
  - ComputeBlockDimensions takes the box with tsg_nx.body_box per body, combined. The C# creates an NXOpen.Point on
    each box corner in the display part, takes their min/max and deletes them - the same box, without the temporary
    points.
  - The split count menu is UF_UI_display_menu through the Python UF binding (DisplayMenu is missing from the
    hand-written stubs, so it is called through typing.Any).
  - A picked body that belongs to no component puts None in the component set, as the C# puts null; the subtract
    raises on it (the C# throws a NullReferenceException there) and the surrounding handler prints it.
  - GFolder.create_or_null (print-only, result unused) is not ported.
  - The AutoSize UDO class can only be registered from C# (see tsg_nx.create_auto_size_udo). Run standalone in a
    session where TSG_Library never registered it, the blocks get no UDO - it prints and carries on.

The Merlin helpers DrawDie.py, PointComponent.py and CastTrimPad.py already port are imported from them rather than
copied.
"""

from __future__ import annotations

import datetime
import os
import random
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

import tsg_nx as nx  # noqa: E402
import PointComponent as merlin  # noqa: E402
import DrawDie as drawdie  # noqa: E402
import CastTrimPad as trimpad  # noqa: E402

# ---------------------------------------------------------------------------------------------------
# Constants (Merlin's, inches unless the name says otherwise)
# ---------------------------------------------------------------------------------------------------

# ComputeBlockDimensions' offset as every split / component builder passes it.
SplitFormOffset = .375
SplitFormHeight = 8
SplitFormColor = 140

# The form steel's minimum thickness past the part, off UPR-3D / LWR-3D: under its lowest point (lower) or over its
# highest (upper) - the draw die cavity's 2.75". Sets the block's Z for the dialog-driven split forms.
FormSteelMinThickness = 2.75

# The local `const double gap = 0.004` each split builder declares.
SplitFormGap = 0.004

# SHCS From Backside: the corner SHCS's inset, as Merlin.CreateSplitFormWithPlateBackside set it.
BacksideShcsInset = 1.0

_gmKeyPath = "G:\\0Library\\0Customer\\GM\\Smart GM Key.prt"
_ctsSmartKeyMetric = "G:\\0Library\\Keys\\Smart Key Metric.prt"
_shcs16mm050Path = "G:\\0Library\\Fasteners\\Metric\\SocketHeadCapScrews-2X\\016-2x\\16mm-shcs-050-2x.prt"
_shcs16mm060Path = "G:\\0Library\\Fasteners\\Metric\\SocketHeadCapScrews-2X\\016-2x\\16mm-shcs-060-2x.prt"
_dwl12mm050Path = "G:\\0Library\\Fasteners\\Metric\\Dowels\\12mm-dwl-050.prt"
_gmHoistRingPath = "G:\\0Library\\0Customer\\GM\\GM 16MM DIA PLDW Hoist Ring.prt"

_VectorX = NXOpen.Vector3d(1.0, 0.0, 0.0)
_VectorY = NXOpen.Vector3d(0.0, 1.0, 0.0)
_VectorZ = NXOpen.Vector3d(0.0, 0.0, 1.0)
_VectorXN = NXOpen.Vector3d(-1.0, 0.0, 0.0)
_VectorYN = NXOpen.Vector3d(0.0, -1.0, 0.0)
_VectorZN = NXOpen.Vector3d(0.0, 0.0, -1.0)


class SplitForm(object):

    @staticmethod
    def execute(is_gm: bool = True) -> None:
        """Merlin.StaticGmSplitForm(is_gm) - the menus (main() runs the dialog instead)."""
        static_gm_split_form(is_gm)

    @staticmethod
    def execute_with(is_gm: bool, is_upper: bool, rows: int, cols: int,
                     bodies: Sequence[NXOpen.TaggedObject], plate: bool = False, backside: bool = False,
                     size_off_bodies: bool = False) -> None:
        """
        The split-form UFunc's entry, after its SplitFormDialog: the assembly (upper / lower), the rows x cols
        grid, the body and the Backing Plate / SHCS From Backside boxes come from the dialog. backside only counts
        with plate. size_off_bodies sizes the blocks off the bodies rather than UPR-3D / LWR-3D (dead strike).
        """
        picked = [cast(NXOpen.Body, b) for b in bodies if b is not None]
        if _begin_from_dialog("Split Form", picked):
            build_gm_split_form(is_gm, is_upper, picked, rows, _form_steel_refset(is_upper), cols, bool(plate),
                                bool(plate) and bool(backside), bool(size_off_bodies))


def static_gm_split_form(is_gm: bool) -> None:
    """Merlin.StaticGmSplitForm - TryBeginGmEntry, the split-count menu, then the build."""
    entry = _try_begin_gm_entry("Split Form", solid_only=False)
    if entry is None:
        return
    is_upper, bodies, reference_set = entry

    splits = _try_pick_split_count()
    if splits is None:
        return

    build_gm_split_form(is_gm, is_upper, bodies, splits, reference_set)


def build_gm_split_form(is_gm: bool, is_upper: bool, bodies: Sequence[NXOpen.Body], splits: int,
                        reference_set: str, columns: int = 1, plate: bool = False, backside: bool = False,
                        size_off_bodies: bool = False) -> None:
    """
    Merlin.BuildGmSplitForm - a columns x splits split form over bodies, subtracting reference_set, optionally on a
    backing plate (plate) screwed from the plate's side (backside). Builds into the work part's station, as the entry
    point does.
    """
    start = datetime.datetime.now()
    top_level = nx.display_part()
    starting_work = nx.work_part()
    nx.set_display_part(nx.work_part())

    with nx.suppress_display():
        _create_split_form(is_upper, top_level, starting_work, list(bodies), SplitFormOffset, splits, reference_set,
                           is_gm, columns, plate, backside, size_off_bodies)

    nx.info("complete -> {}".format(drawdie._time_span(datetime.datetime.now() - start)))


def _create_split_form(is_upper: bool, top_level: NXOpen.Part, start_work: NXOpen.Part,
                       selected_bodies: List[NXOpen.Body], offset: float, splits: int, reference_sets: str,
                       is_gm: bool, columns: int = 1, plate: bool = False, backside: bool = False,
                       size_off_bodies: bool = False) -> None:
    """
    Merlin.CreateSplitForm, changed (2026-10-21): splits rows along Y by columns along X, sized and set in Z off
    UPR-3D / LWR-3D (_compute_refset_block_dimensions), each block a different random split color.

    Since 2026-10-22 it is also the with-plate and with-plate-backside builders (Merlin.CreateSplitFormWithPlate /
    CreateSplitFormWithPlateBackside), which differed only in:
      - plate: the sub plate (_create_backside_backing_plate) first, [cts-]split-form-backing-plate;
      - the corner SHCS: no plate 16mm-shcs-060-2x, plate 16mm-shcs-050-2x, both .75" in, CBORE, from the mounting
        face into the block; backside 16mm-shcs-050-2x 1" in, SHORT-TAP, from the mounting face into the plate;
      - the key debug copy: no plate the library key once after the loop, plate each block's first key.
    The with-plate builder's GM-post keys (PlaceGmPostUpper/LowerKeys1) and identity block orientation were dropped
    for the split keys and the absolute csys the other two used; every mode names its blocks [cts-]split-form.
    """
    try:
        if len(selected_bodies) == 0:
            nx.print_("No bodies selected")
            return

        nx.display_part().Layers.WorkLayer = 1
        # Before the measuring, which kills the picked body occurrences.
        selected_components = _owning_components(selected_bodies)
        dimensions = _compute_refset_block_dimensions("Split Form", selected_bodies, selected_components,
                                                      is_upper, offset, size_off_bodies)
        if dimensions is None:
            return
        xlength, ywidth, height, block_origin, block_z = dimensions

        orientation = _absolute_csys_orientation(nx.display_part())
        grid = _create_grid_blocks(block_origin, orientation, xlength, ywidth, splits, columns, block_z)
        if grid is None:
            return
        column_width, block_height, blocks = grid
        colors = _split_colors()
        prefix = "" if is_gm else "cts-"

        if plate:
            _create_backside_backing_plate(is_upper, xlength, ywidth, block_origin, nx.display_part(), top_level,
                                           "{}split-form-backing-plate".format(prefix), is_gm, block_z)

        # Into the block from its mounting face (CBORE, head in the block), or with the backside plate out of it into
        # the plate (SHORT-TAP, head in the plate).
        if backside:
            shcs_path, shcs_refset, inset = _shcs16mm050Path, "SHORT-TAP", BacksideShcsInset
        else:
            shcs_path, shcs_refset, inset = (_shcs16mm050Path if plate else _shcs16mm060Path), "CBORE", .750
        shcs_normal = (_VectorZ if is_upper else _VectorZN) if backside else (_VectorZN if is_upper else _VectorZ)
        fastener_orientation = drawdie._z_matrix(shcs_normal)

        for block_index, (column, row, block) in enumerate(blocks):
            try:
                nx.set_work_part(start_work)
                block_body = block.GetBodies()[0]
                nx.set_color(block_body, colors[block_index % len(colors)])
                face = _first_planar_face(block_body, _VectorZ if is_upper else _VectorZN)
                nx.set_color(face, 42)
                _color_grid_joints(block_body, column, row, columns, splits)

                # Origin on this block's own corner rather than the assembly's (the opposite corner for an upper).
                new_part, new_component = _promote_to_component(block, _description(xlength, ywidth, height),
                                                                "{}split-form".format(prefix), rebase_to_block=True,
                                                                opposite_corner=is_upper)
                bottom_face = _find_bottom_face()
                box = nx.body_box(trimpad._single_solid_body_on_layer1(nx.display_part()))
                body_reference_set = _find_reference_set(nx.display_part(), "BODY")

                # The mounting face: the top of an upper, the bottom of a lower.
                fastener_z = box.MaxZ if is_upper else box.MinZ
                fastener_origins = [
                    _add(NXOpen.Point3d(box.MinX, box.MinY, fastener_z), inset, inset, 0),
                    _add(NXOpen.Point3d(box.MaxX, box.MinY, fastener_z), -inset, inset, 0),
                    _add(NXOpen.Point3d(box.MaxX, box.MaxY, fastener_z), -inset, -inset, 0),
                    _add(NXOpen.Point3d(box.MinX, box.MaxY, fastener_z), inset, -inset, 0),
                ]

                fasteners = [nx.add_component(nx.display_part(), shcs_path, reference_set=shcs_refset, origin=o,
                                              orientation=fastener_orientation, layer=99)
                             for o in fastener_origins]

                _subtract_and_refset_fasteners(fasteners, bottom_face, body_reference_set)
                current_wcs = nx.display_part().WCS.CoordinateSystem.Orientation.Element
                # The fasteners above measure from `box`, re-read off the body, so they self-correct. The keys are
                # the one thing that measured from the assembly-space stack position - after the re-base each
                # block's own corner is its part's origin.
                this_block_origin = NXOpen.Point3d(0.0, 0.0, 0.0)
                keys = _place_split_keys(is_upper, column_width, this_block_origin, block_height, is_gm, layer=99,
                                         block_z=block_z)
                nx.display_part().WCS.SetOriginAndMatrix(NXOpen.Point3d(0.0, 0.0, 0.0), current_wcs)
                body_reference_set.AddObjectsToReferenceSet(keys)
                if plate:
                    nx.prototype(keys[0]).SaveAs("{}\\{}split-form-key-{}.prt".format(
                        os.path.dirname(nx.display_part().FullPath), prefix, merlin._random_file_token()))
                nx.create_auto_size_udo(nx.work_part())
                nx.work_part().Layers.WorkLayer = 1
                nx.set_display_part(top_level)
                nx.set_reference_set(new_component, "BODY")
                nx.find_or_create_reference_set(new_component.OwningPart, "BODY").AddObjectsToReferenceSet(
                    [new_component])
                nx.set_work_part(new_part)
                _subtract_components(lambda: nx.dynamic_block(nx.work_part()).GetBodies()[0], selected_components,
                                     reference_sets)
                nx.set_attribute(nx.prototype(new_component), "DETAIL NAME", "FORM STEEL")
                nx.set_attribute(nx.prototype(new_component), "MATERIAL", "D2")
                nx.set_reference_set(new_component, "BODY")
                # Propagate BODY as the used reference set to every ancestor assembly (start_work .. -000).
                merlin._set_reference_set_in_ancestor_assemblies(nx.first_occurrence_in(new_part, top_level))
                new_component.Unblank()
                nx.set_display_part(start_work)
            except Exception as ex:
                nx.print_exception(ex)

        # With a plate each block's first key was Save As'd in the loop.
        if not plate:
            nx.find_or_open(_gmKeyPath if is_gm else _ctsSmartKeyMetric).SaveAs("{}\\{}split-form-key-{}.prt".format(
                os.path.dirname(nx.display_part().FullPath), prefix, merlin._random_file_token()))
    except Exception as ex:
        nx.print_exception(ex)
    finally:
        nx.set_display_part(top_level)
        nx.set_work_part(start_work)


# ---------------------------------------------------------------------------------------------------
# Entry-point helpers (shared with Component / SplitFormWithPlateBackside / SplitFormWithPlate)
# ---------------------------------------------------------------------------------------------------

def _try_begin_gm_entry(label: str, solid_only: bool) -> Optional[Tuple[bool, List[NXOpen.Body], str]]:
    """
    Merlin.TryBeginGmEntry - gates on CheckInfoUnits + TryDetectIsUpper, selects bodies (solid-only when solid_only),
    derives UPR-3D / LWR-3D and sets the display part's WCS to absolute. Returns (is_upper, bodies, reference_set),
    or None on any gate failure or cancel. The caller captures the display/work parts.
    """
    ok, message = drawdie._check_info_units()
    if not ok:
        nx.show_error(message)
        return None

    is_upper = trimpad._try_detect_is_upper()
    if is_upper is None:
        return None

    version = nx.assembly_file_version()
    bodies = drawdie._select_bodies("Select solid bodies for {}: {}".format(label, version),
                                    "{}: {}".format(label, version))
    if solid_only:
        bodies = [body for body in bodies if body.IsSolidBody]
    if len(bodies) == 0:
        return None

    reference_set = "UPR-3D" if is_upper else "LWR-3D"
    drawdie._set_wcs_to_absolute(nx.display_part())
    return is_upper, bodies, reference_set


def _try_pick_split_count() -> Optional[int]:
    """Merlin.TryPickSplitCount - a 2/3/4/5 menu; None if the user cancels or backs out."""
    options = ["2", "3", "4", "5"]
    # DisplayMenu is not in the hand-written UFUi stub.
    selected = cast(Any, nx.ufsession_.Ui).DisplayMenu("Select number of splits", 0, options, len(options))
    index = _try_menu_index(int(selected), len(options))
    if index is None:
        return None
    return int(options[index])


def _try_menu_index(response: int, item_count: int) -> Optional[int]:
    """
    Merlin.TryMenuIndex - UF_UI_display_menu's response as a zero-based item index (items start at 5); None for
    back / cancel and anything else outside the item range.
    """
    index = response - 5
    return index if 0 <= index < item_count else None


# ---------------------------------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------------------------------

def _compute_block_dimensions(bodies: Sequence[NXOpen.Body],
                              offset: float) -> Tuple[float, float, float, NXOpen.Point3d]:
    """
    Merlin.ComputeBlockDimensions - (xlength, ywidth, height, block_origin): the bodies' combined box, each span
    rounded up to 1/8" plus offset on each side, centred on the box, block Z always -4. height is the bodies' own Z
    span.
    """
    box = nx.combine_boxes(nx.body_box(body) for body in bodies)
    length = box.MaxX - box.MinX
    width = box.MaxY - box.MinY
    height = box.MaxZ - box.MinZ
    xlength = nx.round_to_125(length) + offset * 2
    ywidth = nx.round_to_125(width) + offset * 2
    block_origin = NXOpen.Point3d(box.MinX - (xlength - length) / 2, box.MinY - (ywidth - width) / 2, -4.0)
    return xlength, ywidth, height, block_origin


# ---------------------------------------------------------------------------------------------------
# The split forms off their dialog (SplitFormDialog): UPR-3D / LWR-3D sizing, a rows x cols grid, random colors
# ---------------------------------------------------------------------------------------------------

def _form_steel_refset(is_upper: bool) -> str:
    """The reference set the form steel is sized off and subtracts: UPR-3D for an upper, LWR-3D for a lower."""
    return "UPR-3D" if is_upper else "LWR-3D"


def _begin_from_dialog(label: str, bodies: List[NXOpen.Body]) -> bool:
    """
    The part of TryBeginGmEntry the dialog does not do: the units gate, a non-empty pick and the display part's WCS
    to absolute. False when the run should stop.
    """
    ok, message = drawdie._check_info_units()
    if not ok:
        nx.show_error(message)
        return False

    if len(bodies) == 0:
        nx.print_("{}: no body was passed in - nothing built.".format(label))
        return False

    drawdie._set_wcs_to_absolute(nx.display_part())
    return True


def _compute_refset_block_dimensions(label: str, bodies: Sequence[NXOpen.Body],
                                     components: Sequence[Optional[NXOpen.Assemblies.Component]], is_upper: bool,
                                     offset: float, size_off_bodies: bool = False
                                     ) -> Optional[Tuple[float, float, float, NXOpen.Point3d, float]]:
    """
    (xlength, ywidth, height, block_origin, block_z) for the split forms. Like _compute_block_dimensions (each span
    rounded up to 1/8" plus offset a side, centred), but measured off each picked body's component's UPR-3D (upper)
    or LWR-3D (lower) solids rather than the picked bodies, and with the block's Z taken from the part:
    block_z = the part's Z span + FormSteelMinThickness, rounded up to 1/8" - a lower's top at the part's highest
    point, so its bottom is at least 2.75" under the lowest; an upper's bottom at the part's lowest point, so its top
    is at least 2.75" over the highest. height is the part's Z span (the DESCRIPTION's third number).

    size_off_bodies (dead strike) measures the picked bodies themselves and never the reference set: a strip
    layout's UPR-3D / LWR-3D can be a tool body - the die surface extruded ~20" and wider than the part - which made
    26" tall blocks, and a footprint wider than the tool body left a thin wall standing round the subtract.

    A component without the reference set uses its picked bodies, after one Question box (No -> None). Measuring
    switches each component's reference set and back, which kills the picked body occurrences, so components must be
    taken off the bodies before this is called.
    """
    refset = _form_steel_refset(is_upper)

    # The picked bodies' boxes first, while the occurrences are alive - the fallback for a component without refset.
    picked: dict = {}
    loose: List[nx.Box3d] = []
    for body in bodies:
        box = nx.body_box(body)
        owner = body.OwningComponent
        if owner is None:
            loose.append(box)
        else:
            picked[owner.Tag] = nx.combine_boxes([picked.get(owner.Tag), box])

    owners = [c for c in components if c is not None]
    if size_off_bodies:
        refset = "the picked bodies"
        box = nx.combine_boxes(loose + list(picked.values()))
    else:
        if not nx.confirm_missing_reference_sets(label, "The form steel is sized off {}".format(refset), owners,
                                                 [refset]):
            return None
        box = nx.combine_boxes(loose + [nx.reference_set_box(c, refset, label) or picked[c.Tag] for c in owners])

    xlength, ywidth, height, block_origin, block_z = _block_dimensions(box, is_upper, offset)
    min_z = block_origin.Z

    nx.info("{}: {} Z {} .. {} - form steel Z {} .. {} ({}\" {} the part)".format(
        label, refset, drawdie._f3(box.MinZ), drawdie._f3(box.MaxZ), drawdie._f3(min_z),
        drawdie._f3(min_z + block_z), FormSteelMinThickness, "over" if is_upper else "under"))
    return xlength, ywidth, height, block_origin, block_z


def _block_dimensions(box: nx.Box3d, is_upper: bool, offset: float
                      ) -> Tuple[float, float, float, NXOpen.Point3d, float]:
    """
    (xlength, ywidth, height, block_origin, block_z) off the part's box: each span rounded up to 1/8" plus offset a
    side, centred; block_z the part's Z span + FormSteelMinThickness rounded up to 1/8", a lower's top at the part's
    highest point, an upper's bottom at its lowest.
    """
    length = box.MaxX - box.MinX
    width = box.MaxY - box.MinY
    height = box.MaxZ - box.MinZ
    xlength = nx.round_to_125(length) + offset * 2
    ywidth = nx.round_to_125(width) + offset * 2
    block_z = nx.round_to_125(height + FormSteelMinThickness)
    min_z = box.MinZ if is_upper else box.MaxZ - block_z
    block_origin = NXOpen.Point3d(box.MinX - (xlength - length) / 2, box.MinY - (ywidth - width) / 2, min_z)
    return xlength, ywidth, height, block_origin, block_z


def _grid_cells(block_origin: NXOpen.Point3d, xlength: float, ywidth: float, rows: int, cols: int
                ) -> Optional[Tuple[float, float, List[Tuple[int, int, NXOpen.Point3d]]]]:
    """
    The box cut into rows along Y by cols along X, SplitFormGap apart both ways, column by column:
    (column_width, row_width, [(column, row, cell origin)]). None when the box is too small.
    """
    gap = SplitFormGap
    row_width = (ywidth - (rows - 1) * gap) / rows
    column_width = (xlength - (cols - 1) * gap) / cols

    if column_width <= 0 or row_width <= 0:
        return None

    cells = [(column, row, _add(block_origin, column * (column_width + gap), row * (row_width + gap), 0.0))
             for column in range(cols)
             for row in range(rows)]
    return column_width, row_width, cells


def _create_grid_blocks(block_origin: NXOpen.Point3d, orientation: NXOpen.Matrix3x3, xlength: float, ywidth: float,
                        rows: int, cols: int, block_z: float
                        ) -> Optional[Tuple[float, float, List[Tuple[int, int, NXOpen.Features.Block]]]]:
    """
    The box cut into rows along Y by cols along X (_grid_cells), like the draw die's form steels:
    (column_width, row_width, [(column, row, block)]). None (printed) when the box is too small.
    """
    grid = _grid_cells(block_origin, xlength, ywidth, rows, cols)
    if grid is None:
        nx.print_("{} x {} is too small to split {} x {}.".format(drawdie._f3(xlength), drawdie._f3(ywidth), cols,
                                                                 rows))
        return None

    column_width, row_width, cells = grid
    blocks = [(column, row, _create_block(origin, orientation, column_width, row_width, block_z))
              for column, row, origin in cells]
    return column_width, row_width, blocks


def preview_boxes(box: nx.Box3d, is_upper: bool, rows: int, cols: int, plate: bool = True
                  ) -> List[Tuple[NXOpen.Point3d, float, float, float]]:
    """
    The (origin, x, y, z) boxes a size_off_bodies split form over a part box builds, in the coordinates the build
    uses (the station's): each grid block, then the backing plate (_create_backside_backing_plate's offsets) when
    plate. Empty when the box is too small to split. Dead Strike's dialog draws them.
    """
    xlength, ywidth, _height, block_origin, block_z = _block_dimensions(box, is_upper, SplitFormOffset)
    grid = _grid_cells(block_origin, xlength, ywidth, rows, cols)
    if grid is None:
        return []
    column_width, row_width, cells = grid
    boxes = [(origin, column_width, row_width, block_z) for _column, _row, origin in cells]
    if plate:
        boxes.append((_add(block_origin, -1.375, -2.75, block_z if is_upper else -1.5),
                      xlength + 1.375 * 2, ywidth + 2.75 * 2, 1.5))
    return boxes


def _split_colors() -> List[int]:
    """Merlin's split colors in a random order, drawn without replacement (BuildPointComponent, the form steels)."""
    return random.sample(merlin.SplitComponentColors, len(merlin.SplitComponentColors))


def _color_grid_joints(body: NXOpen.Body, column: int, row: int, cols: int, rows: int) -> None:
    """Colors 42 every face of a grid block that bounds a gap: +/-Y between rows, +/-X between columns."""
    if row < rows - 1:
        nx.set_color(_first_planar_face(body, _VectorY), 42)
    if row > 0:
        nx.set_color(_first_planar_face(body, _VectorYN), 42)
    if column < cols - 1:
        nx.set_color(_first_planar_face(body, _VectorX), 42)
    if column > 0:
        nx.set_color(_first_planar_face(body, _VectorXN), 42)


def _promote_to_component(block: NXOpen.Features.Block, description: str, text: str, rebase_to_block: bool = False,
                          opposite_corner: bool = False) -> Tuple[NXOpen.Part, NXOpen.Assemblies.Component]:
    """
    Merlin.PromoteToComponent - CreateCtsComponent, optional re-base onto the block, station expressions, BODY
    reference set, DYNAMIC BLOCK, DESCRIPTION / MATERIAL ##, and a SUBTOOL on layer 15 (hidden). Returns the new part
    (the display part) and the component.
    """
    component = merlin._create_cts_component(block, text)
    if rebase_to_block:
        drawdie._rebase_block_to_part_origin(component, cast(NXOpen.Part, component.OwningPart),
                                             opposite_corner=opposite_corner)
    nx.setup_station_expressions(nx.work_part())
    refset = _find_or_create_reference_set_quiet(nx.display_part(), "BODY")
    refset.AddObjectsToReferenceSet(list(nx.display_part().Bodies))
    new_part = nx.display_part()
    _first_block_feature(new_part).SetName("DYNAMIC BLOCK")
    nx.set_attribute(new_part, "DESCRIPTION", description)
    nx.set_attribute(new_part, "MATERIAL", "##")
    new_part.Layers.WorkLayer = 15
    merlin._create_subtool(new_part)
    new_part.Layers.WorkLayer = 1
    new_part.Layers.SetState(15, NXOpen.Layer.State.Hidden)
    return new_part, component


def _subtract_and_refset_fasteners(fasteners: Sequence[NXOpen.Assemblies.Component], bottom_face: NXOpen.Face,
                                   body_refset: Optional[NXOpen.ReferenceSet]) -> None:
    """
    Merlin.SubtractAndRefsetFasteners - work layer 96; per fastener: link it on the reference set it arrived on,
    subtract from bottom_face's body, stamp `subtract`; layer-98 fasteners go to Empty, the rest to BODY and into
    body_refset (None leaves them out).
    """
    nx.display_part().Layers.WorkLayer = 96
    for fastener in fasteners:
        try:
            # The fastener arrives on the reference set it is subtracted with (CBORE, SHORT-TAP, ...).
            subtract_refset = fastener.ReferenceSet
            link = nx.create_linked_body(fastener)
            _subtract_linked_body(nx.display_part(), bottom_face.GetBody(), link)
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


def _subtract_components(get_target: Callable[[], NXOpen.Body],
                         components: Iterable[Optional[NXOpen.Assemblies.Component]], refset: str) -> None:
    """
    Merlin.SubtractComponents - per component: skip with a print unless it has refset, switch to it, skip with a
    print when it carries no solid body, link it into the work part and subtract it from get_target() (re-fetched each
    time), restore BODY. A failed boolean (3520001) prints a line before the exception; any other failure prints and
    moves on. Unlike PointComponent._subtract_components this keeps the C#'s solid-body check.
    """
    for comp in components:
        if comp is None:
            # The C# reads comp.__Prototype() outside its try, so a null component throws out of the loop.
            raise RuntimeError("Object reference not set to an instance of an object (a selected body has no "
                               "owning component).")

        if not nx.has_reference_set(nx.prototype(comp), refset):
            nx.warn("Component {} does not have reference set {}, skipping boolean".format(comp.DisplayName, refset))
            continue

        try:
            nx.set_reference_set(comp, refset)

            # Only solid bodies are linked - a reference set holding nothing but sheets would otherwise fail in the
            # boolean with an error that does not say why.
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


def _parse_boolean_operation(item: str) -> Tuple[str, NXOpen.Features.Feature.BooleanType]:
    """Merlin.ParseBooleanOperation - strips (SUB) / (INT); Subtract / Intersect / otherwise Unite."""
    refset = item.replace("(SUB)", "").replace("(INT)", "").strip()
    if "(SUB)" in item:
        boolean_type = NXOpen.Features.Feature.BooleanType.Subtract
    elif "(INT)" in item:
        boolean_type = NXOpen.Features.Feature.BooleanType.Intersect
    else:
        boolean_type = NXOpen.Features.Feature.BooleanType.Unite
    return refset, boolean_type


def _place_split_keys(is_upper: bool, xlength: float, this_block_origin: NXOpen.Point3d, block_height: float,
                      is_gm: bool, layer: int = 1, block_z: float = SplitFormHeight) -> List[NXOpen.Assemblies.Component]:
    """
    Merlin.PlaceSplitKeys - PlaceEdgeItems with the GM / CTS key, x_edge_inset 2.4498 and the .0748 front/back nudge
    on GM only. The caller saves and restores the WCS (an upper rotates it). An upper's keys sit on top of the block,
    block_z up (PlaceEdgeItems assumes the old 8").
    """
    return drawdie._place_edge_items(_gmKeyPath if is_gm else _ctsSmartKeyMetric, this_block_origin, xlength,
                                     block_height, is_upper, front_back_nudge=0.0748 if is_gm else 0.0,
                                     x_edge_inset=2.4498, extra_z=block_z - SplitFormHeight if is_upper else 0.0,
                                     layer=layer)


def _find_bottom_face() -> NXOpen.Face:
    """Merlin.FindBottomFace - the -Z planar face of the display part's layer-1 solid, colored 42."""
    bottom_face = _first_planar_face(trimpad._single_solid_body_on_layer1(nx.display_part()), _VectorZN)
    nx.set_color(bottom_face, 42)
    return bottom_face


def _color_face(color: int, normal: NXOpen.Vector3d) -> None:
    """Merlin.ColorFace - colors the layer-1 solid's planar face with that normal, when there is one (no redisplay)."""
    body = trimpad._single_solid_body_on_layer1(nx.display_part())
    face = nx.planar_face_with_normal_or_null(body, normal)
    if face is not None:
        face.Color = color


def _add_corner_fasteners(block_min: NXOpen.Point3d, block_max: NXOpen.Point3d, normal_z: NXOpen.Vector3d,
                          z: float, path: str, corner_offset: float = 1.125,
                          z_adjust: float = 0.0) -> List[NXOpen.Assemblies.Component]:
    """Merlin.AddCornerFasteners - 4 corner components (BODY, layer 99) corner_offset in, at z + z_adjust."""
    orientation = drawdie._z_matrix(normal_z)
    points = [
        _add(NXOpen.Point3d(block_min.X + corner_offset, block_min.Y + corner_offset, z), 0, 0, z_adjust),
        _add(NXOpen.Point3d(block_max.X - corner_offset, block_min.Y + corner_offset, z), 0, 0, z_adjust),
        _add(NXOpen.Point3d(block_max.X - corner_offset, block_max.Y - corner_offset, z), 0, 0, z_adjust),
        _add(NXOpen.Point3d(block_min.X + corner_offset, block_max.Y - corner_offset, z), 0, 0, z_adjust),
    ]
    return [nx.add_component(nx.display_part(), path, reference_set="BODY", origin=pt, orientation=orientation,
                             layer=99)
            for pt in points]


def _create_backside_backing_plate(is_upper: bool, xlength: float, ywidth: float, block_origin: NXOpen.Point3d,
                                   owning_part: NXOpen.Part, top_level: NXOpen.Part, name_prefix: str,
                                   is_gm: bool, block_z: float = SplitFormHeight) -> None:
    """
    Merlin.CreateBacksideBackingPlate - the sub plate shared by the split-form-with-plate builders: 1.5" thick,
    padded 1.375" in X and 2.75" in Y around the component block, on top of it (block_z up, 8" in the C#) for an
    upper or 1.5" down from it for a lower; a
    SUBTOOL and BODY; 4 side keys (the first Save As'd as {name_prefix}-key-{token}.prt); a 5x2 grid of CBORE
    16mm-shcs-050-2x subtracted from it; 4 corner hoist rings (GM-only path). DETAIL NAME SUB PLATE, MATERIAL HRS PLT.
    Leaves the display part on top_level and the plate in owning_part's BODY reference set.
    """
    block1 = _create_block(_add(block_origin, -1.375, -2.75, block_z if is_upper else -1.5), nx.identity_matrix(),
                           xlength + 1.375 * 2, ywidth + 2.75 * 2, 1.5)
    block1.SetName("DYNAMIC BLOCK")
    backing_plate = drawdie._create_new_component_core(
        name_prefix,
        [block1.GetBodies()[0]],
        NXOpen.Assemblies.CreateNewComponentBuilder.ComponentOriginType.Absolute,
        NXOpen.Assemblies.CreateNewComponentBuilder.ComponentLayerOptionType.AsSpecified,
        layer_number=1,
        original_objects_deleted=True,
        auto_size_udo=True)

    # Origin on the plate block's corner rather than the assembly's. Before the subtool below, so the extract is
    # taken at the final position. The plate is built at the absolute orientation, so this is a pure translation.
    drawdie._rebase_block_to_part_origin(backing_plate, cast(NXOpen.Part, backing_plate.OwningPart),
                                         opposite_corner=is_upper)
    nx.setup_station_expressions(nx.prototype(backing_plate))

    # Everything below measures from block_origin, the *component* block's corner, not this plate's. The plate is
    # built 1.375 out in X, 2.75 out in Y and block_z up (upper) or 1.5 down (lower) from it, so after the re-base
    # block_origin sits at the negation of that offset.
    block_origin = NXOpen.Point3d(1.375, 2.75, -block_z if is_upper else 1.5)

    nx.set_attribute(nx.prototype(backing_plate), "DETAIL NAME", "SUB PLATE")
    nx.set_attribute(nx.prototype(backing_plate), "MATERIAL", "HRS PLT")

    display = nx.display_part()
    display.Layers.WorkLayer = 15
    merlin._create_subtool(display)
    display.Layers.WorkLayer = 1

    bp_body_refset = _find_or_create_reference_set_quiet(nx.display_part(), "BODY")
    bp_body_refset.AddObjectsToReferenceSet([trimpad._single_solid_body_on_layer1(nx.display_part())])

    _color_face(42, _VectorZ)
    bp_bottom_face = _find_bottom_face()

    bp_key_path = _gmKeyPath if is_gm else _ctsSmartKeyMetric
    bp_side_key_matrix = (nx.matrix_from_axes(_VectorYN, _VectorXN) if is_upper
                          else nx.matrix_from_axes(_VectorYN, _VectorX))
    bp_side_x_key_matrix = nx.matrix_from_axes(_VectorX, _VectorYN) if is_upper else nx.identity_matrix()
    key_z = block_z + 1.5 if is_upper else -1.5
    bp_keys = [
        nx.add_component(nx.display_part(), bp_key_path, reference_set="BODY",
                         origin=_add(block_origin, xlength / 2, -1.25 + (0.0748 if is_gm else 0), key_z),
                         orientation=bp_side_key_matrix, layer=99),
        nx.add_component(nx.display_part(), bp_key_path, reference_set="BODY",
                         origin=_add(block_origin, xlength / 2, ywidth + 1.25 + (-0.0748 if is_gm else 0), key_z),
                         orientation=bp_side_key_matrix, layer=99),
        nx.add_component(nx.display_part(), bp_key_path, reference_set="BODY",
                         origin=_add(block_origin, xlength + 3.875 - 2.4498 - 1.625, ywidth / 2, key_z),
                         orientation=bp_side_x_key_matrix, layer=99),
        nx.add_component(nx.display_part(), bp_key_path, reference_set="BODY",
                         origin=_add(block_origin, -3.875 + 2.4498 + 1.625, ywidth / 2, key_z),
                         orientation=bp_side_x_key_matrix, layer=99),
    ]
    bp_body_refset.AddObjectsToReferenceSet(bp_keys)
    nx.prototype(bp_keys[0]).SaveAs("{}\\{}-key-{}.prt".format(
        os.path.dirname(nx.display_part().FullPath), name_prefix, merlin._random_file_token()))
    nx.display_part().Layers.WorkLayer = 1

    bp_shcs_path = _shcs16mm050Path
    bp_shcs_z = block_origin.Z + block_z + 1.5 if is_upper else block_origin.Z - 1.5
    bp_shcs_orientation = drawdie._z_matrix(_VectorZN if is_upper else _VectorZ)
    bp_ywidth = ywidth + 2.75 * 2
    bp_y_start = block_origin.Y - 2.75
    bp_shcs_ys = [bp_y_start + 3 + (bp_ywidth - 6) * i / 4.0 for i in range(5)]
    bp_shcs: List[NXOpen.Assemblies.Component] = []
    for y in bp_shcs_ys:
        bp_shcs.append(nx.add_component(nx.display_part(), bp_shcs_path, reference_set="CBORE",
                                        origin=_add(NXOpen.Point3d(block_origin.X - .625, y, bp_shcs_z), 0, 0, 0),
                                        orientation=bp_shcs_orientation, layer=99))
        bp_shcs.append(nx.add_component(nx.display_part(), bp_shcs_path, reference_set="CBORE",
                                        origin=_add(NXOpen.Point3d(block_origin.X + xlength - .625, y, bp_shcs_z),
                                                    1 + .25, 0, 0),
                                        orientation=bp_shcs_orientation, layer=99))
    _subtract_and_refset_fasteners(bp_shcs, bp_bottom_face, bp_body_refset)

    bp_min = _add(block_origin, -1.375, -2.75, 0)
    bp_max = _add(block_origin, xlength + 1.375, ywidth + 2.75, 0)
    bp_hoist_rings = _add_corner_fasteners(bp_min, bp_max, _VectorZN if is_upper else _VectorZ, bp_shcs_z,
                                           _gmHoistRingPath, corner_offset=1.0, z_adjust=-1.5 if is_upper else 1.5)
    bp_body_refset.AddObjectsToReferenceSet(bp_hoist_rings)

    nx.find_or_create_reference_set(owning_part, "BODY").AddObjectsToReferenceSet([backing_plate])
    nx.set_reference_set(backing_plate, "BODY")
    plate_part = cast(NXOpen.Part, nx.prototype(backing_plate))
    plate_part.Layers.WorkLayer = 1
    plate_part.Layers.SetState(15, NXOpen.Layer.State.Hidden)

    nx.set_display_part(top_level)

    # Set BODY as the used reference set for the backing plate in every ancestor assembly (owning_part .. -000), so
    # each sub-assembly shows it when opened standalone.
    merlin._set_reference_set_in_ancestor_assemblies(nx.first_occurrence_in(plate_part, top_level))


# ---------------------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------------------

def _add(point: NXOpen.Point3d, x: float, y: float, z: float) -> NXOpen.Point3d:
    """Point3d.__Add(x, y, z)"""
    return NXOpen.Point3d(point.X + x, point.Y + y, point.Z + z)


def _description(xlength: float, ywidth: float, height: float) -> str:
    """$"{xlength} X {ywidth} X {height}" - double.ToString() as .NET Framework prints it."""
    return "{} X {} X {}".format(nx.cs_double_str(xlength), nx.cs_double_str(ywidth), nx.cs_double_str(height))


def _create_block(origin: NXOpen.Point3d, orientation: NXOpen.Matrix3x3, xlength: float, ywidth: float,
                  height: float) -> NXOpen.Features.Block:
    """
    BasePart.__CreateBlock(Point3d, Matrix3x3, double, double, double) - an origin-and-edge-lengths block in the work
    part, the display part's WCS turned to orientation for the commit (CastTrimPad._create_block).
    """
    return trimpad._create_block(origin, orientation, xlength, ywidth, height)


def _absolute_csys_orientation(part: NXOpen.BasePart) -> NXOpen.Matrix3x3:
    """
    Part_.AbsoluteCsys.Orientation.Element - the orientation of the csys of the part's first datum CSYS feature
    (BasePart.__AbsoluteCsys). Throws, as the C# First() does, when the part has no datum CSYS.
    """
    for feature in part.Features.GetFeatures():
        if isinstance(feature, NXOpen.Features.DatumCsys):
            csys_tag, _origin, _axes, _planes = nx.ufsession_.ModlFeatures.AskDatumCsysComponents(feature.Tag)
            csys = cast(NXOpen.CartesianCoordinateSystem, nx.tagged_object(csys_tag))
            return csys.Orientation.Element
    raise RuntimeError("Sequence contains no elements ({} has no datum CSYS)".format(part.Leaf))


def _owning_components(bodies: Iterable[NXOpen.Body]) -> List[Optional[NXOpen.Assemblies.Component]]:
    """bodies.Select(b => b.OwningComponent).ToHashSet() - distinct, in pick order (None kept once, as null is)."""
    components: List[Optional[NXOpen.Assemblies.Component]] = []
    for body in bodies:
        comp = body.OwningComponent
        if comp is None:
            if None not in components:
                components.append(None)
        elif all(seen is None or seen.Tag != comp.Tag for seen in components):
            components.append(comp)
    return components


def _first_planar_face(body: NXOpen.Body, normal: NXOpen.Vector3d) -> NXOpen.Face:
    """GetFaces().First(f => f.__Normal().__Equals(normal)) / Body.__PlanarFaceWithNormal - throws when none."""
    face = nx.planar_face_with_normal_or_null(body, normal)
    if face is None:
        raise RuntimeError("Sequence contains no matching element (no planar face with normal ({}, {}, {}))".format(
            normal.X, normal.Y, normal.Z))
    return face


def _first_block_feature(part: NXOpen.BasePart) -> NXOpen.Features.Block:
    """part.Features.OfType<Block>().First()"""
    block = nx.first_block_feature(part)
    if block is None:
        raise RuntimeError("Sequence contains no elements ({} has no block feature)".format(part.Leaf))
    return block


def _find_reference_set(part: NXOpen.BasePart, name: str) -> NXOpen.ReferenceSet:
    """BasePart.__FindReferenceSet - throws when the part has no such reference set."""
    refset = nx.find_reference_set_or_null(part, name)
    if refset is None:
        raise RuntimeError('Could not find reference set with title "{}" in part "{}".'.format(name, part.Leaf))
    return refset


def _find_or_create_reference_set_quiet(part: NXOpen.BasePart, name: str) -> NXOpen.ReferenceSet:
    """
    Part_.FindOrCreateReferenceSet (BasePart.__FindOrCreateReferenceSet) - like tsg_nx.find_or_create_reference_set
    (Merlin.FindOrCreateReferenceSet) but without its "Created reference set" print, which only Merlin's prints.
    """
    existing = nx.find_reference_set_or_null(part, name)
    if existing is not None:
        return existing
    created = part.CreateReferenceSet()
    created.SetName(name)
    return created


def _subtract_linked_body(part: NXOpen.BasePart, target: NXOpen.Body,
                          link: NXOpen.Features.Feature) -> NXOpen.Features.BooleanFeature:
    """Part.__SubtractLinkedBody - a subtract built in part (tsg_nx.subtract always builds in the work part)."""
    builder = part.Features.CreateBooleanBuilderUsingCollector(None)
    try:
        builder.Target = target
        collector = part.ScCollectors.CreateCollector()
        collector.ReplaceRules([part.ScRuleFactory.CreateRuleBodyDumb(link.GetBodies())], False)
        builder.ToolBodyCollector = collector
        builder.Operation = NXOpen.Features.Feature.BooleanType.Subtract
        return cast(NXOpen.Features.BooleanFeature, builder.Commit())
    finally:
        builder.Destroy()


def main() -> None:
    """The split-form UFunc (its menu button runs this file) - the dialog, then execute_with."""
    import SplitFormDialog
    import usage_db

    with usage_db.run("split-form"):
        try:
            SplitFormDialog.SplitFormDialog.run("Split Form", "SplitForm", "SplitForm", True)
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
