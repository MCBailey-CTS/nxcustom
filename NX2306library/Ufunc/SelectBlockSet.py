"""
The select-block-set UFunc (2026-11-07): pick one block - its body or its component - or any key or fastener a Merlin
UFunc placed, and every component that UFunc run made is put in NX's selection, in the display assembly: the blocks in
their stations and each block's own fasteners, keys and jacks. It reads the MerlinBlockSet run records
(src\\UFuncs\\python\\block_set.py) that nx.merlin_run writes; a component with no record (made before 2026-11-07, or
by hand) says so in an Information box. Its menu button runs this file's main(). No dialog and no confirm box: the
pick is the choice, and cancelling it marks the run cancelled.

The listing window gets one line: the UFunc that made the set, when, and how many components were selected out of how
many recorded. Members are mapped to the display assembly through each part's occurrences (UF_ASSEM_ask_occs_of_part,
then the member's instance in each), so a part shown twice gets both copies selected. Members whose part is not under
the display part, deleted members and unloaded parts are left out of the count. Nothing is changed.

With one component (or a body in one) already selected - right-click it and pick Select Set, which SessionRecord's
TsgContextMenu adds to the menu - that is the pick; otherwise it asks.

Two ways in:
  - File -> Execute -> NX Open on this file runs main().
  - select_set(component) with a component or body occurrence, from other code.
"""

from __future__ import annotations

import os
import sys
from typing import Any, List, Optional, Sequence, cast

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
import NXOpen.UF  # noqa: E402

import block_set  # noqa: E402
import tsg_nx as nx  # noqa: E402

ufunc_name = "select-block-set"
_Title = "Select Block Set"
# UF_UI_SEL_FEATURE_SOLID_BODY (not in UFConstants' Python stubs; AssemblyWavelink uses the same value).
_UF_UI_SEL_FEATURE_SOLID_BODY = 36


def _pick() -> Optional[NXOpen.Assemblies.Component]:
    """One component or solid body, any in the assembly; the body's component. None on cancel."""
    masks = [NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_component_type, 0, 0),
             NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type, 0,
                                         _UF_UI_SEL_FEATURE_SOLID_BODY)]
    nx.prompt("Select a block, or a key or fastener on one")
    response, picked, _ = NXOpen.UI.GetUI().SelectionManager.SelectTaggedObject(
        "Select a block, or a key or fastener on one", _Title, NXOpen.Selection.SelectionScope.AnyInAssembly,
        NXOpen.Selection.SelectionAction.ClearAndEnableSpecific, False, False, masks)
    if response not in (NXOpen.Selection.Response.ObjectSelected, NXOpen.Selection.Response.ObjectSelectedByName):
        return None
    if isinstance(picked, NXOpen.Assemblies.Component):
        return picked
    if isinstance(picked, NXOpen.Body):
        return picked.OwningComponent
    return None


def _in_display(sets: Sequence[block_set.BlockSet], display: NXOpen.Part) -> List[NXOpen.Assemblies.Component]:
    """Every occurrence, in display, of every live member of sets."""
    found: List[NXOpen.Assemblies.Component] = []
    seen = set()
    for record in sets:
        members = record.members
        if not members:
            continue
        if record.part.Tag == display.Tag:
            owners: List[Optional[NXOpen.Assemblies.Component]] = [None]
        else:
            owners = list(nx.occurrences_of_part_in(display, record.part))
        for member in members:
            instance = nx.ufsession_.Assem.AskInstOfPartOcc(member.Tag)
            for owner in owners:
                if owner is None:
                    occurrence = member
                else:
                    tag = nx.ufsession_.Assem.AskPartOccOfInst(owner.Tag, instance)
                    if not tag:
                        continue
                    occurrence = cast(NXOpen.Assemblies.Component, nx.tagged_object(tag))
                if isinstance(occurrence, NXOpen.Assemblies.Component) and occurrence.Tag not in seen:
                    seen.add(occurrence.Tag)
                    found.append(occurrence)
    return found


def select_set(component: NXOpen.Assemblies.Component) -> int:
    """
    Puts every component of the run that made component in NX's selection (in the display assembly) and returns
    how many were selected; 0, with an Information box, when component is in no recorded set.
    """
    runs = block_set.run_of(component)
    if not runs:
        # A grid set written outside a run (code calling block_set.record directly) still has its blocks.
        grid = block_set.find(component)
        runs = [grid] if grid is not None else []
    if not runs:
        nx.message_box(_Title, NXOpen.NXMessageBox.DialogType.Information,
                       "{} is not in a recorded Merlin set.\n\nOnly components a Merlin UFunc made since 2026-11-07 "
                       "are recorded.".format(component.DisplayName))
        return 0

    display = nx.display_part()
    occurrences = _in_display(runs, display)
    # Neither call is in the NXOpen stubs.
    selection: Any = NXOpen.UI.GetUI().SelectionManager
    selection.ClearGlobalSelectionList()
    if occurrences:
        # The global selection (AddToTaggedObjectsSelectionList is for a selection dialog's handle).
        selection.RequestSelections(occurrences)
    recorded = sum(len(record.members) for record in runs)
    first = runs[0]
    nx.print_("{}: {} made {} component(s) on {} ({} part(s)); {} selected in {}.".format(
        _Title, first.builder, recorded, first.created, len(runs), len(occurrences), display.Leaf))
    for record in runs:
        nx.syslog("{}: {} - {} member(s): {}".format(_Title, record.part.Leaf, len(record.members),
                                                      ", ".join(record.member_leaves)))
    return len(occurrences)


def _preselected() -> Optional[NXOpen.Assemblies.Component]:
    """
    The one component, or body in a component, already selected - what the right-click menu's Select Set entry
    (SessionRecord's TsgContextMenu) was opened on; None for any other selection.
    """
    selection: Any = NXOpen.UI.GetUI().SelectionManager
    if selection.GetNumSelectedObjects() != 1:
        return None
    picked = selection.GetSelectedTaggedObject(0)
    if isinstance(picked, NXOpen.Assemblies.Component):
        return picked
    if isinstance(picked, NXOpen.Body) and picked.IsOccurrence:
        return picked.OwningComponent
    return None


def execute() -> None:
    component = _preselected() or _pick()
    if component is None:
        nx.mark_cancelled("the block pick")
        return
    select_set(component)


def main() -> None:
    """The select-block-set UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db
    with usage_db.run(ufunc_name):
        try:
            execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
