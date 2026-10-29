"""
The plot-detail-drawings UFunc: a standalone Python UFunc (no C# class, 2026-10-29); its menu button runs this file's
main(). It replaced the WinForms PlotDetailDrawings form and src\\Static\\PlotDetailDrawings.cs (in git at
5fb0e3c), whose NX work this module had ported unwired.

The dialog (PlotDetailDrawings.dlx, tools\\make-dlx.py): Print All Details / Print Selected Components (the form's
Print All and Print Selected check boxes) and, for Selected, a component picker. OK prints the 4-VIEW sheet of each
detail ({job}-{op}-{detail}) once, in display-name order, to the office MFC (letter, landscape, black and white):
each is displayed in turn, its layers set (work layer 1, category ALL hidden, 100 / 200 / 230 selectable), the sheet
opened, and out-of-date views updated and the part saved. The original display part is shown again at the end.

Print All takes every unsuppressed detail under the display assembly, loading an unloaded one quietly. Print
Selected takes the picked components (anything picked, detail or not, as in the C#).

Differences from the form:
- Its third check box, Print Assembly, is gone: it printed the `children` list, which ButtonOk_Click cleared first
  and Print All cleared again when it ran, so it never printed anything.
- A detail without a 4-VIEW sheet is printed as a warning and skipped, as before; the run ends with a count of the
  sheets sent to the printer.
"""

from __future__ import annotations

import ntpath
import os
import re
import sys
from typing import Dict, List, Optional

# Session.Execute does not put the script's folder on sys.path, so the shared modules would not import.
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
import NXOpen.Drawings  # noqa: E402
import NXOpen.Layer  # noqa: E402

import tsg_nx as nx  # noqa: E402
from tsg_dialog import Dialog, components_of, title_with_version  # noqa: E402

ufunc_name = "plot-detail-drawings"

# NX will not create a dialog from inside another dialog's callback.
_ErrorCannotLaunchDialog = 3520048

ScopeAll = "Print All Details"
ScopeSelected = "Print Selected Components"

# Globals.cs _printerCts (Extensions.__PrinterCts).
_PrinterCts = "\\\\ctsfps1.cts.toolingsystemsgroup.com\\CTS Office MFC"

# NXOpen.UF.UFConstants.UF_drawing_type (same value CreateBurnout.py uses).
_UF_drawing_type = 62

_DrawingName = "4-VIEW"


def _is_detail(name: str) -> bool:
    """string.__IsDetail - the leaf (no folder, no extension) is "{digits}-{digits}-{digits}"."""
    leaf = ntpath.splitext(ntpath.basename(name))[0]
    return re.match(r"^\d+-\d+-\d+$", leaf) is not None


class PlotDetailDrawings(object):

    @staticmethod
    def print_detail_drawing(display_part_name: str, work_part: NXOpen.Part) -> bool:
        """
        Static.PlotDetailDrawingsPrintDetailDrawing - opens the display part's 4-VIEW sheet (updating and saving
        it when out of date) and prints work_part's 4-VIEW to the office MFC, letter, landscape. False when the part
        has no 4-VIEW.
        """
        part = nx.ufsession_.Part.AskDisplayPart()
        # UF_OBJ_cycle_by_name_and_type: the C# ref param comes back as the return value (checked in the pyd;
        # CreateBurnout.py makes the same call). 0 = Tag.Null, start of the cycle.
        drawing = nx.ufsession_.Obj.CycleByNameAndType(part, _DrawingName, _UF_drawing_type, False, 0)

        if not drawing:
            nx.warn("No drawing named 4-VIEW in part {}".format(display_part_name))
            return False

        nx.session_.ApplicationSwitchImmediate("UG_APP_DRAFTING")

        sheet = nx.tagged_object(drawing)
        assert isinstance(sheet, NXOpen.Drawings.DrawingSheet)

        sheet.Open()

        # pyd: IsObjectOutOfDate(objectArg) -> bool (the C# out bool).
        out_of_date = nx.ufsession_.Draw.IsObjectOutOfDate(sheet.Tag)
        if out_of_date:
            try:
                nx.ufsession_.Draw.UpdOutOfDateViews(sheet.Tag)
                # Python enum members True/False are TrueValue/FalseValue.
                sheet.OwningPart.Save(NXOpen.BasePart.SaveComponents.TrueValue,
                                      NXOpen.BasePart.CloseAfterSave.FalseValue)
            except Exception as ex:
                nx.print_exception(ex)

        print_builder1 = work_part.PlotManager.CreatePrintBuilder()

        try:
            print_builder1.Copies = 1
            print_builder1.ThinWidth = 1.0
            print_builder1.NormalWidth = 2.0
            print_builder1.ThickWidth = 3.0
            print_builder1.Output = NXOpen.PrintBuilder.OutputOption.WireframeBlackWhite
            print_builder1.ShadedGeometry = True
            drawing_sheet1 = work_part.DraftingDrawingSheets.FindObject(_DrawingName)
            print_builder1.SourceBuilder.SetSheets([drawing_sheet1])
            print_builder1.PrinterText = _PrinterCts
            print_builder1.Orientation = NXOpen.PrintBuilder.OrientationOption.Landscape
            print_builder1.Paper = NXOpen.PrintBuilder.PaperSize.Letter
            print_builder1.Commit()
        finally:
            print_builder1.Destroy()
        return True

    @staticmethod
    def set_display_part(comp: NXOpen.Assemblies.Component) -> None:
        """Static.PlotDetailDrawingsSetDisplayPart - displays comp's prototype."""
        nx.set_display_part(nx.prototype(comp))

    @staticmethod
    def set_default_layers(display_part: NXOpen.Part) -> None:
        """Static.PlotDetailDrawingsSetDefaultLayers - work layer 1, category ALL hidden, 100/200/230 selectable."""
        display_part.Layers.SetState(1, NXOpen.Layer.State.WorkLayer)
        layer_state = display_part.Layers.GetStates()

        for category in display_part.LayerCategories:
            if category.Name == "ALL":
                layer_state.SetStateOfCategory(category, NXOpen.Layer.State.Hidden)

        display_part.Layers.SetStates(layer_state, True)
        layer_state.Dispose()
        display_part.Layers.SetState(100, NXOpen.Layer.State.Selectable)
        display_part.Layers.SetState(200, NXOpen.Layer.State.Selectable)
        display_part.Layers.SetState(230, NXOpen.Layer.State.Selectable)


def _get_child_components(assembly: NXOpen.Assemblies.Component,
                          children: List[NXOpen.Assemblies.Component]) -> None:
    """
    Static.PlotDetailDrawingsGetChildComponents - adds every unsuppressed detail ({job}-{op}-{detail}) that is
    loaded, or opens quietly, to children, recursing through everything else. As in the C#, one try/except
    wraps the whole loop at each level, so a failure skips the rest of that level's children.
    """
    try:
        for child in assembly.GetChildren():
            if child.IsSuppressed:
                continue

            if not _is_detail(child.DisplayName):
                _get_child_components(child, children)
                continue

            instance = nx.ufsession_.Assem.AskInstOfPartOcc(child.Tag)

            if not instance:
                continue

            # The pyd docstring gives AskPartNameOfChild's rtype as "list of str"; accept either a str or a list
            # (as CopyAttributes.py does).
            part_name_result = nx.ufsession_.Assem.AskPartNameOfChild(instance)
            part_name = part_name_result if isinstance(part_name_result, str) else part_name_result[0]

            if nx.ufsession_.Part.IsLoaded(part_name) == 1:
                children.append(child)
                _get_child_components(child, children)
                continue

            # pyd: OpenQuiet(partName) -> (part, errorStatus); part is None (or the null tag) on failure.
            part_open, _load_status = nx.ufsession_.Part.OpenQuiet(part_name)

            if not part_open:
                continue

            children.append(child)
            _get_child_components(child, children)
    except Exception as ex:
        nx.print_exception(ex)


def all_details(display_part: NXOpen.Part) -> List[NXOpen.Assemblies.Component]:
    """Print All's components: the display assembly's unsuppressed details (none for a part with no assembly)."""
    root = nx.root_component(display_part)
    children: List[NXOpen.Assemblies.Component] = []
    if root is not None:
        _get_child_components(root, children)
    return children


def print_components(components: List[NXOpen.Assemblies.Component]) -> None:
    """
    The Print All / Print Selected loop of ButtonOk_Click: one of each display name, in display-name order -
    displayed, its layers set and its 4-VIEW printed - then the original display part again.
    """
    original = nx.display_part()
    one_each: Dict[str, NXOpen.Assemblies.Component] = {}
    for comp in components:
        one_each.setdefault(comp.DisplayName, comp)

    if not one_each:
        nx.print_("Plot Detail Drawings: no details to print.")
        return

    printed = 0
    try:
        for name in sorted(one_each):
            try:
                PlotDetailDrawings.set_display_part(one_each[name])
                PlotDetailDrawings.set_default_layers(nx.display_part())
                if PlotDetailDrawings.print_detail_drawing(name, nx.work_part()):
                    printed += 1
            except Exception as ex:
                nx.print_exception(ex, name)
    finally:
        nx.set_display_part(original)

    nx.print_("Plot Detail Drawings: sent {} of {} 4-VIEW sheet(s) to {}.".format(printed, len(one_each),
                                                                               _PrinterCts))


class _PlotDetailDrawingsDialog(Dialog):
    """PlotDetailDrawings.dlx: Print All Details / Print Selected Components and the component picker."""

    dlx_name = "PlotDetailDrawings.dlx"

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__()
        # Captured in ok(): the blocks are gone once Launch returns.
        self.components: List[NXOpen.Assemblies.Component] = []

    def initialize(self) -> None:
        self.component_filter(self.block("components"))
        self.assembly_scope(self.block("components"))

    def shown(self) -> None:
        self._show_picker()

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        if block == self.block("scope"):
            self._show_picker()

    def enable_ok(self) -> bool:
        return not self._selected_scope() or len(self._picked()) > 0

    def ok(self) -> bool:
        if self._selected_scope():
            self.components = self._picked()
            if not self.components:
                self.message("Select the components to print.")
                return False
        else:
            self.components = all_details(nx.display_part())
        return True

    def _selected_scope(self) -> bool:
        return str(self.block("scope").ValueAsString) == ScopeSelected

    def _picked(self) -> List[NXOpen.Assemblies.Component]:
        return components_of(self.selected(self.block("components")))

    def _show_picker(self) -> None:
        self.block("components").Show = self._selected_scope()


def execute() -> None:
    if nx.display_part() is None:
        nx.show_error("Plot Detail Drawings needs a display part.")
        return

    title = title_with_version("Plot Detail Drawings")
    dialog: Optional[_PlotDetailDrawingsDialog] = None
    try:
        dialog = _PlotDetailDrawingsDialog(title)
        if not dialog.run():
            return
    except NXOpen.NXException as ex:
        if ex.ErrorCode != _ErrorCannotLaunchDialog:
            raise
        nx.print_exception(ex)
        nx.show_error("NX would not open the {} dialog (error {} - it will not create a dialog from inside a "
                      "callback).\n\nTry running it from File -> Execute -> NX Open rather than from a menu or "
                      "toolbar button.".format(title, _ErrorCannotLaunchDialog))
        return

    print_components(dialog.components)


def main() -> None:
    """The plot-detail-drawings UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
