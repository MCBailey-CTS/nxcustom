"""
The right-click menu's Merlin > Blank Station (blank-station-context-menu, 2026-11-08, not yet run in NX): the Blank
Station built on the right-clicked solid bodies as the slugs. SessionRecord's TsgContextMenu adds the Merlin submenu
when every selected object is a solid body; its button TSG_MERLIN_BLANK_STATION (Menuscript\\startup\\
tsg_context_menu.men) runs this file's main().

BlankStation.execute_on_bodies does the work: the Blank Station's units / -000 gates, then its dialog with the bodies
already picked and a "Build in" radio of the -000's station sets (each NN with a uadNN, updNN and ladNN; 01 checked
when there is one), then the build into that set. No confirm box: the dialog is the choice. With nothing selected (File
-> Execute -> NX Open on this file) the dialog opens with no bodies picked.
"""

from __future__ import annotations

import os
import sys
from typing import Any, List

# Session.Execute does not put the script's folder on sys.path, so the shared modules would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# The shared modules are in the python folder beside this file (src\UFuncs\python; deployed, Ufunc\python).
_shared_python = os.path.join(_here, "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402

import tsg_nx as nx  # noqa: E402

ufunc_name = "blank-station-context-menu"


def _selected_solid_bodies() -> List[NXOpen.Body]:
    """The solid bodies in NX's global selection (the right-clicked ones)."""
    selection: Any = NXOpen.UI.GetUI().SelectionManager
    bodies: List[NXOpen.Body] = []
    for i in range(selection.GetNumSelectedObjects()):
        picked = selection.GetSelectedTaggedObject(i)
        if isinstance(picked, NXOpen.Body) and picked.IsSolidBody:
            bodies.append(picked)
    return bodies


def main() -> None:
    """The menu button runs this file. An escaping exception is printed."""
    with nx.merlin_run(ufunc_name):
        try:
            from BlankStation import BlankStation
            BlankStation.execute_on_bodies(_selected_solid_bodies())
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
