"""
The GM split form dialog (gm-split-form, and the legacy gm-split-form-with-plate / gm-split-form-with-plate-backside,
which open it with their boxes pre-checked): the window titled '{version} - {UFunc}', the assembly (Upper / Lower, pre-checked from the work part, neither when it is not a
station), the grid - Rows (splits along Y) by Cols (splits along X) - a single solid body pick, and two boxes:
Backing Plate (the sub plate under / over the blocks) and SHCS From Backside (greyed out until Backing Plate is checked:
the corner SHCS go up from the plate, SHORT-TAP, instead of down through the block). OK stays greyed out until one
assembly is checked and a body is picked. Once it is accepted the UFunc's module gets
{class}.execute_with(is_gm, is_upper, rows, cols, [body], plate, backside), which does the units gate and the build.

A Block UI Styler dialog (GmSplitFormDialog.dlx, built by tools\\make-dlx.py), in place of the SNAP BlockForm
src\\Ui\\Dialogs\\GmSplitFormDialog.cs that did the same until 2026-10-22 (recover it from git at 65ee00d). The
differences:
  - OK / Cancel, no Apply: the SNAP form's Apply only stored the values, which OK does anyway.
  - The enable-OK callback is a plain BlockDialog.AddEnableOKButtonHandler - the SNAP form reached the dialog SNAP
    keeps internally by reflection to hook it.

    Session.Execute("GmSplitFormDialog.py", "GmSplitFormDialog", "run", name, module, class_name, is_gm, plate, backside)
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import Any, Optional, cast

# Session.Execute does not put the script's folder on sys.path, so the shared modules would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.BlockStyler  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
from tsg_dialog import Dialog, title_with_version  # noqa: E402

# NX will not build a Block Styler dialog from inside some callbacks (a menu or toolbar launch, it seems).
_ErrorCannotLaunchDialog = 3520048

# UF_UI_SEL_FEATURE_SOLID_BODY - not in every UFConstants build, so the number GmPerfect.py uses too.
_SolidBodyDetail = 36


class GmSplitFormDialog(object):

    @staticmethod
    def run(name: str, module: str, class_name: str, is_gm: bool = True, plate: bool = False,
            backside: bool = False) -> None:
        """
        Shows the dialog titled '{AssemblyFileVersion} - {name}', Backing Plate / SHCS From Backside pre-checked from
        plate / backside, and, once it is accepted, calls
        {module}.{class_name}.execute_with(is_gm, is_upper, rows, cols, [body], plate, backside).
        """
        title = title_with_version(name)

        try:
            dialog = _SplitFormDialog(title, bool(plate), bool(plate) and bool(backside))
            accepted = dialog.run()
        except NXOpen.NXException as ex:
            if ex.ErrorCode != _ErrorCannotLaunchDialog:
                raise
            nx.print_exception(ex)
            nx.print_("NX would not open the {} dialog ({}) - try File -> Execute -> NX Open.".format(
                title, _ErrorCannotLaunchDialog))
            return

        if not accepted or dialog.body is None:
            nx.print_("{} dialog was not accepted - nothing built.".format(title))
            return

        # The dialog stands in for the station detection, the split-count menus and the body pick.
        target = getattr(importlib.import_module(module), class_name)
        target.execute_with(bool(is_gm), dialog.is_upper, dialog.rows, dialog.cols, [dialog.body], dialog.plate,
                            dialog.backside)


def detect_is_upper() -> Optional[bool]:
    """
    The work part's station, as Merlin.TryDetectIsUpper reads it: uad/upd/ush/usp upper, lad/lsh/lsp lower, None for
    anything else.
    """
    leaf = nx.work_part().Leaf

    if any(s in leaf for s in ("uad", "upd", "ush", "usp")):
        return True

    if any(s in leaf for s in ("lad", "lsh", "lsp")):
        return False

    return None


class _SplitFormDialog(Dialog):
    """
    GmSplitFormDialog.dlx: assembly label, upper / lower toggles, rows / cols spinners, body pick, plate / backside
    toggles.
    """

    dlx_name = "GmSplitFormDialog.dlx"

    def __init__(self, title: str, plate: bool = False, backside: bool = False) -> None:
        self.title = title
        super().__init__()
        # Captured in ok(): the blocks are gone once Launch returns. plate / backside start as the presets.
        self.is_upper = False
        self.rows = 2
        self.cols = 1
        self.body: Optional[NXOpen.Body] = None
        self.plate = plate
        self.backside = backside

    def initialize(self) -> None:
        mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type, 0, _SolidBodyDetail)
        self.block("body").SetSelectionFilter(NXOpen.Selection.SelectionAction.ClearAndEnableSpecific, [mask])
        # The picked body is usually in a strip component, not the station the work part is set to.
        self.assembly_scope(self.block("body"))

    def shown(self) -> None:
        # Value properties: set once the dialog is up, or its memory would overwrite them.
        is_upper = detect_is_upper()
        self.block("upper").Value = is_upper is True
        self.block("lower").Value = is_upper is False
        self.block("plate").Value = self.plate
        self.block("backside").Value = self.backside
        self.block("backside").Enable = self.plate

        if is_upper is None:
            nx.print_("{}: the work part {} is not an upper (UAD/UPD/USH/USP) or lower (LAD/LSH/LSP) station - "
                      "check the assembly by hand.".format(self.title, nx.work_part().Leaf))

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        # Upper and Lower act as a radio pair: checking one unchecks the other; unchecking leaves neither.
        upper, lower = self.block("upper"), self.block("lower")
        if block == upper and upper.Value:
            lower.Value = False
        elif block == lower and lower.Value:
            upper.Value = False
        # SHCS From Backside only means something with a plate to screw from.
        elif block == self.block("plate"):
            plate = bool(self.block("plate").Value)
            self.block("backside").Enable = plate
            if not plate:
                self.block("backside").Value = False

    def enable_ok(self) -> bool:
        return (bool(self.block("upper").Value) or bool(self.block("lower").Value)) and self._picked_body() is not None

    def ok(self) -> bool:
        upper, lower = bool(self.block("upper").Value), bool(self.block("lower").Value)
        self.body = self._picked_body()

        # enable_ok greys OK out for both; these are a backstop.
        if not upper and not lower:
            self.message("Check Upper or Lower.")
            return False
        if self.body is None:
            self.message("Select a solid body.")
            return False

        self.is_upper = upper
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
    dialog = _SplitFormDialog("GM Split Form (test)")
    if dialog.run() and dialog.body is not None:
        nx.print_("upper={} rows={} cols={} plate={} backside={} body={}".format(
            dialog.is_upper, dialog.rows, dialog.cols, dialog.plate, dialog.backside,
            cast(Any, dialog.body).JournalIdentifier))
    else:
        nx.print_("GM Split Form (test): cancelled.")


if __name__ == "__main__":
    main()
