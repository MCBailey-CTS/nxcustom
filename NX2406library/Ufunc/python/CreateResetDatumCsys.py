"""
The create-reset-datum-csys UFunc as a Block UI Styler dialog: a port of the C# CreateResetDatumCsys form
(src\\UFuncs\\CreateResetDatumCsys.cs) and its Static methods (src\\Static\\CreateResetDatumCsys.cs). Its menu button
runs this file's main(). The class CreateResetDatumCsys at the bottom keeps the entry points callable through
Session.Execute (create_datum_csys, delete_saved_csys, make_plan_view, get_child_components).

The dialog (CreateResetDatumCsys.dlx, tools\\make-dlx.py) is OK / Apply / Cancel; OK and Apply both do the action
picked in the Action radio, Apply keeping the dialog open for the next one:
  - Create WCS/PV        - the form's Select Component + Create WCS/PV buttons. Position the WCS first (a modal
                           dialog cannot hand the WCS dynamics back to the user). The picked component becomes the
                           work component, its CTSDATUMCSYS and PLAN view are deleted (the form's ResetComponent), the
                           WCS is saved and rebuilt as a CTSDATUMCSYS on hidden layer 254, the PLAN view is made from
                           it, and the original display / work parts are restored.
  - Non CtsDatumCsys     - blanks every same-units child of the work part whose part has a csys on layer 254.
  - Reset All Components - after a Yes/No, deletes the layer-250 order block, the CTSDATUMCSYS and the PLAN view of
                           every distinct detail under the work part.

Differences from the C#:
- A component in other units than the display part is refused with a message (the form's Select Component returned
  silently). The form took a multiple selection and used only the first; the dialog picks one.
- Non CtsDatumCsys does not switch the work part context to each child (UF_ASSEM_set_work_part_context_quietly):
  it only reads the child's coordinate systems, which needs no context. A child that throws is printed and skipped.
- Reset All prints and skips a detail that throws instead of stopping there.
- Create WCS/PV still calls UF_PART_set_display_part(NULL_TAG) like the form, but restores the display and work
  parts in a finally, so a failure cannot leave NX without them.
- make_plan_view (the Session.Execute entry) reads the display part from the session instead of taking the form's
  cached displayPart; get_child_components returns its list, which Session.Execute cannot hand back to C#.
- UF_ASSEM_ask_part_name_of_child is documented in NXOpen_UF.pyd as returning "list of str"; the result is joined
  into one string, which is right whether it arrives as a str, a one-element list or a list of characters.

Not run in NX yet.
"""

from __future__ import annotations

import ntpath
import os
import re
import sys
from typing import Any, List, Optional, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# From the source tree (src\UFuncs) the shared modules are in src\python; deployed, they are beside this file.
_shared_python = os.path.join(os.path.dirname(_here), "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.BlockStyler  # noqa: E402
import NXOpen.Features  # noqa: E402
import NXOpen.Layer  # noqa: E402

import tsg_nx as nx  # noqa: E402
from tsg_dialog import Dialog, components_of, title_with_version  # noqa: E402

ufunc_name = "create-reset-datum-csys"

_PlanViewName = "PLAN"
_DatumCsysLayer = 254
_OrderBlockLayer = 250
_UF_OBJ_BLANKED = 1
_NullTag = cast(NXOpen.Tag, 0)
_ErrorCannotLaunchDialog = 3520048

_ActionCreate = "Create WCS/PV"
_ActionNonDatumCsys = "Non CtsDatumCsys"
_ActionResetAll = "Reset All Components"

# NX members the stubs lack (UF_OBJ_ask_owning_part, Session.NewestVisibleUndoMark, collection iteration).
_uf = cast(Any, nx.ufsession_)
_session = cast(Any, nx.session_)

_DatumCsysName = "CTSDATUMCSYS"


def _is_detail(name: str) -> bool:
    """string.__IsDetail - the file name without extension is {digits}-{digits}-{digits}."""
    leaf = ntpath.splitext(ntpath.basename(name))[0]
    return re.match(r"^\d+-\d+-\d+$", leaf) is not None


def _has_datum_csys(work_part: NXOpen.Part) -> bool:
    for feat in work_part.Features:
        if feat.Name == _DatumCsysName:
            return True
    return False


def _make_plan_view(work_part: NXOpen.Part, display_part: NXOpen.Part) -> None:
    """Static.CreateResetDatumCsysMakePlanView"""
    # Get the datum csys information from CTSDATUMCSYS

    try:
        csys_exists = False

        for feat in work_part.Features:
            if feat.Name == _DatumCsysName:
                csys_exists = True

        if not csys_exists:
            return

        for feat in work_part.Features:
            if feat.Name != _DatumCsysName:
                continue

            datum_csys = cast(NXOpen.Features.DatumCsys, feat)
            smart_csys, _origin, _daxes, _dplanes = nx.ufsession_.ModlFeatures.AskDatumCsysComponents(datum_csys.Tag)
            matrix, _wcs_origin = nx.ufsession_.Csys.AskCsysInfo(smart_csys)
            matrix_values = nx.ufsession_.Csys.AskMatrixValues(matrix)
            orientation = NXOpen.Matrix3x3()
            orientation.Xx = matrix_values[0]
            orientation.Xy = matrix_values[1]
            orientation.Xz = matrix_values[2]
            orientation.Yx = matrix_values[3]
            orientation.Yy = matrix_values[4]
            orientation.Yz = matrix_values[5]
            orientation.Zx = matrix_values[6]
            orientation.Zy = matrix_values[7]
            orientation.Zz = matrix_values[8]
            display_part.Views.WorkView.Orient(orientation)
            view1 = work_part.Views.SaveAs(work_part.ModelingViews.WorkView, "PLAN", False, False)
            layout1 = work_part.Layouts.FindObject("L1")
            modeling_view1 = cast(NXOpen.ModelingView, view1)
            modeling_view2 = work_part.ModelingViews.FindObject("TOP")
            layout1.ReplaceView(modeling_view1, modeling_view2, True)
    except Exception as ex:
        nx.print_exception(ex)


def _delete_saved_csys(saved_csys: NXOpen.CartesianCoordinateSystem) -> None:
    """Static.CreateResetDatumCsysDeleteSavedCsys"""
    nx.session_.UpdateManager.ClearErrorList()
    mark_id1 = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "Delete Saved WCS")
    objects1: List[NXOpen.TaggedObject] = [saved_csys]
    nx.session_.UpdateManager.AddObjectsToDeleteList(objects1)
    nx.session_.UpdateManager.DoUpdate(mark_id1)


def _create_datum_csys(work_part: NXOpen.Part, saved_csys: NXOpen.CartesianCoordinateSystem) -> None:
    """Static.CreateResetDatumCsysCreateDatumCsys"""
    try:
        if _has_datum_csys(work_part):
            nx.print_("")
            nx.print_("Error:")
            nx.print_("A CTSDATUMCSYS already exists")
            return

        datum_csys_builder1 = work_part.Features.CreateDatumCsysBuilder(None)
        wp_units = work_part.PartUnits

        if wp_units == NXOpen.BasePart.Units.Inches:
            unit1 = work_part.UnitCollection.FindObject("Inch")
            expression1 = work_part.Expressions.CreateSystemExpressionWithUnits("0", unit1)
        else:
            unit1 = work_part.UnitCollection.FindObject("MilliMeter")
            expression1 = work_part.Expressions.CreateSystemExpressionWithUnits("0", unit1)

        update = NXOpen.SmartObject.UpdateOption.WithinModeling
        length = NXOpen.Scalar.DimensionalityType.Length
        angle = NXOpen.Scalar.DimensionalityType.Angle

        scalar1 = work_part.Scalars.CreateScalarExpression(expression1, length, update)
        expression2 = work_part.Expressions.CreateSystemExpressionWithUnits("0", unit1)
        scalar2 = work_part.Scalars.CreateScalarExpression(expression2, length, update)
        expression3 = work_part.Expressions.CreateSystemExpressionWithUnits("0", unit1)
        scalar3 = work_part.Scalars.CreateScalarExpression(expression3, length, update)
        offset1 = work_part.Offsets.CreateOffsetRectangular(scalar1, scalar2, scalar3, update)

        unit2 = work_part.UnitCollection.FindObject("Degrees")
        expression4 = work_part.Expressions.CreateSystemExpressionWithUnits("0", unit2)
        scalar4 = work_part.Scalars.CreateScalarExpression(expression4, angle, update)
        expression5 = work_part.Expressions.CreateSystemExpressionWithUnits("0", unit2)
        scalar5 = work_part.Scalars.CreateScalarExpression(expression5, angle, update)
        expression6 = work_part.Expressions.CreateSystemExpressionWithUnits("0", unit2)
        scalar6 = work_part.Scalars.CreateScalarExpression(expression6, angle, update)

        # CreateXform(csys, point0, point1, rotationScalarX, rotationScalarY, rotationScalarZ, rotationOption,
        # updateOption, scale) - the C# passes the Offset as point1 and 0 as the rotation option.
        xform1 = work_part.Xforms.CreateXform(saved_csys, None, offset1, scalar4, scalar5, scalar6, 0, update, 1.0)

        cartesian_coordinate_system2 = work_part.CoordinateSystems.CreateCoordinateSystem(xform1, update)

        datum_csys_builder1.Csys = cartesian_coordinate_system2
        datum_csys_builder1.DisplayScaleFactor = 2.0
        nx_object1 = datum_csys_builder1.Commit()
        nx_object1.SetName(_DatumCsysName)
        # As in the C#, the builder is not destroyed when something above throws.
        datum_csys_builder1.Destroy()

        for csys_point in work_part.Points:
            if csys_point.Layer == 254:
                csys_point.Layer = 2
    except Exception as ex:
        nx.print_exception(ex)


def _get_child_components(assembly: NXOpen.Assemblies.Component,
                          children: List[NXOpen.Assemblies.Component]) -> None:
    """Static.CreateResetDatumCsysGetChildComponents"""
    try:
        for child in assembly.GetChildren():
            if child.IsSuppressed:
                continue

            if not _is_detail(child.DisplayName):
                _get_child_components(child, children)
                continue

            instance = nx.ufsession_.Assem.AskInstOfPartOcc(child.Tag)
            raw_name: Any = nx.ufsession_.Assem.AskPartNameOfChild(instance)
            part_name = raw_name if isinstance(raw_name, str) else "".join(raw_name)
            part_load = nx.ufsession_.Part.IsLoaded(part_name)

            if part_load == 1:
                children.append(child)
                _get_child_components(child, children)
                continue

            part_open, _error_status = nx.ufsession_.Part.OpenQuiet(part_name)

            if part_open == 0:  # NXOpen.Tag.Null
                continue

            children.append(child)
            _get_child_components(child, children)
    except Exception as ex:
        nx.print_exception(ex)


# ---------------------------------------------------------------------------------------------------
# The form's button bodies
# ---------------------------------------------------------------------------------------------------

def _delete_datum_csys_features(work_part: NXOpen.Part) -> None:
    """Every CTSDATUMCSYS feature of work_part, under its own invisible undo mark (as in ResetComponent)."""
    nx.session_.UpdateManager.ClearErrorList()
    mark_id1 = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "Delete CTSDATUMCSYS")
    csys_exists = False

    for feat in work_part.Features:
        if feat.Name != _DatumCsysName:
            continue

        csys_exists = True
        nx.session_.UpdateManager.AddToDeleteList(feat)

    if csys_exists:
        nx.session_.UpdateManager.DoUpdate(mark_id1)


def _delete_plan_view(work_part: NXOpen.Part) -> None:
    """Puts TOP back in layout L1 in place of the work view and deletes the PLAN view, when there is one."""
    plan_exists = False

    for m_view in cast(Any, work_part.ModelingViews):
        if m_view.Name == _PlanViewName:
            plan_exists = True

    if not plan_exists:
        return

    layout1 = work_part.Layouts.FindObject("L1")
    modeling_view1 = work_part.ModelingViews.WorkView
    modeling_view2 = work_part.ModelingViews.FindObject("TOP")
    layout1.ReplaceView(modeling_view1, modeling_view2, True)
    modeling_view3 = work_part.ModelingViews.FindObject(_PlanViewName)
    nx.session_.UpdateManager.AddToDeleteList(modeling_view3)
    id1 = _session.NewestVisibleUndoMark
    nx.session_.UpdateManager.DoUpdate(id1)


def _restore_parts(display_part: NXOpen.Part, work_part: NXOpen.Part) -> None:
    """ufsession_.Part.SetDisplayPart + ufsession_.Assem.SetWorkPart, as the form restored its original parts."""
    nx.ufsession_.Part.SetDisplayPart(display_part.Tag)
    nx.set_work_part(work_part)


def _reset_component(original_display: NXOpen.Part, original_work: NXOpen.Part) -> None:
    """CreateResetDatumCsys.ResetComponent - deletes the work part's CTSDATUMCSYS and PLAN view."""
    with nx.suppress_display():
        try:
            nx.ufsession_.Part.SetDisplayPart(_NullTag)
            try:
                work_part = nx.work_part()
                _delete_datum_csys_features(work_part)
                _delete_plan_view(work_part)
            finally:
                _restore_parts(original_display, original_work)
        except Exception as ex:
            nx.print_exception(ex)


def create_wcs_plan_view(component: NXOpen.Assemblies.Component) -> bool:
    """
    The form's Select Component then Create WCS/PV: makes component the work component, replaces its CTSDATUMCSYS
    with one at the current WCS (layer 254, hidden) and makes the PLAN view from it, then restores the display and
    work parts. False when the component's units differ from the display part's (nothing is done).
    """
    original_display = nx.display_part()
    original_work = nx.work_part()

    if nx.prototype(component).PartUnits != original_display.PartUnits:
        return False

    try:
        nx.set_work_component(component)
        _reset_component(original_display, original_work)
        nx.set_work_component(component)

        cartesian_coordinate_system1 = cast(NXOpen.CartesianCoordinateSystem, cast(Any, nx.display_part().WCS).Save())

        with nx.suppress_display():
            nx.ufsession_.Part.SetDisplayPart(_NullTag)
            try:
                work_part = nx.work_part()
                work_part.Layers.WorkLayer = _DatumCsysLayer
                _create_datum_csys(work_part, cartesian_coordinate_system1)
                _delete_saved_csys(cartesian_coordinate_system1)
                work_part.Layers.WorkLayer = 1
                work_part.Layers.SetState(_DatumCsysLayer, NXOpen.Layer.State.Hidden)
                _make_plan_view(work_part, nx.display_part())
            finally:
                _restore_parts(original_display, original_work)
    except Exception as ex:
        nx.print_exception(ex)
    return True


def blank_datum_csys_components() -> None:
    """
    Static.CreateResetDatumCsysBlankDatumCsysComponents (Non CtsDatumCsys) - blanks, in the display part, every
    occurrence of each unsuppressed same-units child of the work part whose part has a csys on layer 254.
    """
    display_part = nx.display_part()
    work_part = nx.work_part()
    count = 0
    count_suppressed = 0

    try:
        if work_part.ComponentAssembly.RootComponent is not None:
            for comp in nx.children(work_part):
                if comp.IsSuppressed:
                    count_suppressed += 1
                    continue

                try:
                    if comp.Prototype is None:
                        continue

                    proto = nx.prototype(comp)

                    if proto.PartUnits != display_part.PartUnits:
                        continue

                    for csys in cast(Any, proto.CoordinateSystems):
                        if csys.Layer != _DatumCsysLayer:
                            continue

                        count += 1
                        part_occs, _count = nx.ufsession_.Assem.AskOccsOfPart(display_part.Tag, proto.Tag)

                        for blank_comp in part_occs:
                            parent_tag = _uf.Obj.AskOwningPart(blank_comp)

                            if parent_tag == display_part.Tag:
                                nx.ufsession_.Obj.SetBlankStatus(blank_comp, _UF_OBJ_BLANKED)
                except Exception as ex:
                    nx.print_exception(ex)

        if count == 0:
            nx.print_("")
            nx.print_("There are no valid components in this assembly")

        if count_suppressed <= 0:
            return

        nx.print_("")
        nx.print_("There are suppressed components in this assembly")
        nx.print_("")
        nx.print_("CTSDATUMCSYS will not be verified in these components")
    except Exception as ex:
        nx.print_exception(ex)
    finally:
        cast(Any, display_part.Views).UpdateDisplay()


def reset_all() -> None:
    """
    Static.CreateResetDatumCsysResetAll (Reset All Components, after its Yes/No) - for every distinct detail under
    the work part, deletes the layer-250 order block, the CTSDATUMCSYS feature and the PLAN view.
    """
    with nx.display_part_reset(), nx.suppress_display():
        try:
            original_display = nx.display_part()
            work_part = nx.work_part()
            root = work_part.ComponentAssembly.RootComponent

            if root is None:
                nx.print_("")
                nx.print_("The work part is not an assembly")
                nx.print_("Reset All Components is not available")
                return

            children: List[NXOpen.Assemblies.Component] = []
            _get_child_components(root, children)

            if len(children) == 0:
                nx.print_("")
                nx.print_("No valid child components in {}".format(root.DisplayName))
                return

            for comp in nx.distinct_by(children, lambda c: c.DisplayName):
                try:
                    nx.set_display_part(nx.prototype(comp))
                    display_part = nx.display_part()

                    # Delete order block on layer 250
                    with nx.do_update("Delete Order Block"):
                        for order_blk in cast(Any, display_part.Bodies):
                            if order_blk.Layer == _OrderBlockLayer:
                                nx.session_.UpdateManager.AddToDeleteList(order_blk)

                    # Delete CTS datum csys
                    nx.session_.UpdateManager.ClearErrorList()
                    detail_work = nx.work_part()

                    with nx.do_update("Delete CTSDATUMCSYS"):
                        for feat in detail_work.Features:
                            if feat.Name == _DatumCsysName:
                                nx.session_.UpdateManager.AddToDeleteList(feat)

                    # Delete Plan view
                    _delete_plan_view(detail_work)
                except Exception as ex:
                    nx.print_exception(ex)
                finally:
                    # As the C#: the work part goes back to the original display part, not the original work part.
                    _restore_parts(original_display, original_display)
        except Exception as ex:
            nx.print_exception(ex)


# ---------------------------------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------------------------------

class _CreateResetDatumCsysDialog(Dialog):
    dlx_name = "CreateResetDatumCsys.dlx"

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__()

    def initialize(self) -> None:
        self.component_filter(self.block("component"))
        self.assembly_scope(self.block("component"))

    def shown(self) -> None:
        self._refresh()

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        if block == self.block("action"):
            self._refresh()

    def enable_ok(self) -> bool:
        return self._action() != _ActionCreate or self._component() is not None

    def ok(self) -> bool:
        action = self._action()

        if action == _ActionCreate:
            component = self._component()
            if component is None:
                self.message("Select a component.", error=True)
                return False
            if not create_wcs_plan_view(component):
                self.message("{} is not in the display part's units.".format(component.DisplayName), error=True)
                return False
            self.block("component").SetSelectedObjects([])
            return True

        if action == _ActionNonDatumCsys:
            blank_datum_csys_components()
            return True

        if action == _ActionResetAll:
            answer = nx.message_box("Verify Remove All", NXOpen.NXMessageBox.DialogType.Question,
                                    "Are you sure that you want to remove all CTSDATUMCSYS")
            if answer != nx.MessageBoxYes:
                return False
            reset_all()
            return True

        self.message("Pick an action.", error=True)
        return False

    def _action(self) -> str:
        return str(self.block("action").ValueAsString)

    def _component(self) -> Optional[NXOpen.Assemblies.Component]:
        components = components_of(self.selected(self.block("component")))
        return components[0] if components else None

    def _refresh(self) -> None:
        create = self._action() == _ActionCreate
        self.block("component").Show = create
        self.block("wcs_note").Show = create


def execute() -> None:
    display = nx.display_part()
    if display is None:
        nx.show_error("Cts Datum Csys needs a display part.")
        return

    title = title_with_version("Cts Datum Csys")
    try:
        _CreateResetDatumCsysDialog(title).run()
    except NXOpen.NXException as ex:
        if ex.ErrorCode != _ErrorCannotLaunchDialog:
            raise
        nx.print_exception(ex)
        nx.show_error("NX would not open the {} dialog (error {} - it will not create a dialog from inside a "
                      "callback).\n\nTry running it from File -> Execute -> NX Open rather than from a menu or "
                      "toolbar button.".format(title, _ErrorCannotLaunchDialog))


def main() -> None:
    """The create-reset-datum-csys UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            execute()
        except Exception as ex:
            nx.print_exception(ex)


# ---------------------------------------------------------------------------------------------------
# Session.Execute entry points (the C# form)
# ---------------------------------------------------------------------------------------------------

class CreateResetDatumCsys(object):

    @staticmethod
    def create_datum_csys(work_part: NXOpen.Part, saved_csys: NXOpen.CartesianCoordinateSystem) -> None:
        """Static.CreateResetDatumCsysCreateDatumCsys - CTSDATUMCSYS on the saved WCS, unless one exists."""
        _create_datum_csys(work_part, saved_csys)

    @staticmethod
    def delete_saved_csys(saved_csys: NXOpen.CartesianCoordinateSystem) -> None:
        """Static.CreateResetDatumCsysDeleteSavedCsys"""
        _delete_saved_csys(saved_csys)

    @staticmethod
    def make_plan_view(work_part: NXOpen.Part) -> None:
        """Static.CreateResetDatumCsysMakePlanView - with the session's display part (see the module docstring)."""
        _make_plan_view(work_part, nx.display_part())

    @staticmethod
    def get_child_components(assembly: NXOpen.Assemblies.Component) -> List[NXOpen.Assemblies.Component]:
        """
        Static.CreateResetDatumCsysGetChildComponents - every unsuppressed detail occurrence under assembly,
        opening unloaded ones quietly. Returns the list (the C# fills the form's list instead).
        """
        children: List[NXOpen.Assemblies.Component] = []
        _get_child_components(assembly, children)
        return children


if __name__ == "__main__":
    main()
