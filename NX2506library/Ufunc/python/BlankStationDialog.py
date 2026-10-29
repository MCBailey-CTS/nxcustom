"""
The blank station dialog (blank-station and secondary-trim-station): the window titled '{version} - {UFunc}',
the slug solid bodies (anywhere in the assembly - the slugs live in components below the -000) and the trim steel
material, D2 or S7, that goes on every punch and lower trim steel. OK stays greyed out until a body is picked.

A Block UI Styler dialog (BlankStationDialog.dlx, built by tools\\make-dlx.py), in place of the SNAP BlockForm
src\\Ui\\Dialogs\\BlankStationDialog.cs (Merlin.BlankStationDialog) that did the same until 2026-10-23 (recover it
from git at 41f2a7b). The differences:
  - The material is a plain radio enum; the SNAP form's bordered radio box stood in for a group box.
  - Accepted is the OK callback's own verdict, not a flag set in OnApply.

BlankStation.BlankStation.execute(is3d) runs the gates and then ask(title); ask returns (bodies, material) or None.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional, Tuple, cast

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


def ask(title: str) -> Optional[Tuple[List[NXOpen.Body], str]]:
    """
    Shows the dialog titled title; (picked slug bodies, "D2" | "S7") once accepted, None otherwise. TSG and GM build
    the same (the blank station has no CTS branch).
    """
    try:
        dialog = _BlankStationDialog(title)
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

    is_gm_customer(dialog.customer_choice)
    return dialog.bodies, dialog.material


class _BlankStationDialog(Dialog):
    """BlankStationDialog.dlx: the bodies pick and the material radio."""

    dlx_name = "BlankStationDialog.dlx"

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__()
        # Captured in ok(): the blocks are gone once Launch returns.
        self.bodies: List[NXOpen.Body] = []
        self.material = "D2"
        self.customer_choice = CustomerNone

    def initialize(self) -> None:
        mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type, 0, _SolidBodyDetail)
        self.block("bodies").SetSelectionFilter(NXOpen.Selection.SelectionAction.ClearAndEnableSpecific, [mask])
        self.assembly_scope(self.block("bodies"))

    def shown(self) -> None:
        self.reset_customer()

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
        return True

    def _picked_bodies(self) -> List[NXOpen.Body]:
        # Occurrences, so OwningComponent is the slug component the build needs.
        return [cast(NXOpen.Body, o) for o in self.selected(self.block("bodies"))
                if isinstance(o, NXOpen.Body) and cast(NXOpen.Body, o).IsSolidBody]


def main() -> None:
    """File -> Execute -> NX Open: the dialog alone - prints what it would hand the build."""
    result = ask("Blank Station (test)")
    if result is not None:
        bodies, material = result
        nx.print_("material={} bodies={}".format(material, [b.JournalIdentifier for b in bodies]))


if __name__ == "__main__":
    main()
