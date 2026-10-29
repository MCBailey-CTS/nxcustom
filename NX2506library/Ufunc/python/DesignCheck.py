"""
Python port of the design-check UFunc: the DesignCheck1 WinForms form (src\\UFuncs\\DesignCheck.cs) as a Block UI
Styler dialog (DesignCheck.dlx, built by tools\\make-dlx.py) over the Python validators (src\\python\\design_check*.py).

NOT ON THE MENU YET (2026-10-23): the design-check button still runs the C# form, which stays until this is confirmed
in NX. Run it with File -> Execute -> NX Open on this file. main() records the run (usage_db.run("design-check")).

The dialog is the form's tree and its Rerun and Erase buttons:
  - the checks' failures as check -> part -> Fail -> failure (sorted by text at every level, as the form's
    TreeViewNodeSorter did); BlockMaterialColor's passes / ignores under its Pass / Ignore nodes;
  - expanding a part node expands everything under it;
  - double click a node whose object is a part to make it the display part;
  - TrimSteelMaterial (a FixesFailures check): right click a failing part, or a failure under it, for
    "Set MATERIAL to {material}" - fixes them under an undo mark and removes the part node when all were fixed;
  - BlockMaterialColor (ListsPassedAndIgnored): clicking one of its part nodes (or a node under one) draws the part's
    stocked box at every visible occurrence, moves the WCS to its block and adds a datum csys at each occurrence (all
    erased when another part is clicked, Erase, Rerun or Close); a failing part's X / Y / Z nodes have a right-click
    menu of .125-1 that grows the drawn box along that axis and rechecks the part with the picked stock (green when it
    would pass); the part node's right-click Apply adds the picked stock to AddX / AddY / AddZ under one undo mark.

Ported from:
  - DesignCheck1 (RunChecks, AddFixMenus/FixPart, the click / expand / double-click handlers, ShowPart, ClearShown,
    AddStockMenus, PickStock, ApplyStock, RecheckPart, btnRerun_Click, btnErase_Click, FormClosed) -> _DesignCheckDialog
  - Static.DesignCheckOccurrences / ...IsVisible / ...BodyIsVisible / ...BlockFrame / ...ShowBoxLines /
    ...CreateCsyses / ...Delete / ...AddStock / ...RemoveBoxLines / ...ToAssembly           -> the module functions
  - Static.DesignCheckComparer                                                              -> _sort_key

Differences from the C#:
  - The dialog is modal: the model can still be rotated and zoomed with it open, but nothing else picked.
  - A WinForms ContextMenuStrip per node becomes the tree's OnMenu callback, which builds the node's menu when it is
    right clicked; Apply's text (with the picked totals) is worked out then, as the strip's Opening event did.
  - Node colors: a Block Styler node has a foreground color only (an NX color index), no background, so a passing
    part shows in green text with no green fill. The green is the palette's closest color to RGB (0, .5, 0), or 36.
  - Sorting is the culture-free (lowercase, text) order, where TreeNode.Text.CompareTo is culture sensitive.
  - The datum csyses are made with the display part as the work part (set and restored with nx.set_work_part), where
    the C# switched the work part context quietly (UF_ASSEM_set_work_part_context_quietly).
  - Each tree node carries an integer in its node data that keys its design_check.Item; Block Styler hands a callback
    a new Node object each time, so they cannot be compared directly.
  - The tree callbacks' Python signatures (select: tree, node, column, selected; menu: tree, node, column; menu
    selection: tree, node, menu item; default action: tree, node, column -> bool; expand: tree, node) are read from the
    NX C++ TreeListDemo sample, and the BlockStyler enums from the NXOpen_BlockStyler.pyd docstrings.
  - Rerun builds the validators again (TrimSteelMaterial / DescriptionNXAttribute / FolderLocations read the display
    part when made), where the form reused the array from Static.DesignCheckValidators each time - which also built
    them fresh, so the result is the same.

NEVER RUN IN NX, nor are the validators.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Tuple, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

_shared_python = os.path.join(os.path.dirname(_here), "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.BlockStyler  # noqa: E402
import NXOpen.Features  # noqa: E402
import NXOpen.Layer  # noqa: E402

import tsg_nx as nx  # noqa: E402
import design_check as dc  # noqa: E402
import design_check_material as material  # noqa: E402
from tsg_dialog import Dialog, title_with_version  # noqa: E402

# _UFunc ufunc name of the C# form
ufunc_design_check = "design-check"

# The BlockStyler enums the stubs lack (TreeNodeInsertOption, NodeExpandOption, TreeColumnResizePolicy).
_bs: Any = NXOpen.BlockStyler

# NX will not build a Block Styler dialog from inside some callbacks (a menu or toolbar launch, it seems).
_ErrorCannotLaunchDialog = 3520048

# The add-stock expressions, in X / Y / Z order (Static.DesignCheckAddNames).
AddNames = ["AddX", "AddY", "AddZ"]

# The amounts on an X / Y / Z node's menu, in inches (DesignCheck1.StockSteps).
StockSteps = [.125, .25, .375, .5, .625, .75, .875, 1.0]

# Menu item ids: the fix, Apply, and the stock picks (_MenuStock + axis * 10 + step index).
_MenuFix = 1
_MenuApply = 2
_MenuStock = 100

# The node data key that holds the node's Item id.
_ItemKey = "design_check_item"

_Column = 0


def _sort_key(item: dc.Item) -> Tuple[str, str]:
    """DesignCheckComparer - by text."""
    return item.text.lower(), item.text


def _green() -> int:
    """The palette color closest to RGB (0, .5, 0); 36 when NX will not say."""
    try:
        ufs: Any = nx.ufsession_
        # UF_DISP_rgb_model = 0, UF_DISP_CCM_EUCLIDEAN_DISTANCE = 0
        return int(ufs.Disp.AskClosestColor(0, [0.0, 0.5, 0.0], 0))
    except Exception:
        return 36


# ---------------------------------------------------------------------------------------------------
# Static.DesignCheck* - occurrences, the box lines, the datum csyses and the add-stock edit
# ---------------------------------------------------------------------------------------------------

def _layer_hidden(display: NXOpen.Part, layer: int) -> bool:
    return display.Layers.GetState(layer) == NXOpen.Layer.State.Hidden


def _layer1_solid_or_none(part: NXOpen.Part) -> Optional[NXOpen.Body]:
    return next((b for b in part.Bodies if b.IsSolidBody and b.Layer == 1), None)


def is_visible(display: NXOpen.Part, component: NXOpen.Assemblies.Component) -> bool:
    """Static.DesignCheckIsVisible: neither the component nor any above it (the root excepted) is blanked, on a layer
    hidden in the display part, or using the Empty reference set."""
    c: Optional[NXOpen.Assemblies.Component] = component
    while c is not None and c.Parent is not None:
        if c.IsBlanked:
            return False
        if _layer_hidden(display, c.Layer):
            return False
        if (c.ReferenceSet or "").lower() == "empty":
            return False
        c = c.Parent
    return True


def body_is_visible(display: NXOpen.Part, body: Optional[NXOpen.Body]) -> bool:
    """Static.DesignCheckBodyIsVisible: an occurrence body not blanked and not on a hidden layer."""
    return body is not None and not body.IsBlanked and not _layer_hidden(display, body.Layer)


def occurrences(display: NXOpen.Part, part: NXOpen.Part) -> List[Optional[NXOpen.Assemblies.Component]]:
    """Static.DesignCheckOccurrences: every loaded, unsuppressed, visible component of part in display whose
    layer-1 solid body (when there is one) is visible too; [None] when part is the display part itself."""
    if part.Tag == display.Tag:
        return [None]

    root = nx.root_component(display)
    if root is None:
        return []

    body = _layer1_solid_or_none(part)
    found: List[Optional[NXOpen.Assemblies.Component]] = []

    for component in nx.descendants(root, False):
        proto = component.Prototype
        if not isinstance(proto, NXOpen.Part) or proto.Tag != part.Tag:
            continue
        if not is_visible(display, component):
            continue
        if body is not None:
            occurrence = component.FindOccurrence(body)
            if not body_is_visible(display, occurrence if isinstance(occurrence, NXOpen.Body) else None):
                continue
        found.append(component)

    return found


def _read_block_builder(block: NXOpen.Features.Block) -> Tuple[NXOpen.Point3d, NXOpen.Matrix3x3]:
    """Block.__Origin / __Orientation: the block builder's origin and its X / Y axes as a matrix."""
    owner: Any = block.OwningPart
    builder = owner.Features.CreateBlockFeatureBuilder(block)
    try:
        origin = builder.Origin
        x_axis, y_axis = builder.GetOrientation()
        return origin, nx.matrix_from_axes(x_axis, y_axis)
    finally:
        builder.Destroy()


def _dynamic_block_or_none(part: NXOpen.Part) -> Optional[NXOpen.Features.Block]:
    """BasePart.__DynamicBlockOrNull - SingleOrDefault, so two DYNAMIC BLOCKs raise."""
    blocks = [f for f in part.Features if isinstance(f, NXOpen.Features.Block) and f.Name == "DYNAMIC BLOCK"]
    if len(blocks) > 1:
        raise RuntimeError("Sequence contains more than one matching element")
    return blocks[0] if blocks else None


def block_frame(part: NXOpen.Part) -> Optional[Tuple[NXOpen.Body, NXOpen.Point3d, NXOpen.Matrix3x3]]:
    """Static.DesignCheckBlockFrame: the layer-1 solid body and the frame its box is drawn in, in the part's own
    coordinates - the dynamic block's origin and orientation, else the body's minimum corner and the absolute axes.
    None (printed) when there is no such body."""
    body = _layer1_solid_or_none(part)

    if body is None:
        nx.print_("{}: no solid body on layer 1 to box".format(part.Leaf))
        return None

    block = _dynamic_block_or_none(part)
    if block is not None:
        origin, orientation = _read_block_builder(block)
    else:
        box = nx.body_box(body)
        origin, orientation = NXOpen.Point3d(box.MinX, box.MinY, box.MinZ), nx.identity_matrix()

    return body, origin, orientation


def _to_assembly_point(component: Optional[NXOpen.Assemblies.Component], local: NXOpen.Point3d,
                       translate: bool) -> NXOpen.Point3d:
    """Static.DesignCheckToAssembly: a point (or, translate False, a direction) in a component's part, in the
    assembly's coordinates; the orientation's rows are the component's X, Y and Z axes."""
    if component is None:
        return local

    position, o = component.GetPosition()
    sx, sy, sz = (position.X, position.Y, position.Z) if translate else (0.0, 0.0, 0.0)
    return NXOpen.Point3d(
        sx + local.X * o.Xx + local.Y * o.Yx + local.Z * o.Zx,
        sy + local.X * o.Xy + local.Y * o.Yy + local.Z * o.Zy,
        sz + local.X * o.Xz + local.Y * o.Yz + local.Z * o.Zz)


def _to_assembly_vector(component: Optional[NXOpen.Assemblies.Component], local: NXOpen.Vector3d) -> NXOpen.Vector3d:
    p = _to_assembly_point(component, NXOpen.Point3d(local.X, local.Y, local.Z), False)
    return NXOpen.Vector3d(p.X, p.Y, p.Z)


def show_box_lines(part: NXOpen.Part, extra_inches: Optional[List[float]] = None) -> int:
    """
    Static.DesignCheckShowBoxLines: at every visible occurrence of part in the display part, the temporary stocked box
    Block Attributer's Select Block previews (the layer-1 body's extent along the block axes plus AddX / AddY / AddZ,
    rounded up to 1/8", from the block origin, sizes labelled), grown by extra_inches (X / Y / Z, the stock picked but
    not applied). A view refresh clears them. Returns how many boxes were drawn.
    """
    display = nx.display_part()
    frame = block_frame(part)
    if frame is None:
        return 0
    body, origin, orientation = frame

    if part.PartUnits != display.PartUnits:
        nx.print_("{}: its units do not match {}'s".format(part.Leaf, display.Leaf))
        return 0

    to_display = 25.4 if display.PartUnits == NXOpen.BasePart.Units.Millimeters else 1.0
    drawn = 0

    for component in occurrences(display, part):
        try:
            occurrence = body if component is None else component.FindOccurrence(body)
            if not isinstance(occurrence, NXOpen.Body):
                continue

            box_origin = _to_assembly_point(component, origin, True)
            x_axis = _to_assembly_vector(component, nx.axis_x(orientation))
            y_axis = _to_assembly_vector(component, nx.axis_y(orientation))
            z_axis = _to_assembly_vector(component, nx.axis_z(orientation))

            size = material.stocked_block_size(occurrence, box_origin, x_axis, y_axis, part)

            if extra_inches is not None:
                for i in range(3):
                    size[i] += extra_inches[i] * to_display

            material.display_temporary_block_edges(box_origin, x_axis, y_axis, z_axis, size[0], size[1], size[2],
                                                   display)
            drawn += 1
        except Exception as ex:
            nx.print_exception(ex)

    return drawn


def _create_datum_csys(display: NXOpen.Part, origin: NXOpen.Point3d, matrix: NXOpen.Matrix3x3) -> NXOpen.NXObject:
    """BasePart.__CreateDatumCsys(origin, matrix) in the display part (which must be the work part)."""
    part: Any = display
    builder = part.Features.CreateDatumCsysBuilder(None)
    try:
        update = NXOpen.SmartObject.UpdateOption.WithinModeling
        xform = part.Xforms.CreateXform(origin, nx.axis_x(matrix), nx.axis_y(matrix), update, 1.0)
        builder.Csys = part.CoordinateSystems.CreateCoordinateSystem(xform, update)
        return builder.Commit()
    finally:
        builder.Destroy()


def create_csyses(part: NXOpen.Part) -> List[NXOpen.NXObject]:
    """
    Static.DesignCheckCreateCsyses: moves the display part's WCS to part's block origin and orientation as placed by its
    first occurrence (and leaves it there), and creates a datum csys in the display part at each occurrence's position
    and orientation, returned for deletion. The display part itself gets only the WCS.
    """
    display = nx.display_part()
    created: List[NXOpen.NXObject] = []
    found = occurrences(display, part)

    try:
        frame = block_frame(part) if found else None
        if frame is not None:
            _body, origin, orientation = frame
            first = found[0]
            x_axis = _to_assembly_vector(first, nx.axis_x(orientation))
            y_axis = _to_assembly_vector(first, nx.axis_y(orientation))
            display.WCS.SetOriginAndMatrix(_to_assembly_point(first, origin, True), nx.matrix_from_axes(x_axis, y_axis))
    except Exception as ex:
        nx.print_exception(ex)

    components = [c for c in found if c is not None]
    if not components:
        return created

    work = nx.work_part()
    try:
        if work.Tag != display.Tag:
            nx.set_work_part(display)
        for component in components:
            try:
                created.append(_create_datum_csys(display, nx.component_origin(component),
                                                  nx.component_orientation(component)))
            except Exception as ex:
                nx.print_exception(ex)
    finally:
        if work.Tag != display.Tag:
            nx.set_work_part(work)

    return created


def delete_shown(objects: List[NXOpen.NXObject]) -> None:
    """Static.DesignCheckDelete: deletes what create_csyses made, skipping anything already gone (an undo)."""
    for obj in objects:
        try:
            # tsg_nx's second delete_objects (a sequence) is the one Python keeps.
            cast(Any, nx.delete_objects)([obj])
        except Exception as ex:
            # An undo past the click already removed it.
            nx.print_("Design Check: could not delete a temporary csys: {}".format(ex))


def add_stock(part: NXOpen.Part, inches: List[float]) -> None:
    """Static.DesignCheckAddStock: adds inches (X / Y / Z) to part's AddX / AddY / AddZ, in the part's units, skipping
    the zeros, under one visible undo mark, and updates. Raises, before editing anything, when one is missing."""
    to_part = 25.4 if part.PartUnits == NXOpen.BasePart.Units.Millimeters else 1.0
    edits: List[Tuple[NXOpen.Expression, float]] = []

    for axis in range(3):
        if inches[axis] <= 0:
            continue
        name = AddNames[axis]
        add = nx.find_expression_or_null(part, name)
        if add is None:
            raise RuntimeError("{} has no {} expression".format(part.Leaf, name))
        edits.append((add, add.Value + inches[axis] * to_part))

    if not edits:
        return

    text = ", ".join("{} {}".format(expression.Name, _fmt(value, 3)) for expression, value in edits)
    session: Any = nx.session_
    mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Design Check: {}".format(text))

    work = nx.work_part()
    try:
        if work.Tag != part.Tag:
            nx.set_work_part(part)
        expressions: Any = part.Expressions
        for expression, value in edits:
            expressions.Edit(expression, _fmt(value, 6))
    finally:
        if work.Tag != part.Tag:
            nx.set_work_part(work)

    session.UpdateManager.DoUpdate(mark)


def remove_box_lines() -> None:
    """Static.DesignCheckRemoveBoxLines: a view refresh clears the temporary lines."""
    cast(Any, nx.display_part()).Views.Refresh()


def _fmt(value: float, places: int) -> str:
    """C# value.ToString("0.###...") with InvariantCulture."""
    text = "{:.{}f}".format(value, places).rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


# ---------------------------------------------------------------------------------------------------
# The dialog
# ---------------------------------------------------------------------------------------------------

class _DesignCheckDialog(Dialog):
    """DesignCheck1 - see the module docstring."""

    dlx_name = "DesignCheck.dlx"
    # Close only: closing is not a cancel.
    close_only = True

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__()
        self._tree: Any = None
        self._checked_part = nx.display_part()
        # Item id -> (Item, its tree node).
        self._items: Dict[int, dc.Item] = {}
        self._nodes: Dict[int, Any] = {}
        self._ids: Dict[int, int] = {}
        self._next_id = 1
        # The check items of the listing checks (BlockMaterialColor) and the fixing checks, by item id.
        self._box_line_checks: Dict[int, dc.Check] = {}
        self._fixers: Dict[int, dc.FixesFailures] = {}
        # The part whose box lines and csyses are showing, and the csyses made for it.
        self._shown_part: Optional[NXOpen.Part] = None
        self._shown_objects: List[NXOpen.NXObject] = []
        # The stock picked per part tag, inches X / Y / Z, not applied yet - kept across clicks, Erase and Rerun.
        self._picked_stock: Dict[Any, List[float]] = {}
        self._expanding_all = False
        self._default_color: Optional[int] = None
        self._green = _green()

    # ----- Dialog -----

    def initialize(self) -> None:
        self._tree = self.block("tree")
        self._tree.SetOnSelectHandler(self._on_select)
        self._tree.SetOnMenuHandler(self._on_menu)
        self._tree.SetOnMenuSelectionHandler(self._on_menu_selection)
        self._tree.SetOnExpandHandler(self._on_expand)
        self._tree.SetOnDefaultActionHandler(self._on_default_action)

    def shown(self) -> None:
        self._tree.InsertColumn(_Column, "Design Check", 640)
        self._tree.SetColumnResizePolicy(_Column, _bs.TreeColumnResizePolicy.ResizeWithTree)
        self._run_checks()

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        if block == self.block("rerun"):
            self._rerun()
        elif block == self.block("erase"):
            self._clear_shown()

    def closed(self) -> None:
        """DesignCheck1_FormClosed: erase what is shown."""
        self._clear_shown()

    # ----- the tree -----

    def _run_checks(self) -> None:
        """RunChecks: clears the tree and fills it from a fresh run over the display part."""
        try:
            self._clear_shown()
            self._clear_tree()

            display = nx.display_part()
            for check_run in dc.run(display, dc.validators(display)):
                self._insert(check_run.node, None)
                check_id = self._id_of(check_run.node)

                if isinstance(check_run.check, dc.FixesFailures):
                    self._fixers[check_id] = check_run.check

                if not isinstance(check_run.check, dc.ListsPassedAndIgnored):
                    continue

                self._box_line_checks[check_id] = check_run.check

                # A part with stock still picked from before the rerun shows its result with that stock.
                for part_item in [c for c in check_run.node.children if isinstance(c.obj, NXOpen.Part)]:
                    if part_item.obj.Tag in self._picked_stock:
                        self._recheck_part(part_item)
        except Exception as ex:
            nx.print_exception(ex)

    def _clear_tree(self) -> None:
        for item_id, item in list(self._items.items()):
            if item.parent is None:
                try:
                    self._tree.DeleteNode(self._nodes[item_id])
                except Exception as ex:
                    nx.print_exception(ex)
        self._items.clear()
        self._nodes.clear()
        self._ids.clear()
        self._box_line_checks.clear()
        self._fixers.clear()

    def _insert(self, item: dc.Item, parent_node: Any) -> None:
        """Adds item and everything under it to the tree, each level sorted by text."""
        node = self._tree.CreateNode(item.text)
        self._tree.InsertNode(node, parent_node, None, _bs.TreeNodeInsertOption.Last)

        item_id = self._next_id
        self._next_id += 1
        self._items[item_id] = item
        self._nodes[item_id] = node
        self._ids[id(item)] = item_id

        data = node.GetNodeData()
        try:
            data.AddInteger(_ItemKey, item_id)
        finally:
            data.Dispose()

        if self._default_color is None:
            self._default_color = int(node.ForegroundColor)

        for child in sorted(item.children, key=_sort_key):
            self._insert(child, node)

    def _delete(self, item: dc.Item) -> None:
        """Removes item (and everything under it) from the tree and the maps."""
        item_id = self._id_of(item)
        self._tree.DeleteNode(self._nodes[item_id])
        for gone in item.walk():
            gone_id = self._ids.pop(id(gone), None)
            if gone_id is not None:
                self._items.pop(gone_id, None)
                self._nodes.pop(gone_id, None)

    def _id_of(self, item: dc.Item) -> int:
        return self._ids[id(item)]

    def _item_of(self, node: Any) -> Optional[dc.Item]:
        if node is None:
            return None
        data = node.GetNodeData()
        try:
            return self._items.get(int(data.GetInteger(_ItemKey)))
        except Exception:
            return None
        finally:
            data.Dispose()

    def _check_of(self, item: dc.Item) -> Optional[dc.Check]:
        root_id = self._ids.get(id(item.root()))
        if root_id is None:
            return None
        return self._box_line_checks.get(root_id) or self._fixers.get(root_id)

    def _expand_all(self, item: dc.Item) -> None:
        self._expanding_all = True
        try:
            for under in item.walk():
                node = self._nodes.get(self._ids.get(id(under), -1))
                if node is not None and under.children:
                    node.Expand(_bs.NodeExpandOption.Expand)
        finally:
            self._expanding_all = False

    # ----- tree callbacks -----

    def _on_select(self, tree: Any, node: Any, column: int, selected: bool) -> None:
        """NodeMouseClick: clicking a part node under a listing check, or a node under it, shows that part."""
        try:
            if not selected:
                return
            item = self._item_of(node)
            if item is None or self._ids.get(id(item.root())) not in self._box_line_checks:
                return
            part_item = _part_item(item)
            if part_item is not None:
                self._show_part(part_item.obj)
        except Exception as ex:
            nx.print_exception(ex)

    def _on_default_action(self, tree: Any, node: Any, column: int) -> bool:
        """NodeMouseDoubleClick: a node whose object is a part makes it the display part."""
        try:
            item = self._item_of(node)
            if item is not None and isinstance(item.obj, NXOpen.Part):
                nx.set_display_part(item.obj)
        except Exception as ex:
            nx.print_exception(ex)
        return True

    def _on_expand(self, tree: Any, node: Any) -> None:
        """AfterExpand: expanding a part node expands everything under it."""
        try:
            if self._expanding_all:
                return
            item = self._item_of(node)
            if item is not None and isinstance(item.obj, NXOpen.Part):
                self._expand_all(item)
        except Exception as ex:
            nx.print_exception(ex)

    def _on_menu(self, tree: Any, node: Any, column: int) -> None:
        """The node's right-click menu: a fix (FixesFailures), the stock picks (an X / Y / Z node) or Apply."""
        try:
            item = self._item_of(node)
            if item is None:
                return

            entries = self._menu_entries(item)
            if not entries:
                return

            menu = tree.CreateMenu()
            try:
                for menu_id, text, enabled in entries:
                    menu.AddMenuItem(menu_id, text)
                    if not enabled:
                        menu.SetItemDisable(menu_id, True)
                tree.SetMenu(menu)
            finally:
                menu.Dispose()
        except Exception as ex:
            nx.print_exception(ex)

    def _menu_entries(self, item: dc.Item) -> List[Tuple[int, str, bool]]:
        check = self._check_of(item)

        if isinstance(check, dc.FixesFailures):
            part_item = self._fix_part_item(item)
            if part_item is not None and _failures(part_item):
                return [(_MenuFix, check.fix_text, True)]
            return []

        if isinstance(check, dc.ListsPassedAndIgnored):
            part_item = self._stock_part_item(item)
            if part_item is None:
                return []
            if item is part_item:
                part: NXOpen.Part = part_item.obj
                picked = ["{} +{}".format(AddNames[axis], _fmt(self._picked(part, axis), 3))
                          for axis in range(3) if self._picked(part, axis) > 0]
                return [(_MenuApply, "Apply ({})".format(", ".join(picked)) if picked else "Apply", bool(picked))]
            if item.name in AddNames and item.parent is not None and item.parent.parent is part_item:
                axis = AddNames.index(item.name)
                return [(_MenuStock + axis * 10 + index, _step_text(step), True)
                        for index, step in enumerate(StockSteps)]

        return []

    def _on_menu_selection(self, tree: Any, node: Any, menu_item: int) -> None:
        try:
            item = self._item_of(node)
            if item is None:
                return
            check = self._check_of(item)

            if menu_item == _MenuFix and isinstance(check, dc.FixesFailures):
                part_item = self._fix_part_item(item)
                if part_item is not None:
                    self._fix_part(check, part_item)
            elif menu_item == _MenuApply:
                part_item = self._stock_part_item(item)
                if part_item is not None:
                    self._apply_stock(part_item)
            elif menu_item >= _MenuStock:
                part_item = self._stock_part_item(item)
                axis, index = divmod(menu_item - _MenuStock, 10)
                if part_item is not None and 0 <= axis < 3 and 0 <= index < len(StockSteps):
                    self._pick_stock(part_item, axis, StockSteps[index])
        except Exception as ex:
            nx.print_exception(ex)

    # ----- fixes (AddFixMenus / FixPart) -----

    @staticmethod
    def _fix_part_item(item: dc.Item) -> Optional[dc.Item]:
        """The failing part node a fix menu is on (AddFixMenus put it on the part node and each failure under its
        Fail node), or None."""
        top = _top_item(item)
        if top is None or not isinstance(top.obj, NXOpen.Part):
            return None
        return top if item is top or item in _failures(top) else None

    def _fix_part(self, fixer: dc.FixesFailures, part_item: dc.Item) -> None:
        """FixPart: fixes every failure under the part under one undo mark; removes the part node when all were
        fixed (a failure whose fix raised is printed and the node stays)."""
        session: Any = nx.session_
        session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Design Check: {}".format(fixer.fix_text))
        all_fixed = True

        for failure in _failures(part_item):
            try:
                fixer.fix(failure.obj)
            except Exception as ex:
                all_fixed = False
                nx.print_exception(ex)

        if all_fixed:
            self._delete(part_item)
            part_item.remove()

    # ----- stock (ShowPart / AddStockMenus / PickStock / ApplyStock / RecheckPart) -----

    @staticmethod
    def _stock_part_item(item: dc.Item) -> Optional[dc.Item]:
        """The part node straight under the listing check node that item is or sits under - AddStockMenus only went on
        those (failing or rechecked parts), not on the Pass / Ignore entries."""
        top = _top_item(item)
        return top if top is not None and isinstance(top.obj, NXOpen.Part) else None

    def _picked(self, part: NXOpen.Part, axis: int) -> float:
        picked = self._picked_stock.get(part.Tag)
        return picked[axis] if picked is not None else 0.0

    def _show_part(self, part: NXOpen.Part) -> None:
        """ShowPart: another part clears the one showing, moves the WCS and adds the occurrence csyses; then the box
        lines are redrawn, grown by the stock picked for the part."""
        try:
            if self._shown_part is None or self._shown_part.Tag != part.Tag:
                self._clear_shown()
                self._shown_part = part
                self._shown_objects = create_csyses(part)

            remove_box_lines()
            show_box_lines(part, self._picked_stock.get(part.Tag))
        except Exception as ex:
            nx.print_exception(ex)

    def _clear_shown(self) -> None:
        """ClearShown: deletes the showing part's csyses and clears the box lines; the picked stock is kept."""
        if self._shown_part is None:
            return
        try:
            delete_shown(self._shown_objects)
            remove_box_lines()
        except Exception as ex:
            nx.print_exception(ex)
        finally:
            self._shown_part = None
            self._shown_objects = []

    def _pick_stock(self, part_item: dc.Item, axis: int, inches: float) -> None:
        """PickStock: adds inches to the stock picked along axis, redraws, and rechecks the part with it."""
        part: NXOpen.Part = part_item.obj
        picked = self._picked_stock.setdefault(part.Tag, [0.0, 0.0, 0.0])
        picked[axis] += inches
        self._show_part(part)
        self._recheck_part(part_item)

    def _apply_stock(self, part_item: dc.Item) -> None:
        """ApplyStock: adds the picked stock to the Add expressions (one undo mark), forgets it, rechecks the part and
        erases the lines and csyses, as Erase does."""
        part: NXOpen.Part = part_item.obj
        inches = [self._picked(part, axis) for axis in range(3)]

        if all(amount <= 0 for amount in inches):
            return

        try:
            add_stock(part, inches)
            self._picked_stock.pop(part.Tag, None)
            self._recheck_part(part_item)
        except Exception as ex:
            nx.print_exception(ex)
        finally:
            self._clear_shown()

    def _recheck_part(self, part_item: dc.Item) -> None:
        """RecheckPart: the part node's result from a fresh run of its check (with the picked stock, if any), in
        place; a pass turns it green, and its text says whether it passes."""
        check = self._box_line_checks.get(self._ids.get(id(part_item.root()), -1))
        if check is None:
            return

        part: NXOpen.Part = part_item.obj
        picked = self._picked_stock.get(part.Tag)
        has_picked = picked is not None and any(amount > 0 for amount in picked)

        if has_picked and isinstance(check, material.BlockMaterialColor):
            result, node = check.check_with_stock(part, picked)  # type: Tuple[str, Optional[dc.Item]]
        else:
            result, node = check.check(part)

        passes = result == dc.Result.Pass
        tree_node = self._nodes[self._id_of(part_item)]
        tree_node.ForegroundColor = self._green if passes else (self._default_color or 0)

        if not has_picked:
            text = part.Leaf + (" - passes" if passes else "")
        else:
            text = part.Leaf + (" - passes with picked stock" if passes else " - still fails with picked stock")
        part_item.text = text
        tree_node.SetColumnDisplayText(_Column, text)

        for child in list(part_item.children):
            self._delete(child)
        part_item.clear()

        if node is not None:
            part_item.add(node)
            self._insert(node, tree_node)

        self._expand_all(part_item)

    # ----- buttons -----

    def _rerun(self) -> None:
        """btnRerun_Click: displays the part the dialog was opened on again (when still open) and reruns."""
        try:
            if any(p.Tag == self._checked_part.Tag for p in nx.session_.Parts):
                if nx.display_part().Tag != self._checked_part.Tag:
                    nx.set_display_part(self._checked_part)
        except Exception as ex:
            nx.print_exception(ex)

        self._run_checks()


def _part_item(item: dc.Item) -> Optional[dc.Item]:
    """The nearest item carrying a part: item itself, or the part node it sits under."""
    current: Optional[dc.Item] = item
    while current is not None and not isinstance(current.obj, NXOpen.Part):
        current = current.parent
    return current


def _top_item(item: dc.Item) -> Optional[dc.Item]:
    """The item straight under item's check node (the part node, Pass or Ignore), or None for the check node."""
    if item.parent is None:
        return None
    top = item
    while top.parent is not None and top.parent.parent is not None:
        top = top.parent
    return top


def _failures(part_item: dc.Item) -> List[dc.Item]:
    """The failure items under a part node's Fail node."""
    return [failure for child in part_item.children if child.text == dc.Result.Fail for failure in child.children]


def _step_text(amount: float) -> str:
    """amount.ToString(amount < 1 ? ".000" : "0")"""
    return "{:.3f}".format(amount)[1:] if amount < 1 else "{:.0f}".format(amount)


def _run() -> None:
    """DesignCheck1's constructor and Show: the dialog over a run on the display part."""
    title = "Design Check"

    try:
        dialog = _DesignCheckDialog(title_with_version(title))
        try:
            dialog.run()
        finally:
            dialog.closed()
    except NXOpen.NXException as ex:
        if ex.ErrorCode != _ErrorCannotLaunchDialog:
            raise
        nx.print_exception(ex)
        nx.show_error("NX would not open the {} dialog (error {} - it will not create a dialog from inside a "
                      "callback).\n\nTry running it from File -> Execute -> NX Open rather than from a menu or "
                      "toolbar button.".format(title, _ErrorCannotLaunchDialog))


def main() -> None:
    """The design-check UFunc. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_design_check):
        try:
            _run()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
