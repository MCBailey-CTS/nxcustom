"""
The assembly-wavelink UFunc, Python only since 2026-10-30: its menu button runs this file's main(). Ported from
src\\UFuncs\\AssemblyWavelink.cs (the form), src\\Static\\AssemblyWavelink.cs (WaveLinkFasteners, WavelinkSubtool),
src\\Static.cs (the pickers, LinkedBodyName, WaveLinkBoolean) and src\\Ui\\Dialogs\\ReferenceSetDialog.cs, all
deleted that day (in git at 97eb2a6). This module was src\\python\\assembly_wavelink.py, which the form's buttons
ran after their C# picks (2026-10-21).

The form's 14 buttons are real buttons again (2026-11-05), in its Fasteners and Booleans groups, two to a row, in one
Block Styler dialog (AssemblyWavelink.dlx, _WavelinkDialog) below the target / tool picks, with the boolean's reference
set and Blank Tool Components after them. A button runs wave_link_fasteners, wave_link_subtool or wave_link_boolean
below on the picks, so the picks now come first: NX opens no selection from a dialog callback, which is how the form
picked after the click. First opened in NX 2026-10-30 (as an OK / Apply / Cancel dialog, whose OK closed it); the
operations themselves are not yet confirmed there.

Since 2026-10-30 the dialog is modeless, like the form was: NX stays usable while it is up, and only Close ends it
(a button runs an operation and stays open). main() returns as soon as it is shown, so the usage run (tblUFuncsExe, the
syslog banners) is closed when the dialog closes, and GetUnloadOption keeps this file loaded until NX exits
(UnloadLibrary disposes the dialog). A second launch while it is open just says so.

The picks work like Profile Subtract's (2026-11-06): many targets and one tool, or one target and many tools. Picking
past that keeps the side just changed to its latest pick, as a single selection would. No body in a strip or layout can
be a target. The target bodies are blanked when the Tool components selection gets focus, so the tools behind them can
be picked, and shown again when the Target bodies selection gets focus, an operation runs or the dialog closes.
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

# The fastener buttons -> their (shcs, dwl, jck) reference sets.
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
# AssemblyWavelink.dlx's button ids -> the operations above.
_OperationButtons: Dict[str, str] = {
    "short_tap_ream": "Short - Tap & Ream", "tap_ream": "Tap & Ream", "tap": "Tap", "ream": "Ream",
    "short_tap": "Short-Tap", "short_ream": "Short-Ream", "clr_hole": "Clr-Hole", "cbore": "Cbore",
    "tap_insert": "Tap Insert", "subtract": "Subtract", "unite": "Unite", "intersect": "Intersect", "link": "Link",
    "sub_tool": _OperationSubTool}
# Only Link goes through BODY; the form's reference set dialog left it out of the other booleans.
_RefsetBody = "BODY"

# The reference set menu when the picked tools share none (SetEnumMembers needs one member).
_NoReferenceSet = "(no common reference set)"

_ErrorCannotLaunchDialog = 3520048


def _is_layout(name: str) -> bool:
    """string._IsLayout_"""
    return "-layout" in name.lower()


def _in_strip_or_layout(body: NXOpen.Body) -> bool:
    """The body's component or any assembly above it is a strip or layout (its own part, when not an occurrence)."""
    component: Optional[NXOpen.Assemblies.Component] = body.OwningComponent
    names = [] if component is not None else [cast(NXOpen.Part, body.OwningPart).Leaf]
    while component is not None:
        names.append(component.DisplayName)
        component = component.Parent
    return any("strip" in name.lower() or "layout" in name.lower() for name in names)


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
      - Target bodies (solid, anywhere in the assembly, not in a strip or layout) and Tool components: many targets
        and one tool, or one target and many tools (_limit_picks). The targets are blanked while the tools are picked
        (focus);
      - Fasteners and Booleans: the form's 14 buttons, each running on those picks;
      - Reference set (for the booleans): the reference sets every picked tool has;
      - Blank Tool Components (chkBlankTools; Sub-Tool never read it).
    The operation is only known when its button is pressed, so filter() (2026-10-30: a rejected object does not
    highlight and cannot be picked) holds the rules every operation shares, and the button applies the rest
    (_picks_for), listing what it leaves out. A button runs the operation, clears both picks and stays open, as the
    form did. The buttons are greyed out until there is something to run. The dialog is modeless and Close only;
    closing it without running anything marks the run cancelled.
    """

    dlx_name = "AssemblyWavelink.dlx"

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__()
        self._reference_sets: List[str] = []
        # The target bodies blanked for the tool pick, by tag.
        self._blanked: Dict[int, NXOpen.Body] = {}
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
        for button, operation in _OperationButtons.items():
            if block == self.block(button):
                try:
                    self._press(operation)
                finally:
                    self._refresh()
                return
        if block == self.block("targets") or block == self.block("tools"):
            self._filter_tools()
            self._limit_picks(block)
        # focus() normally got here first.
        if block == self.block("tools"):
            self._hide_targets()
        self._refresh()

    def focus(self, block: NXOpen.BlockStyler.UIBlock, gained: bool) -> None:
        if not gained:
            return
        if block == self.block("tools"):
            self._hide_targets()
        elif block == self.block("targets"):
            self.show_targets()

    def filter(self, block: NXOpen.BlockStyler.UIBlock, obj: NXOpen.TaggedObject) -> bool:
        if block == self.block("targets"):
            return isinstance(obj, NXOpen.Body) and obj.IsSolidBody and not _in_strip_or_layout(obj)
        if block == self.block("tools"):
            return isinstance(obj, NXOpen.Assemblies.Component) and self._tool_allowed(obj, self._target_owners())
        return True

    def _can_run(self) -> bool:
        return bool(self._targets()) and bool(self._tools())

    def _press(self, operation: str) -> None:
        """An operation's button: run it on the picks, then clear both for the next one."""
        if not self._run_operation(operation):
            return
        self.applied = True
        self.block("targets").SetSelectedObjects([])
        self.block("tools").SetSelectedObjects([])

    def _run_operation(self, operation: str) -> bool:
        if self.usage_run is not None:
            import usage_db
            usage_db.resume(self.usage_run)
        targets, tools = self._picks_for(operation)
        if not targets or not tools:
            self.message("{}: no target body and tool component to run on - the listing window says why.".format(
                operation))
            return False
        blank_tools = bool(self.block("blank_tools").Value)
        undo_name = title_with_version(ufunc_name)
        if operation in _FastenerOperations:
            shcs, dwl, jck = _FastenerOperations[operation]
            self.show_targets()
            AssemblyWavelink.wave_link_fasteners(undo_name, blank_tools, shcs or "", dwl or "", jck or "", targets,
                                                 tools)
        elif operation == _OperationSubTool:
            # SelectSingleSolidBody1: the form took one target.
            if len(targets) > 1:
                self.message("Sub-Tool takes one target body; {} are picked.".format(len(targets)))
                return False
            self.show_targets()
            AssemblyWavelink.wave_link_subtool("{} - WavelinkSubtool".format(undo_name), targets[0], tools)
        else:
            reference_set = self._reference_set()
            if reference_set is None:
                self.message("The picked tools share no reference set to link through.")
                return False
            if reference_set == _RefsetBody and operation != "Link":
                self.message("{} cannot go through BODY: pick another reference set.".format(operation))
                return False
            self.show_targets()
            AssemblyWavelink.wave_link_boolean(blank_tools, _BooleanOperations[operation], reference_set, targets,
                                               tools)
        return True

    # ----- picks -----

    def _targets(self) -> List[NXOpen.Body]:
        return [cast(NXOpen.Body, o) for o in self.selected(self.block("targets")) if isinstance(o, NXOpen.Body)]

    def _tools(self) -> List[NXOpen.Assemblies.Component]:
        return components_of(self.selected(self.block("tools")))

    def _target_ok(self, body: NXOpen.Body, operation: str) -> bool:
        if operation not in _FastenerOperations:
            return True
        # SelectFastenerTargetsAndTools: an occurrence, not in a strip / press / layout or an assembly holder.
        if not body.IsOccurrence:
            return False
        name = body.OwningComponent.DisplayName
        lower = name.lower()
        return not any(token in lower for token in ("strip", "press", "layout")) and not _is_assembly_holder(name)

    @staticmethod
    def _tool_allowed(tool: NXOpen.Assemblies.Component, target_owners: Set[int]) -> bool:
        """The rule every operation shares."""
        return tool.Tag not in target_owners and not _is_assembly_holder(tool.DisplayName)

    def _tool_ok(self, tool: NXOpen.Assemblies.Component, operation: str) -> bool:
        name = tool.DisplayName
        if operation in _FastenerOperations:
            return not _is_layout(name) and "strip" not in name.lower() and not _is_fastener_extended(name)
        if operation == _OperationSubTool:
            return any(n.upper() in _SubToolRefSetNames for n in _reference_set_names(tool))
        return True

    def _picks_for(self, operation: str) -> Tuple[List[NXOpen.Body], List[NXOpen.Assemblies.Component]]:
        """The picks the operation's own form picker would have allowed; the rest are listed, not run on."""
        targets: List[NXOpen.Body] = []
        tools: List[NXOpen.Assemblies.Component] = []
        for body in self._targets():
            if self._target_ok(body, operation):
                targets.append(body)
            else:
                owner = body.OwningComponent
                nx.print_("{}: skipped target body in {}.".format(
                    operation, owner.DisplayName if owner is not None else body.OwningPart.Leaf))
        for tool in self._tools():
            if self._tool_ok(tool, operation):
                tools.append(tool)
            else:
                nx.print_("{}: skipped tool {}.".format(operation, tool.DisplayName))
        return targets, tools

    def _target_owners(self) -> Set[int]:
        """The tags of the picked targets' components - a tool may not be one of them."""
        return {b.OwningComponent.Tag for b in self._targets() if b.OwningComponent is not None}

    def _filter_tools(self) -> None:
        owners = self._target_owners()
        picked = self._tools()
        kept = [t for t in picked if self._tool_allowed(t, owners)]
        if len(kept) != len(picked):
            self.block("tools").SetSelectedObjects(kept)

    def _limit_picks(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        """Many targets and one tool, or one target and many tools: past that, block keeps only its latest pick."""
        targets, tools = self._targets(), self._tools()
        if len(targets) > 1 and len(tools) > 1:
            cast(Any, block).SetSelectedObjects((targets if block == self.block("targets") else tools)[-1:])

    def _hide_targets(self) -> None:
        """Blanks the picked target bodies, so the tools behind them can be picked."""
        for body in self._targets():
            if body.Tag not in self._blanked:
                try:
                    body.Blank()
                    self._blanked[body.Tag] = body
                except Exception as ex:
                    nx.print_exception(ex)

    def show_targets(self) -> None:
        """Shows every target body _hide_targets blanked again (no-op when none)."""
        for body in self._blanked.values():
            try:
                body.Unblank()
            except Exception as ex:
                nx.print_exception(ex)
        self._blanked = {}

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
            # Greyed out until there is something to run.
            enable = self._can_run()
            for button in _OperationButtons:
                self.block(button).Enable = enable

    def _refresh_reference_sets(self) -> None:
        names = _common_reference_sets(self._tools(), [])
        if names == self._reference_sets:
            return
        previous = self._reference_set()
        self._reference_sets = names
        members = names or [_NoReferenceSet]
        others = [n for n in names if n != _RefsetBody]
        self.block("reference_set").SetEnumMembers(members)
        # BODY only serves Link, so anything else first.
        self.block("reference_set").ValueAsString = previous if previous in names else (others or members)[0]


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

        def closed(response: str) -> None:
            try:
                dialog.show_targets()
            finally:
                usage_db.finish_run(current)

        if not show_modeless(ufunc_name, dialog, closed):
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
