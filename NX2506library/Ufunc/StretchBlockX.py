"""
The stretch-block-x UFunc (2026-11-07): the DYNAMIC BLOCK of one component grows 1" along its own +X, so its +X face
moves out and the other five stay put. It edits the block the way the component builder does (NewCompBuild's
UpdateDynamicBlock, src\\UFuncs\\python\\NewCompBuildEdit.py): the component made the work component, then the
block's BlockFeatureBuilder with SetOriginAndLengths - the same origin, Length + 1" (25.4 in a metric part), and the
Width and Height expressions' own right-hand sides, so a parallel's uprParallel* / lwrParallel* formulas are kept.
CommitFeature alone only stores the new length, so a DoUpdate follows; everything built on the block (its cuts,
the AutoSize description) updates with it. Run in NX 2026-11-07 on 006356-010's Window1-blank-1 (17.25 -> 18.25, the
body's min corner unchanged), then undone. One undo mark, nothing saved.

Its way in is the right-click menu: Stretch +X 1 in (SessionRecord's TsgContextMenu, shown for one component whose part
has one DYNAMIC BLOCK; the menuscript button TSG_STRETCH_BLOCK_X in Menuscript\\startup\\tsg_context_menu.men). With
one component (or a body in one) already selected that is the target, with no confirm box: the menu click is the
choice. Otherwise it asks for one, and the pick is the choice.

  - File -> Execute -> NX Open on this file runs main().
  - stretch(component, inches=1.0) from other code; component None is the display part's block.
"""

from __future__ import annotations

import os
import sys
from typing import Any, List, Optional, Tuple

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
import NXOpen.Features  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402

ufunc_name = "stretch-block-x"
_Title = "Stretch Block +X"
# UF_UI_SEL_FEATURE_SOLID_BODY (not in UFConstants' Python stubs; AssemblyWavelink uses the same value).
_UF_UI_SEL_FEATURE_SOLID_BODY = 36
_Library = "g:" + chr(92) + "0library"


def _preselected() -> Optional[NXOpen.Assemblies.Component]:
    """The one component, or body in a component, already selected (the right-click menu's target)."""
    selection: Any = NXOpen.UI.GetUI().SelectionManager
    if selection.GetNumSelectedObjects() != 1:
        return None
    picked = selection.GetSelectedTaggedObject(0)
    if isinstance(picked, NXOpen.Assemblies.Component):
        return picked
    if isinstance(picked, NXOpen.Body) and picked.IsOccurrence:
        return picked.OwningComponent
    return None


def _pick() -> Optional[NXOpen.Assemblies.Component]:
    """One component or solid body, any in the assembly; the body's component. None on cancel."""
    masks = [NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_component_type, 0, 0),
             NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type, 0, _UF_UI_SEL_FEATURE_SOLID_BODY)]
    cue = "Select the dynamic block to stretch 1 inch along its +X"
    nx.prompt(cue)
    response, picked, _ = NXOpen.UI.GetUI().SelectionManager.SelectTaggedObject(
        cue, _Title, NXOpen.Selection.SelectionScope.AnyInAssembly,
        NXOpen.Selection.SelectionAction.ClearAndEnableSpecific, False, False, masks)
    if response not in (NXOpen.Selection.Response.ObjectSelected, NXOpen.Selection.Response.ObjectSelectedByName):
        return None
    if isinstance(picked, NXOpen.Assemblies.Component):
        return picked
    if isinstance(picked, NXOpen.Body):
        return picked.OwningComponent
    return None


def _dynamic_block(part: NXOpen.Part) -> Tuple[Optional[NXOpen.Features.Block], str]:
    """The part's one unsuppressed DYNAMIC BLOCK, or None and why not."""
    blocks = [f for f in part.Features.GetFeatures()
              if isinstance(f, NXOpen.Features.Block) and f.Name == "DYNAMIC BLOCK"]
    if len(blocks) != 1:
        return None, "{} has {} DYNAMIC BLOCK features, not one".format(part.Leaf, len(blocks))
    if blocks[0].Suppressed:
        return None, "{}'s DYNAMIC BLOCK is suppressed".format(part.Leaf)
    return blocks[0], ""


def _size_expressions(part: NXOpen.Part, block: NXOpen.Features.Block) -> List[Any]:
    """The block's Length, Width and Height expressions (UF_MODL_ask_block_parms: "name=value" each)."""
    parms = nx.ufsession_.ModlFeatures.AskBlockParms(block.Tag, 0)
    return [part.Expressions.FindObject(parm.split("=", 1)[0].strip()) for parm in parms]


def stretch(component: Optional[NXOpen.Assemblies.Component], inches: float = 1.0) -> bool:
    """
    Grows component's DYNAMIC BLOCK by inches along the block's +X (component None: the display part's). Returns
    whether it did; an Information box says why not.
    """
    part: Any = nx.display_part() if component is None else component.Prototype
    if not isinstance(part, NXOpen.Part):
        nx.message_box(_Title, NXOpen.NXMessageBox.DialogType.Information,
                       "{} is not loaded.".format(component.DisplayName if component is not None else "The part"))
        return False
    if part.FullPath.lower().startswith(_Library):
        nx.message_box(_Title, NXOpen.NXMessageBox.DialogType.Information,
                       "{} is a library part.".format(part.Leaf))
        return False
    block, why = _dynamic_block(part)
    if block is None:
        nx.message_box(_Title, NXOpen.NXMessageBox.DialogType.Information, why + ".")
        return False

    length, width, height = _size_expressions(part, block)
    metric = part.PartUnits == NXOpen.BasePart.Units.Millimeters
    distance = inches * (25.4 if metric else 1.0)
    old_length = float(length.Value)
    new_length = old_length + distance

    mark = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, _Title)
    previous_work = nx.session_.Parts.WorkComponent
    try:
        if component is not None:
            nx.set_work_component(component)
        else:
            nx.set_work_part(part)
        builder = part.Features.CreateBlockFeatureBuilder(block)
        try:
            builder.SetOriginAndLengths(builder.Origin, nx.cs_double_str(new_length), width.RightHandSide,
                                        height.RightHandSide)
            builder.CommitFeature()
        finally:
            builder.Destroy()
        # CommitFeature only stores the new length: the body (and what is built on it) waits for an update.
        nx.session_.UpdateManager.DoUpdate(mark)
    finally:
        nx.set_work_component(previous_work)

    units = "mm" if metric else "in"
    nx.print_("{}: {} length {} -> {} {}.".format(_Title, part.Leaf, nx.cs_double_str(round(old_length, 4)),
                                                 nx.cs_double_str(round(float(length.Value), 4)), units))
    return True


def execute() -> None:
    component = _preselected() or _pick()
    if component is None:
        nx.mark_cancelled("the block pick")
        return
    stretch(component)


def main() -> None:
    """The stretch-block-x UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db
    with usage_db.run(ufunc_name):
        try:
            execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
