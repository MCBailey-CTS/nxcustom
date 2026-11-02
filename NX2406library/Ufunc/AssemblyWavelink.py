"""
The assembly-wavelink UFunc, Python only since 2026-10-30: its menu button runs this file's main(). Ported from
src\\UFuncs\\AssemblyWavelink.cs (the form), src\\Static\\AssemblyWavelink.cs (WaveLinkFasteners, WavelinkSubtool),
src\\Static.cs (the pickers, LinkedBodyName, WaveLinkBoolean) and src\\Ui\\Dialogs\\ReferenceSetDialog.cs, all
deleted that day (in git at 97eb2a6). This module was src\\python\\assembly_wavelink.py, which the form's buttons
ran after their C# picks (2026-10-21).

The form's 14 buttons are the Operation menu of one Block Styler dialog (AssemblyWavelink.dlx, _WavelinkDialog)
holding the target / tool picks, the boolean's reference set and Blank Tool Components; its Apply button runs
wave_link_fasteners, wave_link_subtool or wave_link_boolean below. First opened in NX 2026-10-30 (as an
OK / Apply / Cancel dialog, whose OK closed it); the operations themselves are not yet confirmed there.

Since 2026-10-30 the dialog is modeless, like the form was: NX stays usable while it is up, and only Close ends it
(Apply runs an operation and stays open). main() returns as soon as it is shown, so the usage run (tblUFuncsExe, the
syslog banners) is closed when the dialog closes, and GetUnloadOption keeps this file loaded until NX exits
(UnloadLibrary disposes the dialog). A second launch while it is open just says so.
"""

import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# The shared modules are in the python folder beside this file (src\UFuncs\python; deployed, Ufunc\python).
_shared_python = os.path.join(_here, "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.BlockStyler  # noqa: E402
import NXOpen.Features  # noqa: E402
import NXOpen.Layer  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
from CopyAttributes import _is_assembly_holder  # noqa: E402
from tsg_dialog import Dialog, components_of, dispose_modeless, show_modeless, title_with_version  # noqa: E402

# Static.SubToolRefSetNames - matched against the upper-cased reference set name.
_SubToolRefSetNames = ("SUB_TOOL", "SUB-TOOL", "SUBTOOL")

# Layer the linked bodies are created on.
_LinkedBodyLayer = 96

# UF_UI_SEL_FEATURE_SOLID_BODY: the target pick takes solid bodies.
_UF_UI_SEL_FEATURE_SOLID_BODY = 36


def _linked_body_name(linked, reference_set, owner):
    """Static.LinkedBodyName"""
    if owner is None:
        return "{}, {}".format(linked.DisplayName, reference_set)
    return "{}, {}, {}".format(linked.DisplayName, reference_set, owner.DisplayName)


class AssemblyWavelink(object):

    @staticmethod
    def wave_link_fasteners(undo_name, blank_tools, shcs_ref_set, dwl_ref_set, jck_ref_set, targets, tools):
        """
        Subtracts each tool component's fasteners from every target body. Mirrors the part of the C#
        WaveLinkFasteners that runs after selection; see its doc comment for the rules.

        targets and tools are picked in C# (SelectFastenerTargetsAndTools) and passed in as TaggedObject
        arrays. Session.Execute cannot pass null, so an empty string means "no reference set" for the three
        refset arguments.
        """
        shcs_ref_set = shcs_ref_set or None
        dwl_ref_set = dwl_ref_set or None
        jck_ref_set = jck_ref_set or None
        targets = list(targets or [])
        tools = list(tools or [])

        if not targets or not tools:
            return

        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, undo_name)

        with nx.display_part_reset():
            try:
                with nx.suppress_display():
                    for target in targets:
                        for tool in tools:
                            with nx.display_part_reset(), nx.reset_work_layer():
                                try:
                                    _subtract_tool_fasteners(
                                        target, tool, shcs_ref_set, dwl_ref_set, jck_ref_set)

                                    if nx.work_part().Layers.WorkLayer != 96:
                                        nx.work_part().Layers.SetState(96, NXOpen.Layer.State.Selectable)

                                    if blank_tools:
                                        tool.Blank()
                                except Exception as ex:
                                    nx.print_exception(ex)

                nx.work_part().Layers.SetState(1, NXOpen.Layer.State.WorkLayer)
            except Exception as ex:
                nx.print_exception(ex)

    @staticmethod
    def wave_link_subtool(undo_name, target, tools):
        """
        AssemblyWavelink.WavelinkSubtool, after the picks. Subtracts each tool's sub tool geometry from the one
        target body: the tool is switched to whichever SUB_TOOL / SUB-TOOL / SUBTOOL reference set it publishes,
        linked into the target's part and subtracted, then put back on its own reference set. A tool with none
        or several of those, or that does not interfere, is reported and stepped over.

        As in the C#, any other failure ends the run (it is caught outside the tool loop).
        """
        tools = list(tools or [])

        if target is None or not tools:
            return

        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, undo_name)

        with nx.display_part_reset():
            try:
                current = nx.display_part().Layers.WorkLayer

                try:
                    nx.set_work_component(target.OwningComponent)
                    nx.display_part().Layers.SetState(_LinkedBodyLayer, NXOpen.Layer.State.WorkLayer)

                    for tool in tools:
                        # ReferenceSetReset
                        original_ref_set = tool.ReferenceSet
                        try:
                            _subtract_sub_tool(target, tool)
                        finally:
                            nx.set_reference_set(tool, original_ref_set)
                            tool.RedisplayObject()
                finally:
                    nx.display_part().Layers.SetState(current, NXOpen.Layer.State.WorkLayer)

                    if nx.work_part().Layers.WorkLayer != _LinkedBodyLayer:
                        nx.work_part().Layers.SetState(_LinkedBodyLayer, NXOpen.Layer.State.Selectable)
            except Exception as ex:
                nx.print_exception(ex)

        nx.work_part().Layers.SetState(1, NXOpen.Layer.State.WorkLayer)

    @staticmethod
    def wave_link_boolean(blank_tools, boolean_type, reference_set, targets, tools):
        """
        Static.WaveLinkBoolean, after the picks and the reference-set dialog. Links every tool,
        through reference_set, into every target's part (one LINKED_BODY per solid body) and applies the
        boolean to each link. boolean_type is the Feature.BooleanType member name - "Subtract", "Unite",
        "Intersect", or "Create", which links only.

        As in the C#, a failure inside one link prints and moves on; a failure to make the links ends the run.
        """
        targets = list(targets or [])
        tools = list(tools or [])

        if not targets or not tools or not reference_set:
            return

        link_only = boolean_type == "Create"
        operation = getattr(NXOpen.Features.Feature.BooleanType, boolean_type)

        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Assembly Wavelink")

        with nx.display_part_reset():
            try:
                for target in targets:
                    for tool in tools:
                        with nx.display_part_reset():
                            nx.set_work_component(target.OwningComponent)
                            nx.display_part().Layers.SetState(_LinkedBodyLayer, NXOpen.Layer.State.WorkLayer)

                            current_ref_set = tool.ReferenceSet
                            nx.set_reference_set(tool, reference_set)

                            try:
                                for ext in nx.create_linked_bodies(tool):
                                    try:
                                        ext.SetName(_linked_body_name(tool, reference_set, tool.Parent))
                                        nx.print_("//////////////////")
                                        nx.print_("Created {} in {}".format(ext.GetFeatureName(), ext.OwningPart.Leaf))

                                        if link_only:
                                            continue

                                        boolean_feature = nx.create_boolean(target, ext.GetBodies(), operation)
                                        nx.print_("Created {} in {}".format(
                                            boolean_feature.GetFeatureName(), ext.OwningPart.Leaf))
                                    except NXOpen.NXException as ex:
                                        if ex.ErrorCode == nx.ErrorNoInterference:
                                            nx.print_("Error occurred when trying to subtract {}, no interference."
                                                      .format(tool.DisplayName))
                                        else:
                                            nx.print_exception(ex)
                                    except Exception as ex:
                                        nx.print_exception(ex)
                            finally:
                                nx.set_reference_set(tool, current_ref_set)

                            if nx.work_part().Layers.WorkLayer != _LinkedBodyLayer:
                                nx.work_part().Layers.SetState(_LinkedBodyLayer, NXOpen.Layer.State.Selectable)

                nx.work_part().Layers.SetState(1, NXOpen.Layer.State.WorkLayer)

                if blank_tools:
                    for tool in tools:
                        tool.Blank()
            except Exception as ex:
                nx.print_exception(ex)


def _subtract_sub_tool(target, tool):
    """The body of the WavelinkSubtool tool loop."""
    matches = [r for r in nx.prototype(tool).GetAllReferenceSets() if r.Name.upper() in _SubToolRefSetNames]

    # SingleOrDefault: several is the InvalidOperationException the C# catches.
    if len(matches) > 1:
        nx.print_("Found more than one sub tool reference set for {} - {} - {}".format(
            tool.DisplayName, tool.Name, tool.Tag))
        return

    if not matches:
        nx.print_("Didn't find any sub tool reference sets for {} - {} - {}".format(
            tool.DisplayName, tool.Name, tool.Tag))
        return

    reference_set = matches[0].Name
    nx.set_reference_set(tool, reference_set)
    linked_body = nx.create_linked_body(tool)
    # The tool is what gets linked here, so its own parent is the owner field.
    linked_body.SetName(_linked_body_name(tool, reference_set, tool.Parent))
    nx.print_("//////////////////")
    nx.print_("Created {} in {}".format(linked_body.GetFeatureName(), linked_body.OwningPart.Leaf))

    try:
        boolean_feature = nx.subtract(target, linked_body.GetBodies())
    except NXOpen.NXException as ex:
        if ex.ErrorCode != nx.ErrorNoInterference:
            raise
        nx.print_("Error occurred when trying to subtract {}, no interference.".format(tool.DisplayName))
        return

    nx.print_("Created {} in {}".format(boolean_feature.GetFeatureName(), linked_body.OwningPart.Leaf))


def _subtract_tool_fasteners(target, tool, shcs_ref_set, dwl_ref_set, jck_ref_set):
    nx.set_work_component(target.OwningComponent)
    nx.display_part().Layers.SetState(96, NXOpen.Layer.State.WorkLayer)

    ref_sets = [r for r in (shcs_ref_set, dwl_ref_set) if r]

    for child in tool.GetChildren():
        try:
            if not nx.is_loaded(child):
                nx.print_("Child fastener {} was not loaded.".format(child.DisplayName))
                continue

            if child.IsSuppressed:
                continue

            original_ref_set = child.ReferenceSet
            proto_child = nx.proto_child_comp(child)

            if proto_child.Layer != nx.LayerFastener and proto_child.Layer != 90:
                continue

            try:
                # Intersect keeps the prototype's order, like LINQ's Intersect.
                names = [n for n in nx.reference_set_names(proto_child.Prototype) if n in ref_sets]
                names = list(dict.fromkeys(names))

                if len(names) == 0:
                    # Same grouping as the C#: the last clause is (jck and tsg) or plain jck.
                    if ((shcs_ref_set is not None and nx.is_shcs(child.DisplayName))
                            or (dwl_ref_set is not None and nx.is_dwl(child.DisplayName))
                            or (jck_ref_set is not None and nx.is_jck_screw_tsg(child.DisplayName))
                            or nx.is_jck_screw(child.DisplayName)):
                        nx.print_("Coulnd't find any valid ref sets for {}".format(child.DisplayName))
                    continue

                if len(names) > 1:
                    nx.print_("Found more than one valid ref set for {}".format(child.DisplayName))
                    continue

                nx.set_reference_set(child, names[0])

                if not nx.interferes_with(target, child):
                    nx.print_("Could not subtract fastener {}, no interference.".format(child.DisplayName))
                    continue

                ext = nx.create_linked_body(child)
                ext.SetName(_linked_body_name(child, names[0], tool))
                nx.print_("//////////////////")
                nx.print_("Created {} in {}".format(ext.GetFeatureName(), ext.OwningPart.Leaf))
                boolean_feature = nx.subtract(target, ext.GetBodies())
                nx.print_("Created {} in {}".format(boolean_feature.GetFeatureName(), ext.OwningPart.Leaf))
                nx.set_reference_set(child, original_ref_set)
            except Exception as ex:
                nx.print_exception(ex, child.DisplayName)
        except Exception as ex:
            nx.print_exception(ex)


# ---------------------------------------------------------------------------------------------------
# The dialog (AssemblyWavelink.dlx, 2026-10-30) - the WinForms form, its pickers and the ReferenceSetDialog
# ---------------------------------------------------------------------------------------------------

ufunc_name = "assembly-wavelink"

# Globals.cs reference set constants the form's buttons passed.
_RefsetTap, _RefsetShortTap, _RefsetReam, _RefsetReamShort = "TAP", "SHORT-TAP", "REAM", "REAM_SHORT"
_RefsetClrHole, _RefsetCBore, _RefsetTapInsert = "CLR_HOLE", "CBORE", "TAP_INSERT"

# The Operation menu (the form's buttons, in its order) -> the fastener button's (shcs, dwl, jck) reference sets.
_FastenerOperations: Dict[str, Tuple[Optional[str], Optional[str], Optional[str]]] = {
    "Tap & Ream": (_RefsetTap, _RefsetReam, None),
    "Short - Tap & Ream": (_RefsetShortTap, _RefsetReamShort, None),
    "Tap": (_RefsetTap, None, None),
    "Tap Insert": (_RefsetTapInsert, None, None),
    "Ream": (None, _RefsetReam, None),
    "Short-Tap": (_RefsetShortTap, None, None),
    "Short-Ream": (None, _RefsetReamShort, None),
    "Clr-Hole": (_RefsetClrHole, _RefsetClrHole, _RefsetClrHole),
    "Cbore": (_RefsetCBore, _RefsetCBore, None),
}
_OperationSubTool = "Sub-Tool"
# The boolean buttons -> Feature.BooleanType member names (Link = Create: links only).
_BooleanOperations: Dict[str, str] = {"Subtract": "Subtract", "Unite": "Unite", "Intersect": "Intersect",
                                      "Link": "Create"}

# The reference set menu when the picked tools share none (SetEnumMembers needs one member).
_NoReferenceSet = "(no common reference set)"

_ErrorCannotLaunchDialog = 3520048


def _is_layout(name: str) -> bool:
    """string._IsLayout_"""
    return "-layout" in name.lower()


def _is_fastener_extended(name: str) -> bool:
    """
    string._IsFastenerExtended_ - a SHCS, dowel or jack screw (substring tests: the C#'s __IsFastener used the
    stricter regexes), or a LHCS / SSS / BHCS / FHCS / BLHCS.
    """
    lower = name.lower()
    return (nx.is_shcs(name) or nx.is_dwl(name) or nx.is_jck_screw(name) or nx.is_jck_screw_tsg(name)
            or any(token in lower for token in ("-lhcs-", "-sss-", "-bhcs-", "-fhcs-", "0375-bhcs-062",
                                                 "10mm-bhcs-016")))


def _reference_set_names(component: NXOpen.Assemblies.Component) -> List[str]:
    return [r.Name for r in nx.prototype(component).GetAllReferenceSets()]


def _common_reference_sets(tools: Sequence[NXOpen.Assemblies.Component], exclude: Sequence[str]) -> List[str]:
    """ReferenceSetDialog.CommonReferenceSets - the reference sets every tool has, minus exclude, sorted."""
    if not tools:
        return []
    common = set(_reference_set_names(tools[0]))
    for tool in tools[1:]:
        common &= set(_reference_set_names(tool))
    return sorted(name for name in common if name not in exclude)


class _WavelinkDialog(Dialog):
    """
    AssemblyWavelink.dlx, in place of the WinForms form, its pickers (Static.SelectFastenerTargetsAndTools,
    SelectSubToolTargetAndTools, SelectBooleanTargetsAndTools) and the ReferenceSetDialog:
      - Operation: the form's 14 buttons;
      - Target bodies (solid, anywhere in the assembly; one for Sub-Tool - a new pick replaces the old);
      - Tool components;
      - Reference set (the booleans only): the reference sets every picked tool has, BODY left out except for Link;
      - Blank Tool Components (chkBlankTools; Sub-Tool never read it).
    The pickers' filters run as the cursor passes over an object (filter(), 2026-10-30): one they reject does not
    highlight and cannot be picked. update() applies them again to what is already picked, since changing the
    operation or the targets can make an earlier pick invalid (and keeps Sub-Tool to the latest target). The
    dialog is modeless and Close only: its Apply button runs the operation, clears both picks and stays open, as the
    form did (an OK closed the modeless dialog too, 2026-10-30). Closing it without an Apply marks the run cancelled.
    """

    dlx_name = "AssemblyWavelink.dlx"

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__()
        self._reference_sets: List[str] = []
        # The usage run execute() opened; the operations file their exceptions under it (other UFuncs may run while
        # the dialog is up).
        self.usage_run: Optional[Any] = None

    def initialize(self) -> None:
        mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type, 0, _UF_UI_SEL_FEATURE_SOLID_BODY)
        self.block("targets").SetSelectionFilter(NXOpen.Selection.SelectionAction.ClearAndEnableSpecific, [mask])
        self.assembly_scope(self.block("targets"))
        self.component_filter(self.block("tools"))
        self.assembly_scope(self.block("tools"))

    def shown(self) -> None:
        self._refresh()

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        if block == self.block("apply"):
            try:
                self._apply()
            finally:
                self._refresh()
            return
        if block == self.block("operation") or block == self.block("targets"):
            self._filter_targets()
            self._filter_tools()
        elif block == self.block("tools"):
            self._filter_tools()
        self._refresh()

    def filter(self, block: NXOpen.BlockStyler.UIBlock, obj: NXOpen.TaggedObject) -> bool:
        if block == self.block("targets"):
            return isinstance(obj, NXOpen.Body) and self._target_ok(obj)
        if block == self.block("tools"):
            return isinstance(obj, NXOpen.Assemblies.Component) and self._tool_ok(obj, self._target_owners())
        return True

    def _can_apply(self) -> bool:
        if not self._targets() or not self._tools():
            return False
        return not self._is_boolean() or self._reference_set() is not None

    def _apply(self) -> None:
        """The Apply button: run the operation, then clear both picks for the next one."""
        if not self._run_operation():
            return
        self.applied = True
        self.block("targets").SetSelectedObjects([])
        self.block("tools").SetSelectedObjects([])

    def _run_operation(self) -> bool:
        if self.usage_run is not None:
            import usage_db
            usage_db.resume(self.usage_run)
        targets, tools = self._targets(), self._tools()
        if not targets or not tools:
            # _refresh greys Apply out for this; it is a backstop.
            self.message("Select the target bodies and the tool components.")
            return False
        operation = self._operation()
        blank_tools = bool(self.block("blank_tools").Value)
        undo_name = title_with_version(ufunc_name)
        if operation in _FastenerOperations:
            shcs, dwl, jck = _FastenerOperations[operation]
            AssemblyWavelink.wave_link_fasteners(undo_name, blank_tools, shcs or "", dwl or "", jck or "", targets,
                                                 tools)
        elif operation == _OperationSubTool:
            AssemblyWavelink.wave_link_subtool("{} - WavelinkSubtool".format(undo_name), targets[0], tools)
        else:
            reference_set = self._reference_set()
            if reference_set is None:
                self.message("The picked tools share no reference set to link through.")
                return False
            AssemblyWavelink.wave_link_boolean(blank_tools, _BooleanOperations[operation], reference_set, targets,
                                               tools)
        return True

    # ----- picks -----

    def _operation(self) -> str:
        return str(self.block("operation").ValueAsString)

    def _is_boolean(self) -> bool:
        return self._operation() in _BooleanOperations

    def _targets(self) -> List[NXOpen.Body]:
        return [cast(NXOpen.Body, o) for o in self.selected(self.block("targets")) if isinstance(o, NXOpen.Body)]

    def _tools(self) -> List[NXOpen.Assemblies.Component]:
        return components_of(self.selected(self.block("tools")))

    def _target_ok(self, body: NXOpen.Body) -> bool:
        if not body.IsSolidBody:
            return False
        if self._operation() not in _FastenerOperations:
            return True
        # SelectFastenerTargetsAndTools: an occurrence, not in a strip / press / layout or an assembly holder.
        if not body.IsOccurrence:
            return False
        name = body.OwningComponent.DisplayName
        lower = name.lower()
        return not any(token in lower for token in ("strip", "press", "layout")) and not _is_assembly_holder(name)

    def _tool_ok(self, tool: NXOpen.Assemblies.Component, target_owners: Set[int]) -> bool:
        name = tool.DisplayName
        if tool.Tag in target_owners or _is_assembly_holder(name):
            return False
        operation = self._operation()
        if operation in _FastenerOperations:
            return not _is_layout(name) and "strip" not in name.lower() and not _is_fastener_extended(name)
        if operation == _OperationSubTool:
            return any(n.upper() in _SubToolRefSetNames for n in _reference_set_names(tool))
        return True

    def _filter_targets(self) -> None:
        picked = self._targets()
        kept = [b for b in picked if self._target_ok(b)]
        if self._operation() == _OperationSubTool and len(kept) > 1:
            # SelectSingleSolidBody1: one target - the latest pick wins.
            kept = kept[-1:]
        if len(kept) != len(picked):
            self.block("targets").SetSelectedObjects(kept)

    def _target_owners(self) -> Set[int]:
        """The tags of the picked targets' components - a tool may not be one of them."""
        return {b.OwningComponent.Tag for b in self._targets() if b.OwningComponent is not None}

    def _filter_tools(self) -> None:
        owners = self._target_owners()
        picked = self._tools()
        kept = [t for t in picked if self._tool_ok(t, owners)]
        if len(kept) != len(picked):
            self.block("tools").SetSelectedObjects(kept)

    # ----- reference set -----

    def _reference_set(self) -> Optional[str]:
        if not self._reference_sets:
            return None
        value = str(self.block("reference_set").ValueAsString)
        return value if value in self._reference_sets else None

    def _refresh(self) -> None:
        try:
            self._refresh_reference_sets()
        finally:
            # Apply stands in for the OK a Close-only dialog has not got: greyed out until there is something to run.
            self.block("apply").Enable = self._can_apply()

    def _refresh_reference_sets(self) -> None:
        boolean = self._is_boolean()
        self.block("reference_set").Show = boolean
        self.block("blank_tools").Enable = self._operation() != _OperationSubTool
        if not boolean:
            return
        exclude = [] if self._operation() == "Link" else ["BODY"]
        names = _common_reference_sets(self._tools(), exclude)
        if names == self._reference_sets:
            return
        previous = self._reference_set()
        self._reference_sets = names
        self.block("reference_set").SetEnumMembers(names or [_NoReferenceSet])
        self.block("reference_set").ValueAsString = previous if previous in names else (names or [_NoReferenceSet])[0]


def execute() -> None:
    """
    The form, as a modeless Block Styler dialog: shows it and returns. Opens the usage run, which the dialog's close
    ends (or this, when the dialog never opened).
    """
    import usage_db

    current = usage_db.start_run(ufunc_name)
    try:
        dialog = _WavelinkDialog(title_with_version("Assembly Wavelink"))
        dialog.usage_run = current
        if not show_modeless(ufunc_name, dialog, lambda response: usage_db.finish_run(current)):
            usage_db.mark_cancelled("already open")
            usage_db.finish_run(current)
    except NXOpen.NXException as ex:
        if ex.ErrorCode != _ErrorCannotLaunchDialog:
            usage_db.finish_run(current, ex)
            raise
        nx.print_exception(ex)
        usage_db.finish_run(current)
    except BaseException as ex:
        usage_db.finish_run(current, ex)
        raise


def main() -> None:
    """The assembly-wavelink UFunc - its menu button runs this file. An escaping exception is printed."""
    try:
        execute()
    except Exception as ex:
        nx.print_exception(ex)


# Session.LibraryUnloadOption.AtTermination (Immediately 1, Explicitly 2, AtTermination 3 in NXOpen.dll 2306). NX's
# Python has no LibraryUnloadOption enum, so the number.
_UnloadAtTermination = 3


def GetUnloadOption(arg: Any) -> int:
    """NX: keep this file loaded while the modeless dialog may be up - until NX exits."""
    return _UnloadAtTermination


def UnloadLibrary(arg: Any) -> None:
    """NX, at exit: dispose the dialog (open or closed)."""
    dispose_modeless(ufunc_name)


if __name__ == "__main__":
    main()
