"""
Python port of the NX work in the CycleComponents form (src\\UFuncs\\CycleComponents.cs), whose static methods
now live in src\\Static\\CycleComponents.cs (partial class Static):

- CycleComponentsSetDisplayPart(comp)                    -> CycleComponents.set_display_part
- CycleComponentsSetDefaultLayers()                      -> CycleComponents.set_default_layers
- CycleComponentsSetBurnoutComponentState(updateViews)   -> CycleComponents.set_burnout_component_state
- CycleComponentsSet4ViewComponentState(updateViews)     -> CycleComponents.set_4view_component_state
- CycleComponentsGetChildComponents(assembly, list)      -> _get_child_components (helper)
- CycleComponentsGetAssemblyComponents(assembly, list)   -> _get_assembly_components (helper)
- CycleComponentsIsAssemblyNameValid(comp)               -> _is_assembly_name_valid (helper)
- CycleComponentsGetOneComponentOfMany(list)             -> _get_one_component_of_many (helper)
- CycleComponentsAreFullyLoaded / IsAssemblyLoaded       -> _are_fully_loaded / _is_assembly_loaded (helpers)
- CycleComponentsGetAutoSizeUdoClass()                   -> _get_auto_size_udo_class (helper, see below)
- CycleComponentsIsAutoUpdateOff(part, udoClass)         -> _is_auto_update_off (helper)

**Wired (2026-10-21), never run in NX** - the four CycleComponents entry points. The form's cycling (Prev/Next,
double-click, the first item of each list) calls Static.CycleComponentsSetDisplayPartPython -> set_display_part;
CycleComponentsSetDefaultLayers / SetBurnoutComponentState / Set4ViewComponentState now call set_default_layers /
set_burnout_component_state / set_4view_component_state, with the replaced C# commented out beside them. The C#
CycleComponentsSetDisplayPart stays live for CycleComponentsTurnOnAutoUpdate; the whole Auto Update list (UDO vs
AUTO UPDATE status, Turn On, Fix, the DESCRIPTION link) stays C#. The helpers below are not called by anything.

Not ported, deliberately:
- The cycling state machine: the Prev/Next/Return/double-click handlers, the filter buttons (Select, Select All,
  Material, Broken Links, B.O. Comp, 4-View, Auto Update Off, Non-Assoc), ClearCycleModes and the right-click
  Turn On. They read and write the form's list box, the filtered component list and the cycle modes, and the
  Select / Select All picks stay C#.
- CycleComponentsCreateMaterialList: it only reads the :COMPONENT_MATERIALS: block of the .ucf for the
  material combo and the Select All filter - no NX work.
- The helpers have no entry points: each answers a list or a bool that the C# filter consumes, and
  Session.Execute cannot hand a value back to C#. They are here for when a filter's post-pick work moves.

_get_auto_size_udo_class differs: the C# registers the UdoAutoSizeComponent class itself when NX reports it
missing (1535022, AutoSizeComponent.initializeUDO), which Python cannot do - registration and its update callback
live in the DLL. The port returns None instead, which the Auto Update Off filter already treats as "not
registered" (it prints and returns). Run from the DLL, the class is normally registered already.

The C# helpers these mirror have moved on since the port and were NOT re-ported (nothing calls the Python copies):
CycleComponentsGetChildComponents / GetAssemblyComponents now use the shared __LoadedDescendants walk (which no
longer stops at the first non-assembly child), and the Auto Update filter uses the newer UDO/attribute mismatch
helpers. Re-port from the current C# before wiring any of them.

The calls (Static\\CycleComponents.cs, through CycleComponentsPython):
    PythonLibrary.Execute("CycleComponents.py", "CycleComponents", "set_display_part", component);
    PythonLibrary.Execute("CycleComponents.py", "CycleComponents", "set_default_layers");
    PythonLibrary.Execute("CycleComponents.py", "CycleComponents", "set_burnout_component_state", updateViews);
    PythonLibrary.Execute("CycleComponents.py", "CycleComponents", "set_4view_component_state", updateViews);
"""

from __future__ import annotations

import ntpath
import os
import re
import sys
from typing import Iterable, List, Optional

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.Layer  # noqa: E402
import NXOpen.UserDefinedObjects  # noqa: E402

import tsg_nx as nx  # noqa: E402

# NXException.ErrorCode when the UdoAutoSizeComponent class is not registered in the session.
_ErrorUdoClassNotRegistered = 1535022

# UF_DRAW_set_display_state: 1 = modeling.
_Modeling = 1


def _is_detail(name: str) -> bool:
    """string.__IsDetail - the leaf (no folder, no extension) is "{digits}-{digits}-{digits}"."""
    leaf = ntpath.splitext(ntpath.basename(name))[0]
    return re.match(r"^\d+-\d+-\d+$", leaf) is not None


def _are_fully_loaded(source_comp_sp: Iterable[NXOpen.Assemblies.Component]) -> bool:
    """Static.CycleComponentsAreFullyLoaded - every unsuppressed component has a loaded Part prototype."""
    return all(isinstance(component.Prototype, NXOpen.Part)
               for component in source_comp_sp if not component.IsSuppressed)


def _is_assembly_loaded(comp_sp: NXOpen.Assemblies.Component) -> bool:
    """Static.CycleComponentsIsAssemblyLoaded - _are_fully_loaded over __DescendantsAll (root included, nothing
    skipped)."""
    return _are_fully_loaded(nx.descendants(comp_sp, include_root=True, include_suppressed=True,
                                            include_unloaded=True))


def _get_auto_size_udo_class() -> Optional[NXOpen.UserDefinedObjects.UserDefinedClass]:
    """Static.CycleComponentsGetAutoSizeUdoClass - the UdoAutoSizeComponent class, or None when it is not
    registered (the C# registers it; Python cannot - see the module docstring)."""
    class_name = "UdoAutoSizeComponent"

    try:
        return nx.session_.UserDefinedClassManager.GetUserDefinedClassFromClassName(class_name)
    except NXOpen.NXException as ex:
        if ex.ErrorCode != _ErrorUdoClassNotRegistered:
            raise
        return None


def _is_auto_update_off(part: NXOpen.Part, udo_class: NXOpen.UserDefinedObjects.UserDefinedClass) -> bool:
    """
    Static.CycleComponentsIsAutoUpdateOff - True when the part carries an AutoSize UDO whose first integer is 0.
    A part with no UDO (a library part, or a detail built before the UDO existed) is not "off" - it is unmanaged.
    """
    udos = part.UserDefinedObjectManager.GetUdosOfClass(udo_class)

    if len(udos) == 0:
        return False

    integers = udos[0].GetIntegers()
    return len(integers) > 0 and integers[0] == 0


def _part_name_of_child(instance: NXOpen.Tag) -> str:
    # The pyd docstring gives AskPartNameOfChild's rtype as "list of str"; accept either a str or a list
    # (as CopyAttributes.py does).
    part_name_result = nx.ufsession_.Assem.AskPartNameOfChild(instance)
    return part_name_result if isinstance(part_name_result, str) else part_name_result[0]


def _get_child_components(assembly: NXOpen.Assemblies.Component,
                          all_components: List[NXOpen.Assemblies.Component]) -> None:
    """
    Static.CycleComponentsGetChildComponents - adds every unsuppressed detail ({job}-{op}-{detail}) that is loaded,
    or exists on disk and opens quietly, to all_components, recursing through everything else. As in the C#, one
    try/except wraps the whole loop at each level, so a failure skips the rest of that level's children.
    """
    try:
        for child in assembly.GetChildren():
            if child.IsSuppressed:
                continue

            is_valid = _is_detail(child.DisplayName)

            if not is_valid:
                _get_child_components(child, all_components)
                continue

            instance = nx.ufsession_.Assem.AskInstOfPartOcc(child.Tag)

            if not instance:
                continue

            part_name = _part_name_of_child(instance)
            part_load = nx.ufsession_.Part.IsLoaded(part_name)

            if part_load == 1:
                all_components.append(child)
                _get_child_components(child, all_components)
                continue

            # pyd: AskFileExist(fileSpec) -> int status (0 = exists).
            status = nx.ufsession_.Cfi.AskFileExist(part_name)

            if status != 0:
                continue

            # pyd: OpenQuiet(partName) -> (part, errorStatus); part is None (or the null tag) on failure.
            part_open, _load_status = nx.ufsession_.Part.OpenQuiet(part_name)

            if not part_open:
                continue

            all_components.append(child)
            _get_child_components(child, all_components)
    except Exception as ex:
        nx.print_exception(ex)


def _get_assembly_components(assembly: NXOpen.Assemblies.Component,
                             all_components: List[NXOpen.Assemblies.Component]) -> None:
    """
    Static.CycleComponentsGetAssemblyComponents - adds the lsp/usp/lsh/ush/upr/lwr sub-assemblies to
    all_components, opening unloaded ones quietly. Quirk kept: the first child whose name is not one of those
    recurses and then RETURNS, so the rest of that level's children are never looked at.
    """
    try:
        for child in assembly.GetChildren():
            if child.IsSuppressed:
                continue

            is_valid = _is_assembly_name_valid(child)

            if not is_valid:
                _get_assembly_components(child, all_components)
                return

            instance = nx.ufsession_.Assem.AskInstOfPartOcc(child.Tag)

            if not instance:
                continue

            part_name = _part_name_of_child(instance)
            part_load = nx.ufsession_.Part.IsLoaded(part_name)

            if part_load == 1:
                all_components.append(child)
                _get_assembly_components(child, all_components)
                continue

            part_open, _load_status = nx.ufsession_.Part.OpenQuiet(part_name)

            if not part_open:
                continue

            all_components.append(child)
            _get_assembly_components(child, all_components)
    except Exception as ex:
        nx.print_exception(ex)


def _is_assembly_name_valid(comp: NXOpen.Assemblies.Component) -> bool:
    """Static.CycleComponentsIsAssemblyNameValid - the text after the last '-' contains lsp/usp, or is
    lsh/ush/upr/lwr."""
    last_index = comp.DisplayName.rfind('-')
    sub_assem_name = comp.DisplayName[last_index + 1:]

    if "lsp" in sub_assem_name or "usp" in sub_assem_name:
        return True

    return sub_assem_name in ("lsh", "ush", "upr", "lwr")


def _get_one_component_of_many(comp_list: List[NXOpen.Assemblies.Component]
                               ) -> Optional[List[NXOpen.Assemblies.Component]]:
    """
    Static.CycleComponentsGetOneComponentOfMany - the first component of each DisplayName, in order. Like the C#,
    an empty list raises (compList[0]) and the None branch can never be reached.
    """
    one_comp = [comp_list[0]]

    # The C# query is lazy, so each candidate is checked against one_comp as it grows - same as this loop.
    for comp in comp_list:
        if not any(c.DisplayName == comp.DisplayName for c in one_comp):
            one_comp.append(comp)

    return one_comp if len(one_comp) != 0 else None


def _hide_category_all(display_part: NXOpen.Part) -> None:
    """The shared 'category ALL hidden' step of the three layer setters."""
    layer_state = display_part.Layers.GetStates()
    try:
        for category in display_part.LayerCategories:
            if category.Name == "ALL":
                layer_state.SetStateOfCategory(category, NXOpen.Layer.State.Hidden)

        display_part.Layers.SetStates(layer_state, True)
    finally:
        layer_state.Dispose()


def _open_sheet(display_part: NXOpen.Part, sheet_name: str, update_views: bool) -> None:
    """Opens every drawing sheet named sheet_name, updating its drafting views when update_views."""
    for dwg_sheet in display_part.DrawingSheets:
        if dwg_sheet.Name != sheet_name:
            continue

        dwg_sheet.Open()

        if not update_views:
            continue

        for view in dwg_sheet.GetDraftingViews():
            view.Update()


class CycleComponents(object):

    @staticmethod
    def set_display_part(comp: NXOpen.Assemblies.Component) -> None:
        """Static.CycleComponentsSetDisplayPart - displays the component's part in modeling, oriented Top and
        fitted."""
        nx.set_display_part(nx.prototype(comp))
        nx.ufsession_.Draw.SetDisplayState(_Modeling)
        nx.display_part().ModelingViews.WorkView.Orient(NXOpen.View.Canned.Top, NXOpen.View.ScaleAdjustment.Fit)

    @staticmethod
    def set_default_layers() -> None:
        """
        Static.CycleComponentsSetDefaultLayers - work layer 1, category ALL hidden, then 96/99/100/200/230 (and 10
        in a layout) selectable unless one is the work layer.
        """
        try:
            display_part = nx.display_part()
            display_part.Layers.SetState(1, NXOpen.Layer.State.WorkLayer)
            # C#: a using block disposes the state collection, so the try/finally in _hide_category_all matches.
            _hide_category_all(display_part)

            layers = [96, 99, 100, 200, 230]

            if "layout" in display_part.Leaf.lower():
                layers.append(10)

            # The C# filters the list first (ToList) and then sets the states - same here.
            for i in [i for i in layers if display_part.Layers.GetState(i) != NXOpen.Layer.State.WorkLayer]:
                display_part.Layers.SetState(i, NXOpen.Layer.State.Selectable)
        except Exception as ex:
            nx.print_exception(ex)

    @staticmethod
    def set_burnout_component_state(update_views: bool) -> None:
        """
        Static.CycleComponentsSetBurnoutComponentState - modeling, work layer 100, category ALL hidden, layer 1
        selectable, and the BURNOUT sheet opened (its views updated when update_views - the form's Update Views
        check box).
        """
        try:
            nx.ufsession_.Draw.SetDisplayState(_Modeling)
            display_part = nx.display_part()
            display_part.Layers.SetState(100, NXOpen.Layer.State.WorkLayer)
            # The C# disposes the state collection only on success; disposing it in a finally is harmless.
            _hide_category_all(display_part)
            display_part.Layers.SetState(1, NXOpen.Layer.State.Selectable)
            _open_sheet(display_part, "BURNOUT", update_views)
        except Exception as ex:
            nx.print_exception(ex)

    @staticmethod
    def set_4view_component_state(update_views: bool) -> None:
        """
        Static.CycleComponentsSet4ViewComponentState - modeling, work layer 1, category ALL hidden, 94/96/99/200/230
        selectable unless one is the work layer, and the 4-VIEW sheet opened (its views updated when update_views).
        """
        try:
            nx.ufsession_.Draw.SetDisplayState(_Modeling)
            display_part = nx.display_part()
            display_part.Layers.SetState(1, NXOpen.Layer.State.WorkLayer)
            _hide_category_all(display_part)

            for i in [i for i in (94, 96, 99, 200, 230)
                      if display_part.Layers.GetState(i) != NXOpen.Layer.State.WorkLayer]:
                display_part.Layers.SetState(i, NXOpen.Layer.State.Selectable)

            _open_sheet(display_part, "4-VIEW", update_views)
        except Exception as ex:
            nx.print_exception(ex)
