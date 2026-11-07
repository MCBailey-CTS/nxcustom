"""
The split form dialog (split-form, and the legacy split-form-with-plate / split-form-with-plate-backside,
which open it with their boxes pre-checked): the window titled '{version} - {UFunc}', a "Build in" radio of the display
assembly's stations (lad01, uad01, ... - CastTrimPad._station_components, plus the display part when it is a station
itself; 2026-11-04, in place of the Upper / Lower boxes: the work part's station is checked, else the first, and none is
an error before the dialog), the grid - Rows (splits along Y) by Cols (splits along X) - a single solid body pick, and
two boxes: Backing Plate (the sub plate under / over the blocks) and SHCS From Backside (greyed out until Backing Plate
is checked: the corner SHCS go up from the plate, SHORT-TAP, instead of down through the block). OK stays greyed out
until a customer is checked and a body is picked. Once it is accepted the picked station becomes the work part, so the
blocks are built into it, upper or lower by its name, and the UFunc's module gets
{class}.execute_with(is_gm, is_upper, rows, cols, [body], plate, backside), which does the units gate and the build.

A Block UI Styler dialog (SplitFormDialog.dlx, built by tools\\make-dlx.py), in place of the SNAP BlockForm
src\\Ui\\Dialogs\\GmSplitFormDialog.cs that did the same until 2026-10-22 (recover it from git at 65ee00d). The
differences:
  - OK / Cancel, no Apply: the SNAP form's Apply only stored the values, which OK does anyway.
  - The enable-OK callback is a plain BlockDialog.AddEnableOKButtonHandler - the SNAP form reached the dialog SNAP
    keeps internally by reflection to hook it.

    Session.Execute("SplitFormDialog.py", "SplitFormDialog", "run", name, module, class_name, is_gm, plate, backside)
"""

from __future__ import annotations

import importlib
import os
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, cast

# Session.Execute does not put the script's folder on sys.path, so the shared modules would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# CastTrimPad is a UFunc entry, in the folder above this one (src\UFuncs; deployed, Ufunc).
_ufuncs = os.path.dirname(_here)
if _ufuncs not in sys.path:
    sys.path.insert(1, _ufuncs)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.BlockStyler  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
import CastTrimPad as trimpad  # noqa: E402
from tsg_dialog import CustomerNone, Dialog, is_gm_customer, title_with_version  # noqa: E402

# NX will not build a Block Styler dialog from inside some callbacks (a menu or toolbar launch, it seems).
_ErrorCannotLaunchDialog = 3520048

# UF_UI_SEL_FEATURE_SOLID_BODY - not in every UFConstants build, so the number Perfect.py uses too.
_SolidBodyDetail = 36


class SplitFormDialog(object):

    @staticmethod
    def run(name: str, module: str, class_name: str, is_gm: bool = True, plate: bool = False,
            backside: bool = False) -> None:
        """
        Shows the dialog titled '{AssemblyFileVersion} - {name}', Backing Plate / SHCS From Backside pre-checked from
        plate / backside, and, once it is accepted, makes the picked station the work part and calls
        {module}.{class_name}.execute_with(is_gm, is_upper, rows, cols, [body], plate, backside).
        """
        title = title_with_version(name)

        # Checked before the dialog so a job with no station fails before the user selects anything.
        stations = _find_stations()
        if not stations:
            nx.show_error(trimpad._StationError)
            return

        try:
            dialog = _SplitFormDialog(title, list(stations), bool(plate), bool(plate) and bool(backside))
            accepted = dialog.run()
        except NXOpen.NXException as ex:
            if ex.ErrorCode != _ErrorCannotLaunchDialog:
                raise
            nx.print_exception(ex)
            nx.print_("NX would not open the {} dialog ({}) - try File -> Execute -> NX Open.".format(
                title, _ErrorCannotLaunchDialog))
            return

        # A cancel prints nothing: Dialog.run already marked the run cancelled.
        if not accepted or dialog.body is None:
            return

        # The dialog's Customer radio decides is_gm (TSG uses the CTS parts); the is_gm argument is not used.
        is_gm = is_gm_customer(dialog.customer_choice)

        # The builders put everything in the work part. The display part itself has no occurrence to pick.
        station = stations[dialog.station]
        if station is None:
            nx.set_work_part(nx.display_part())
        else:
            nx.set_work_component(station)
        is_upper = bool(trimpad._station_is_upper(dialog.station))

        # The dialog stands in for the station detection, the split-count menus and the body pick.
        target = getattr(importlib.import_module(module), class_name)

        # The listing window gets only errors (progress and timings go to the syslog); the time it took goes in a
        # message box. With errors, nx.merlin_run's box says so instead.
        import usage_db
        errors_before = usage_db.errors_logged()
        started = time.time()
        with nx.quiet_listing():
            target.execute_with(is_gm, is_upper, dialog.rows, dialog.cols, [dialog.body], dialog.plate,
                                dialog.backside)
        if usage_db.errors_logged() == errors_before:
            nx.message_box(title, NXOpen.NXMessageBox.DialogType.Information,
                           "Complete in {}.".format(_elapsed_text(time.time() - started)))


def _elapsed_text(seconds: float) -> str:
    """'42.3 seconds', or '2 min 05 s' from a minute up."""
    if seconds < 60:
        return "{:.1f} seconds".format(seconds)
    minutes, rest = divmod(int(round(seconds)), 60)
    return "{} min {:02d} s".format(minutes, rest)


def _find_stations() -> Dict[str, Optional[NXOpen.Assemblies.Component]]:
    """
    The "Build in" radio's choices: station leaf -> its first occurrence under the display part, or None for the
    display part itself when it is a station.
    """
    display = nx.display_part()
    stations: Dict[str, Optional[NXOpen.Assemblies.Component]] = {}
    if trimpad._StationLeaf.match(display.Leaf):
        stations[display.Leaf] = None
    for component in trimpad._station_components():
        stations.setdefault(nx.prototype(component).Leaf, component)
    return stations


class _SplitFormDialog(Dialog):
    """
    SplitFormDialog.dlx: the "station" radio (filled from stations; the .dlx holds a placeholder), rows / cols
    spinners, body pick, plate / backside toggles.
    """

    dlx_name = "SplitFormDialog.dlx"

    def __init__(self, title: str, stations: Sequence[str], plate: bool = False, backside: bool = False) -> None:
        self.title = title
        self.stations: List[str] = list(stations)
        super().__init__()
        # Captured in ok(): the blocks are gone once Launch returns. plate / backside start as the presets.
        self.station = self.stations[0]
        self.rows = 2
        self.cols = 1
        self.body: Optional[NXOpen.Body] = None
        self.plate = plate
        self.backside = backside
        self.customer_choice = CustomerNone

    def initialize(self) -> None:
        mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type, 0, _SolidBodyDetail)
        self.block("body").SetSelectionFilter(NXOpen.Selection.SelectionAction.ClearAndEnableSpecific, [mask])
        # The picked body is usually in a strip component, not the station the work part is set to.
        self.assembly_scope(self.block("body"))
        # The stations come from the assembly; the .dlx only holds a placeholder.
        self.block("station").SetEnumMembers(self.stations)

    def shown(self) -> None:
        # Value properties: set once the dialog is up, or its memory would overwrite them.
        self.reset_customer()
        work = nx.work_part().Leaf
        self.block("station").ValueAsString = work if work in self.stations else self.stations[0]
        self.block("plate").Value = self.plate
        self.block("backside").Value = self.backside
        self.block("backside").Enable = self.plate

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        # SHCS From Backside only means something with a plate to screw from.
        if block == self.block("plate"):
            plate = bool(self.block("plate").Value)
            self.block("backside").Enable = plate
            if not plate:
                self.block("backside").Value = False

    def enable_ok(self) -> bool:
        return self.customer_picked() and self._picked_body() is not None

    def ok(self) -> bool:
        self.body = self._picked_body()

        # enable_ok greys OK out for these; they are a backstop.
        if not self.customer_picked():
            self.message("Check TSG or GM.")
            return False
        if self.body is None:
            self.message("Select a solid body.")
            return False

        self.customer_choice = self.customer()
        self.station = str(self.block("station").ValueAsString)
        self.rows = int(self.block("rows").Value)
        self.cols = int(self.block("cols").Value)
        self.plate = bool(self.block("plate").Value)
        self.backside = self.plate and bool(self.block("backside").Value)
        return True

    def _picked_body(self) -> Optional[NXOpen.Body]:
        for obj in self.selected(self.block("body")):
            if isinstance(obj, NXOpen.Body):
                return cast(NXOpen.Body, obj)
        return None


def main() -> None:
    """File -> Execute -> NX Open: the dialog alone - prints what it would hand the build."""
    stations = list(_find_stations())
    if not stations:
        nx.print_("Split Form (test): no station under {}.".format(nx.display_part().Leaf))
        return
    dialog = _SplitFormDialog("Split Form (test)", stations)
    if dialog.run() and dialog.body is not None:
        nx.print_("station={} rows={} cols={} plate={} backside={} body={}".format(
            dialog.station, dialog.rows, dialog.cols, dialog.plate, dialog.backside,
            cast(Any, dialog.body).JournalIdentifier))
    else:
        nx.print_("Split Form (test): cancelled.")


if __name__ == "__main__":
    main()
