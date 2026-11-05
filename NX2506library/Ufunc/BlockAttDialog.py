"""
The block-att-dialog UFunc (Block Attributer), Python only since 2026-10-30: one Block Styler dialog
(BlockAttDialog.dlx, tools\\make-dlx.py) in place of the WinForms form (src\\UFuncs\\BlockAttDialog.cs) and the SNAP
Stock and Burn / Default Attributes dialog it opened (src\\Ui\\Dialogs\\BlockAttStockBurn.cs). The form's buttons are
the Mode radio:

- Select Block: pick a solid body. Its block (the component's first block feature, placed by the component; a body in
  the display part: its DYNAMIC BLOCK) is drawn as temporary lines, stocked and rounded up to 1/8" (redrawn as the
  Add Stock picks change), the component becomes the work component (its units must match the display part's), and
  the Add Stock, Burn Settings and Default Attributes groups load from its part. OK / Apply writes them
  (BlockAttStockBurn.OnApply: AddX/Y/Z, Burnout, Grind, GrindTolerance, BurnDir, the defaults, Auto Update on with an
  information box when it was off), then the form's Apply (BlockAttDialogUpdateBlockDescription: " PARALLEL" on
  DESCRIPTION when an lwrParallel / uprParallel expression is "yes").
- Custom Description: pick a component (none: the display part); its DESCRIPTION loads into the box, the
  Descriptions menu (CUSTOM_DESCRIPTIONS) copies into it. OK / Apply writes DESCRIPTION and turns Auto Update off, with
  a warning box for a part with a DYNAMIC BLOCK.
- Change Attributes: pick components; OK / Apply writes the Default Attributes to each part (one per display name;
  blank fields and Unchanged are left alone, Dieset / Weldment only when changed - ticked when every picked part has
  the note on).
- Auto Update On: pick components (none: the work part); OK / Apply turns each part's Auto Update on, displaying it,
  and adds the PARALLEL suffix as above.

Apply clears the picks, as the form's Reset did. The menus come from U:\\nxFiles\\UfuncFiles\\ConceptControlFile.UCF:
Materials (COMPONENT_MATERIALS, or COMPONENT_BURN_MATERIALS while Burnout is ticked), Vendor (PURCHASED_MATERIALS;
picking one clears Material and typing a Material clears it), Detail Names (COMPONENT_NAMES), Tolerance
(COMPONENT_TOLERANCES, else "none").

Left out or changed from the C#:
- Measure (WriteSizeDescription was commented out, so it wrote nothing) and the unwired Dieset / Weldment buttons.
- The Select Block size preview along the WCS (ShowSizePreview) - only the block's own stocked box is drawn.
- " PARALLEL" is not appended again to a DESCRIPTION that already ends with it (the C# added it on every Apply).
- The work part goes back to what it was when the block pick is cleared, the mode changes, after Apply and on close
  (the C# set it to the display part at its next Reset). Parts are written directly, not as a quiet work part.
- A broken AddX / ... expression (NX 3270012) prints, as before, and clears the pick.
Never run in NX. The C# form, BlockAttStockBurn, most of Static\\BlockAttDialog.cs and the _Runner case are in git
at 29a9315 (Static\\BlockAttDialog.cs keeps the box helpers the C# DesignCheck form draws with; Static\\BlockAtt.cs
stays for Block Attributer).
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple, cast

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
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
import design_check_material as material  # noqa: E402
from design_check_attributes import _is_udo_auto_size, _try_udo_auto_size, _udo_auto_size_or_null  # noqa: E402
from tsg_dialog import Dialog, components_of, title_with_version  # noqa: E402

ufunc_name = "block-att-dialog"

_SettingsFile = "U:\\nxFiles\\UfuncFiles\\ConceptControlFile.UCF"

# The Mode radio (BlockAttDialog.dlx).
ModeBlock, ModeCustom, ModeChange, ModeAutoUpdate = \
    "Select Block", "Custom Description", "Change Attributes", "Auto Update On"

AddStockItems = [".000", ".125", ".250", ".375", ".500", ".625", ".750", ".875", "1.000"]
BurnNone, BurnZ = "None", "Z"
BurnDirectionItems = [BurnNone, "X", "Y", BurnZ]
YesNoUnchanged = "Unchanged"
YesNoItems = [YesNoUnchanged, "YES", "NO"]
# Item 0 of the "_list" menus, which copy their pick into the box beside them.
_ListPrompt = "(list)"
_NoVendor = "(none)"
_AutoUpdateAttribute = "AUTO UPDATE"
# NX: an expression that does not evaluate (BlockAttTryReadBlockExpressions).
_ErrorBrokenExpression = 3270012


# ---------------------------------------------------------------------------------------------------
# ConceptControlFile.UCF
# ---------------------------------------------------------------------------------------------------

def _read_ucf_list(start: str, end: str) -> List[str]:
    """BlockAttStockBurn.ReadUcfList (string.PerformStreamReaderList): the section's non-empty lines; [] (printed)
    when the file or section cannot be read."""
    try:
        with open(_SettingsFile, "r", newline="") as f:
            text = f.read()
        section = re.split(end, re.split(start, text)[1])[0]
        return [line for line in re.split("\r\n", section) if line != ""]
    except Exception as ex:
        nx.print_exception(ex)
        return []


def _distinct(items: Sequence[str]) -> List[str]:
    seen: Dict[str, bool] = {}
    result: List[str] = []
    for item in items:
        if item not in seen:
            seen[item] = True
            result.append(item)
    return result


class _Lists(object):
    """MainForm_Load / the BlockAttStockBurn constructor: the UCF lists behind the menus."""

    def __init__(self) -> None:
        self.descriptions = _distinct(_read_ucf_list(":CUSTOM_DESCRIPTIONS:", ":END_CUSTOM_DESCRIPTIONS:"))
        self.materials = _distinct(_read_ucf_list(":COMPONENT_MATERIALS:", ":END_COMPONENT_MATERIALS:"))
        self.burn_materials = _distinct(_read_ucf_list(":COMPONENT_BURN_MATERIALS:", ":END_COMPONENT_BURN_MATERIALS:"))
        self.vendors = [_NoVendor] + sorted(_distinct(_read_ucf_list(":PURCHASED_MATERIALS:",
                                                                     ":END_PURCHASED_MATERIALS:")))
        self.names = _distinct(_read_ucf_list(":COMPONENT_NAMES:", ":END_COMPONENT_NAMES:"))
        self.tolerances = _read_ucf_list(":COMPONENT_TOLERANCES:", ":END_COMPONENT_TOLERANCES:") or ["none"]


# ---------------------------------------------------------------------------------------------------
# Expressions, attributes, Auto Update
# ---------------------------------------------------------------------------------------------------

def _last_expression(part: NXOpen.BasePart, name: str) -> Optional[NXOpen.Expression]:
    """BlockAttStockBurn.Find: the part's last expression with exactly that name."""
    found: Optional[NXOpen.Expression] = None
    for expression in part.Expressions:
        if expression.Name == name:
            found = expression
    return found


def _string_value(part: NXOpen.BasePart, name: str) -> str:
    """BlockAttStockBurn.StringValue: the last such expression's right-hand side without quotes, "" when none."""
    expression = _last_expression(part, name)
    return "" if expression is None else expression.RightHandSide.replace('"', "")


def _attribute(part: NXOpen.BasePart, title: str) -> str:
    return nx.get_attribute(part, title) if nx.has_attribute(part, title) else ""


def _set_add_stock(part: NXOpen.BasePart, name: str, value: str) -> None:
    """BlockAttStockBurn.SetAddStock: edits the expression, or creates it in the part's units."""
    expression = _last_expression(part, name)
    if expression is not None:
        expression.RightHandSide = value
        return
    unit = part.UnitCollection.FindObject("Inch" if part.PartUnits == NXOpen.BasePart.Units.Inches else "MilliMeter")
    part.Expressions.CreateWithUnits("{}={}".format(name, value), unit)


def _set_string(part: NXOpen.BasePart, name: str, value: str) -> None:
    """BlockAttStockBurn.SetString: a string expression, edited or created."""
    expression = _last_expression(part, name)
    if expression is not None:
        expression.RightHandSide = '"{}"'.format(value)
    else:
        part.Expressions.CreateExpression("String", '{}="{}"'.format(name, value))


def apply_description_note(part: NXOpen.BasePart, note_name: str, suffix: str, on: bool) -> None:
    """
    Static.BlockAttApplyDescriptionNote: adds " SUFFIX" to DESCRIPTION (unless it already holds it, ignoring case) or
    takes it out; a part without DESCRIPTION gets "NO DESCRIPTION" when turning on (without the suffix, as in the C#).
    Then the note expression is set to "yes" / "no".
    """
    if nx.has_attribute(part, "DESCRIPTION"):
        description = nx.get_attribute(part, "DESCRIPTION")
        if description != "":
            if not on:
                nx.set_attribute(part, "DESCRIPTION", description.replace(" " + suffix, ""))
            elif suffix.lower() not in description.lower():
                nx.set_attribute(part, "DESCRIPTION", "{} {}".format(description, suffix))
    elif on:
        nx.set_attribute(part, "DESCRIPTION", "NO DESCRIPTION")

    _set_string(part, note_name, "yes" if on else "no")


def _expressions_readable(part: NXOpen.BasePart) -> bool:
    """Static.BlockAttTryReadBlockExpressions: reads the block expressions; a broken one (3270012) is printed and
    gives False."""
    try:
        for expression in part.Expressions:
            if expression.Name in ("AddX", "AddY", "AddZ"):
                _ = expression.Value
            elif expression.Name in ("BurnDir", "Burnout", "Grind", "GrindTolerance", "DiesetNote"):
                _ = expression.RightHandSide
        return True
    except NXOpen.NXException as ex:
        if ex.ErrorCode != _ErrorBrokenExpression:
            raise
        nx.print_("Detected broken expression in part {}".format(part.Leaf))
        return False


def _has_dynamic_block(part: NXOpen.BasePart) -> bool:
    return any(isinstance(f, NXOpen.Features.Block) and f.Name == "DYNAMIC BLOCK" for f in part.Features)


def _set_auto_update(part: NXOpen.BasePart, on: bool) -> None:
    """BasePart.__UdoAutoSizeUpdateStatus(bool): the AutoSize UDO's status, and the AUTO UPDATE attribute beside it."""
    udo = _udo_auto_size_or_null(part)
    if udo is None:
        raise ValueError("{} is not a UdoAutoSizeComponent".format(part.Leaf))
    cast(Any, udo).SetIntegers([1 if on else 0])
    nx.set_attribute(part, _AutoUpdateAttribute, "ON" if on else "OFF")


def _turn_auto_update_on(part: NXOpen.BasePart) -> bool:
    """BlockAttStockBurn.TurnAutoUpdateOn: True when it was off and is now on."""
    if not _is_udo_auto_size(part):
        nx.print_("{}: no AutoSize UDO, so auto update was not turned on.".format(part.Leaf))
        return False
    known, is_on = _try_udo_auto_size(part)
    if known and is_on:
        return False
    _set_auto_update(part, True)
    nx.print_('{}: {} has been set to "On".'.format(part.Leaf, _AutoUpdateAttribute))
    return True


def update_block_description(part: NXOpen.BasePart) -> None:
    """
    Static.BlockAttDialogUpdateBlockDescription, what is left of it (its size description was commented out):
    " PARALLEL" on DESCRIPTION when an lwrParallel / uprParallel string expression is "yes" - here only when DESCRIPTION
    does not already end with it.
    """
    try:
        if not nx.has_attribute(part, "DESCRIPTION"):
            return
        description = nx.get_attribute(part, "DESCRIPTION")
        parallel = False
        for expression in part.Expressions:
            if expression.Name.lower() not in ("lwrparallel", "uprparallel"):
                continue
            if expression.RightHandSide.replace('"', "").lower() == "yes":
                parallel = True
        if parallel and not description.endswith(" PARALLEL"):
            nx.set_attribute(part, "DESCRIPTION", "{} PARALLEL".format(description))
    except Exception as ex:
        nx.print_exception(ex)


def set_auto_update_on(part: NXOpen.BasePart) -> None:
    """Static.BlockAttDialogSetWorkPartAutoUpdateOn"""
    if _is_udo_auto_size(part):
        _set_auto_update(part, True)
    update_block_description(part)


# ---------------------------------------------------------------------------------------------------
# The picked block
# ---------------------------------------------------------------------------------------------------

def _builder_frame(block: NXOpen.Features.Block) -> Tuple[NXOpen.Point3d, NXOpen.Vector3d, NXOpen.Vector3d]:
    owner: Any = block.OwningPart
    builder = owner.Features.CreateBlockFeatureBuilder(block)
    try:
        x_axis, y_axis = builder.GetOrientation()
        return builder.Origin, x_axis, y_axis
    finally:
        builder.Destroy()


def _to_assembly(component: NXOpen.Assemblies.Component, x: float, y: float, z: float,
                 translate: bool) -> Tuple[float, float, float]:
    """Static.BlockAttDialogToAssemblySpace: the orientation's rows are the component's axes."""
    position, o = component.GetPosition()
    sx, sy, sz = (position.X, position.Y, position.Z) if translate else (0.0, 0.0, 0.0)
    return (sx + x * o.Xx + y * o.Yx + z * o.Zx,
            sy + x * o.Xy + y * o.Yy + z * o.Zy,
            sz + x * o.Xz + y * o.Yz + z * o.Zz)


def _unit(x: float, y: float, z: float) -> NXOpen.Vector3d:
    length = (x * x + y * y + z * z) ** 0.5
    return NXOpen.Vector3d(x / length, y / length, z / length)


def _cross(a: NXOpen.Vector3d, b: NXOpen.Vector3d) -> NXOpen.Vector3d:
    return NXOpen.Vector3d(a.Y * b.Z - a.Z * b.Y, a.Z * b.X - a.X * b.Z, a.X * b.Y - a.Y * b.X)


class _Frame(object):
    """The picked body, its block's origin and axes in display-part coordinates, and the part the stock is on."""

    def __init__(self, body: NXOpen.Body) -> None:
        self.body = body
        if body.IsOccurrence:
            # BlockAttDialogGetBlockOriginInAssembly / ...OrientationInAssembly: the first block feature.
            component = body.OwningComponent
            part = cast(NXOpen.Part, component.Prototype)
            if not part.IsFullyLoaded:
                part.LoadThisPartFully().Dispose()
            block = next((f for f in part.Features if isinstance(f, NXOpen.Features.Block)), None)
            if block is None:
                raise RuntimeError("{} has no block feature".format(part.Leaf))
            origin, x_local, y_local = _builder_frame(block)
            self.origin = NXOpen.Point3d(*_to_assembly(component, origin.X, origin.Y, origin.Z, True))
            self.x_axis = _unit(*_to_assembly(component, x_local.X, x_local.Y, x_local.Z, False))
            self.y_axis = _unit(*_to_assembly(component, y_local.X, y_local.Y, y_local.Z, False))
            self.component: Optional[NXOpen.Assemblies.Component] = component
            self.part = part
        else:
            self.part = cast(NXOpen.Part, body.OwningPart)
            self.origin, self.x_axis, self.y_axis = _builder_frame(nx.dynamic_block(self.part))
            self.component = None
        self.z_axis = _cross(self.x_axis, self.y_axis)

    def stocked_size(self, stock: Sequence[float]) -> List[float]:
        """Static.BlockAttDialogStockedBlockSize, with the stock given (the dialog's picks) in place of the part's
        AddX / AddY / AddZ."""
        ufs: Any = nx.ufsession_
        x, y = self.x_axis, self.y_axis
        matrix = ufs.Mtx3.Initialize([x.X, x.Y, x.Z], [y.X, y.Y, y.Z])
        matrix_tag = ufs.Csys.CreateMatrix(list(matrix))
        csys = ufs.Csys.CreateTempCsys([self.origin.X, self.origin.Y, self.origin.Z], matrix_tag)

        distances = [d + s for d, s in zip(material.OrientedBox(self.body.Tag, csys).distances, stock)]

        is_metric = nx.display_part().PartUnits == NXOpen.BasePart.Units.Millimeters
        if is_metric:
            distances = [d / 25.4 for d in distances]
        material.round_distances(distances)
        if is_metric:
            distances = [d * 25.4 for d in distances]
        return distances

    def draw(self, stock: Sequence[float]) -> None:
        """BlockAttDialogDisplayTemporaryBlockEdges: the stocked box's edges, after a view refresh clears the last."""
        display = nx.display_part()
        display.Views.Refresh()
        size = self.stocked_size(stock)
        material.display_temporary_block_edges(self.origin, self.x_axis, self.y_axis, self.z_axis,
                                               size[0], size[1], size[2], display)


# ---------------------------------------------------------------------------------------------------
# The dialog
# ---------------------------------------------------------------------------------------------------

class _BlockAttDialog(Dialog):
    """BlockAttDialog.dlx - see the module docstring."""

    dlx_name = "BlockAttDialog.dlx"

    def __init__(self, title: str, lists: _Lists) -> None:
        self.title = title
        self.lists = lists
        super().__init__()
        self._frame: Optional[_Frame] = None
        # The work part before Select Block made the picked component the work component.
        self._previous_work: Optional[NXOpen.BasePart] = None
        # What Dieset / Weldment showed when loaded: they are written only when changed.
        self._dieset_on = False
        self._weldment_on = False

    # ----- callbacks -----

    def initialize(self) -> None:
        mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type, 0, 36)  # solid bodies
        self.block("block_body").SetSelectionFilter(NXOpen.Selection.SelectionAction.ClearAndEnableSpecific, [mask])
        self.component_filter(self.block("custom_component"))
        self.component_filter(self.block("components"))
        for block_id in ("block_body", "custom_component", "components"):
            self.assembly_scope(self.block(block_id))

    def shown(self) -> None:
        self.block("description_list").SetEnumMembers([_ListPrompt] + self.lists.descriptions)
        self.block("detail_name_list").SetEnumMembers([_ListPrompt] + self.lists.names)
        self.block("vendor").SetEnumMembers(self.lists.vendors)
        self.block("tolerance").SetEnumMembers(self.lists.tolerances)
        self._enter_mode()

    def enable_ok(self) -> bool:
        mode = self._mode()
        if mode == ModeBlock:
            return self._frame is not None
        if mode == ModeCustom:
            return self.string_value(self.block("description")) != ""
        if mode == ModeChange:
            return len(self._components()) > 0
        return True

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        if block == self.block("mode"):
            self._enter_mode()
        elif block == self.block("block_body"):
            self._block_picked()
        elif block == self.block("custom_component"):
            self._load_description()
        elif block == self.block("components"):
            if self._mode() == ModeChange:
                self._load_notes_of_picked()
        elif block in (self.block("add_x"), self.block("add_y"), self.block("add_z")):
            self._redraw()
        elif block == self.block("vendor"):
            if self.block("vendor").ValueAsString != _NoVendor:
                self.set_string_value(self.block("material"), "")
        elif block == self.block("material"):
            if self.string_value(self.block("material")) != "":
                self.block("vendor").ValueAsString = _NoVendor
        elif block == self.block("material_list"):
            if self._copy_list_pick("material_list", "material"):
                self.block("vendor").ValueAsString = _NoVendor
        elif block == self.block("detail_name_list"):
            self._copy_list_pick("detail_name_list", "detail_name")
        elif block == self.block("description_list"):
            self._copy_list_pick("description_list", "description")
        elif block == self.block("burnout"):
            # BlockAttStockBurn.OnUpdate: the material menu follows Burnout (the typed material carries over), and
            # Burnout sets the burn direction to Z.
            burnout = bool(self.block("burnout").Value)
            self._fill_material_list(burnout)
            if burnout:
                self.block("burn_direction").ValueAsString = BurnZ
            elif self.block("burn_direction").ValueAsString == BurnZ:
                self.block("burn_direction").ValueAsString = BurnNone
        elif block == self.block("grind"):
            grind = bool(self.block("grind").Value)
            self.block("tolerance").Enable = grind
            if grind:
                self.block("tolerance").ValueAsString = self.lists.tolerances[0]
                self.block("burn_direction").ValueAsString = BurnZ
            elif not self.block("burnout").Value:
                self.block("burn_direction").ValueAsString = BurnNone

    def ok(self) -> bool:
        mode = self._mode()
        try:
            if mode == ModeBlock:
                return self._apply_block()
            if mode == ModeCustom:
                return self._apply_custom()
            if mode == ModeChange:
                return self._apply_defaults_to_picked()
            self._apply_auto_update()
        except Exception as ex:
            nx.print_exception(ex)
        return True

    def apply(self) -> bool:
        if not self.ok():
            return False
        # buttonReset_Click: the picks cleared, the work part back.
        self._enter_mode()
        return True

    # ----- modes -----

    def _mode(self) -> str:
        return str(self.block("mode").ValueAsString)

    def _enter_mode(self) -> None:
        """The mode's picks and groups shown, everything cleared (buttonReset_Click), the mode's values loaded."""
        mode = self._mode()
        self.restore_work_part()
        self._frame = None
        for block_id in ("block_body", "custom_component", "components"):
            self.block(block_id).SetSelectedObjects([])
        nx.display_part().Views.Refresh()

        self.block("block_body").Show = mode == ModeBlock
        self.block("custom_component").Show = mode == ModeCustom
        self.block("custom_group").Show = mode == ModeCustom
        self.block("components").Show = mode in (ModeChange, ModeAutoUpdate)
        # A selection block's label is LabelString; setting Label throws 3520034.
        self.block("components").LabelString = "Components (none: the work part)" if mode == ModeAutoUpdate \
            else "Components"
        self.block("stock_group").Show = mode == ModeBlock
        self.block("burn_group").Show = mode == ModeBlock
        self.block("defaults_group").Show = mode in (ModeBlock, ModeChange)

        self._blank_values()
        if mode == ModeCustom:
            self._load_description()

    def _blank_values(self) -> None:
        """BlockAttStockBurn.ShowBlankDefaults, and the stock and burn values at their first items."""
        for block_id in ("add_x", "add_y", "add_z"):
            self.block(block_id).ValueAsString = AddStockItems[0]
        self.block("burnout").Value = False
        self.block("grind").Value = False
        self.block("tolerance").ValueAsString = self.lists.tolerances[0]
        self.block("tolerance").Enable = False
        self.block("burn_direction").ValueAsString = BurnNone
        self._fill_material_list(False)
        for block_id in ("material", "detail_name", "description"):
            self.set_string_value(self.block(block_id), "")
        for block_id in ("material_list", "detail_name_list", "description_list"):
            self.block(block_id).ValueAsString = _ListPrompt
        self.block("vendor").ValueAsString = _NoVendor
        self.block("wire_dev").ValueAsString = YesNoUnchanged
        self.block("wire_taper").ValueAsString = YesNoUnchanged
        self._set_notes(False, False)

    def _set_notes(self, dieset: bool, weldment: bool) -> None:
        self._dieset_on, self._weldment_on = dieset, weldment
        self.block("dieset").Value = dieset
        self.block("weldment").Value = weldment

    def _fill_material_list(self, burnout: bool) -> None:
        items = self.lists.burn_materials if burnout else self.lists.materials
        self.block("material_list").SetEnumMembers([_ListPrompt] + items)
        self.block("material_list").ValueAsString = _ListPrompt

    def _copy_list_pick(self, list_id: str, box_id: str) -> bool:
        """comboBoxDescription_SelectedIndexChanged: a menu pick goes into its box and the menu goes back to
        (list). True when something was copied."""
        picked = str(self.block(list_id).ValueAsString)
        if picked == _ListPrompt:
            return False
        self.set_string_value(self.block(box_id), picked)
        self.block(list_id).ValueAsString = _ListPrompt
        return True

    def restore_work_part(self) -> None:
        """The work part Select Block replaced, back (also called after the dialog closes)."""
        previous, self._previous_work = self._previous_work, None
        if previous is None:
            return
        try:
            nx.set_work_part(previous)
        except Exception as ex:
            nx.print_exception(ex)

    # ----- Select Block -----

    def _stock(self) -> List[float]:
        return [float(str(self.block(block_id).ValueAsString)) for block_id in ("add_x", "add_y", "add_z")]

    def _block_picked(self) -> None:
        """buttonSelectBlockComp_Click, with Stock and Burn's OnShow."""
        self.restore_work_part()
        self._frame = None
        self._blank_values()
        nx.display_part().Views.Refresh()

        bodies = [o for o in self.selected(self.block("block_body")) if isinstance(o, NXOpen.Body)]
        if not bodies:
            return
        try:
            frame = _Frame(cast(NXOpen.Body, bodies[0]))
            display = nx.display_part()
            if frame.component is not None and frame.part.PartUnits != display.PartUnits:
                nx.message_box("Caught exception : Select Block", NXOpen.NXMessageBox.DialogType.Error,
                               "Part units do not match")
                self.block("block_body").SetSelectedObjects([])
                return
            if not _expressions_readable(frame.part):
                self.block("block_body").SetSelectedObjects([])
                return
            if frame.component is not None:
                self._previous_work = nx.work_part()
                nx.set_work_component(frame.component)
            self._frame = frame
            self._load_block_values(frame.part)
            frame.draw(self._stock())
        except Exception as ex:
            nx.print_exception(ex)
            self.block("block_body").SetSelectedObjects([])

    def _redraw(self) -> None:
        if self._frame is None:
            return
        try:
            self._frame.draw(self._stock())
        except Exception as ex:
            nx.print_exception(ex)

    def _load_block_values(self, part: NXOpen.Part) -> None:
        """BlockAttStockBurn.OnShow"""
        for block_id, name in (("add_x", "AddX"), ("add_y", "AddY"), ("add_z", "AddZ")):
            expression = _last_expression(part, name)
            value = None if expression is None else expression.RightHandSide
            if value is not None and value not in AddStockItems:
                nx.print_("{}: {} = {} is not an Add Stock choice; the dialog shows {} and OK will write that."
                          .format(part.Leaf, name, value, AddStockItems[0]))
            self.block(block_id).ValueAsString = value if value in AddStockItems else AddStockItems[0]

        burnout = _string_value(part, "Burnout").lower() == "yes"
        grind = _string_value(part, "Grind").lower() == "yes"
        self.block("burnout").Value = burnout
        self.block("grind").Value = grind
        burn_dir = _string_value(part, "BurnDir").lower()
        self.block("burn_direction").ValueAsString = next(
            (item for item in BurnDirectionItems if item.lower() == burn_dir), BurnNone)
        tolerance = _string_value(part, "GrindTolerance")
        self.block("tolerance").ValueAsString = tolerance if tolerance in self.lists.tolerances \
            else self.lists.tolerances[0]
        self.block("tolerance").Enable = grind

        self._fill_material_list(burnout)
        self.set_string_value(self.block("material"), _attribute(part, "MATERIAL"))
        self.set_string_value(self.block("detail_name"), _attribute(part, "DETAIL NAME"))
        self.block("wire_dev").ValueAsString = self._yes_no(_attribute(part, "WFTD"))
        self.block("wire_taper").ValueAsString = self._yes_no(_attribute(part, "WTN"))
        self._set_notes(_string_value(part, "DiesetNote").lower() == "yes",
                        _string_value(part, "WeldmentNote").lower() == "yes")

    @staticmethod
    def _yes_no(value: str) -> str:
        """BlockAttStockBurn.SelectYesNo"""
        return next((item for item in YesNoItems[1:] if item.lower() == value.lower()), YesNoUnchanged)

    def _apply_block(self) -> bool:
        """BlockAttStockBurn.OnApply, then the form's Apply (UpdateBlockDescription)."""
        frame = self._frame
        if frame is None:
            self.message("Select the block body.")
            return False
        part = frame.part
        grind = bool(self.block("grind").Value)
        burn_dir = str(self.block("burn_direction").ValueAsString)

        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Stock and Burn")
        with nx.do_update("Expression"):
            stock = [str(self.block(block_id).ValueAsString) for block_id in ("add_x", "add_y", "add_z")]
            _set_add_stock(part, "AddX", stock[0])
            _set_add_stock(part, "AddY", stock[1])
            _set_add_stock(part, "AddZ", stock[2])
            _set_string(part, "Burnout", "yes" if self.block("burnout").Value else "no")
            _set_string(part, "Grind", "yes" if grind else "no")
            _set_string(part, "GrindTolerance", str(self.block("tolerance").ValueAsString) if grind else "none")
            _set_string(part, "BurnDir", "none" if burn_dir == BurnNone else burn_dir)
            self._write_defaults(part, bool(self.block("dieset").Value) != self._dieset_on,
                                 bool(self.block("weldment").Value) != self._weldment_on)
            turned_on = _turn_auto_update_on(part)
        self._set_notes(bool(self.block("dieset").Value), bool(self.block("weldment").Value))

        nx.print_("{}: add stock, burn settings and default attributes updated.".format(part.Leaf))
        if turned_on:
            nx.message_box("Stock and Burn", NXOpen.NXMessageBox.DialogType.Information,
                           "Auto Update has been turned on for {}.".format(part.Leaf))

        update_block_description(part)
        return True

    # ----- Default Attributes -----

    def _write_defaults(self, part: NXOpen.BasePart, write_dieset: bool, write_weldment: bool) -> None:
        """BlockAttStockBurn.WriteDefaultAttributes: blank boxes and Unchanged are left alone."""
        material_value = self.string_value(self.block("material"))
        if material_value == "" and self.block("vendor").ValueAsString != _NoVendor:
            material_value = str(self.block("vendor").ValueAsString)
        if material_value != "":
            nx.set_attribute(part, "MATERIAL", material_value)

        name = self.string_value(self.block("detail_name"))
        if name != "":
            nx.set_attribute(part, "DETAIL NAME", name)

        if self.block("wire_dev").ValueAsString != YesNoUnchanged:
            nx.set_attribute(part, "WFTD", str(self.block("wire_dev").ValueAsString))
        if self.block("wire_taper").ValueAsString != YesNoUnchanged:
            nx.set_attribute(part, "WTN", str(self.block("wire_taper").ValueAsString))

        if write_dieset:
            apply_description_note(part, "DiesetNote", "DIESET", bool(self.block("dieset").Value))
        if write_weldment:
            apply_description_note(part, "WeldmentNote", "WELDMENT", bool(self.block("weldment").Value))

    def _components(self) -> List[NXOpen.Assemblies.Component]:
        return components_of(self.selected(self.block("components")))

    def _picked_parts(self) -> List[NXOpen.Part]:
        """buttonSelectMultiple_Click: one component per display name, their prototypes."""
        by_name: Dict[str, NXOpen.Assemblies.Component] = {}
        for component in self._components():
            by_name.setdefault(component.DisplayName, component)
        parts: List[NXOpen.Part] = []
        for component in by_name.values():
            part = component.Prototype
            if isinstance(part, NXOpen.Part) and all(p.Tag != part.Tag for p in parts):
                parts.append(part)
        return parts

    def _load_notes_of_picked(self) -> None:
        """ShowBlankDefaults: Dieset / Weldment ticked when every picked part has the note on."""
        parts = self._picked_parts()
        self._set_notes(all(_string_value(p, "DiesetNote").lower() == "yes" for p in parts),
                        all(_string_value(p, "WeldmentNote").lower() == "yes" for p in parts))

    def _apply_defaults_to_picked(self) -> bool:
        """BlockAttStockBurn.ApplyDefaultsToAll"""
        parts = self._picked_parts()
        if not parts:
            self.message("Select the components.")
            return False
        write_dieset = bool(self.block("dieset").Value) != self._dieset_on
        write_weldment = bool(self.block("weldment").Value) != self._weldment_on
        written = 0

        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Default Attributes")
        with nx.do_update("Default Attributes"):
            for part in parts:
                try:
                    self._write_defaults(part, write_dieset, write_weldment)
                    written += 1
                except Exception as ex:
                    nx.print_exception(ex, part.Leaf)

        self._set_notes(bool(self.block("dieset").Value), bool(self.block("weldment").Value))
        nx.print_("Default attributes updated on {} of {} component(s).".format(written, len(parts)))
        return True

    # ----- Custom Description -----

    def _custom_target(self) -> NXOpen.Part:
        """UpdateCompAttributes: the picked component's part, else the display part (Reset made it the work part)."""
        picked = components_of(self.selected(self.block("custom_component")))
        if picked and isinstance(picked[0].Prototype, NXOpen.Part):
            return cast(NXOpen.Part, picked[0].Prototype)
        return nx.display_part()

    def _load_description(self) -> None:
        """LoadDescriptionAndMaterial: DESCRIPTION into the box ("NO DESCRIPTION" when blank)."""
        try:
            target = self._custom_target()
            if nx.has_attribute(target, "DESCRIPTION"):
                description = nx.get_attribute(target, "DESCRIPTION")
                self.set_string_value(self.block("description"), description if description != "" else
                                      "NO DESCRIPTION")
            else:
                self.set_string_value(self.block("description"), "")
        except Exception as ex:
            nx.print_exception(ex)

    def _apply_custom(self) -> bool:
        description = self.string_value(self.block("description"))
        if description == "":
            self.message("Enter a description.")
            return False
        target = self._custom_target()
        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Block Attributer")
        nx.set_attribute(target, "DESCRIPTION", description)
        if _has_dynamic_block(target):
            nx.message_box("Custom Description", NXOpen.NXMessageBox.DialogType.Warning,
                           "Block component = Auto Update Off")
        try:
            # SetAutoUpdateOff
            if _is_udo_auto_size(target):
                _set_auto_update(target, False)
        except Exception as ex:
            nx.print_exception(ex)
        return True

    # ----- Auto Update On -----

    def _apply_auto_update(self) -> None:
        """buttonSetAutoUpdateOn_Click: each picked component's part displayed in turn; none picked, the work part."""
        components = self._components()
        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Block Attributer")
        if not components:
            set_auto_update_on(nx.work_part())
            return

        with nx.display_part_reset(), nx.suppress_display():
            for component in components:
                try:
                    component.Unhighlight()
                    part = nx.prototype(component)
                    nx.set_display_part(part)
                    nx.set_work_part(part)
                    set_auto_update_on(part)
                except Exception as ex:
                    nx.print_exception(ex)


def main() -> None:
    """The block-att-dialog UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        dialog: Optional[_BlockAttDialog] = None
        try:
            dialog = _BlockAttDialog(title_with_version("Block Attributer"), _Lists())
            dialog.run()
        except Exception as ex:
            nx.print_exception(ex)
        finally:
            if dialog is not None:
                dialog.restore_work_part()
                nx.display_part().Views.Refresh()


if __name__ == "__main__":
    main()
