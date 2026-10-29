"""
Python ports of the NewCompBuild (component-builder) form's block-edit buttons (src\\UFuncs\\NewCompBuild.cs). The
form stays C#; each button keeps its selection, its checks and its control enabling, and calls a method here through
    PythonLibrary.Execute("NewCompBuildEdit.py", "NewCompBuildEdit", "<method>", args...)

Button -> method(s):
    Update Session      none - UpdateForm only refreshes the form's controls (form title, detail-number text box, the
                        name / material lists) and reads NX; it makes no NX change, so it stays C#.
    Dynamic / Move      begin_component_edit / create_edit_data, reset_non_block_error. The position loop stays C#:
                        it is a UF_UI_specify_screen_position drag with a native motion callback (MotionCallback),
                        which Python cannot hand NX.
    Match               edit_match. Its C# body hard-codes `flag = false`, so the only path that runs is the
                        "Analysis --> Units does not match the session units" error; the unreachable match branch
                        (and MoveComponent / NewMethod10 / NewMethod52, which only it calls) is not ported.
    Edit Size           begin_component_edit, edit_size, create_edit_data. The C# still throws
                        NotImplementedException after them (EditSizeLoop was never written), so that throw stays in C#.
    Align               edit_align
    Align Component     align_component
    Align Edge Distance work_part_emphasis_off, align_edge_distance, restore_display
    (shared)            set_disp_units, update_dynamic_block

C# <-> Python state. Session.Execute returns nothing, so the form's edit state is handed over through NX:
  - in:  the form passes its _workCompOrigin / _workCompOrientation as twelve doubles (ox, oy, oz, xx .. zz) and,
         where the C# reads its _workPart field, that part.
  - out: every method that takes the twelve doubles ends with the display part's WCS on the edit csys it finished
         with, and the edge-rep lines (XBASE1 .. ZBASE4) are lines in the display part. The form reads both back
         (ReloadEditState) - _edgeRepLines, _workCompOrigin, _workCompOrientation, and the upr/lwr parallel fields
         for its own UpdateDynamicBlock.
  The form keeps _isNewSelection, _updateComponent and _editBody, and decides the "not a block component" branch
  itself (the prototype's DYNAMIC BLOCK count, which is what the C# tested after setting the work component).

Differences from the C#:
  - The WCS is left on the edit csys at the end of a call (see above; begin_component_edit only when it found a
    DYNAMIC BLOCK). The C# left it wherever it was when an Align Component / Align Edge Distance press picked no
    handle on a reused selection (e.g. on the work view after a Move).
  - The form is hidden for the whole align loop, the first handle pick included (the C# hid it after the first pick),
    and shown again after the call - also on the Align "Invalid input" return, where the C# left it hidden.
    Error boxes raised inside the loop therefore show before the form comes back, not after.
  - The offset prompt (Align Edge Distance, and Align with an offset) is UF_UI_ask_string_input on the cue line
    instead of the .NET NXInputBox (not available in Python): default "0.004", OK accepts it; anything that is not
    an optionally signed decimal number (the NumberStyles the C# allowed) counts as invalid, as does cancel.
    AskStringInput is assumed to take the default as a plain str and to return (str, length, response), and
    PointConstruct (baseMethod, pointTag, basePt, response), per the pyd docstrings; neither has been run in NX.
  - The block size comes from UF_MODL_ask_block_parms (BlockFeatureBuilder.Length/Width/Height are None in Python);
    the C# reads of the builder's unused Length/Width/Height RightHandSide strings are dropped.
  - The EDIT BLOCK builder leaves out BooleanOption.SetTargetBodies(new Body[] { null }); the
    SetBooleanOperationAndTarget(Create, None) after it is kept.
  - When the work part has no dynamic block, update_dynamic_block called from the form reads the upr/lwr parallel
    expressions from the component's prototype (the display part with no component) - the part the C# SetWcs*
    read them from - instead of carrying them over from the previous CreateEditData.
  - EDITCSYS csys are collected before any is deleted (the C# deleted inside its foreach).
  - Python cannot register a UDO class. The form calls DynamicHandle.GetDynamicHandle() first so UdoDynamicHandle is
    registered; run without that, the handles are skipped with a print.

Kept as the C# has them (they look like bugs; don't fix them here):
  - On a new selection the loops search the form's _workPart - the component's prototype - for the handle points and
    edge-rep lines, while CreateEditData makes them in the display part. Later presses search the display part.
  - SetWcsWorkComponent returns with the prototype still displayed when it has no single DYNAMIC BLOCK.
  - begin_component_edit suppresses the display and nothing on the "not a block component" path turns it back on.
  - The first builder in CreateEditData is left undestroyed when a block dimension is under .001.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any, List, Optional, Sequence, Tuple, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.Features  # noqa: E402
import NXOpen.GeometricUtilities  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402

# The stubs cover only part of what this module uses, so the session objects go through Any.
_ses: Any = nx.session_
_ufs: Any = nx.ufsession_
_uf: Any = NXOpen.UF
_ufc: Any = NXOpen.UF.UFConstants

# NXOpen.UF.UFConstants (NX 2306).
_UF_CSYS_ROOT_COORDS = 1
_UF_CSYS_WORK_COORDS = 2
_UF_CSYS_ROOT_WCS_COORDS = 3
_UF_DISP_SUPPRESS_DISPLAY = 0
_UF_DISP_UNSUPPRESS_DISPLAY = 1
_UF_UI_OK = 2
_UF_UI_FROM_CUSTOM = 1

# UF_UI_ask_string_input responses: 3 = OK (accept the default), 5 = data entered.
_AskStringAccepted = (3, 5)

# NumberStyles.AllowLeadingSign | AllowDecimalPoint.
_OffsetPattern = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)$")

# The twelve edge-rep lines CreateBlockLines makes, in creation order.
_EdgeRepLineNames = ("XBASE1", "YBASE1", "ZBASE1", "XBASE2", "YBASE2", "XCEILING1", "YCEILING1",
                     "XCEILING2", "YCEILING2", "ZBASE2", "ZBASE3", "ZBASE4")

_DynamicHandleClass = "UdoDynamicHandle"

# SmartObject.VisibilityOption.Visible (not in the stubs).
_Visible: Any = cast(Any, NXOpen.SmartObject).VisibilityOption.Visible


class _EditState(object):
    """The form statics the edit methods read and write: _workCompOrigin, _workCompOrientation, _edgeRepLines and
    the upr/lwr parallel fields."""

    def __init__(self, origin: Any, orientation: Any) -> None:
        self.origin = origin
        self.orientation = orientation
        self.edge_rep_lines: List[Any] = _find_edge_rep_lines()
        self.is_upr_parallel = False
        self.is_lwr_parallel = False
        self.parallel_height_exp = ""
        self.parallel_width_exp = ""


class NewCompBuildEdit(object):

    # -----------------------------------------------------------------------------------------------
    # Shared steps
    # -----------------------------------------------------------------------------------------------

    @staticmethod
    def set_disp_units() -> None:
        """Static.NewCompBuildSetDispUnits(disp.PartUnits) - the NX half of the form's SetDispUnits()."""
        _set_disp_units()

    @staticmethod
    def reset_non_block_error() -> None:
        """The NX half of NewCompBuild.ResetNonBlockError (the form keeps EnableForm and its fields)."""
        _reset_non_block_error()

    @staticmethod
    def work_part_emphasis_off() -> None:
        """The two preference writes at the top of ButtonAlignEdgeDistance_Click."""
        _work_part_emphasis_off()

    @staticmethod
    def restore_display() -> None:
        """UF_DISP_set_display(UNSUPPRESS) + regenerate - the tail of ButtonAlignEdgeDistance_Click."""
        _restore_display()

    @staticmethod
    def begin_component_edit(component: Any, work_component_given: bool,
                             ox: float, oy: float, oz: float,
                             xx: float, xy: float, xz: float,
                             yx: float, yy: float, yz: float,
                             zx: float, zy: float, zz: float) -> None:
        """
        The new-selection block every edit button repeats: suppress the display, make the component the work
        component, then CreateEditData once per DYNAMIC BLOCK in its prototype. work_component_given picks how the
        work component is set, as each button's C# did: True is worc_ (Current refset, Given: Align Component), False is
        Parts.SetWorkComponent(component, out status) (Dynamic, Move, Edit Size, Align, Align Edge Distance).
        """
        state = _state_from_args(_component_or_none(component), ox, oy, oz, xx, xy, xz, yx, yy, yz, zx, zy, zz)
        # With no DYNAMIC BLOCK nothing is edited and the C# left the WCS alone, so this does too.
        if _begin_component_edit(component, work_component_given, state):
            _leave_wcs_on_edit_csys(state)

    @staticmethod
    def create_edit_data(component: Any,
                         ox: float, oy: float, oz: float,
                         xx: float, xy: float, xz: float,
                         yx: float, yy: float, yz: float,
                         zx: float, zy: float, zz: float) -> None:
        """NewCompBuild.CreateEditData; component "" = none."""
        comp = _component_or_none(component)
        state = _state_from_args(comp, ox, oy, oz, xx, xy, xz, yx, yy, yz, zx, zy, zz)
        try:
            _create_edit_data(comp, state)
        finally:
            _leave_wcs_on_edit_csys(state)

    @staticmethod
    def update_dynamic_block(component: Any,
                             ox: float, oy: float, oz: float,
                             xx: float, xy: float, xz: float,
                             yx: float, yy: float, yz: float,
                             zx: float, zy: float, zz: float) -> None:
        """NewCompBuild.UpdateDynamicBlock (+ DeleteHandles); component "" = none. Also what Apply runs."""
        comp = _component_or_none(component)
        state = _state_from_args(comp, ox, oy, oz, xx, xy, xz, yx, yy, yz, zx, zy, zz)
        try:
            _update_dynamic_block(comp, state)
        finally:
            _leave_wcs_on_edit_csys(state)

    # -----------------------------------------------------------------------------------------------
    # Buttons
    # -----------------------------------------------------------------------------------------------

    @staticmethod
    def edit_match() -> None:
        """
        ButtonEditMatch_Click as it runs: its `flag` is hard-coded false, so it always ends in the units error.
        The form keeps UpdateSessionParts / buttonApply / EnableForm.
        """
        try:
            _set_disp_units()
            _restore_display()
            _message("Caught exception : Match Block", NXOpen.NXMessageBox.DialogType.Error,
                     "Analysis --> Units does not match the session units")
        except NXOpen.NXException as ex:
            _message("Caught exception : Match Block", NXOpen.NXMessageBox.DialogType.Error, str(ex))
            _restore_display()

    @staticmethod
    def edit_size(component: Any,
                  ox: float, oy: float, oz: float,
                  xx: float, xy: float, xz: float,
                  yx: float, yy: float, yz: float,
                  zx: float, zy: float, zz: float) -> None:
        """ButtonEditSize_Click's block path for a component: UpdateDynamicBlock then CreateEditData. The form then
        disables itself and throws NotImplementedException, as the C# does."""
        comp = _component_or_none(component)
        state = _state_from_args(comp, ox, oy, oz, xx, xy, xz, yx, yy, yz, zx, zy, zz)
        try:
            _update_dynamic_block(comp, state)
            _create_edit_data(comp, state)
        except NXOpen.NXException as ex:
            _message("Caught exception - Edit Size", NXOpen.NXMessageBox.DialogType.Error, str(ex))
            _restore_display()
        finally:
            _leave_wcs_on_edit_csys(state)

    @staticmethod
    def edit_align(component: Any, specify_offset: bool, work_part_field: Any,
                   ox: float, oy: float, oz: float,
                   xx: float, xy: float, xz: float,
                   yx: float, yy: float, yz: float,
                   zx: float, zy: float, zz: float) -> None:
        """
        NewCompBuild.EditAlign from UpdateDynamicBlock on (the selection and the "not a block component" branch stay
        in the form): UpdateDynamicBlock + CreateEditData, then pick a handle / a reference point until the handle
        pick is cancelled, moving that face of the edit block onto the point (less the offset when specify_offset).
        work_part_field is the form's _workPart.
        """
        comp = _component_or_none(component)
        state = _state_from_args(comp, ox, oy, oz, xx, xy, xz, yx, yy, yz, zx, zy, zz)
        try:
            _edit_align(comp, specify_offset, work_part_field, state)
        except NXOpen.NXException as ex:
            _message("Caught exception - Edit Align", NXOpen.NXMessageBox.DialogType.Error, str(ex))
            _restore_display()
        finally:
            _leave_wcs_on_edit_csys(state)

    @staticmethod
    def align_component(component: Any, work_part_field: Any,
                        ox: float, oy: float, oz: float,
                        xx: float, xy: float, xz: float,
                        yx: float, yy: float, yz: float,
                        zx: float, zy: float, zz: float) -> None:
        """
        ButtonAlignComponent_Click's handle loop: pick a handle, pick a reference point, move every named X/Y/Z point
        and line of the form's _workPart by the handle-to-point distance along that axis, then update the block and
        rebuild the edit data. Ends when the handle pick is cancelled.
        """
        comp = _component_or_none(component)
        state = _state_from_args(comp, ox, oy, oz, xx, xy, xz, yx, yy, yz, zx, zy, zz)
        try:
            _align_component(comp, work_part_field, state)
        except NXOpen.NXException as ex:
            _message("Caught exception - Edit Align Component", NXOpen.NXMessageBox.DialogType.Error, str(ex))
            _restore_display()
        finally:
            _leave_wcs_on_edit_csys(state)

    @staticmethod
    def align_edge_distance(component: Any, work_part_field: Any,
                            ox: float, oy: float, oz: float,
                            xx: float, xy: float, xz: float,
                            yx: float, yy: float, yz: float,
                            zx: float, zy: float, zz: float) -> None:
        """ButtonAlignEdgeDistance_Click's handle loop: like Align, with an offset prompt after each reference point."""
        comp = _component_or_none(component)
        state = _state_from_args(comp, ox, oy, oz, xx, xy, xz, yx, yy, yz, zx, zy, zz)
        try:
            _align_edge_distance(comp, work_part_field, state)
        except Exception as ex:
            nx.print_exception(ex)
        finally:
            _leave_wcs_on_edit_csys(state)


# ---------------------------------------------------------------------------------------------------
# Arguments / state
# ---------------------------------------------------------------------------------------------------

def _component_or_none(component: Any) -> Optional[NXOpen.Assemblies.Component]:
    """Session.Execute cannot pass null - the form sends "" for no component."""
    if component is None or isinstance(component, str):
        return None
    return component


def _matrix(xx: float, xy: float, xz: float, yx: float, yy: float, yz: float,
            zx: float, zy: float, zz: float) -> Any:
    matrix: Any = NXOpen.Matrix3x3()
    matrix.Xx, matrix.Xy, matrix.Xz = xx, xy, xz
    matrix.Yx, matrix.Yy, matrix.Yz = yx, yy, yz
    matrix.Zx, matrix.Zy, matrix.Zz = zx, zy, zz
    return matrix


def _state_from_args(component: Optional[NXOpen.Assemblies.Component],
                     ox: float, oy: float, oz: float,
                     xx: float, xy: float, xz: float,
                     yx: float, yy: float, yz: float,
                     zx: float, zy: float, zz: float) -> _EditState:
    state = _EditState(NXOpen.Point3d(ox, oy, oz), _matrix(xx, xy, xz, yx, yy, yz, zx, zy, zz))
    # The parallel fields the last SetWcs* left behind: read from the part it read them from.
    part: Any = nx.prototype(component) if component is not None else nx.display_part()
    _read_parallel_flags(part, state)
    _set_parallels(state)
    return state


def _leave_wcs_on_edit_csys(state: _EditState) -> None:
    """Hand _workCompOrigin / _workCompOrientation back to the form (it reads the WCS)."""
    try:
        nx.display_part().WCS.SetOriginAndMatrix(state.origin, state.orientation)
    except Exception as ex:
        nx.print_exception(ex)


def _find_edge_rep_lines() -> List[Any]:
    """_edgeRepLines - CreateBlockLine makes them in the display part (the work part is the display part then)."""
    disp: Any = nx.display_part()
    if disp is None:
        return []
    found = [line for line in disp.Lines if line.Name in _EdgeRepLineNames]
    return sorted(found, key=lambda line: _EdgeRepLineNames.index(line.Name))


# ---------------------------------------------------------------------------------------------------
# Small ports
# ---------------------------------------------------------------------------------------------------

def _message(title: str, dialog_type: Any, text: str) -> None:
    nx.message_box(title, dialog_type, text)


def _set_disp_units() -> None:
    """Static.NewCompBuildSetDispUnits(disp.PartUnits)"""
    disp: Any = nx.display_part()
    defaults: Any = NXOpen.UnitCollection.UnitDefaults
    if disp.PartUnits == NXOpen.BasePart.Units.Millimeters:
        disp.UnitCollection.SetDefaultDataEntryUnits(defaults.GMmNDegC)
        disp.UnitCollection.SetDefaultObjectInformationUnits(defaults.GMmNDegC)
    else:
        disp.UnitCollection.SetDefaultDataEntryUnits(defaults.LbmInLbfDegF)
        disp.UnitCollection.SetDefaultObjectInformationUnits(defaults.LbmInLbfDegF)


def _reset_non_block_error() -> None:
    """ResetNonBlockError minus EnableForm and the form fields."""
    _ufs.Disp.RegenerateDisplay()
    _ses.Preferences.EmphasisVisualization.WorkPartEmphasis = True
    _ses.Preferences.Assemblies.WorkPartDisplayAsEntirePart = False
    nx.set_work_part(nx.display_part())


def _work_part_emphasis_off() -> None:
    _ses.Preferences.EmphasisVisualization.WorkPartEmphasis = False
    _ses.Preferences.Assemblies.WorkPartDisplayAsEntirePart = False


def _restore_display() -> None:
    _ufs.Disp.SetDisplay(_UF_DISP_UNSUPPRESS_DISPLAY)
    _ufs.Disp.RegenerateDisplay()


def _translucency(obj: Any, translucency: int) -> None:
    """DisplayableObject.__Translucency"""
    _ufs.Obj.SetTranslucency(obj.Tag, translucency)
    obj.RedisplayObject()


def _map_point(input_csys: int, point: Sequence[float], output_csys: int) -> List[float]:
    """UF_CSYS_map_point"""
    return [float(v) for v in _ufs.Csys.MapPoint(input_csys, [float(point[0]), float(point[1]), float(point[2])],
                                                  output_csys)]


def _p3(values: Sequence[float]) -> NXOpen.Point3d:
    return NXOpen.Point3d(values[0], values[1], values[2])


def _coords(point: Any) -> List[float]:
    c = point.Coordinates
    return [c.X, c.Y, c.Z]


def _map_acs_to_wcs(point: Any) -> List[float]:
    """Point3d.__MapAcsToWcs"""
    return _map_point(_UF_CSYS_ROOT_COORDS, [point.X, point.Y, point.Z], _UF_CSYS_ROOT_WCS_COORDS)


def _map_wcs_to_acs(values: Sequence[float]) -> NXOpen.Point3d:
    """Point3d.__MapWcsToAcs"""
    return _p3(_map_point(_UF_CSYS_ROOT_WCS_COORDS, values, _UF_CSYS_ROOT_COORDS))


def _add_axis(values: List[float], axis: int, distance: float) -> List[float]:
    """Point3d.__AddX / __AddY / __AddZ"""
    result = list(values)
    result[axis] += distance
    return result


def _dynamic_blocks(part: Any) -> List[Any]:
    """BasePart.__DynamicBlocks"""
    return [f for f in part.Features.GetFeatures()
            if isinstance(f, NXOpen.Features.Block) and f.Name == "DYNAMIC BLOCK"]


def _dynamic_block_or_none(part: Any) -> Any:
    """BasePart.__DynamicBlockOrNull - SingleOrDefault, so a second DYNAMIC BLOCK throws."""
    blocks = _dynamic_blocks(part)
    if len(blocks) > 1:
        raise RuntimeError("Sequence contains more than one matching element")
    return blocks[0] if blocks else None


def _block_sizes(part: Any, block: Any) -> Tuple[float, float, float]:
    """BlockFeatureBuilder.Length/Width/Height.Value - through UF_MODL_ask_block_parms, since the builder's
    Length/Width/Height are None in Python."""
    values = []
    for parm in _ufs.ModlFeatures.AskBlockParms(block.Tag, 0):
        values.append(float(part.Expressions.FindObject(parm.split("=", 1)[0].strip()).Value))
    return values[0], values[1], values[2]


def _create_temp_csys(origin: Any, x_axis: Any, y_axis: Any) -> Any:
    """The UF_MTX3_initialize / UF_CSYS_create_matrix / UF_CSYS_create_temp_csys triplet SetWcs* use."""
    values = _ufs.Mtx3.Initialize([x_axis.X, x_axis.Y, x_axis.Z], [y_axis.X, y_axis.Y, y_axis.Z])
    matrix_tag = _ufs.Csys.CreateMatrix(list(values))
    csys_tag = _ufs.Csys.CreateTempCsys([origin.X, origin.Y, origin.Z], matrix_tag)
    return nx.tagged_object(csys_tag)


def _move_objects(objects: Sequence[Any], distance: float, delta_xyz: str, state: _EditState) -> None:
    """Static.NewCompBuildMoveObjects"""
    try:
        if abs(distance) < 0.001:
            return
        nx.display_part().WCS.SetOriginAndMatrix(state.origin, state.orientation)
        work: Any = nx.work_part()
        builder: Any = work.BaseFeatures.CreateMoveObjectBuilder(None)
        try:
            gu: Any = NXOpen.GeometricUtilities
            motion = builder.TransformMotion
            motion.DistanceAngle.OrientXpress.AxisOption = gu.OrientXpressBuilder.Axis.Passive
            motion.DistanceAngle.OrientXpress.PlaneOption = gu.OrientXpressBuilder.Plane.Passive
            motion.OrientXpress.AxisOption = gu.OrientXpressBuilder.Axis.Passive
            motion.OrientXpress.PlaneOption = gu.OrientXpressBuilder.Plane.Passive
            motion.Option = gu.ModlMotion.Options.DeltaXyz
            motion.DeltaEnum = gu.ModlMotion.Delta.ReferenceWcsWorkPart
            text = nx.cs_double_str(distance)
            if delta_xyz == "X":
                motion.DeltaXc.RightHandSide = text
                motion.DeltaYc.RightHandSide = "0"
                motion.DeltaZc.RightHandSide = "0"
            if delta_xyz == "Y":
                motion.DeltaXc.RightHandSide = "0"
                motion.DeltaYc.RightHandSide = text
                motion.DeltaZc.RightHandSide = "0"
            if delta_xyz == "Z":
                motion.DeltaXc.RightHandSide = "0"
                motion.DeltaYc.RightHandSide = "0"
                motion.DeltaZc.RightHandSide = text
            builder.ObjectToMoveObject.Add(list(objects))
            builder.Commit()
        finally:
            builder.Destroy()
    except Exception as ex:
        nx.print_exception(ex)


# ---------------------------------------------------------------------------------------------------
# Dynamic handles (DynamicHandle.cs / AutoSizeComponent.CreateDynamicHandleUdo)
# ---------------------------------------------------------------------------------------------------

def _dynamic_handle_class() -> Any:
    """DynamicHandle.GetDynamicHandle - None (with a print) when UdoDynamicHandle is not registered, since only C#
    can register it."""
    try:
        return _ses.UserDefinedClassManager.GetUserDefinedClassFromClassName(_DynamicHandleClass)
    except NXOpen.NXException as ex:
        if ex.ErrorCode != nx.ErrorUdoClassNotRegistered:
            raise
        nx.print_("{} is not registered in this session - no dynamic handles.".format(_DynamicHandleClass))
        return None


def _hide_dynamic_handles() -> None:
    """DynamicHandle.HideDynamicHandles"""
    try:
        udo_class = _dynamic_handle_class()
        if udo_class is None:
            return
        work: Any = nx.work_part()
        current = work.UserDefinedObjectManager.GetUdosOfClass(udo_class)
        if len(current) == 0:
            return
        for udo in current:
            udo.SetIntegers([0])
        for point in work.Points:
            if point.Name != "":
                point.Blank()
    except Exception as ex:
        nx.print_exception(ex)


def _show_dynamic_handles() -> None:
    """DynamicHandle.ShowDynamicHandles"""
    try:
        udo_class = _dynamic_handle_class()
        if udo_class is None:
            return
        work: Any = nx.work_part()
        current = work.UserDefinedObjectManager.GetUdosOfClass(udo_class)
        if len(current) == 0:
            return
        for udo in current:
            udo.SetIntegers([1])
            _ufs.Disp.AddItemToDisplay(udo.Tag)
        work_layer = nx.display_part().Layers.WorkLayer
        for point in work.Points:
            if point.Name != "" and point.Layer == work_layer:
                point.SetVisibility(_Visible)
                point.RedisplayObject()
    except Exception as ex:
        nx.print_exception(ex)


def _create_point(coordinates: Sequence[float], name: str) -> Any:
    """Static.NewCompBuildCreatePoint - work_.CreatePoint (visible), named, on the display part's work layer."""
    work: Any = nx.work_part()
    point = work.Points.CreatePoint(_p3(coordinates))
    point.SetVisibility(_Visible)
    point.SetName(name)
    nx.set_layer(point, nx.display_part().Layers.WorkLayer)
    return point


def _create_point_blk_origin() -> None:
    """Static.NewCompBuildCreatePointBlkOrigin"""
    work: Any = nx.work_part()
    point = work.Points.CreatePoint(nx.display_part().WCS.Origin)
    point.SetVisibility(_Visible)
    point.Blank()
    point.SetName("BLKORIGIN")
    nx.set_layer(point, nx.display_part().Layers.WorkLayer)


def _create_udo(udo: Any, point_on_face: Sequence[float], name: str) -> None:
    """AutoSizeComponent.CreateUdo"""
    point = _create_point(point_on_face, name)
    udo.SetName(name)
    udo.SetDoubles([float(v) for v in point_on_face])
    udo.SetIntegers([0])
    udo_types: Any = NXOpen.UserDefinedObjects.UserDefinedObject
    link = udo_types.LinkDefinition()
    link.AssociatedObject = point
    link.Status = udo_types.LinkStatus.UpToDate
    udo.SetLinks(udo_types.LinkType.Type1, [link])


def _round(values: Sequence[float], digits: int = 10) -> List[float]:
    return [round(float(v), digits) for v in values]


def _create_dynamic_handle_udo(edit_body: Any) -> None:
    """AutoSizeComponent.CreateDynamicHandleUdo - a handle UDO + named point on each face whose normal is a WCS
    axis, then the BLKORIGIN point. Does nothing when the work part already has handle UDOs."""
    try:
        udo_class = _dynamic_handle_class()
        if udo_class is None:
            return
        work: Any = nx.work_part()
        if len(work.UserDefinedObjectManager.GetUdosOfClass(udo_class)) != 0:
            return
        manager = work.UserDefinedObjectManager
        for face in edit_body.GetFaces():
            udo = manager.CreateUserDefinedObject(udo_class)
            matrix = nx.display_part().WCS.CoordinateSystem.Orientation.Element
            _face_type, point_on_face, direction, _box, _radius, _rad_data, _norm_dir = \
                _ufs.Modeling.AskFaceData(face.Tag)
            direction = _round(direction)
            x = _round([matrix.Xx, matrix.Xy, matrix.Xz])
            y = _round([matrix.Yx, matrix.Yy, matrix.Yz])
            z = _round([matrix.Zx, matrix.Zy, matrix.Zz])
            neg_x = [-v for v in x]
            neg_y = [-v for v in y]
            neg_z = [-v for v in z]
            for axis, name in ((x, "POSX"), (y, "POSY"), (z, "POSZ"), (neg_x, "NEGX"), (neg_y, "NEGY"),
                               (neg_z, "NEGZ")):
                if _ufs.Vec3.IsEqual(direction, axis, 0.00) == 1:
                    _create_udo(udo, point_on_face, name)
        _create_point_blk_origin()
    except Exception as ex:
        nx.print_exception(ex)


def _show_temporary_size_text(edge_rep_lines: Sequence[Any]) -> None:
    """Static.NewCompBuildShowTemporarySizeText"""
    disp: Any = nx.display_part()
    disp.Views.Refresh()
    inches = disp.PartUnits == NXOpen.BasePart.Units.Inches
    for line in edge_rep_lines:
        if line.Name in ("XBASE1", "YBASE1", "ZBASE1"):
            length = round(line.GetLength(), 3)
            text = "{:.3f}".format(length if inches else length / 25.4)
            color: Any = _uf.Obj.DispProps()
            color.Color = 31
            start, end = line.StartPoint, line.EndPoint
            middle = [(start.X + end.X) / 2.0, (start.Y + end.Y) / 2.0, (start.Z + end.Z) / 2.0]
            mapped = _map_point(_UF_CSYS_WORK_COORDS, middle, _UF_CSYS_ROOT_COORDS)
            _ufs.Disp.DisplayTemporaryText(disp.Views.WorkView.Tag, _uf.Disp.ViewType.USE_WORK_VIEW, [text], mapped,
                                           _uf.Disp.TextRef.MIDDLECENTER, color, 0.125 if inches else 3.175, 1)


# ---------------------------------------------------------------------------------------------------
# Edit lines / WCS (CreateBlockLines, SetWcs*, DeleteHandles)
# ---------------------------------------------------------------------------------------------------

def _create_block_line(start: NXOpen.Point3d, end: NXOpen.Point3d, name: str, state: _EditState) -> None:
    """NewCompBuild.CreateBlockLine"""
    work: Any = nx.work_part()
    line = work.Curves.CreateLine(start, end)
    line.SetName(name)
    nx.set_color(line, 7)
    state.edge_rep_lines.append(line)


def _create_block_lines(origin: NXOpen.Point3d, length: float, width: float, height: float,
                        state: _EditState) -> None:
    """NewCompBuild.CreateBlockLines"""
    wcs1 = _map_acs_to_wcs(origin)
    absolute1 = _map_wcs_to_acs(_add_axis(wcs1, 0, length))
    _create_block_line(origin, absolute1, "XBASE1", state)
    absolute2 = _map_wcs_to_acs(_add_axis(wcs1, 1, width))
    _create_block_line(origin, absolute2, "YBASE1", state)
    absolute3 = _map_wcs_to_acs(_add_axis(wcs1, 2, height))
    _create_block_line(origin, absolute3, "ZBASE1", state)
    absolute4 = _map_wcs_to_acs(_add_axis(_map_acs_to_wcs(absolute2), 0, length))
    _create_block_line(absolute2, absolute4, "XBASE2", state)
    _create_block_line(absolute1, absolute4, "YBASE2", state)
    wcs2 = _map_acs_to_wcs(absolute3)
    absolute5 = _map_wcs_to_acs(_add_axis(wcs2, 0, length))
    _create_block_line(absolute3, absolute5, "XCEILING1", state)
    absolute6 = _map_wcs_to_acs(_add_axis(wcs2, 1, width))
    _create_block_line(absolute3, absolute6, "YCEILING1", state)
    absolute7 = _map_wcs_to_acs(_add_axis(_map_acs_to_wcs(absolute6), 0, length))
    _create_block_line(absolute6, absolute7, "XCEILING2", state)
    _create_block_line(absolute5, absolute7, "YCEILING2", state)
    _create_block_line(absolute1, absolute5, "ZBASE2", state)
    _create_block_line(absolute2, absolute6, "ZBASE3", state)
    _create_block_line(absolute4, absolute7, "ZBASE4", state)


def _read_parallel_flags(part: Any, state: _EditState) -> None:
    """SetParallelExpressions"""
    for expression in part.Expressions:
        if expression.Name == "uprParallel":
            state.is_upr_parallel = "yes" in expression.RightHandSide
        if expression.Name == "lwrParallel":
            state.is_lwr_parallel = "yes" in expression.RightHandSide


def _set_parallels(state: _EditState) -> None:
    """SetParallels"""
    if state.is_upr_parallel:
        state.parallel_height_exp = "uprParallelHeight"
        state.parallel_width_exp = "uprParallelWidth"
    if not state.is_lwr_parallel:
        return
    state.parallel_height_exp = "lwrParallelHeight"
    state.parallel_width_exp = "lwrParallelWidth"


def _set_wcs_to_work_part(component: Optional[NXOpen.Assemblies.Component], state: _EditState) -> None:
    """NewCompBuild.SetWcsToWorkPart"""
    try:
        if component is None:
            _set_wcs_display_part(state)
        else:
            _set_wcs_work_component(component, state)
    except Exception as ex:
        nx.print_exception(ex)


def _set_wcs_display_part(state: _EditState) -> None:
    """NewCompBuild.SetWcsDisplayPart"""
    state.is_upr_parallel = False
    state.is_lwr_parallel = False
    state.parallel_height_exp = ""
    work: Any = nx.work_part()
    _read_parallel_flags(work, state)
    block = _dynamic_block_or_none(work)
    if block is None:
        return
    builder = work.Features.CreateBlockFeatureBuilder(block)
    origin = builder.Origin
    _set_parallels(state)
    x_axis, y_axis = builder.GetOrientation()
    csys = _create_temp_csys(origin, x_axis, y_axis)
    nx.display_part().WCS.SetOriginAndMatrix(csys.Origin, csys.Orientation.Element)
    state.origin = csys.Origin
    state.orientation = csys.Orientation.Element


def _set_wcs_work_component(component: NXOpen.Assemblies.Component, state: _EditState) -> None:
    """NewCompBuild.SetWcsWorkComponent"""
    try:
        display_part = nx.display_part()
        nx.set_display_part(nx.prototype(component))
        state.is_upr_parallel = False
        state.is_lwr_parallel = False
        state.parallel_height_exp = ""
        state.parallel_width_exp = ""
        work: Any = nx.work_part()
        _read_parallel_flags(work, state)
        block = _dynamic_block_or_none(work)
        if block is None:
            return
        builder = work.Features.CreateBlockFeatureBuilder(block)
        origin = builder.Origin
        _set_parallels(state)
        x_axis, y_axis = builder.GetOrientation()
        csys1 = _create_temp_csys(origin, x_axis, y_axis)
        disp: Any = nx.display_part()
        disp.WCS.SetOriginAndMatrix(csys1.Origin, csys1.Orientation.Element)
        csys2 = disp.WCS.Save()
        csys2.SetName("EDITCSYS")
        csys2.Layer = 254
        body_refset: Any = nx.find_reference_set_or_null(disp, "BODY")
        if body_refset is not None:
            body_refset.AddObjectsToReferenceSet([csys2])
        nx.set_display_part(display_part)
        nx.set_work_component(component)
        work = nx.work_part()
        edit_csyses = [c for c in work.CoordinateSystems if c.Layer == 254 and c.Name == "EDITCSYS"]
        for csys3 in edit_csyses:
            occurrence = _ses.Parts.WorkComponent.FindOccurrence(csys3)
            if occurrence is not None:
                nx.display_part().WCS.SetOriginAndMatrix(occurrence.Origin, occurrence.Orientation.Element)
                state.origin = occurrence.Origin
                state.orientation = occurrence.Orientation.Element
            mark = _ses.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "")
            _ses.UpdateManager.AddToDeleteList(csys3)
            _ses.UpdateManager.DoUpdate(mark)
            _ses.DeleteUndoMark(mark, "")
    except Exception as ex:
        nx.print_exception(ex)


def _delete_handles(state: _EditState) -> None:
    """NewCompBuild.DeleteHandles"""
    with nx.do_update():
        _dynamic_handle_class()
        work: Any = nx.work_part()
        for point in work.Points:
            if point.Name != "":
                _ses.UpdateManager.AddToDeleteList(point)
        for line in state.edge_rep_lines:
            _ses.UpdateManager.AddToDeleteList(line)
    state.edge_rep_lines.clear()


# ---------------------------------------------------------------------------------------------------
# CreateEditData / UpdateDynamicBlock
# ---------------------------------------------------------------------------------------------------

def _create_edit_data(component: Optional[NXOpen.Assemblies.Component], state: _EditState) -> None:
    """NewCompBuild.CreateEditData - 75% translucent, WCS on the dynamic block, then a temporary EDIT BLOCK at the
    WCS whose faces give the handle UDOs, the twelve edge-rep lines and the size text. The EDIT BLOCK is deleted."""
    with nx.suppress_display():
        try:
            if component is not None:
                _translucency(component, 75)
            else:
                work0: Any = nx.work_part()
                for body in work0.Bodies:
                    if body.Layer == 1:
                        _translucency(body, 75)
            _set_wcs_to_work_part(component, state)
            work: Any = nx.work_part()
            block = _dynamic_block_or_none(work)
            if block is None:
                return
            builder1 = work.Features.CreateBlockFeatureBuilder(block)
            line_length, line_width, line_height = _block_sizes(work, block)
            disp: Any = nx.display_part()
            nx.set_work_part(disp)
            if abs(line_length) < 0.001 or abs(line_width) < 0.001 or abs(line_height) < 0.001:
                return
            builder2 = disp.Features.CreateBlockFeatureBuilder(None)
            builder2.BooleanOption.Type = NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Create
            builder2.Type = NXOpen.Features.BlockFeatureBuilder.Types.OriginAndEdgeLengths
            origin = disp.WCS.Origin
            builder2.SetOriginAndLengths(origin, nx.cs_double_str(line_length), nx.cs_double_str(line_width),
                                         nx.cs_double_str(line_height))
            builder2.SetBooleanOperationAndTarget(NXOpen.Features.Feature.BooleanType.Create, None)
            feature = builder2.CommitFeature()
            feature.SetName("EDIT BLOCK")
            bodies = feature.GetBodies()
            _create_block_lines(origin, line_length, line_width, line_height, state)
            builder1.Destroy()
            builder2.Destroy()
            work_now: Any = nx.work_part()
            work_now.FacetedBodies.DeleteTemporaryFacesAndEdges()
            _create_dynamic_handle_udo(bodies[0])
            _show_dynamic_handles()
            _show_temporary_size_text(state.edge_rep_lines)
            mark = _ses.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "")
            _ses.UpdateManager.AddToDeleteList(feature)
            _ses.UpdateManager.DoUpdate(mark)
            _ses.DeleteUndoMark(mark, "")
        except Exception as ex:
            nx.print_exception(ex)


def _update_dynamic_block(component: Optional[NXOpen.Assemblies.Component], state: _EditState) -> None:
    """NewCompBuild.UpdateDynamicBlock - opaque again, then the dynamic block is re-sized from the edge-rep lines and
    re-originated on BLKORIGIN; the handles and lines are deleted."""
    with nx.display_part_reset():
        try:
            work: Any = nx.work_part()
            if component is not None:
                _translucency(component, 0)
            else:
                for body in work.Bodies:
                    if body.Layer == 1:
                        _translucency(body, 0)
            point3d = [0.0, 0.0, 0.0]
            length_expression = ""
            width_expression = ""
            height_expression = ""
            for point in work.Points:
                if point.Name == "BLKORIGIN":
                    point3d = _coords(point)
            for line in state.edge_rep_lines:
                if line.Name == "XBASE1":
                    length_expression = nx.cs_double_str(line.GetLength())
                if line.Name == "YBASE1":
                    width_expression = nx.cs_double_str(line.GetLength())
                if line.Name == "ZBASE1":
                    height_expression = nx.cs_double_str(line.GetLength())
            if state.is_upr_parallel:
                width_expression = state.parallel_height_exp
                height_expression = state.parallel_width_exp
            if state.is_lwr_parallel:
                width_expression = state.parallel_height_exp
                height_expression = state.parallel_width_exp
            nx.display_part().WCS.SetOriginAndMatrix(_p3(point3d), state.orientation)
            state.origin = _p3(point3d)
            nx.set_work_component(component)
            mapped = _p3(_map_point(_UF_CSYS_ROOT_COORDS, point3d, _UF_CSYS_WORK_COORDS))
            work = nx.work_part()
            block = _dynamic_block_or_none(work)
            if block is None:
                return
            builder = work.Features.CreateBlockFeatureBuilder(block)
            try:
                origin_point = work.Points.CreatePoint(mapped)
                origin_point.SetCoordinates(mapped)
                builder.OriginPoint = origin_point
                builder.SetOriginAndLengths(mapped, length_expression, width_expression, height_expression)
                builder.CommitFeature()
            finally:
                builder.Destroy()
            nx.set_work_part(nx.display_part())
            _delete_handles(state)
            disp: Any = nx.display_part()
            disp.WCS.Visibility = True
            disp.Views.Refresh()
        except Exception as ex:
            nx.print_exception(ex)


def _begin_component_edit(component: Any, work_component_given: bool, state: _EditState) -> bool:
    """Returns whether CreateEditData ran (the C#'s `flag`)."""
    comp = _component_or_none(component)
    _ufs.Disp.SetDisplay(_UF_DISP_SUPPRESS_DISPLAY)
    _set_work_component(comp, work_component_given)
    blocks = _dynamic_blocks(nx.work_part())
    for _block in blocks:
        _create_edit_data(comp, state)
    return len(blocks) > 0


def _set_work_component(component: Optional[NXOpen.Assemblies.Component], work_component_given: bool) -> None:
    """worc_ = component (Current / Given), or the C#'s Parts.SetWorkComponent(component, out status)."""
    if work_component_given:
        nx.set_work_component(component)
        return
    load_status = _ses.Parts.SetWorkComponent(component)
    if load_status is not None:
        load_status.Dispose()


# ---------------------------------------------------------------------------------------------------
# Handle / point picks
# ---------------------------------------------------------------------------------------------------

def _select_handle_point() -> List[Any]:
    """Ui.Selection.SelectHandlePoint - one point in the work part, or [] on cancel."""
    mask = NXOpen.Selection.MaskTriple(_ufc.UF_point_type, _ufc.UF_point_subtype, 0)
    result: Any = NXOpen.UI.GetUI().SelectionManager.SelectTaggedObject(
        "Select Point",
        "Select Point",
        NXOpen.Selection.SelectionScope.WorkPart,
        NXOpen.Selection.SelectionAction.ClearAndEnableSpecific,
        False,
        False,
        [mask])
    response, obj = result[0], result[1]
    r: Any = NXOpen.Selection.Response
    if response in (r.Ok, r.ObjectSelected, r.ObjectSelectedByName) and isinstance(obj, NXOpen.Point):
        return [obj]
    return []


def _point_construct(cue: str) -> Tuple[int, List[float]]:
    """Ui.Selection.PointConstruct (inferred, UI locked) - (response, absolute coordinates)."""
    _ufs.Ui.LockUgAccess(_UF_UI_FROM_CUSTOM)
    try:
        _method, _point_tag, base_pt, response = _ufs.Ui.PointConstruct(cue, _uf.Ui.PointBaseMethod.POINT_INFERRED)
    finally:
        _ufs.Ui.UnlockUgAccess(_UF_UI_FROM_CUSTOM)
    return int(response), [float(v) for v in base_pt]


def _ask_offset() -> Optional[float]:
    """NXInputBox.ParseInputNumber("Enter offset value", "Enter offset value", 0.004, ...) - None when cancelled
    or not a number."""
    result: Any = _ufs.Ui.AskStringInput("Enter offset value", "0.004")
    text, response = result[0], result[-1]
    if isinstance(text, (list, tuple)):
        text = text[0] if len(text) > 0 else ""
    if int(response) not in _AskStringAccepted:
        return None
    text = str(text)
    if _OffsetPattern.match(text) is None:
        return None
    return float(text)


def _handle_prototype(handle: Any) -> Any:
    return handle.Prototype if handle.IsOccurrence else handle


def _lines_named(state: _EditState, *names: str) -> List[Any]:
    return [line for line in state.edge_rep_lines if line.Name in names]


def _split_points(point_prototype: Any, part: Any) -> Tuple[List[Any], List[Any], List[Any]]:
    """Static.NewCompBuildNewMethod - (doNotMovePts, movePtsHalf, movePtsFull): the named points of part that stay,
    move half the distance, and move with the handle. BLKORIGIN stays for a POS handle and moves for a NEG one."""
    do_not_move: List[Any] = []
    half: List[Any] = []
    full: List[Any] = []
    is_pos = "POS" in point_prototype.Name
    handle = point_prototype.Name
    for point in part.Points:
        name = point.Name
        if name == "":
            continue
        if "X" in name and "X" in handle:
            do_not_move.append(point)
        elif "Y" in name and "Y" in handle:
            do_not_move.append(point)
        elif "Z" in name and "Z" in handle:
            do_not_move.append(point)
        elif "BLKORIGIN" in name:
            (do_not_move if is_pos else full).append(point)
        else:
            half.append(point)
    full.append(point_prototype)
    return do_not_move, half, full


# Per handle: (axis index, delta letter, the lines that move with the handle face, end or start point moves).
_HandleMoves = {
    "POSX": (0, "X", ("YBASE2", "YCEILING2", "ZBASE2", "ZBASE4"), True),
    "NEGX": (0, "X", ("YBASE1", "YCEILING1", "ZBASE1", "ZBASE3"), False),
    "POSY": (1, "Y", ("XBASE2", "XCEILING2", "ZBASE3", "ZBASE4"), True),
    "NEGY": (1, "Y", ("XBASE1", "XCEILING1", "ZBASE1", "ZBASE2"), False),
    "POSZ": (2, "Z", ("XCEILING1", "XCEILING2", "YCEILING1", "YCEILING2"), True),
    "NEGZ": (2, "Z", ("XBASE1", "XBASE2", "YBASE1", "YBASE2"), False),
}


def _stretch_axis_lines(state: _EditState, axis: int, letter: str, use_end: bool, distance: float) -> None:
    """The `foreach (line in all{x|y|z}AxisLines)` blocks: move the end (POS) or start (NEG) of every edge-rep line
    whose name starts with the axis letter by distance along that WCS axis."""
    for line in [ln for ln in state.edge_rep_lines if ln.Name.startswith(letter)]:
        if use_end:
            line.SetEndPoint(_map_wcs_to_acs(_add_axis(_map_acs_to_wcs(line.EndPoint), axis, distance)))
        else:
            line.SetStartPoint(_map_wcs_to_acs(_add_axis(_map_acs_to_wcs(line.StartPoint), axis, distance)))


def _rebuild_after_move(component: Optional[NXOpen.Assemblies.Component], work_component_given: bool,
                        state: _EditState) -> Any:
    """The tail of each loop pass: UpdateDynamicBlock, display suppressed, the component back as work component
    (worc_ for Align, Parts.SetWorkComponent for Align Component - as the C# loops do), CreateEditData. Returns the
    new _workPart."""
    _update_dynamic_block(component, state)
    _ufs.Disp.SetDisplay(_UF_DISP_SUPPRESS_DISPLAY)
    _set_work_component(component, work_component_given)
    work_part_field = nx.work_part()
    _create_edit_data(component, state)
    return work_part_field


# ---------------------------------------------------------------------------------------------------
# Button loops
# ---------------------------------------------------------------------------------------------------

def _align_component(component: Optional[NXOpen.Assemblies.Component], work_part_field: Any,
                     state: _EditState) -> None:
    """ButtonAlignComponent_Click from the first SelectHandlePoint on."""
    point_list = _select_handle_point()
    while len(point_list) == 1:
        _hide_dynamic_handles()
        point1 = _handle_prototype(point_list[0])
        objects: List[Any] = []
        for point in work_part_field.Points:
            name = point.Name
            if "X" in name or "Y" in name or "Z" in name or "BLKORIGIN" in name:
                objects.append(point)
        for line in work_part_field.Lines:
            name = line.Name
            if "X" in name or "Y" in name or "Z" in name:
                objects.append(line)
        response, picked = _point_construct("Select Reference Point")
        if response == _UF_UI_OK:
            output_point1 = _map_point(_UF_CSYS_ROOT_COORDS, picked, _UF_CSYS_ROOT_WCS_COORDS)
            output_point2 = _map_point(_UF_CSYS_ROOT_COORDS, _coords(point1), _UF_CSYS_ROOT_WCS_COORDS)
            move = _HandleMoves.get(point1.Name)
            if move is not None:
                axis, letter = move[0], move[1]
                distance = abs(output_point2[axis] - output_point1[axis])
                if output_point1[axis] < output_point2[axis]:
                    distance *= -1.0
                _move_objects(objects, distance, letter, state)
        work_part_field = _rebuild_after_move(component, False, state)
        point_list = _select_handle_point()


def _align_edge_distance(component: Optional[NXOpen.Assemblies.Component], work_part_field: Any,
                         state: _EditState) -> None:
    """ButtonAlignEdgeDistance_Click from the first SelectHandlePoint on."""
    point_list = _select_handle_point()
    while len(point_list) == 1:
        _hide_dynamic_handles()
        point1 = _handle_prototype(point_list[0])
        _do_not_move, move_half, move_full = _split_points(point1, work_part_field)
        response, picked = _point_construct("Select Reference Point")
        if response == _UF_UI_OK:
            offset = _ask_offset()
            if offset is not None:
                output_point1 = _map_point(_UF_CSYS_ROOT_COORDS, picked, _UF_CSYS_ROOT_WCS_COORDS)
                output_point2 = _map_point(_UF_CSYS_ROOT_COORDS, _coords(point1), _UF_CSYS_ROOT_WCS_COORDS)
                move = _HandleMoves.get(point1.Name)
                if move is not None:
                    axis, letter, face_lines, use_end = move
                    num = abs(output_point2[axis] - output_point1[axis])
                    distance = num - offset if output_point1[axis] >= output_point2[axis] else num * -1.0 + offset
                    move_full.extend(_lines_named(state, *face_lines))
                    _stretch_axis_lines(state, axis, letter, use_end, distance)
                    _move_objects(move_full, distance, letter, state)
                    _move_objects(move_half, distance / 2.0, letter, state)
            else:
                _message("Caught exception", NXOpen.NXMessageBox.DialogType.Error, "Invalid input")
        _update_dynamic_block(component, state)
        _work_part_emphasis_off()
        work_part_field = _rebuild_after_move_no_update(component, state)
        point_list = _select_handle_point()


def _rebuild_after_move_no_update(component: Optional[NXOpen.Assemblies.Component], state: _EditState) -> Any:
    """Align Edge Distance's tail after its own UpdateDynamicBlock + preference writes."""
    _ufs.Disp.SetDisplay(_UF_DISP_SUPPRESS_DISPLAY)
    _set_work_component(component, False)
    work_part_field = nx.work_part()
    _create_edit_data(component, state)
    return work_part_field


def _edit_align(component: Optional[NXOpen.Assemblies.Component], specify_offset: bool, work_part_field: Any,
                state: _EditState) -> None:
    """NewCompBuild.EditAlign from UpdateDynamicBlock on."""
    _update_dynamic_block(component, state)
    _create_edit_data(component, state)
    point_list = _select_handle_point()
    while len(point_list) == 1:
        _hide_dynamic_handles()
        point_prototype = _handle_prototype(point_list[0])
        _do_not_move, move_half, move_full = _split_points(point_prototype, work_part_field)
        response, picked = _point_construct("Select Reference Point")
        if response == _UF_UI_OK:
            result = 0.0
            if specify_offset:
                offset = _ask_offset()
                if offset is None:
                    nx.show_error("Invalid input")
                    return
                result = offset
            output_point1 = _map_point(_UF_CSYS_ROOT_COORDS, picked, _UF_CSYS_ROOT_WCS_COORDS)
            output_point2 = _map_point(_UF_CSYS_ROOT_COORDS, _coords(point_prototype), _UF_CSYS_ROOT_WCS_COORDS)
            move = _HandleMoves.get(point_prototype.Name)
            if move is not None:
                axis, letter, face_lines, use_end = move
                if use_end:
                    # POS handle: the full distance moves the face, the lines stretch by distance - offset.
                    distance = abs(output_point2[axis] - output_point1[axis])
                    if output_point1[axis] < output_point2[axis]:
                        distance *= -1.0
                    line_distance = distance - result
                else:
                    num = abs(output_point2[axis] - output_point1[axis])
                    distance = num - result if output_point1[axis] >= output_point2[axis] else num * -1.0 + result
                    line_distance = distance
                move_full.extend(_lines_named(state, *face_lines))
                _stretch_axis_lines(state, axis, letter, use_end, line_distance)
                _move_objects(move_full, distance, letter, state)
                _move_objects(move_half, distance / 2.0, letter, state)
        work_part_field = _rebuild_after_move(component, True, state)
        point_list = _select_handle_point()
