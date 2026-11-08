"""
The stretch-block-x UFunc (2026-11-07) and the right-click Stretch Block submenu's engine: a component's DYNAMIC
BLOCK grows out of one side (+X / -X / +Y / -Y / +Z / -Z of the block's own axes), so that face moves out and the
other five stay put. It edits the block the way the component builder does (NewCompBuild's UpdateDynamicBlock,
src\\UFuncs\\python\\NewCompBuildEdit.py): the component made the work component, then the block's
BlockFeatureBuilder with SetOriginAndLengths - that side's size + the distance (25.4 mm an inch in a metric part), the
origin moved back by the distance for a - side, and the other two sizes' own right-hand sides, so a parallel's
uprParallel* / lwrParallel* formulas are kept (a size that is itself a formula is refused). CommitFeature alone only
stores the new size, so a DoUpdate follows; everything built on the block (its cuts, the AutoSize description)
updates with it. One undo mark, nothing saved. Run in NX 2026-11-07 on 006356-010's Window1-blank-1 (+X: 17.25 ->
18.25, the body's min corner unchanged, undone) and in batch on a made-up block (-X, +Z, -Y: only that face moved).

Ways in:
  - The right-click menu's Stretch Block > 1 in / 1/2 in / 1/4 in > side (SessionRecord's TsgContextMenu; menuscript
    buttons TSG_STRETCH_XPOS_100 ... in Menuscript\\startup\\tsg_context_menu.men): context-menu.dll's
    ContextMenuCommand calls StretchBlockX.stretch_selected(axis, positive, inches) on the selected component (a
    pick when nothing is selected). No confirm box: the menu click is the choice.
  - File -> Execute -> NX Open on this file runs main(): +X by 1", on the selection or a pick.
  - stretch(component, inches, axis, positive) from other code; component None is the display part's block.
"""

from __future__ import annotations

import os
import re
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


_AxisLetters = "XYZ"
_NumberRe = re.compile(r"^\s*[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?\s*$")


def _side(axis: int, positive: bool) -> str:
    return ("+" if positive else "-") + _AxisLetters[axis]


def stretch(component: Optional[NXOpen.Assemblies.Component], inches: float = 1.0, axis: int = 0,
            positive: bool = True) -> bool:
    """
    Grows component's DYNAMIC BLOCK by inches out of one side (component None: the display part's block): axis 0 / 1
    / 2 is the block's own X / Y / Z, positive the + side. A + side grows the length; a - side grows it and moves
    the origin back by the same distance, so the opposite face stays put. A negative inches shrinks that side
    instead. Returns whether it did; an Information box says why not.
    """
    title = "Stretch Block " + _side(axis, positive)
    part: Any = nx.display_part() if component is None else component.Prototype
    if not isinstance(part, NXOpen.Part):
        nx.message_box(title, NXOpen.NXMessageBox.DialogType.Information,
                       "{} is not loaded.".format(component.DisplayName if component is not None else "The part"))
        return False
    if part.FullPath.lower().startswith(_Library):
        nx.message_box(title, NXOpen.NXMessageBox.DialogType.Information,
                       "{} is a library part.".format(part.Leaf))
        return False
    block, why = _dynamic_block(part)
    if block is None:
        nx.message_box(title, NXOpen.NXMessageBox.DialogType.Information, why + ".")
        return False

    sizes = _size_expressions(part, block)
    target = sizes[axis]
    if not _NumberRe.match(target.RightHandSide):
        # A parallel's width / height (uprParallelHeight, ...) or another formula: a number would replace it.
        nx.message_box(title, NXOpen.NXMessageBox.DialogType.Information,
                       "{}'s block {} is driven by the formula {} = {}; it is left alone.".format(
                           part.Leaf, _AxisLetters[axis], target.Name, target.RightHandSide))
        return False
    metric = part.PartUnits == NXOpen.BasePart.Units.Millimeters
    distance = inches * (25.4 if metric else 1.0)
    old_size = float(target.Value)
    new_size = old_size + distance
    if new_size <= 0.001:
        nx.message_box(title, NXOpen.NXMessageBox.DialogType.Information,
                       "{}'s block {} is only {}.".format(part.Leaf, _AxisLetters[axis], nx.cs_double_str(old_size)))
        return False

    mark = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, title)
    previous_work = nx.session_.Parts.WorkComponent
    try:
        if component is not None:
            nx.set_work_component(component)
        else:
            nx.set_work_part(part)
        builder = part.Features.CreateBlockFeatureBuilder(block)
        try:
            origin = builder.Origin
            if not positive:
                x_axis, y_axis = builder.GetOrientation()
                z_axis = NXOpen.Vector3d(x_axis.Y * y_axis.Z - x_axis.Z * y_axis.Y,
                                         x_axis.Z * y_axis.X - x_axis.X * y_axis.Z,
                                         x_axis.X * y_axis.Y - x_axis.Y * y_axis.X)
                direction = (x_axis, y_axis, z_axis)[axis]
                origin = NXOpen.Point3d(origin.X - direction.X * distance, origin.Y - direction.Y * distance,
                                        origin.Z - direction.Z * distance)
            lengths = [expression.RightHandSide for expression in sizes]
            lengths[axis] = nx.cs_double_str(new_size)
            builder.SetOriginAndLengths(origin, lengths[0], lengths[1], lengths[2])
            builder.CommitFeature()
        finally:
            builder.Destroy()
        # CommitFeature only stores the new size: the body (and what is built on it) waits for an update.
        nx.session_.UpdateManager.DoUpdate(mark)
    finally:
        nx.set_work_component(previous_work)

    units = "mm" if metric else "in"
    nx.print_("{}: {} {} {} -> {} {}.".format(title, part.Leaf, _AxisLetters[axis],
                                              nx.cs_double_str(round(old_size, 4)),
                                              nx.cs_double_str(round(float(target.Value), 4)), units))
    return True


class StretchBlockX(object):
    """For C# (the right-click Stretch Block submenu, ContextMenuCommand): PythonLibrary.Execute("StretchBlockX.py",
    "StretchBlockX", "stretch_selected", axis, positive, inches)."""

    @staticmethod
    def stretch_selected(axis: int, positive: bool, inches: float) -> None:
        try:
            component = _preselected() or _pick()
            if component is None:
                nx.mark_cancelled("the block pick")
                return
            stretch(component, float(inches), int(axis), bool(positive))
        except Exception as ex:
            nx.print_exception(ex)


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
