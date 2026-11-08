"""
The blank station dialog (blank-station and secondary-trim-station): the window titled '{version} - {UFunc}',
the slug solid bodies (anywhere in the assembly - the slugs live in components below the -000) and the trim steel
material, D2 or S7, that goes on every punch and lower trim steel. OK stays greyed out until a body is picked.

A Block UI Styler dialog (BlankStationDialog.dlx, built by tools\\make-dlx.py), in place of the SNAP BlockForm
src\\Ui\\Dialogs\\BlankStationDialog.cs (Merlin.BlankStationDialog) that did the same until 2026-10-23 (recover it
from git at 41f2a7b). The differences:
  - The material is a plain radio enum; the SNAP form's bordered radio box stood in for a group box.
  - Accepted is the OK callback's own verdict, not a flag set in OnApply.

BlankStation.BlankStation.execute(is3d) runs the gates and then ask(title); ask returns (bodies, material, is_gm) or
None. The right-click menu's Merlin > Blank Station (BlankStation.execute_on_bodies, 2026-11-08) calls
ask_with_station(title, bodies, stations): the right-clicked bodies already picked and the "station" radio ("Build in",
hidden otherwise) filled with the -000's station sets; it returns (bodies, material, is_gm, station) or None.
"""

from __future__ import annotations

import os
import sys
from typing import Callable, List, Optional, Sequence, Tuple, cast

# Session.Execute does not put the script's folder on sys.path, so the shared modules would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
from tsg_dialog import CustomerNone, Dialog, is_gm_customer  # noqa: E402

# NX will not build a Block Styler dialog from inside some callbacks (a menu or toolbar launch, it seems).
_ErrorCannotLaunchDialog = 3520048

# UF_UI_SEL_FEATURE_SOLID_BODY - not in every UFConstants build, so the number Perfect.py uses too.
_SolidBodyDetail = 36


def ask(title: str) -> Optional[Tuple[List[NXOpen.Body], str, bool]]:
    """
    Shows the dialog titled title; (picked slug bodies, "D2" | "S7", is_gm) once accepted, None otherwise. TSG and GM
    build the same, except that GM adds the 15 / 30 mm offset lines round the lower trim steel's LWR-PROFILE cut
    (BlankStation._create_gm_profile_offsets).
    """
    dialog = _show(title, lambda: _BlankStationDialog(title))
    if dialog is None:
        return None
    return dialog.bodies, dialog.material, is_gm_customer(dialog.customer_choice)


def ask_with_station(title: str, bodies: Sequence[NXOpen.Body],
                     stations: Sequence[str]) -> Optional[Tuple[List[NXOpen.Body], str, bool, str]]:
    """
    ask with bodies already picked and the "Build in" radio showing stations (the NN of each uadNN / updNN / ladNN
    set; 01 checked when it is one): (bodies, material, is_gm, station) once accepted, None otherwise.
    """
    dialog = _show(title, lambda: _BlankStationDialog(title, bodies, stations))
    if dialog is None:
        return None
    return dialog.bodies, dialog.material, is_gm_customer(dialog.customer_choice), dialog.station


def _show(title: str, make: Callable[[], "_BlankStationDialog"]) -> Optional["_BlankStationDialog"]:
    """Builds the dialog with make and runs it; the dialog once accepted with a body picked, None otherwise."""
    try:
        dialog = make()
        accepted = dialog.run()
    except NXOpen.NXException as ex:
        if ex.ErrorCode != _ErrorCannotLaunchDialog:
            raise
        nx.print_exception(ex)
        nx.show_error("NX would not open the {} dialog (error {} - it will not create a dialog from inside a "
                      "callback).\n\nTry running it from File -> Execute -> NX Open rather than from a menu or "
                      "toolbar button.".format(title, _ErrorCannotLaunchDialog))
        return None

    # A cancel prints nothing: Dialog.run already marked the run cancelled.
    if not accepted or not dialog.bodies:
        return None

    return dialog


class _BlankStationDialog(Dialog):
    """
    BlankStationDialog.dlx: the bodies pick and the material radio, and the "station" radio ("Build in") when stations
    are given (the .dlx holds a placeholder member; hidden otherwise). preselected bodies start out picked.
    """

    dlx_name = "BlankStationDialog.dlx"

    def __init__(self, title: str, preselected: Sequence[NXOpen.Body] = (), stations: Sequence[str] = ()) -> None:
        self.title = title
        self.preselected = list(preselected)
        self.stations = list(stations)
        super().__init__()
        # Captured in ok(): the blocks are gone once Launch returns.
        self.bodies: List[NXOpen.Body] = []
        self.material = "D2"
        self.customer_choice = CustomerNone
        self.station = self.stations[0] if self.stations else ""

    def initialize(self) -> None:
        mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type, 0, _SolidBodyDetail)
        self.block("bodies").SetSelectionFilter(NXOpen.Selection.SelectionAction.ClearAndEnableSpecific, [mask])
        self.assembly_scope(self.block("bodies"))
        if self.stations:
            self.block("station").SetEnumMembers(self.stations)

    def shown(self) -> None:
        self.reset_customer()
        station = self.block("station")
        station.Show = bool(self.stations)
        if self.stations:
            station.ValueAsString = "01" if "01" in self.stations else self.stations[0]
        if self.preselected:
            self.block("bodies").SetSelectedObjects(self.preselected)

    def enable_ok(self) -> bool:
        return self.customer_picked() and len(self._picked_bodies()) > 0

    def ok(self) -> bool:
        self.bodies = self._picked_bodies()
        # enable_ok greys OK out for these; they are a backstop.
        if not self.customer_picked():
            self.message("Check TSG or GM.")
            return False
        if not self.bodies:
            self.message("Select at least one slug body.")
            return False
        self.material = str(self.block("material").ValueAsString)
        self.customer_choice = self.customer()
        if self.stations:
            self.station = str(self.block("station").ValueAsString)
        return True

    def _picked_bodies(self) -> List[NXOpen.Body]:
        # Occurrences, so OwningComponent is the slug component the build needs.
        return [cast(NXOpen.Body, o) for o in self.selected(self.block("bodies"))
                if isinstance(o, NXOpen.Body) and cast(NXOpen.Body, o).IsSolidBody]


def main() -> None:
    """File -> Execute -> NX Open: the dialog alone - prints what it would hand the build."""
    result = ask("Blank Station (test)")
    if result is not None:
        bodies, material, is_gm = result
        nx.print_("material={} is_gm={} bodies={}".format(material, is_gm, [b.JournalIdentifier for b in bodies]))


if __name__ == "__main__":
    main()
