"""
The set-component-name UFunc, Python only since 2026-10-30 (the C# src\\UFuncs\\SetComponentName.cs, a legacy class whose
method was spelled excute() and which nothing could launch, is in git at 97eb2a6).

After the "Are you sure" box, asks "How many component digits?" (3 / 4; backing out ends the run, cancelled), then names each loaded, unsuppressed
component under the display part whose display name is {job}-{op}-{detail} after its detail number - unless the
display name already ends with the component name, or the name already is the detail. Prints the count. One undo
mark; nothing is saved.

The C# asked the question and stopped: the naming pass after it was commented out. This is that commented-out pass,
revived (its loop target was left unfinished - "disp.ComponentAssembly.()" - so it walks every component under the
display part). The digit count is asked, as the C# did, but neither the C# nor this pass uses it. Never run in NX.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any, Optional, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# The shared modules are in the python folder beside this file (src\UFuncs\python; deployed, Ufunc\python).
_shared_python = os.path.join(_here, "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402

import tsg_nx as nx  # noqa: E402

ufunc_name = "set-component-name"

_DetailName = re.compile(r"\d+-\d+-(\d+)")
_DigitOptions = ["3", "4"]


def _ask_digits() -> Optional[int]:
    """sess.SelectMenuItem14gt("How many componenet digits?", {"3", "4"}) - None on back / cancel."""
    # DisplayMenu is not in the hand-written UFUi stub; its items start at response 5.
    response = int(cast(Any, nx.ufsession_.Ui).DisplayMenu("How many component digits?", 0, _DigitOptions,
                                                            len(_DigitOptions)))
    index = response - 5
    return int(_DigitOptions[index]) if 0 <= index < len(_DigitOptions) else None


def set_component_names() -> int:
    """The commented-out pass: returns how many component names it set."""
    root = nx.root_component(nx.display_part())
    if root is None:
        return 0
    edits = 0
    for comp in nx.descendants(root, include_root=False):
        try:
            if comp.DisplayName.endswith(comp.Name):
                continue
            match = _DetailName.search(comp.DisplayName)
            if match is None:
                continue
            detail = match.group(1)
            if comp.Name == detail:
                continue
            comp.SetName(detail)
            edits += 1
        except Exception as ex:
            nx.print_exception(ex, comp.DisplayName)
    return edits


def main() -> None:
    """The set-component-name UFunc. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            if not nx.confirm_execute(ufunc_name):
                return
            if _ask_digits() is None:
                nx.mark_cancelled("the component digits menu")
                return
            nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Set Component Names")
            edits = set_component_names()
            nx.print_("Set Component Names {}".format(nx.assembly_file_version()))
            nx.print_("Set {} component names".format(edits))
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
