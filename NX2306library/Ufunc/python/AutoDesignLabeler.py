"""
The auto-design-labeler UFunc: a standalone Python UFunc (no C# class, 2026-10-29); its menu button runs this file's
main(). It replaced the WinForms AutoDesignLabeler form and src\\Static\\AutoDesignLabeler.cs (in git at 5fb0e3c),
which were never on a ribbon.

Labels strip solids for Auto Design (AutoDesign.py): the picked bodies get the PROGRAM object attribute Auto Design
groups them by - Blank BLANK, Trim TRIM, Pierce PRC, Draw DRAW, Restrike RESTRIKE, Dead Hit DEADHIT. Flange Up and
Flange Down are on the radio but not implemented yet: OK / Apply with one of them prints that and labels nothing.

The dialog (AutoDesignLabeler.dlx, tools\\make-dlx.py): the solid bodies (anywhere in the assembly), a line listing
their PROGRAM values now, and the Program radio (the form's six buttons). OK labels and closes; Apply labels and
stays open, the pick cleared, for the next program. One undo mark per label.

As in the C#, the value goes on the prototype body, so every occurrence of it carries it, and an existing value is
overwritten. Difference: Auto Design reads the occurrence's PROGRAM before the prototype's, so a picked occurrence
that has its own (one assigned with the -000 displayed) is overwritten too - the C# left it, and it won.
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional, cast

# Session.Execute does not put the script's folder on sys.path, so the shared modules would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# From the source tree (src\UFuncs) the shared modules are in src\python; deployed, they are beside this file.
_shared_python = os.path.join(os.path.dirname(_here), "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.BlockStyler  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
from tsg_dialog import Dialog, title_with_version  # noqa: E402

ufunc_name = "auto-design-labeler"

# NX will not create a dialog from inside another dialog's callback.
_ErrorCannotLaunchDialog = 3520048

# The attribute Auto Design (AutoDesign.AutoDesignAttribute) groups the strip solids by.
Attribute = "PROGRAM"

# The Program radio's items -> the PROGRAM value (the form's button Tags).
Programs: Dict[str, str] = {
    "Blank": "BLANK",
    "Trim": "TRIM",
    "Pierce": "PRC",
    "Draw": "DRAW",
    "Restrike": "RESTRIKE",
    "Dead Hit": "DEADHIT",
}

# Program radio items with no PROGRAM value yet (2026-10-29): OK / Apply print that and label nothing.
NotImplementedPrograms = ["Flange Up", "Flange Down"]

# UF_UI_SEL_FEATURE_SOLID_BODY - not in every UFConstants build, so the number Perfect.py uses too.
_SolidBodyDetail = 36


def program_of(body: NXOpen.Body) -> str:
    """The PROGRAM value Auto Design would read (occurrence first, then prototype), "" for none."""
    sources = [body, cast(NXOpen.Body, body.Prototype)] if body.IsOccurrence else [body]
    for source in sources:
        if nx.has_attribute(source, Attribute):
            value = (nx.get_attribute(source, Attribute) or "").strip().upper()
            if value:
                return value
    return ""


def label(bodies: List[NXOpen.Body], program: str) -> int:
    """
    Static.AutoDesignLabelerApply: PROGRAM = program on each picked body's prototype (each once), and on a picked
    occurrence that has its own PROGRAM. One undo mark; a body's failure is printed and skipped. Returns the count.
    """
    if not bodies:
        return 0

    nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Auto Design Labeler: {}".format(program))
    labeled = 0
    done: List[NXOpen.Body] = []

    for body in bodies:
        try:
            prototype = cast(NXOpen.Body, body.Prototype) if body.IsOccurrence else body
            if body.IsOccurrence and nx.has_attribute(body, Attribute):
                nx.set_attribute(body, Attribute, program)
            if prototype in done:
                continue
            nx.set_attribute(prototype, Attribute, program)
            done.append(prototype)
            labeled += 1
        except Exception as ex:
            nx.print_exception(ex)

    nx.print_("Auto Design Labeler: {} = {} on {} body(ies)".format(Attribute, program, labeled))
    return labeled


class _LabelerDialog(Dialog):
    """AutoDesignLabeler.dlx: the bodies, their PROGRAM now, and the Program radio."""

    dlx_name = "AutoDesignLabeler.dlx"

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__()

    def initialize(self) -> None:
        mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type, 0, _SolidBodyDetail)
        self.block("bodies").SetSelectionFilter(NXOpen.Selection.SelectionAction.ClearAndEnableSpecific, [mask])
        # The strip's solids live in components below the -000.
        self.assembly_scope(self.block("bodies"))

    def shown(self) -> None:
        self._show_current()

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        if block == self.block("bodies"):
            self._show_current()

    def enable_ok(self) -> bool:
        return len(self._picked()) > 0

    def ok(self) -> bool:
        bodies = self._picked()
        if not bodies:
            self.message("Select the strip solid bodies.")
            return False
        choice = str(self.block("program").ValueAsString)
        if choice in NotImplementedPrograms:
            nx.print_("Auto Design Labeler: {} is not implemented - nothing labeled.".format(choice))
            return True
        label(bodies, Programs[choice])
        return True

    def apply(self) -> bool:
        if not self.ok():
            return False
        self.block("bodies").SetSelectedObjects([])
        self._show_current()
        return True

    def _picked(self) -> List[NXOpen.Body]:
        return [cast(NXOpen.Body, o) for o in self.selected(self.block("bodies"))
                if isinstance(o, NXOpen.Body) and cast(NXOpen.Body, o).IsSolidBody]

    def _show_current(self) -> None:
        counts: Dict[str, int] = {}
        for body in self._picked():
            try:
                value = program_of(body) or "none"
            except Exception:
                value = "?"
            counts[value] = counts.get(value, 0) + 1
        text = ", ".join("{} x{}".format(v, n) for v, n in sorted(counts.items())) if counts else "nothing picked"
        self.block("current").Label = "PROGRAM now: {}".format(text)


def execute() -> None:
    title = title_with_version("Auto Design Labeler")
    dialog: Optional[_LabelerDialog] = None
    try:
        dialog = _LabelerDialog(title)
        dialog.run()
    except NXOpen.NXException as ex:
        if ex.ErrorCode != _ErrorCannotLaunchDialog:
            raise
        nx.print_exception(ex)
        nx.show_error("NX would not open the {} dialog (error {} - it will not create a dialog from inside a "
                      "callback).\n\nTry running it from File -> Execute -> NX Open rather than from a menu or "
                      "toolbar button.".format(title, _ErrorCannotLaunchDialog))


def main() -> None:
    """The auto-design-labeler UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
