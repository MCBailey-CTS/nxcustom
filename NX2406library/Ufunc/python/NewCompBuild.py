"""
Python ports of NewCompBuild's (component-builder, src\\UFuncs\\NewCompBuild.cs) creation buttons. The form stays a
C# WinForms form; each button below calls
    PythonLibrary.Execute("NewCompBuild.py", "NewCompBuild", "<method>", args...)
and keeps its own control enabling / refreshing in C#.

Button -> method:
    the 8 color buttons (ApplyColor)   apply_color(color_name, color, change_color, change_color_component, <form>)
    Auto Lwr                           auto_lwr(bodies, <form>)
    Auto Upr                           auto_upr(bodies, <form>)
    Lwr Ret Assm                       lwr_ret_assm(bodies, <form>)
    Upr Ret Assm                       upr_ret_assm(bodies, <form>)
    Save As                            save_as(<form>)
    Copy                               copy(work_part)
    Make Unique                        make_unique(detail_number)
    Apply                              apply(update_component, edge_rep_lines, origin xyz, orientation 9,
                                             is_upr_parallel, is_lwr_parallel, parallel_height_exp, parallel_width_exp)

<form> is the form state the C# methods read, in this order:
    detail_number (textBoxDetailNumber.Text), is_name_reset (_isNameReset), is_upper (checkBoxUpperComp.Checked),
    four_digits (chk4Digits.Checked), any_assembly (chkAnyAssembly.Checked),
    name_attr / name_value (the selected comboBoxCompName CtsAttributes; value "" = nothing selected),
    material_attr / material_value (the selected listBoxMaterial CtsAttributes; value "" = nothing selected),
    comp_names / materials (every item of the two lists as "AttrName<TAB>AttrValue" lines in one string - the
    retainer buttons look items up by value),
    work_part / display_part / original_work_part / original_display_part (the form's _workPart, _displayPart,
    _originalWorkPart, _originalDisplayPart statics; "" = null).
Session.Execute cannot pass null, so "" stands for null everywhere.

The form's statics, its text box, its two lists and its upper check box are mirrored in a _FormState for the run and
updated exactly where the C# wrote them. Python cannot hand values back to C#, so the C# handler refreshes the form
afterwards (updateSessionButton / ResetForm / restoring the list selections), as the C# methods did at their end.

Differences from the C#:
  - The C# form registers a work-part-changed handler (WorkPartChanged1) that fires on every display / work part
    switch during a create: it re-runs ResetForm (the detail-number text box becomes the next free number and
    _isNameReset true, or the box is cleared for an invalid assembly name; the list selections are cleared) and sets
    the upper check box from the assembly name - and the next component of a multi-body Auto / retainer run reads
    those. The real C# handler still fires on the form while Python runs, but Python cannot read the form, so
    _FormState emulates it (_switch / _on_work_part_changed) at the same part switches.
  - _compColor (the alternating material color of SetComponentColor) is kept across runs on the sys module
    (sys._tsg_new_comp_build_color), since the interpreter outlives one Session.Execute and the C# static lived for
    the NX session. If NX ever starts a fresh interpreter per call, the alternation restarts at DARK GREY each click.
  - The AutoSize UDO class can only be registered from C# (AutoSizeComponent.initializeUDO); the C# handlers call
    __UdoAutoSizeClass() first. Run standalone without it, tsg_nx.create_auto_size_udo prints and skips the UDO.
  - ufsession_.Ui.AskInfoUnits (result discarded in the C#) is not called.
  - BlockFeatureBuilder.BooleanOption.SetTargetBodies(new Body[] { null }) is not called (a Python list holding None
    is not a valid Body[]); the boolean type is Create either way.
  - FileNew.Application = Gateway (obsolete) is set through Any.
  - ColorComponent reads the body's first feature with Body.GetFeatures() / Feature.FeatureType / Feature.GetFaces()
    instead of UF_MODL_ask_body_feats / ask_feat_type / ask_feat_faces (the Python UF_MODL is split across objects).
  - Copy's two WinForms MessageBox.Show calls are NX Information message boxes (title "Copy Component").
  - Apply: when the C# passes no edge-representation lines (its _edgeRepLines is empty - e.g. once the Edit buttons
    run in Python and build them there), the lines are found by name (XBASE1 ... ZBASE4) in the display part, where
    CreateBlockLine puts them. DynamicHandle.GetDynamicHandle (result unused) is only looked up, not registered.
  - make_unique uses the component picker of Selection.SelectSingleComponent without its UF filter proc (the mask
    already limits the pick to components).
  - Kept from the C#: CreateComponent promotes the block and then displays children[0] of the work part - the FIRST
    child, not necessarily the new one; Auto Lwr in metric goes through CreateComponentStatic (no name / material
    attributes, no fastener subtract, no detail-number formatting); ColorComponent leaves the display suppressed on the
    prototype when it has more than one layer-1 body; the 3-digit ResetForm leaves the box empty at exactly 100 and
    the 4-digit one at exactly 1000.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from typing import Any, Callable, List, Optional, Sequence, Tuple, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.Features  # noqa: E402
import NXOpen.GeometricUtilities  # noqa: E402
import NXOpen.Layer  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402

# ---------------------------------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------------------------------

# NewCompBuild.CtsComponentColor
CtsComponentColor = {
    "Orange": 11, "Purple": 12, "AquaMarine": 14, "DarkHardOrange": 84, "LightGrey": 87, "LightDullAzure": 92,
    "MediumAzureCyan": 98, "DarkDullGreen": 101, "LightRedOrange": 113, "DarkGrey": 130, "MediumAzureBlue": 134,
    "ObscureDullGreen": 144, "DarkWeakMagenta": 166, "DarkWeakRed": 167, "DarkDullBlue": 171,
}

_Shcs12mm050 = "G:\\0Library\\Fasteners\\Metric\\SocketHeadCapScrews-2X\\012-2x\\12mm-shcs-050-2x.prt"
_Dwl10mm050 = "G:\\0Library\\Fasteners\\Metric\\Dowels\\10mm-dwl-050.prt"

# UF_reference_set_type
_UfReferenceSetType = 64

# UF_CSYS_ROOT_COORDS / UF_CSYS_WORK_COORDS
_UfCsysRootCoords = 1
_UfCsysWorkCoords = 2

_EdgeRepLineNames = ("XBASE1", "YBASE1", "ZBASE1", "XBASE2", "YBASE2", "XCEILING1", "YCEILING1", "XCEILING2",
                     "YCEILING2", "ZBASE2", "ZBASE3", "ZBASE4")

_ColorKey = "_tsg_new_comp_build_color"


# ---------------------------------------------------------------------------------------------------
# Form state
# ---------------------------------------------------------------------------------------------------

class _FormState(object):
    """The NewCompBuild statics and controls a run reads and writes (see the module docstring)."""

    def __init__(self, detail_number: str, is_name_reset: bool, is_upper: bool, four_digits: bool,
                 any_assembly: bool, name_attr: str, name_value: str, material_attr: str, material_value: str,
                 comp_names: Any, materials: Any, work_part: Any, display_part: Any,
                 original_work_part: Any, original_display_part: Any) -> None:
        self.detail_number = detail_number or ""
        self.is_name_reset = bool(is_name_reset)
        self.is_upper = bool(is_upper)
        self.four_digits = bool(four_digits)
        self.any_assembly = bool(any_assembly)
        self.name_attr = name_attr
        self.name_value: Optional[str] = name_value or None
        self.material_attr = material_attr
        self.material_value: Optional[str] = material_value or None
        self.comp_names = _parse_items(comp_names)
        self.materials = _parse_items(materials)
        self.work_part: Optional[NXOpen.Part] = _part_or_none(work_part)
        self.display_part: Optional[NXOpen.Part] = _part_or_none(display_part)
        self.original_work_part: Optional[NXOpen.Part] = _part_or_none(original_work_part)
        self.original_display_part: Optional[NXOpen.Part] = _part_or_none(original_display_part)
        self.is_save_as = False

    def update_session_parts(self) -> None:
        """_workPart = work_; _displayPart = disp;"""
        self.work_part = nx.work_part()
        self.display_part = nx.display_part()

    def update_all_parts(self) -> None:
        """The four-line static refresh the C# repeats everywhere."""
        self.update_session_parts()
        self.original_work_part = self.work_part
        self.original_display_part = self.display_part

    @property
    def material_text(self) -> str:
        """listBoxMaterial.Text"""
        return self.material_value or ""


def _parse_items(items: Any) -> List[Tuple[str, str]]:
    """A list's CtsAttributes as (AttrName, AttrValue): one "name<TAB>value" per line (Session.Execute cannot pass a
    string[]), or a sequence of such strings. A line without a tab is a value with an empty name."""
    if not items:
        return []
    lines = items.splitlines() if isinstance(items, str) else [str(item) for item in items]
    parsed: List[Tuple[str, str]] = []
    for line in lines:
        if not line:
            continue
        name, tab, value = line.partition("\t")
        parsed.append((name, value) if tab else ("", name))
    return parsed


def _part_or_none(obj: Any) -> Optional[NXOpen.Part]:
    return None if obj is None or isinstance(obj, str) else cast(NXOpen.Part, obj)


def _tagged_or_none(obj: Any) -> Any:
    return None if obj is None or isinstance(obj, str) else obj


def _same(a: Optional[NXOpen.TaggedObject], b: Optional[NXOpen.TaggedObject]) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return a.Tag == b.Tag


def _on_work_part_changed(state: _FormState) -> None:
    """NewCompBuild.WorkPartChanged1, minus the work-plane and form-control writes (the real C# handler does those)."""
    try:
        if not state.is_save_as:
            state.update_session_parts()
            _reset_form(state, nx.work_part())
        component = nx.session_.Parts.WorkComponent
        if component is None:
            work = nx.work_part()
            if work is None or work.ComponentAssembly.RootComponent is None:
                return
            component = work.ComponentAssembly.RootComponent
        kind = _check(component)
        if kind == "Lower":
            state.is_upper = False
        elif kind == "Upper":
            state.is_upper = True
    except Exception:
        # The C# handler prints its own exceptions; printing here would double them.
        pass


def _switch(state: _FormState, action: Callable[[], None]) -> None:
    """Runs a display / work part change and, when the work part changed, what the C# handler does on it."""
    before = nx.work_part()
    action()
    if not _same(before, nx.work_part()):
        _on_work_part_changed(state)


def _set_display(state: _FormState, part: NXOpen.BasePart) -> None:
    """disp = part"""
    _switch(state, lambda: nx.set_display_part(part))


def _set_work(state: _FormState, part: NXOpen.BasePart) -> None:
    """work_ = part"""
    _switch(state, lambda: nx.set_work_part(part))


def _set_work_component(state: _FormState, component: Optional[NXOpen.Assemblies.Component]) -> None:
    """worc_ = component"""
    _switch(state, lambda: nx.set_work_component(component))


def _reset_form(state: _FormState, wp: Optional[NXOpen.Part]) -> None:
    """NewCompBuild.ResetForm(wp) - the text box, _isNameReset, _isSaveAs and list-selection effects."""
    state.update_session_parts()
    if wp is None:
        return
    if not _is_name_valid(wp, state.any_assembly):
        # textBoxDetailNumber.Clear(); InitializeMainForm() clears the material list; NameCheckFailed.
        state.detail_number = ""
        state.material_value = None
        return

    # InitializeMainForm + NameCheckPassed: text cleared, both lists deselected.
    state.detail_number = ""
    state.name_value = None
    state.material_value = None
    state.is_name_reset = True
    state.is_save_as = False
    work = nx.work_part()
    if work is None or work.ComponentAssembly.RootComponent is None:
        return
    names = nx.distinct_by([c.DisplayName for c in nx.children(wp)], lambda n: n)
    details = [int(m.group("detail")) for m in (re.match(r"^\d+-\d+-(?P<detail>\d+)$", n) for n in names) if m]
    if not details:
        return
    details.sort()
    num = details[-1] + 1
    if state.four_digits:
        if 0 < num < 10:
            state.detail_number = "000{}".format(num)
        if 9 < num < 100:
            state.detail_number = "00{}".format(num)
        if 99 < num < 1000:
            state.detail_number = "0{}".format(num)
        if num <= 1000:
            return
        state.detail_number = "{}".format(num)
    else:
        if 0 < num < 10:
            state.detail_number = "00{}".format(num)
        if 9 < num < 100:
            state.detail_number = "0{}".format(num)
        if num <= 100:
            return
        state.detail_number = str(num)


# ---------------------------------------------------------------------------------------------------
# The buttons
# ---------------------------------------------------------------------------------------------------

class NewCompBuild(object):

    @staticmethod
    def apply_color(color_name: str, color: int, change_color: bool, change_color_component: Any,
                    detail_number: str, is_name_reset: bool, is_upper: bool, four_digits: bool,
                    any_assembly: bool, name_attr: str, name_value: str, material_attr: str, material_value: str,
                    comp_names: Any, materials: Any, work_part: Any, display_part: Any,
                    original_work_part: Any, original_display_part: Any) -> None:
        """
        NewCompBuild.ApplyColor - the 8 color buttons. Sets the component color, then either recolors the component
        the Change Color check box picked (ColorComponent) or builds a 4 x 4 x 1.5 (101.6 x 101.6 x 38.1) DYNAMIC
        BLOCK detail at the WCS (CreateComponent()). The C# handler unchecks Change Color / restores the list
        selections afterwards.
        """
        _set_comp_color(color_name, int(color))
        state = _FormState(detail_number, is_name_reset, is_upper, four_digits, any_assembly, name_attr, name_value,
                           material_attr, material_value, comp_names, materials, work_part, display_part,
                           original_work_part, original_display_part)
        if change_color:
            _color_component(state, _tagged_or_none(change_color_component))
        else:
            _create_component_at_wcs(state)

    @staticmethod
    def auto_lwr(bodies: Sequence[NXOpen.TaggedObject], detail_number: str, is_name_reset: bool, is_upper: bool,
                 four_digits: bool, any_assembly: bool, name_attr: str, name_value: str, material_attr: str,
                 material_value: str, comp_names: Any, materials: Any, work_part: Any,
                 display_part: Any, original_work_part: Any, original_display_part: Any) -> None:
        """
        NewCompBuild.ButtonAutoLwr_Click after the pick: per body a 1.5" (38.1) block 1.25" (31.75) bigger on every
        side, below Z 0, then the body's component is linked on LWR-PROFILE and subtracted from the new block.
        bodies empty (standalone) = reset the WCS and pick here.
        """
        state = _FormState(detail_number, is_name_reset, False, four_digits, any_assembly, name_attr, name_value,
                           material_attr, material_value, comp_names, materials, work_part, display_part,
                           original_work_part, original_display_part)
        body_list = _bodies_or_pick(bodies)
        for body in body_list:
            num_array, distances, metric = _measure(state, body)
            if metric:
                new_component = _auto_lwr_metric(state, num_array, distances)
            else:
                new_component = _auto_lwr_english(state, num_array, distances)

            body_owning_component = body.OwningComponent
            nx.set_reference_set(body_owning_component, "LWR-PROFILE")
            _set_work_component(state, new_component)
            linked = nx.create_linked_body(body_owning_component)
            work = nx.work_part()
            nx.subtract(_dynamic_block(work).GetBodies()[0], linked.GetBodies())
            _set_work(state, nx.display_part())
            nx.set_reference_set(body_owning_component, "BODY")

    @staticmethod
    def auto_upr(bodies: Sequence[NXOpen.TaggedObject], detail_number: str, is_name_reset: bool, is_upper: bool,
                 four_digits: bool, any_assembly: bool, name_attr: str, name_value: str, material_attr: str,
                 material_value: str, comp_names: Any, materials: Any, work_part: Any,
                 display_part: Any, original_work_part: Any, original_display_part: Any) -> None:
        """NewCompBuild.ButtonAutoUpr_Click after the pick: per body a 1.5" block 1.25" bigger a side, from Z 3.5 down."""
        state = _FormState(detail_number, is_name_reset, True, four_digits, any_assembly, name_attr, name_value,
                           material_attr, material_value, comp_names, materials, work_part, display_part,
                           original_work_part, original_display_part)
        for body in _bodies_or_pick(bodies):
            num_array, distances, metric = _measure(state, body)
            if metric:
                _auto_upper_metric(state, num_array, distances)
            else:
                _auto_upper_english(state, num_array, distances)

    @staticmethod
    def lwr_ret_assm(bodies: Sequence[NXOpen.TaggedObject], detail_number: str, is_name_reset: bool,
                     is_upper: bool, four_digits: bool, any_assembly: bool, name_attr: str, name_value: str,
                     material_attr: str, material_value: str, comp_names: Any, materials: Any,
                     work_part: Any, display_part: Any, original_work_part: Any, original_display_part: Any) -> None:
        """NewCompBuild.ButtonLwrRetAssm_Click after the pick: per body the lower trim steel, RETAINER (4140) and
        BLOCK (O1 GS) backing plate (LowerRetainerAssembly)."""
        state = _FormState(detail_number, is_name_reset, False, four_digits, any_assembly, name_attr, name_value,
                           material_attr, material_value, comp_names, materials, work_part, display_part,
                           original_work_part, original_display_part)
        for body in _bodies_or_pick(bodies):
            num_array, distances, metric = _measure(state, body)
            _lower_retainer_assembly(state, num_array, distances, metric)

    @staticmethod
    def upr_ret_assm(bodies: Sequence[NXOpen.TaggedObject], detail_number: str, is_name_reset: bool,
                     is_upper: bool, four_digits: bool, any_assembly: bool, name_attr: str, name_value: str,
                     material_attr: str, material_value: str, comp_names: Any, materials: Any,
                     work_part: Any, display_part: Any, original_work_part: Any, original_display_part: Any) -> None:
        """NewCompBuild.ButtonUprRetAssm_Click after the pick: per body the upper punch steel, RETAINER (4140) and
        BLOCK (O1 GS) backing plate (UpperRetainerEnglish / UpperRetainerMetric)."""
        state = _FormState(detail_number, is_name_reset, True, four_digits, any_assembly, name_attr, name_value,
                           material_attr, material_value, comp_names, materials, work_part, display_part,
                           original_work_part, original_display_part)
        for body in _bodies_or_pick(bodies):
            num_array, distances, metric = _measure(state, body)
            if metric:
                _upper_retainer_metric(state, num_array, distances)
            else:
                _upper_retainer_english(state, num_array, distances)

    @staticmethod
    def save_as(detail_number: str, is_name_reset: bool, is_upper: bool, four_digits: bool, any_assembly: bool,
                name_attr: str, name_value: str, material_attr: str, material_value: str,
                comp_names: Any, materials: Any, work_part: Any, display_part: Any,
                original_work_part: Any, original_display_part: Any) -> None:
        """
        NewCompBuild.SaveAsButton_Click inside its form hide/show, minus the final ResetForm (C#): pick components one
        at a time and Save As each as the next {job}-{op}-{detail} beside the original work part, renaming its
        occurrences and adding them to the work part's BODY reference set, until the pick is cancelled.
        """
        state = _FormState(detail_number, is_name_reset, is_upper, four_digits, any_assembly, name_attr, name_value,
                           material_attr, material_value, comp_names, materials, work_part, display_part,
                           original_work_part, original_display_part)
        if state.display_part is None:
            nx.print_("No display part")
            return

        units = NXOpen.BasePart.Units.Inches
        part_units = state.display_part.PartUnits
        try:
            comp_save_as = _select_one_component("Select Component to SaveAs")
            while comp_save_as is not None:
                if state.work_part is None or not _is_name_valid(state.work_part, state.any_assembly):
                    state.is_name_reset = False
                    state.is_save_as = False
                    break
                flag = _format_detail_number(state)
                text = state.detail_number
                if not flag and not text:
                    state.is_name_reset = False
                    state.is_save_as = False
                    break
                prototype = cast(NXOpen.Part, comp_save_as.Prototype)
                units = prototype.PartUnits
                _save_as(state, comp_save_as, text, units != part_units)
                comp_save_as = _select_one_component("Select Component to SaveAs")
        except Exception as ex:
            nx.print_exception(ex)
            nx.ufsession_.Disp.SetDisplay(nx.UF_DISP_UNSUPPRESS_DISPLAY)
            nx.ufsession_.Disp.RegenerateDisplay()
            if units != part_units and state.original_display_part is not None:
                nx.set_display_part(state.original_display_part)
            if state.original_work_part is not None:
                nx.set_work_part(state.original_work_part)
            nx.message_box("Caught exception", NXOpen.NXMessageBox.DialogType.Error, str(ex))
            state.update_all_parts()

    @staticmethod
    def copy(work_part: Any) -> None:
        """
        NewCompBuild.CopyButton_Click: pick a component, copy its part file to "<name>(n).prt" (first free n) and add
        the copy to the work part at the same position, layer and name, on BODY. work_part is the form's _workPart.
        """
        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Copy Component")
        component = _select_one_component("Select Component to Copy")

        if component is None:
            return

        work = _part_or_none(work_part) or nx.work_part()
        prototype = component.Prototype
        num2 = 0
        path = "{}({}).prt".format(prototype.FullPath[:-4], num2)
        while os.path.isfile(path):
            num2 += 1
            path = "{}({}).prt".format(prototype.FullPath[:-4], num2)

        num3 = work.FullPath.rfind("\\")

        if work.FullPath[:num3 + 1] != path[:num3 + 1]:
            _message_box("The selected component is not from the work part directory. \n"
                         "                   Save As before making a copy.")
            return

        if not os.path.isfile(prototype.FullPath):
            _message_box("Save the original file to the assembly before making a copy")
            return

        shutil.copyfile(prototype.FullPath, path)

        opened, load_status = nx.session_.Parts.OpenBase(path)
        if load_status is not None:
            load_status.Dispose()
        new_component, add_status = work.ComponentAssembly.AddComponent(
            opened,
            "BODY",
            component.DisplayName,
            nx.component_origin(component),
            nx.component_orientation(component),
            component.Layer)
        if add_status is not None:
            add_status.Dispose()

    @staticmethod
    def make_unique(detail_number: str) -> None:
        """
        Static.NewCompBuildMakeUnique (btnMakeUnique_Click): pick a component and make its part unique as
        {job}-{op}-{detail} in its parent's op folder, then rename the parent's children whose display name ends with
        the detail number to it.
        """
        try:
            picked = _select_one_component("Select single component", "Select single component")
            if picked is None:
                return
            component = picked
            parent = cast(NXOpen.Assemblies.Component, component.Parent)
            op = _ask_detail_op(parent.DisplayName)
            builder = cast(Any, nx.work_part().AssemblyManager).CreateMakeUniquePartBuilder()
            try:
                detail = detail_number
                if not detail:
                    nx.print_("please type a detail number")
                else:
                    new_unique_name = _GFolder.create(parent.Prototype.FullPath).file_detail0(op, detail)
                    builder.SelectedComponents.Add(component)
                    cast(Any, component.Prototype).SetMakeUniqueName(new_unique_name)
                    builder.Commit()
                    for child in [c for c in parent.GetChildren() if c.DisplayName.endswith(detail)]:
                        child.SetName(detail)
            finally:
                builder.Destroy()
        except Exception as ex:
            nx.print_exception(ex)

    @staticmethod
    def apply(update_component: Any, edge_rep_lines: Any,
              origin_x: float, origin_y: float, origin_z: float,
              xx: float, xy: float, xz: float, yx: float, yy: float, yz: float, zx: float, zy: float, zz: float,
              is_upr_parallel: bool, is_lwr_parallel: bool, parallel_height_exp: str, parallel_width_exp: str) -> None:
        """
        NewCompBuild.Apply (buttonApply_Click), minus the field resets (C#): commits the edited size/position to the
        DYNAMIC BLOCK (UpdateDynamicBlock), deletes the handles and edge lines, puts the WCS back and drops every undo
        mark. update_component "" = the work part's own block; edge_rep_lines "" or empty = find them by name.
        The origin / orientation / parallel arguments are the form's _workCompOrigin, _workCompOrientation,
        _isUprParallel, _isLwrParallel, _parallelHeightExp and _parallelWidthExp.
        """
        orientation = NXOpen.Matrix3x3()
        orientation.Xx, orientation.Xy, orientation.Xz = xx, xy, xz
        orientation.Yx, orientation.Yy, orientation.Yz = yx, yy, yz
        orientation.Zx, orientation.Zy, orientation.Zz = zx, zy, zz
        origin = NXOpen.Point3d(origin_x, origin_y, origin_z)

        lines: List[NXOpen.Line] = []
        if edge_rep_lines is not None and not isinstance(edge_rep_lines, str):
            lines = [cast(NXOpen.Line, line) for line in edge_rep_lines]
        if not lines:
            lines = [line for line in cast(Any, nx.display_part()).Lines if line.Name in _EdgeRepLineNames]

        origin = _update_dynamic_block(_tagged_or_none(update_component), lines, origin, orientation,
                                       bool(is_upr_parallel), bool(is_lwr_parallel), parallel_height_exp or "",
                                       parallel_width_exp or "")
        disp = nx.display_part()
        disp.WCS.SetOriginAndMatrix(origin, orientation)
        cast(Any, disp.WCS).Visibility = True
        cast(Any, nx.session_).DeleteAllUndoMarks()


# ---------------------------------------------------------------------------------------------------
# Auto Lwr / Auto Upr / retainer assemblies
# ---------------------------------------------------------------------------------------------------

def _bodies_or_pick(bodies: Optional[Sequence[NXOpen.TaggedObject]]) -> List[NXOpen.Body]:
    """The C# handlers pass their Selection.SelectMultipleBodies pick; standalone, reset the WCS and pick here."""
    if bodies is not None and not isinstance(bodies, str) and len(bodies) > 0:
        return [cast(NXOpen.Body, body) for body in bodies]
    nx.display_part().WCS.SetOriginAndMatrix(NXOpen.Point3d(0.0, 0.0, 0.0), nx.identity_matrix())
    return _select_multiple_bodies()


def _measure(state: _FormState, body: NXOpen.Body) -> Tuple[List[float], List[float], bool]:
    """The per-body head of the four Auto loops: OrientedBox in the display part's WCS, units, eighth rounding."""
    body.Unhighlight()
    display = state.display_part if state.display_part is not None else nx.display_part()
    min_corner, _directions, box_distances = nx.ufsession_.ModlGeneral.AskBoundingBoxExact(
        body.Tag, display.WCS.CoordinateSystem.Tag)
    num_array = [float(v) for v in min_corner]
    distances = [float(v) for v in box_distances]
    work = state.work_part if state.work_part is not None else nx.work_part()
    flag = _convert_units(distances, work)
    _distance0(distances)
    _min_corner3(num_array)
    return num_array, distances, flag


def _to_metric(min_corner: List[float], distances: List[float]) -> None:
    for index in range(3):
        min_corner[index] *= 25.4
        distances[index] *= 25.4


def _s(value: float) -> str:
    """double.ToString()"""
    return nx.cs_double_str(value)


def _auto_lwr_english(state: _FormState, min_corner: List[float],
                      distances: List[float]) -> Optional[NXOpen.Assemblies.Component]:
    """NewCompBuild.AutoLwrEnglish"""
    origin = NXOpen.Point3d(min_corner[0] - 1.25, min_corner[1] - 1.25, -1.5)
    _set_component_color(state)
    return _create_component(state, origin, _s(distances[0] + 2.5), _s(distances[1] + 2.5), "1.50")


def _auto_lwr_metric(state: _FormState, min_corner: List[float],
                     distances: List[float]) -> Optional[NXOpen.Assemblies.Component]:
    """NewCompBuild.AutoLwrMetric - through CreateComponentStatic."""
    _to_metric(min_corner, distances)
    origin = NXOpen.Point3d(min_corner[0] - 31.75, min_corner[1] - 31.75, -38.1)
    _set_component_color(state)
    return _create_component_static(state, state.detail_number, state.is_upper, origin,
                                    _s(distances[0] + 63.5), _s(distances[1] + 63.5), "38.1")


def _auto_upper_english(state: _FormState, min_corner: List[float], distances: List[float]) -> None:
    """NewCompBuild.AutoUpperEnglish"""
    origin = NXOpen.Point3d(min_corner[0] - 1.25, min_corner[1] + 1.25 + distances[1], 3.5)
    _set_component_color(state)
    _create_component(state, origin, _s(distances[0] + 2.5), _s(distances[1] + 2.5), "1.50")


def _auto_upper_metric(state: _FormState, min_corner: List[float], distances: List[float]) -> None:
    """NewCompBuild.AutoUpperMetric"""
    _to_metric(min_corner, distances)
    origin = NXOpen.Point3d(min_corner[0] - 31.75, min_corner[1] + 31.75 + distances[1], 88.9)
    _set_component_color(state)
    _create_component(state, origin, _s(distances[0] + 63.5), _s(distances[1] + 63.5), "38.1")


def _select_name(state: _FormState, value: str) -> None:
    """comboBoxCompName.SelectedIndex = index of the (last) item with that value, -1 when there is none."""
    matches = [item for item in state.comp_names if item[1] == value]
    if matches:
        state.name_attr, state.name_value = matches[-1]
    else:
        state.name_value = None


def _select_material(state: _FormState, value: str) -> None:
    """listBoxMaterial.SetSelected(index, true) - throws on -1, as the C# does."""
    matches = [item for item in state.materials if item[1] == value]
    if not matches:
        raise ValueError("InvalidArgument=Value of '-1' is not valid for 'index'.\r\nParameter name: index")
    state.material_attr, state.material_value = matches[-1]


def _lower_retainer_assembly(state: _FormState, min_corner: List[float], distances: List[float],
                             metric: bool) -> None:
    """NewCompBuild.LowerRetainerAssembly"""
    if metric:
        _to_metric(min_corner, distances)

    off1 = 15.875 if metric else 0.625
    off2 = 31.75 if metric else 1.25
    z1 = -82.804 if metric else -3.26
    z3 = -88.9 if metric else -3.5
    sz1 = 31.75 if metric else 1.25
    sz2 = 63.5 if metric else 2.5
    h1 = "88.9" if metric else "3.50"
    h2 = "31.75" if metric else "1.375"
    h3 = "6.096" if metric else ".24"

    selected_name = (state.name_attr, state.name_value)
    selected_material = (state.material_attr, state.material_value)

    _set_component_color(state)
    _create_component(state, NXOpen.Point3d(min_corner[0] - off1, min_corner[1] - off1, z1),
                      _s(distances[0] + sz1), _s(distances[1] + sz1), h1)

    _select_name(state, "RETAINER")
    _select_material(state, "4140")
    _set_component_color(state)
    _create_component(state, NXOpen.Point3d(min_corner[0] - off2, min_corner[1] - off2, z1),
                      _s(distances[0] + sz2), _s(distances[1] + sz2), h2)

    _select_name(state, "BLOCK")
    _select_material(state, "O1 GS")
    _set_component_color(state)
    _create_component(state, NXOpen.Point3d(min_corner[0] - off2, min_corner[1] - off2, z3),
                      _s(distances[0] + sz2), _s(distances[1] + sz2), h3)

    state.name_attr, state.name_value = selected_name
    state.material_attr, state.material_value = selected_material


def _upper_retainer_english(state: _FormState, min_corner: List[float], distances: List[float]) -> None:
    """NewCompBuild.UpperRetainerEnglish"""
    selected_name = (state.name_attr, state.name_value)
    selected_material = (state.material_attr, state.material_value)
    _set_component_color(state)
    _create_component(state, NXOpen.Point3d(min_corner[0] - 0.625, min_corner[1] + 0.625 + distances[1], 3.26),
                      _s(distances[0] + 1.25), _s(distances[1] + 1.25), "3.50")
    _select_name(state, "RETAINER")
    _select_material(state, "4140")
    _set_component_color(state)
    _create_component(state, NXOpen.Point3d(min_corner[0] - 1.25, min_corner[1] + 1.25 + distances[1], 3.26),
                      _s(distances[0] + 2.5), _s(distances[1] + 2.5), "1.25")
    _select_name(state, "BLOCK")
    _select_material(state, "O1 GS")
    _set_component_color(state)
    _create_component(state, NXOpen.Point3d(min_corner[0] - 1.25, min_corner[1] + 1.25 + distances[1], 3.5),
                      _s(distances[0] + 2.5), _s(distances[1] + 2.5), ".24")
    state.name_attr, state.name_value = selected_name
    state.material_attr, state.material_value = selected_material


def _upper_retainer_metric(state: _FormState, min_corner: List[float], distances: List[float]) -> None:
    """NewCompBuild.UpperRetainerMetric"""
    _to_metric(min_corner, distances)
    selected_name = (state.name_attr, state.name_value)
    selected_material = (state.material_attr, state.material_value)
    _set_component_color(state)
    _create_component(state, NXOpen.Point3d(min_corner[0] - 15.875, min_corner[1] + 15.875 + distances[1], 82.804),
                      _s(distances[0] + 31.75), _s(distances[1] + 31.75), "88.9")
    _select_name(state, "RETAINER")
    _select_material(state, "4140")
    _set_component_color(state)
    _create_component(state, NXOpen.Point3d(min_corner[0] - 31.75, min_corner[1] + 31.75 + distances[1], 82.804),
                      _s(distances[0] + 63.5), _s(distances[1] + 63.5), "31.75")
    _select_name(state, "BLOCK")
    _select_material(state, "O1 GS")
    _set_component_color(state)
    _create_component(state, NXOpen.Point3d(min_corner[0] - 31.75, min_corner[1] + 31.75 + distances[1], 88.9),
                      _s(distances[0] + 63.5), _s(distances[1] + 63.5), "6.096")
    state.name_attr, state.name_value = selected_name
    state.material_attr, state.material_value = selected_material


# ---------------------------------------------------------------------------------------------------
# Component color (_compColor / SetComponentColor)
# ---------------------------------------------------------------------------------------------------

def _comp_color() -> Tuple[str, int]:
    """NewCompBuild._compColor - (ColorName, ComponentColor); DARK GREY until a button sets it."""
    value = getattr(sys, _ColorKey, None)
    if isinstance(value, tuple) and len(value) == 2:
        return str(value[0]), int(value[1])
    return "DARK GREY", CtsComponentColor["DarkGrey"]


def _set_comp_color(name: str, color: int) -> None:
    setattr(sys, _ColorKey, (name, color))


def _toggle(current: str, first: Tuple[str, str], second: Tuple[str, str]) -> None:
    """_compColor = _compColor.ColorName == first ? second : first"""
    name, key = second if current == first[0] else first
    _set_comp_color(name, CtsComponentColor[key])


def _set_component_color(state: _FormState) -> None:
    """NewCompBuild.SetComponentColor - by listBoxMaterial.Text, alternating between two shades where it can."""
    current = _comp_color()[0]
    text = state.material_text
    if text in ("A2", "A2 GS"):
        _toggle(current, ("LIGHT RED ORANGE", "LightRedOrange"), ("ORANGE", "Orange"))
    elif text == "D2":
        _toggle(current, ("DARK WEAK MAGENTA", "DarkWeakMagenta"), ("PURPLE", "Purple"))
    elif text == "CRS":
        _set_comp_color("DARK DULL BLUE", CtsComponentColor["DarkDullBlue"])
    elif text in ("HRS", "HRS PLT", "ANGLE IRON"):
        _set_comp_color("DARK WEAK RED", CtsComponentColor["DarkWeakRed"])
    elif text in ("O1", "ALUM", "O1 GS", "O1 DR", "ACUSEAL", "STEELCRAFT"):
        _toggle(current, ("LIGHT GREY", "LightGrey"), ("DARK GREY", "DarkGrey"))
    elif text in ("S7", "H13", "P20", "DIEVAR"):
        _toggle(current, ("OBSCURE DULL GREEN", "ObscureDullGreen"), ("DARK DULL GREEN", "DarkDullGreen"))
    elif text in ("4140", "4140 PH", "4140 PLT"):
        _toggle(current, ("MEDIUM AZURE BLUE", "MediumAzureBlue"), ("LIGHT DULL AZURE", "LightDullAzure"))
    elif text == "AMPCO 18":
        _set_comp_color("DARK HARD ORANGE", CtsComponentColor["DarkHardOrange"])
    elif text in ("GM238/G2500", "GM241/G3500", "GM245/D4512", "GM246/D5506", "GM338/D6510", "GM190/S0050A"):
        _toggle(current, ("AQUAMARINE", "AquaMarine"), ("MEDIUM AZURE CYAN", "MediumAzureCyan"))
    else:
        _set_comp_color("DARK GREY", CtsComponentColor["DarkGrey"])


# ---------------------------------------------------------------------------------------------------
# Component creation (CreateComponent() / CreateComponent(Point3d, ...) / CreateComponentStatic)
# ---------------------------------------------------------------------------------------------------

def _set_default_units(part: NXOpen.Part, millimeters: bool) -> None:
    """The SetDefaultDataEntryUnits / SetDefaultObjectInformationUnits pair at the top of every create."""
    defaults = cast(Any, NXOpen.UnitCollection.UnitDefaults)
    units = defaults.GMmNDegC if millimeters else defaults.LbmInLbfDegF
    collection = cast(Any, part.UnitCollection)
    collection.SetDefaultDataEntryUnits(units)
    collection.SetDefaultObjectInformationUnits(units)


def _reset_wcs() -> None:
    """Session.__ResetWcs"""
    nx.display_part().WCS.SetOriginAndMatrix(NXOpen.Point3d(0.0, 0.0, 0.0), nx.identity_matrix())


def _commit_dynamic_block(work: NXOpen.Part, origin_point: NXOpen.Point3d, length: str, width: str, height: str,
                          orientation: Optional[NXOpen.Matrix3x3]) -> NXOpen.Features.Feature:
    """The BlockFeatureBuilder (OriginAndEdgeLengths, Create) every create builds, named DYNAMIC BLOCK."""
    builder = work.Features.CreateBlockFeatureBuilder(None)
    try:
        builder.BooleanOption.Type = NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Create
        builder.Type = NXOpen.Features.BlockFeatureBuilder.Types.OriginAndEdgeLengths
        if orientation is not None:
            builder.SetOrientation(nx.axis_x(orientation), nx.axis_y(orientation))
        builder.SetOriginAndLengths(origin_point, length, width, height)
        feature = builder.CommitFeature()
        feature.SetName("DYNAMIC BLOCK")
    finally:
        builder.Destroy()
    cast(Any, work).FacetedBodies.DeleteTemporaryFacesAndEdges()
    return feature


def _promote_block(work: NXOpen.Part, display: NXOpen.Part, feature: NXOpen.Features.Feature, text: str) -> None:
    """The FileNew + CreateNewComponentBuilder pair: {work folder}{job-op}-{text}.prt, Entire Part, absolute."""
    nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Create New Component")
    file_new = nx.session_.Parts.FileNew()
    file_new_any = cast(Any, file_new)
    file_new_any.TemplateFileName = "Blank"
    file_new_any.Application = cast(Any, NXOpen).FileNewApplication.Gateway
    file_new.Units = (NXOpen.Part.Units.Millimeters if display.PartUnits == NXOpen.BasePart.Units.Millimeters
                      else NXOpen.Part.Units.Inches)
    full_path = work.FullPath
    num3 = full_path.rfind("\\")
    num4 = full_path.rfind("-")
    str1 = full_path[:num3 + 1]
    str2 = full_path[num3 + 1:num4]
    file_new.NewFileName = "{}{}-{}.prt".format(str1, str2, text)
    file_new_any.MasterFileName = ""
    file_new.UseBlankTemplate = True
    file_new_any.MakeDisplayedPart = False
    builder = work.AssemblyManager.CreateNewComponentBuilder()
    builder.ReferenceSet = NXOpen.Assemblies.CreateNewComponentBuilder.ComponentReferenceSetType.EntirePartOnly
    cast(Any, builder).ReferenceSetName = "Entire Part"
    builder.LayerOption = NXOpen.Assemblies.CreateNewComponentBuilder.ComponentLayerOptionType.Work
    builder.NewComponentName = text
    builder.ComponentOrigin = NXOpen.Assemblies.CreateNewComponentBuilder.ComponentOriginType.Absolute
    builder.ObjectForNewComponent.Add(feature.GetBodies()[0])
    builder.NewFile = file_new
    builder.Commit()
    builder.Destroy()


def _create_expressions(work: NXOpen.Part, display: NXOpen.Part) -> None:
    """AddX/AddY/AddZ in the display part's units plus Burnout/Grind/GrindTolerance/BurnDir, then DoUpdate."""
    undo_mark = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "Expression")
    unit_type = work.UnitCollection.FindObject("Inch" if display.PartUnits == NXOpen.BasePart.Units.Inches
                                               else "MilliMeter")
    work.Expressions.CreateWithUnits("AddX=.000", unit_type)
    work.Expressions.CreateWithUnits("AddY=.000", unit_type)
    work.Expressions.CreateWithUnits("AddZ=.000", unit_type)
    work.Expressions.CreateExpression("String", 'Burnout="no"')
    work.Expressions.CreateExpression("String", 'Grind="no"')
    work.Expressions.CreateExpression("String", 'GrindTolerance="none"')
    work.Expressions.CreateExpression("String", 'BurnDir="none"')
    nx.session_.UpdateManager.DoUpdate(undo_mark)


def _extract_layer1_body(work: NXOpen.Part) -> None:
    """The subtool ExtractFaceBuilder - the last layer-1 body, extracted onto the work layer (15)."""
    builder = work.Features.CreateExtractFaceBuilder(None)
    try:
        builder.FaceOption = NXOpen.Features.ExtractFaceBuilder.FaceOptionType.FaceChain
        builder.Type = NXOpen.Features.ExtractFaceBuilder.ExtractType.Body
        builder.FaceOption = NXOpen.Features.ExtractFaceBuilder.FaceOptionType.FaceChain
        builder.FixAtCurrentTimestamp = True
        layer1: Optional[NXOpen.Body] = None
        for body in work.Bodies:
            if body.Layer == 1:
                layer1 = body
        builder.BodyToExtract.Add(cast(NXOpen.Body, layer1))
        builder.Commit()
    finally:
        builder.Destroy()


def _color_new_bodies(work: NXOpen.Part, display: NXOpen.Part, upper_component: bool) -> None:
    """Layer-1 bodies take _compColor with the base face colored 6; layer-15 bodies color 42."""
    color = _comp_color()[1]
    for body in work.Bodies:
        if body.Layer == 1:
            body.Color = color
            _color_base_face(body, upper_component, display)
        if body.Layer == 15:
            body.Color = 42


def _add_to_body_refsets(part: NXOpen.Part, component: NXOpen.Assemblies.Component) -> None:
    """The UF_OBJ_cycle_objs_in_part loop: every reference set named BODY gets the component, on BODY."""
    assem = cast(Any, nx.ufsession_.Assem)
    for refset in nx.cycle_objs_in_part(part.Tag, _UfReferenceSetType):
        if nx.ufsession_.Obj.AskName(refset) != "BODY":
            continue
        tags = [component.Tag]
        assem.AddRefSetMembers(refset, len(tags), tags)
        assem.ReplaceRefset(len(tags), tags, "BODY")


def _block_parameters(block: NXOpen.Features.Feature) -> Tuple[NXOpen.Point3d, NXOpen.Matrix3x3, float, float]:
    """Block.__Origin / __Orientation / __Length / __Width. Length/Width come from UF_MODL_ask_block_parms, since
    the builder's Length/Width are None in Python."""
    part = block.OwningPart
    parms = nx.ufsession_.ModlFeatures.AskBlockParms(block.Tag, 0)
    lengths = [part.Expressions.FindObject(parm.split("=", 1)[0].strip()).Value for parm in parms]
    builder = part.Features.CreateBlockFeatureBuilder(block)
    try:
        origin = builder.Origin
        x_axis, y_axis = builder.GetOrientation()
    finally:
        builder.Destroy()
    return origin, nx.matrix_from_axes(x_axis, y_axis), lengths[0], lengths[1]


def _add_fasteners(display: NXOpen.Part) -> None:
    """The four 12mm-shcs-050-2x on the block's corners and two 10mm-dwl-050 on the X mid-points, CBORE, layer 99."""
    origin, matrix, length, width = _block_parameters(_dynamic_block(display))
    x_axis = nx.axis_x(matrix)
    y_axis = nx.axis_y(matrix)
    nx.add_component(display, _Shcs12mm050, "CBORE", origin=origin, layer=99)
    nx.add_component(display, _Shcs12mm050, "CBORE", origin=nx.add_along(origin, x_axis, length), layer=99)
    nx.add_component(display, _Shcs12mm050, "CBORE", origin=nx.add_along(origin, y_axis, width), layer=99)
    nx.add_component(display, _Shcs12mm050, "CBORE",
                     origin=nx.add_along(nx.add_along(origin, y_axis, width), x_axis, length), layer=99)
    nx.add_component(display, _Dwl10mm050, "CBORE",
                     origin=nx.add_along(nx.add_along(origin, y_axis, width), x_axis, length / 2), layer=99)
    nx.add_component(display, _Dwl10mm050, "CBORE", origin=nx.add_along(origin, x_axis, length / 2), layer=99)


def _create_auto_size_udo(work: NXOpen.Part) -> None:
    """Static.NewCompBuildCreateAutoSizeUdo inside its 1535022 catch."""
    try:
        nx.create_auto_size_udo(work)
    except NXOpen.NXException as ex:
        if ex.ErrorCode != nx.ErrorUdoClassNotRegistered:
            raise
        nx.print_exception(ex)


def _create_component_at_wcs(state: _FormState) -> None:
    """NewCompBuild.CreateComponent() - the color buttons: a 4 x 4 x 1.5 block at the WCS (lower: below it; upper:
    rolled 180 about X with its origin 3.5 up), promoted to {job-op}-{detail}."""
    try:
        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Create Component")
        try:
            display_static = cast(NXOpen.Part, state.display_part)
            part_units = display_static.PartUnits
            millimeters = part_units == NXOpen.BasePart.Units.Millimeters
            _set_default_units(display_static, millimeters)
            upper_component = state.is_upper
            if state.name_value is None:
                selected_item: Optional[Tuple[str, str]] = None
            else:
                selected_item = (state.name_attr, state.name_value)
            if state.material_value is None:
                material = ("MATERIAL", "")
            else:
                material = (state.material_attr, state.material_value)
            state.update_all_parts()
            display = cast(NXOpen.Part, state.display_part)
            work = cast(NXOpen.Part, state.work_part)
            origin = display.WCS.CoordinateSystem.Origin
            element = display.WCS.CoordinateSystem.Orientation.Element
            cast(Any, display.WCS).Visibility = False
            _reset_wcs()
            point3d = NXOpen.Point3d(0.0, 0.0, 0.0)
            matrix3x3: Optional[NXOpen.Matrix3x3] = None
            if state.is_upper:
                display.WCS.Rotate(NXOpen.WCS.Axis.XAxis, 180.0)
                point3d = NXOpen.Point3d(0.0, 0.0, 3.5 if part_units == NXOpen.BasePart.Units.Inches else 88.9)
                matrix3x3 = display.WCS.CoordinateSystem.Orientation.Element
            _reset_wcs()
            nx.ufsession_.Disp.SetDisplay(nx.UF_DISP_SUPPRESS_DISPLAY)
            display.Layers.WorkLayer = 1
            if state.is_upper:
                origin_point = point3d
            else:
                wcs_origin = display.WCS.CoordinateSystem.Origin
                origin_point = nx.add_z(wcs_origin, -1.5 if part_units == NXOpen.BasePart.Units.Inches else -38.1)
            if part_units == NXOpen.BasePart.Units.Inches:
                feature = _commit_dynamic_block(work, origin_point, "4", "4", "1.5", matrix3x3)
            else:
                feature = _commit_dynamic_block(work, origin_point, "101.6", "101.6", "38.1", matrix3x3)
            text = state.detail_number
            _promote_block(work, display, feature, text)
            children = nx.children(work)
            _set_display(state, nx.prototype(children[0]))
            state.update_session_parts()
            state.is_upper = upper_component
            work = nx.work_part()
            display = nx.display_part()
            _create_expressions(work, display)
            work.Layers.WorkLayer = 15
            _extract_layer1_body(work)
            _create_ref_sets_categories(work, display)
            work.Layers.WorkLayer = 1
            work.Layers.SetState(15, NXOpen.Layer.State.Hidden)
            _create_auto_size_udo(work)
            _color_new_bodies(work, display, upper_component)
            try:
                if selected_item is None:
                    raise AttributeError("Object reference not set to an instance of an object.")
                work.SetUserAttribute(selected_item[0], -1, selected_item[1], NXOpen.Update.Option.Later)
                work.SetUserAttribute(material[0], -1, material[1], NXOpen.Update.Option.Later)
                work.SetUserAttribute("BREAK", -1, "###", NXOpen.Update.Option.Later)
                work.SetUserAttribute("EC", -1, "???", NXOpen.Update.Option.Later)
            except NXOpen.NXException as ex:
                nx.message_box("Caught exception : Set Attributes - Name, Material",
                                                    NXOpen.NXMessageBox.DialogType.Error, str(ex))
                nx.ufsession_.Disp.SetDisplay(nx.UF_DISP_UNSUPPRESS_DISPLAY)
                nx.ufsession_.Disp.RegenerateDisplay()
            work.Layers.SetState(3, NXOpen.Layer.State.WorkLayer)
            cast(Any, work.Preferences).ObjectPreferences.SetColor(
                cast(Any, NXOpen).PartObject.ObjectType.Solidbody, _comp_color()[1])
            nx.session_.ApplicationSwitchImmediate("UG_APP_MODELING")
            _set_display(state, cast(NXOpen.Part, state.original_display_part))
            state.update_session_parts()
            nx.ufsession_.Disp.SetDisplay(nx.UF_DISP_UNSUPPRESS_DISPLAY)
            nx.ufsession_.Disp.RegenerateDisplay()
            _set_work(state, cast(NXOpen.Part, state.original_work_part))
            state.update_session_parts()
            display = nx.display_part()
            display.WCS.SetOriginAndMatrix(origin, element)
            cast(Any, display.WCS).Visibility = True
            children[0].RedisplayObject()
            nx.work_part().ComponentAssembly.ReplaceReferenceSet(children[0], "BODY")
            _add_to_body_refsets(cast(NXOpen.Part, state.work_part), children[0])
        except NXOpen.NXException as ex:
            nx.ufsession_.Disp.SetDisplay(nx.UF_DISP_UNSUPPRESS_DISPLAY)
            nx.ufsession_.Disp.RegenerateDisplay()
            state.update_session_parts()
            nx.message_box("Caught exception in Create Component",
                                                NXOpen.NXMessageBox.DialogType.Error, str(ex))
            cast(Any, nx.session_).UndoToLastVisibleMark()
            work = cast(NXOpen.Part, state.work_part)
            to_delete: List[NXOpen.TaggedObject] = [f for f in work.Features.GetFeatures()
                                                    if f.Name == "DYNAMIC BLOCK"]
            to_delete.extend(line for line in cast(Any, work).Lines if line.Name != "")
            to_delete.extend(point for point in work.Points if point.Name != "")
            if len(to_delete) <= 0:
                return
            cast(Any, nx.delete_objects)(to_delete)
    except Exception as ex:
        nx.print_exception(ex)


def _create_component(state: _FormState, body_origin: NXOpen.Point3d, length: str, width: str,
                      height: str) -> Optional[NXOpen.Assemblies.Component]:
    """
    NewCompBuild.CreateComponent(Point3d, string, string, string, out Component) - the Auto / retainer block: next
    detail number, block at body_origin (upper: rolled 180 about X), promoted, six fasteners added and subtracted,
    attributes. Returns the new occurrence, or None when it failed (printed).
    """
    nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Create Component")
    new_part: Optional[NXOpen.Part] = None
    try:
        display_static = cast(NXOpen.Part, state.display_part)
        _set_default_units(display_static, display_static.PartUnits == NXOpen.BasePart.Units.Millimeters)
        selected_name = (state.name_attr, state.name_value)
        selected_material = (state.material_attr, state.material_value)
        upper_component = state.is_upper
        selected_item = None if state.name_value is None else (state.name_attr, state.name_value)
        material = ("MATERIAL", "") if state.material_value is None else (state.material_attr, state.material_value)
        if _format_detail_number(state):
            state.update_all_parts()
            display = cast(NXOpen.Part, state.display_part)
            work = cast(NXOpen.Part, state.work_part)
            cast(Any, display.WCS).Visibility = False
            _reset_wcs()
            matrix3x3: Optional[NXOpen.Matrix3x3] = None
            if state.is_upper:
                display.WCS.Rotate(NXOpen.WCS.Axis.XAxis, 180.0)
                matrix3x3 = display.WCS.CoordinateSystem.Orientation.Element
            _reset_wcs()
            nx.ufsession_.Disp.SetDisplay(nx.UF_DISP_SUPPRESS_DISPLAY)
            display.Layers.WorkLayer = 1
            origin_point = NXOpen.Point3d(body_origin.X, body_origin.Y, body_origin.Z)
            feature = _commit_dynamic_block(work, origin_point, length, width, height, matrix3x3)
            text = state.detail_number
            _promote_block(work, display, feature, text)
            children = nx.children(work)
            _set_display(state, nx.prototype(children[0]))
            state.update_session_parts()
            state.is_upper = upper_component
            work = nx.work_part()
            display = nx.display_part()
            _create_expressions(work, display)
            work.Layers.WorkLayer = 15
            _extract_layer1_body(work)
            _create_ref_sets_categories(work, display)

            _add_fasteners(display)
            new_part = display

            body_refset = nx.find_reference_set_or_null(new_part, "BODY")
            if body_refset is None:
                raise RuntimeError('Could not find reference set with title "BODY" in part "{}".'.format(
                    new_part.Leaf))
            for child in nx.children(new_part):
                try:
                    linked = nx.create_linked_body(child)
                    target = _dynamic_block(new_part).GetBodies()[0]
                    nx.subtract(target, linked.GetBodies())
                    nx.set_reference_set(child, "BODY")
                    body_refset.AddObjectsToReferenceSet([child])
                except Exception as ex:
                    nx.print_exception(ex)

            work.Layers.WorkLayer = 1
            work.Layers.SetState(15, NXOpen.Layer.State.Hidden)
            _create_auto_size_udo(work)
            _color_new_bodies(work, display, upper_component)

            if selected_item is None:
                raise AttributeError("Object reference not set to an instance of an object.")
            work.SetUserAttribute(selected_item[0], -1, selected_item[1], NXOpen.Update.Option.Later)
            work.SetUserAttribute(material[0], -1, material[1], NXOpen.Update.Option.Later)
            work.SetUserAttribute("BREAK", -1, "###", NXOpen.Update.Option.Later)
            work.SetUserAttribute("EC", -1, "???", NXOpen.Update.Option.Later)
            work.Layers.SetState(3, NXOpen.Layer.State.WorkLayer)
            cast(Any, work.Preferences).ObjectPreferences.SetColor(
                cast(Any, NXOpen).PartObject.ObjectType.Solidbody, _comp_color()[1])
            _set_display(state, cast(NXOpen.Part, state.original_display_part))
            state.update_session_parts()
            nx.ufsession_.Disp.SetDisplay(nx.UF_DISP_UNSUPPRESS_DISPLAY)
            nx.ufsession_.Disp.RegenerateDisplay()
            _set_work(state, cast(NXOpen.Part, state.original_work_part))
            state.update_session_parts()
            cast(Any, nx.display_part().WCS).Visibility = True
            children[0].RedisplayObject()
            nx.work_part().ComponentAssembly.ReplaceReferenceSet(children[0], "BODY")
            nx.print_(nx.work_part().Leaf)
            _add_to_body_refsets(cast(NXOpen.Part, state.work_part), children[0])

        # UpdateFormText(); the list selections go back to what they were (the C# handler had cleared them).
        state.name_attr, state.name_value = selected_name
        state.material_attr, state.material_value = selected_material

        if new_part is None:
            raise AttributeError("Object reference not set to an instance of an object.")
        return nx.occurrences_of_part_in(nx.display_part(), new_part)[0]
    except Exception as ex:
        nx.print_exception(ex)
        return None


def _create_component_static(state: _FormState, text: str, upper: bool, body_origin: NXOpen.Point3d,
                             length: str, width: str, height: str) -> Optional[NXOpen.Assemblies.Component]:
    """NewCompBuild.CreateComponentStatic - CreateComponent(Point3d, ...) without the detail-number formatting, the
    name / material attributes and the fastener subtract (all commented out in the C#)."""
    nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Create Component")
    new_part: Optional[NXOpen.Part] = None
    try:
        display_static = cast(NXOpen.Part, state.display_part)
        _set_default_units(display_static, display_static.PartUnits == NXOpen.BasePart.Units.Millimeters)
        state.update_all_parts()
        display = cast(NXOpen.Part, state.display_part)
        work = cast(NXOpen.Part, state.work_part)
        cast(Any, display.WCS).Visibility = False
        _reset_wcs()
        matrix3x3: Optional[NXOpen.Matrix3x3] = None
        if upper:
            display.WCS.Rotate(NXOpen.WCS.Axis.XAxis, 180.0)
            matrix3x3 = display.WCS.CoordinateSystem.Orientation.Element
        _reset_wcs()
        nx.ufsession_.Disp.SetDisplay(nx.UF_DISP_SUPPRESS_DISPLAY)
        display.Layers.WorkLayer = 1
        origin_point = NXOpen.Point3d(body_origin.X, body_origin.Y, body_origin.Z)
        feature = _commit_dynamic_block(work, origin_point, length, width, height, matrix3x3)
        _promote_block(work, display, feature, text)
        children = nx.children(work)
        _set_display(state, nx.prototype(children[0]))
        state.update_session_parts()
        work = nx.work_part()
        display = nx.display_part()
        _create_expressions(work, display)
        work.Layers.WorkLayer = 15
        _extract_layer1_body(work)
        _create_ref_sets_categories(work, display)
        _add_fasteners(display)
        new_part = display
        work.Layers.WorkLayer = 1
        work.Layers.SetState(15, NXOpen.Layer.State.Hidden)
        _create_auto_size_udo(work)
        _color_new_bodies(work, display, upper)
        work.SetUserAttribute("BREAK", -1, "###", NXOpen.Update.Option.Later)
        work.SetUserAttribute("EC", -1, "???", NXOpen.Update.Option.Later)
        work.Layers.SetState(3, NXOpen.Layer.State.WorkLayer)
        cast(Any, work.Preferences).ObjectPreferences.SetColor(
            cast(Any, NXOpen).PartObject.ObjectType.Solidbody, _comp_color()[1])
        _set_display(state, cast(NXOpen.Part, state.original_display_part))
        state.update_session_parts()
        nx.ufsession_.Disp.SetDisplay(nx.UF_DISP_UNSUPPRESS_DISPLAY)
        nx.ufsession_.Disp.RegenerateDisplay()
        _set_work(state, cast(NXOpen.Part, state.original_work_part))
        state.update_session_parts()
        cast(Any, nx.display_part().WCS).Visibility = True
        children[0].RedisplayObject()
        nx.work_part().ComponentAssembly.ReplaceReferenceSet(children[0], "BODY")
        nx.print_(nx.work_part().Leaf)
        _add_to_body_refsets(cast(NXOpen.Part, state.work_part), children[0])
        return nx.occurrences_of_part_in(nx.display_part(), new_part)[0]
    except Exception as ex:
        nx.print_exception(ex)
        return None


# ---------------------------------------------------------------------------------------------------
# Color Component (ColorComponent)
# ---------------------------------------------------------------------------------------------------

def _color_component(state: _FormState, component: Optional[NXOpen.Assemblies.Component]) -> None:
    """NewCompBuild.ColorComponent - recolors the component's single layer-1 body, keeping the color of every face
    its first (EXTRUDE / BLOCK / BREP) feature did not make."""
    nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Color Component")
    try:
        try:
            if component is None:
                return
            nx.ufsession_.Disp.SetDisplay(nx.UF_DISP_SUPPRESS_DISPLAY)
            nx.set_display_part(nx.prototype(component))
            state.update_session_parts()
            display = nx.display_part()
            list1 = [body for body in display.Bodies if body.Layer == 1]
            if len(list1) == 1:
                feature_faces: List[NXOpen.Face] = []
                first_feature = list1[0].GetFeatures()[0]
                if first_feature.FeatureType in ("EXTRUDE", "BLOCK", "BREP"):
                    feature_faces.extend(cast(Any, first_feature).GetFaces())
                feature_face_tags = {face.Tag for face in feature_faces}
                kept = [face for face in list1[0].GetFaces() if face.Tag not in feature_face_tags]
                kept_colors = [face.Color for face in kept]
                color = _comp_color()[1]
                nx.set_color(list1[0], color)
                cast(Any, display.Preferences).ObjectPreferences.SetColor(
                    cast(Any, NXOpen).PartObject.ObjectType.Solidbody, color)
                for face, face_color in zip(kept, kept_colors):
                    nx.set_color(face, face_color)
                # changeColorCheckBox.Checked = false stays in the C# handler.
                _restore_original_parts(state)
            else:
                nx.message_box(
                    "Caught exception", NXOpen.NXMessageBox.DialogType.Error,
                    "Component {} has more than one solid body on layer 1".format(component.DisplayName))
        except NXOpen.NXException as ex:
            _restore_original_parts(state)
            nx.message_box("Caught exception", NXOpen.NXMessageBox.DialogType.Error, str(ex))
            cast(Any, nx.session_).UndoToLastVisibleMark()
    except Exception as ex:
        nx.print_exception(ex)


def _restore_original_parts(state: _FormState) -> None:
    """ColorComponent's restore: original display, display on, original work, statics, Views.Regenerate."""
    if state.original_display_part is not None:
        nx.set_display_part(state.original_display_part)
    nx.ufsession_.Disp.SetDisplay(nx.UF_DISP_UNSUPPRESS_DISPLAY)
    nx.ufsession_.Disp.RegenerateDisplay()
    if state.original_work_part is not None:
        nx.set_work_part(state.original_work_part)
    state.update_all_parts()
    cast(Any, nx.display_part().Views).Regenerate()


# ---------------------------------------------------------------------------------------------------
# Save As (SaveAs / FormatDetailNumber)
# ---------------------------------------------------------------------------------------------------

def _save_as(state: _FormState, comp_save_as: NXOpen.Assemblies.Component, comp_name: str,
             diff_units: bool) -> None:
    """NewCompBuild.SaveAs(Component, string, bool)"""
    state.is_save_as = True
    prototype = cast(NXOpen.Part, comp_save_as.Prototype)
    if diff_units:
        nx.ufsession_.Disp.SetDisplay(nx.UF_DISP_SUPPRESS_DISPLAY)
        nx.set_display_part(prototype)
    else:
        nx.set_work_part(prototype)
    state.update_session_parts()

    original_work = cast(NXOpen.Part, state.original_work_part)
    idx = original_work.FullPath.rfind("-")
    new_file_name = "{}{}.prt".format(original_work.FullPath[:idx + 1], comp_name)
    work = cast(NXOpen.Part, state.work_part)
    save_status = work.SaveAs(new_file_name)
    if save_status is not None:
        save_status.Dispose()

    ref_set = 0
    for tag in nx.cycle_objs_in_part(original_work.Tag, _UfReferenceSetType):
        if nx.ufsession_.Obj.AskName(tag) == "BODY":
            ref_set = tag

    part_occs, _count = nx.ufsession_.Assem.AskOccsOfPart(original_work.Tag, prototype.Tag)
    obj = cast(Any, nx.ufsession_.Obj)
    assem = cast(Any, nx.ufsession_.Assem)
    for tag in part_occs:
        obj.SetName(tag, comp_name)
        assem.RenameInstance(nx.ufsession_.Assem.AskInstOfPartOcc(tag), comp_name)
    if ref_set != 0:
        nx.ufsession_.Assem.AddRefSetMembers(ref_set, len(part_occs), list(part_occs))
    for attribute in cast(Any, work).GetUserAttributes():
        if attribute.Title == "DETAIL NUMBER":
            work.SetUserAttribute(attribute.Title, -1, comp_name, NXOpen.Update.Option.Now)

    if diff_units and state.original_display_part is not None:
        nx.set_display_part(state.original_display_part)
    nx.set_work_part(original_work)
    state.update_all_parts()
    if diff_units:
        nx.ufsession_.Disp.SetDisplay(nx.UF_DISP_UNSUPPRESS_DISPLAY)
        nx.ufsession_.Disp.RegenerateDisplay()
    state.is_name_reset = False


def _try_parse_int(text: str) -> Tuple[bool, int]:
    """int.TryParse"""
    try:
        return True, int(text.strip())
    except (ValueError, AttributeError):
        return False, 0


def _format_detail_number(state: _FormState) -> bool:
    """NewCompBuild.FormatDetailNumber - writes the next detail number into state.detail_number."""
    s = state.detail_number
    flag, result = _try_parse_int(s)
    num1 = result
    original_path = cast(NXOpen.Part, state.original_work_part).FullPath
    num2 = original_path.rfind("-")
    path = "{}{}.prt".format(original_path[:num2 + 1], s)
    index = nx.ufsession_.Part.IsLoaded(path)
    while os.path.isfile(path) or index == 1:
        num1 += 1
        s = str(num1).rjust(3, "0")
        path = "{}{}.prt".format(original_path[:num2 + 1], s)
        index = nx.ufsession_.Part.IsLoaded(path)

    if state.four_digits:
        if len(s) != 4 or not flag or result <= 0 or result >= 10000:
            return False
        if state.is_name_reset:
            state.is_name_reset = False
            state.detail_number = s
            return True
        num3 = result + 1
        if 0 < num3 < 10:
            state.detail_number = "000" + str(num3)
            return True
        if 9 < num3 < 100:
            state.detail_number = "00" + str(num3)
            return True
        if 99 < num3 < 1000:
            state.detail_number = "0" + str(num3)
            return True
        if num3 <= 999:
            return False
        state.detail_number = str(num3)
        return True

    if len(s) != 3 or not flag or result <= 0 or result >= 991:
        return False
    if state.is_name_reset:
        state.is_name_reset = False
        state.detail_number = s
        return True
    num4 = result + 1
    if 0 < num4 < 10:
        state.detail_number = "00" + str(num4)
        return True
    if 9 < num4 < 100:
        state.detail_number = "0" + str(num4)
        return True
    if num4 <= 100:
        return False
    state.detail_number = str(num4)
    return True


# ---------------------------------------------------------------------------------------------------
# Apply (UpdateDynamicBlock / DeleteHandles)
# ---------------------------------------------------------------------------------------------------

def _update_dynamic_block(update_comp: Optional[NXOpen.Assemblies.Component], edge_rep_lines: List[NXOpen.Line],
                          work_comp_origin: NXOpen.Point3d, work_comp_orientation: NXOpen.Matrix3x3,
                          is_upr_parallel: bool, is_lwr_parallel: bool, parallel_height_exp: str,
                          parallel_width_exp: str) -> NXOpen.Point3d:
    """NewCompBuild.UpdateDynamicBlock - returns the new _workCompOrigin (the BLKORIGIN point)."""
    with nx.display_part_reset():
        try:
            if update_comp is not None:
                _translucency(update_comp, 0)
            else:
                for body in nx.work_part().Bodies:
                    if body.Layer == 1:
                        _translucency(body, 0)
            point3d = NXOpen.Point3d(0.0, 0.0, 0.0)
            length_expression = ""
            width_expression = ""
            height_expression = ""
            for point in nx.work_part().Points:
                if point.Name == "BLKORIGIN":
                    coordinates = point.Coordinates
                    point3d = NXOpen.Point3d(coordinates.X, coordinates.Y, coordinates.Z)
            for line in edge_rep_lines:
                if line.Name == "XBASE1":
                    length_expression = _s(line.GetLength())
                if line.Name == "YBASE1":
                    width_expression = _s(line.GetLength())
                if line.Name == "ZBASE1":
                    height_expression = _s(line.GetLength())
            if is_upr_parallel:
                width_expression = parallel_height_exp
                height_expression = parallel_width_exp
            if is_lwr_parallel:
                width_expression = parallel_height_exp
                height_expression = parallel_width_exp
            nx.display_part().WCS.SetOriginAndMatrix(point3d, work_comp_orientation)
            work_comp_origin = point3d
            nx.set_work_component(update_comp)
            output = nx.ufsession_.Csys.MapPoint(_UfCsysRootCoords, [point3d.X, point3d.Y, point3d.Z],
                                                 _UfCsysWorkCoords)
            mapped = NXOpen.Point3d(output[0], output[1], output[2])
            work = nx.work_part()
            block = _dynamic_block_or_none(work)
            if block is None:
                return work_comp_origin
            builder = work.Features.CreateBlockFeatureBuilder(block)
            try:
                point = work.Points.CreatePoint(mapped)
                point.SetCoordinates(mapped)
                cast(Any, builder).OriginPoint = point
                builder.SetOriginAndLengths(mapped, length_expression, width_expression, height_expression)
                builder.CommitFeature()
            finally:
                builder.Destroy()
            nx.set_work_part(nx.display_part())
            _delete_handles(edge_rep_lines)
            cast(Any, nx.display_part().WCS).Visibility = True
            cast(Any, nx.display_part().Views).Refresh()
        except Exception as ex:
            nx.print_exception(ex)
    return work_comp_origin


def _delete_handles(edge_rep_lines: List[NXOpen.Line]) -> None:
    """NewCompBuild.DeleteHandles - every named point in the work part and the edge lines, in one update."""
    with nx.do_update():
        try:
            nx.session_.UserDefinedClassManager.GetUserDefinedClassFromClassName("UdoDynamicHandle")
        except NXOpen.NXException:
            pass
        for point in nx.work_part().Points:
            if point.Name != "":
                nx.session_.UpdateManager.AddToDeleteList(point)
        for line in edge_rep_lines:
            nx.session_.UpdateManager.AddToDeleteList(line)


def _translucency(obj: NXOpen.DisplayableObject, translucency: int) -> None:
    """DisplayableObject.__Translucency"""
    cast(Any, nx.ufsession_.Obj).SetTranslucency(obj.Tag, translucency)
    obj.RedisplayObject()


# ---------------------------------------------------------------------------------------------------
# Static\NewCompBuild.cs helpers
# ---------------------------------------------------------------------------------------------------

def _check(component: Optional[NXOpen.Assemblies.Component]) -> str:
    """Static.NewCompBuildCheck - "Lower" / "Upper" / "None" from the nearest classifiable ancestor's name."""
    while component is not None and not component.IsSuppressed:
        upper = component.DisplayName.upper()
        if any(key in upper for key in ("LWR", "LSP", "LSH", "LAD", "LFTR", "LOWER")):
            return "Lower"
        if any(key in upper for key in ("UPR", "USP", "USH", "UAD", "UPPER")):
            return "Upper"
        if component.Parent is None:
            break
        component = component.Parent
    return "None"


def _is_name_valid(part_to_check: NXOpen.BasePart, any_assembly: bool) -> bool:
    """Static.NewCompBuildIsNameValid"""
    if any_assembly:
        return True
    leaf = part_to_check.FullPath[part_to_check.FullPath.rfind("\\") + 1:].lower()
    return any(key in leaf for key in ("lsp", "usp", "ush", "lsh", "lftr", "lnitro", "unitro", "acc", "lair",
                                       "lele"))


def _color_base_face(block: NXOpen.Body, upper_component: bool, display_part: NXOpen.Part) -> None:
    """Static.NewCompBuildColorBaseFace - the planar face facing the WCS Z (upper) / away from it (lower) gets 6."""
    vec3 = cast(Any, nx.ufsession_.Vec3)
    for face in block.GetFaces():
        if face.SolidFaceType != NXOpen.Face.FaceType.Planar:
            continue
        z = nx.axis_z(display_part.WCS.CoordinateSystem.Orientation.Element)
        vec1 = [z.X, z.Y, z.Z]
        direction = nx.ufsession_.Modeling.AskFaceData(face.Tag)[2]
        is_parallel = vec3.IsParallel(vec1, direction, 0.001)
        if is_parallel == 1:
            is_equal = nx.ufsession_.Vec3.IsEqual(vec1, direction, 0.001)
            if upper_component:
                if is_equal == 1:
                    nx.set_color(face, 6)
            elif is_equal == 0:
                nx.set_color(face, 6)


def _create_ref_sets_categories(work_part: NXOpen.Part, display_part: NXOpen.Part) -> None:
    """Static.NewCompBuildCreateRefSetsCategories - BODY (layer-1 body) and SUB_TOOL (layer-15 body) reference sets,
    then the standard layer categories, and layer 3 made the work layer."""
    undo_mark = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Reference Sets")
    body_refset: Optional[NXOpen.ReferenceSet] = None
    for refset in work_part.GetAllReferenceSets():
        if refset.Name == "BODY":
            body_refset = refset
    if body_refset is None:
        body_refset = work_part.CreateReferenceSet()
        sub_tool = work_part.CreateReferenceSet()
        body_refset.SetName("BODY")
        sub_tool.SetName("SUB_TOOL")
    else:
        sub_tool = work_part.CreateReferenceSet()
        sub_tool.SetName("SUB_TOOL")
    cast(Any, body_refset).SetAddComponentsAutomatically(False, False)
    cast(Any, sub_tool).SetAddComponentsAutomatically(False, False)
    body1: Optional[NXOpen.Body] = None
    body15: Optional[NXOpen.Body] = None
    for body in work_part.Bodies:
        if body.Layer == 1:
            body1 = body
    for body in work_part.Bodies:
        if body.Layer == 15:
            body15 = body
    if body1 is not None:
        body_refset.AddObjectsToReferenceSet([body1])
    if body15 is not None:
        sub_tool.AddObjectsToReferenceSet([body15])
    nx.session_.UpdateManager.DoUpdate(undo_mark)

    categories = work_part.LayerCategories
    categories.CreateCategory("BODY", "", [1])
    categories.CreateCategory("BURNOUT", "", [100, 101, 102, 103, 104, 105])
    categories.CreateCategory("CONSTRUCTION", "", [2, 3, 4, 5, 6, 7, 8, 9, 10])
    categories.CreateCategory("DATUM", "", [255])
    categories.CreateCategory("FASTENERS", "", [99])
    categories.CreateCategory("HANDLINGHOLES", "", [98])
    categories.CreateCategory("HOLECHARTTEXT", "", [230])
    categories.CreateCategory("NESTEDBLOCKS", "", [96])
    categories.CreateCategory("ORDERBLOCK", "", [250])
    categories.CreateCategory("SUBTOOL", "", [15, 16, 17, 18, 19, 20])
    categories.CreateCategory("TITLEBLOCK", "", [200])
    categories.CreateCategory("TOOLINGHOLES", "", [97])
    categories.CreateCategory("WIRESTARTHOLE", "", [94])
    display_part.Layers.SetState(3, NXOpen.Layer.State.WorkLayer)


def _convert_units(distances: List[float], work_part: NXOpen.BasePart) -> bool:
    """Static.NewCompBuildConvertUnits - millimetre parts: distances to inches, True."""
    if work_part.PartUnits != NXOpen.BasePart.Units.Millimeters:
        return False
    for index in range(len(distances)):
        distances[index] /= 25.4
    return True


def _cs_round(value: float, digits: int) -> float:
    """System.Math.Round(double, int) - banker's rounding, as Python's round()."""
    return round(value, digits)


def _cs_truncate(value: float) -> float:
    return float(int(value))


def _round_up_to_eighth(value: float) -> Optional[float]:
    """The shared 'round and truncate, then up to the next 1/8' step; None when the loop finds nothing."""
    round_value = _cs_round(value, 3)
    truncate_value = _cs_truncate(round_value)
    fraction_value = round_value - truncate_value
    if abs(fraction_value) <= 0.0001:
        return round_value
    num1 = 0.125
    while num1 <= 1.0:
        if fraction_value <= num1:
            return truncate_value + num1
        num1 += 0.125
    return None


def _distance0(distances: List[float]) -> None:
    """Static.NewCompBuildDistance0 - each distance up to the next 1/8."""
    for index in range(3):
        rounded = _round_up_to_eighth(distances[index])
        if rounded is not None:
            distances[index] = rounded


def _min_corner3(min_corner: List[float]) -> None:
    """Static.NewCompBuildMinCorner3 - each coordinate away from zero to the next 1/8."""
    for index in range(3):
        flag = False
        if min_corner[index] < 0.0:
            min_corner[index] *= -1.0
            flag = True
        round_value = _cs_round(min_corner[index], 3)
        truncate_value = _cs_truncate(round_value)
        fraction_value = round_value - truncate_value
        if abs(fraction_value) <= 0.0001:
            # Kept from the C#: a whole number loses its sign here.
            min_corner[index] = round_value
            continue
        num1 = 0.125
        while num1 <= 1.0:
            if fraction_value <= num1:
                num2 = truncate_value + num1
                min_corner[index] = num2 * -1.0 if flag else num2
                break
            num1 += 0.125


def _dynamic_block_or_none(part: NXOpen.BasePart) -> Optional[NXOpen.Features.Block]:
    """BasePart.__DynamicBlockOrNull - SingleOrDefault: raises when there are two."""
    blocks = [f for f in part.Features.GetFeatures()
              if isinstance(f, NXOpen.Features.Block) and f.Name == "DYNAMIC BLOCK"]
    if len(blocks) > 1:
        raise RuntimeError("Sequence contains more than one matching element")
    return blocks[0] if blocks else None


def _dynamic_block(part: NXOpen.BasePart) -> NXOpen.Features.Block:
    """BasePart.__DynamicBlock"""
    block = _dynamic_block_or_none(part)
    if block is None:
        raise RuntimeError("Could not find ")
    return block


def _ask_detail_op(path: str) -> str:
    """string.__AskDetailOp"""
    leaf = os.path.splitext(os.path.basename(path))[0]
    match = re.match(r"^\d+-(?P<op>\d+)-.+$", leaf)
    if not match:
        raise RuntimeError("could not find an op: '{}'".format(leaf))
    return match.group("op")


class _GFolder(object):
    """GFolder (src\\Utilities\\GFolder.cs) - only Create and file_detail0."""

    def __init__(self, dir_job: str, customer_number: str) -> None:
        self.DirJob = dir_job
        self.CustomerNumber = customer_number

    def dir_op(self, op: str) -> str:
        return "{}\\{}-{}".format(self.DirJob, self.CustomerNumber, op)

    def file_detail0(self, op: str, detail: str) -> str:
        return "{}\\{}-{}-{}.prt".format(self.dir_op(op), self.CustomerNumber, op, detail)

    @staticmethod
    def create(job_folder: str) -> "_GFolder":
        """GFolder.Create(string)"""
        split = job_folder.split("\\")
        if len(split) < 3:
            raise IndexError(job_folder)
        directory = "{}\\{}\\{}".format(split[0], split[1], split[2])
        number = _GFolder._job_number(directory, split[2])
        if number:
            return _GFolder(directory, number)
        # Not the C#: a job copied below the usual depth (G:\CTS\junk\Mark B\006073\006073-010\...) has no job
        # number in the third piece, so the job folder is the first deeper folder whose name starts with one.
        for i in range(3, len(split) - 1):
            deeper = "\\".join(split[:i + 1])
            number = _GFolder._job_number(deeper, split[i])
            if number:
                return _GFolder(deeper, number)
        if "\\cts\\" not in directory.lower():
            return _GFolder(directory, "")
        raise ValueError("Could not make GFolder from '{}'".format(job_folder))

    @staticmethod
    def _job_number(directory: str, leaf: str) -> Optional[str]:
        """GFolder.Create's rules for the job folder `directory` named `leaf`: its customer number, or None."""
        if "\\cts\\" not in directory.lower():
            match0 = re.match(r"^(?P<num_0>\d{2,})", leaf)
            return match0.group("num_0") if match0 else None
        if _try_parse_int(leaf)[0]:
            return leaf
        match = re.match(r"^(?P<cts_number>\d{2,}) \([A-Z]+-[xX]+\)", leaf)
        if match:
            return match.group("cts_number")
        match = re.match(r"^(?P<cts_number>\d{2,}) \([A-Za-z]+-(?P<customer_number>\d+)\)", leaf)
        if match:
            return match.group("customer_number")
        match = re.match(r"^(?P<customer_number>\d{2,})", leaf)
        if match:
            return match.group("customer_number")
        return None


# ---------------------------------------------------------------------------------------------------
# Selection / dialogs
# ---------------------------------------------------------------------------------------------------

def _select_one_component(message: str, title: Optional[str] = None) -> Optional[NXOpen.Assemblies.Component]:
    """Selection.SelectOneComponent(message) - None on cancel."""
    mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_component_type, 0, 0)
    result = cast(Any, NXOpen.UI.GetUI().SelectionManager).SelectTaggedObject(
        message,
        title if title is not None else message,
        NXOpen.Selection.SelectionScope.AnyInAssembly,
        NXOpen.Selection.SelectionAction.ClearAndEnableSpecific,
        False,
        False,
        [mask])
    response, obj = result[0], result[1]
    if response not in (NXOpen.Selection.Response.Ok, NXOpen.Selection.Response.ObjectSelected,
                        cast(Any, NXOpen.Selection.Response).ObjectSelectedByName):
        return None
    return obj if isinstance(obj, NXOpen.Assemblies.Component) else None


def _select_multiple_bodies(message: str = "Select Bodies") -> List[NXOpen.Body]:
    """Selection.SelectMultipleBodies - solid and sheet bodies; [] unless the response is Ok."""
    mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type, 0, 0)
    response, objects = NXOpen.UI.GetUI().SelectionManager.SelectTaggedObjects(
        message,
        message,
        NXOpen.Selection.SelectionScope.AnyInAssembly,
        NXOpen.Selection.SelectionAction.ClearAndEnableSpecific,
        False,
        False,
        [mask])
    if response != NXOpen.Selection.Response.Ok:
        return []
    return [cast(NXOpen.Body, obj) for obj in objects]


def _message_box(text: str) -> None:
    """MessageBox.Show(text) - an NX Information box."""
    nx.message_box("Copy Component", NXOpen.NXMessageBox.DialogType.Information, text)


def main() -> None:
    """File -> Execute -> NX Open: there is no form to read, so this only reports the entry points."""
    nx.print_("NewCompBuild.py is driven by the component-builder form (PythonLibrary.Execute).")


if __name__ == "__main__":
    main()
