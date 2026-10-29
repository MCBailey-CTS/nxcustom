"""
Example Block UI Styler dialog: select faces or components, a "hello" toggle, and a sam / ellie drop-down.
OK prints what was picked to the listing window.

Run it from NX as a journal (File > Execute > NX Open, or Tools > Journal > Play). HelloDialog.dlx has to sit
next to this file.

SNAP (Snap.UI.BlockForm) is .NET only, so Python builds the same kind of dialog from a .dlx. HelloDialog.dlx
was assembled from blocks NX itself generated (the CheckDeepHoles Python sample and ReportObjectAttributes),
so it opens and edits in the Block UI Styler like any other dialog.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional, cast

import NXOpen
import NXOpen.Assemblies
import NXOpen.BlockStyler
import NXOpen.UF

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tsg_nx as nx  # noqa: E402

_DlxName = "HelloDialog.dlx"


def _dlx_path() -> str:
    """HelloDialog.dlx next to this script. A journal run may not set __file__, so fall back to argv[0]."""
    here = globals().get("__file__") or (sys.argv[0] if sys.argv else "")
    return os.path.join(os.path.dirname(os.path.abspath(here)), _DlxName)


class HelloDialog(object):

    def __init__(self) -> None:
        self.the_session = NXOpen.Session.GetSession()
        self.the_ui = NXOpen.UI.GetUI()
        self.the_dialog = self.the_ui.CreateDialog(_dlx_path())
        self.the_dialog.AddInitializeHandler(self.initialize_cb)
        self.the_dialog.AddUpdateHandler(self.update_cb)
        self.the_dialog.AddOkHandler(self.ok_cb)

        self.selection: Optional[NXOpen.BlockStyler.SelectObject] = None
        self.hello: Optional[NXOpen.BlockStyler.Toggle] = None
        self.name: Optional[NXOpen.BlockStyler.Enumeration] = None

        # What OK captured; the blocks are gone once Launch returns. Callers test accepted rather than the
        # Launch response, whose member names differ between bindings.
        self.accepted = False
        self.selected_objects: List[NXOpen.TaggedObject] = []
        self.hello_checked = False
        self.selected_name = ""

    def launch(self) -> None:
        response = "error"
        try:
            self.the_dialog.Launch()
            response = "ok" if self.accepted else "cancel"
        finally:
            nx.log_dialog("block-dialog", "Hello Dialog", None, None, response)

    def dispose(self) -> None:
        self.the_dialog.Dispose()

    def initialize_cb(self) -> None:
        try:
            top = self.the_dialog.TopBlock
            selection = cast(NXOpen.BlockStyler.SelectObject, top.FindBlock("selection"))
            self.selection = selection
            self.hello = cast(NXOpen.BlockStyler.Toggle, top.FindBlock("hello"))
            self.name = cast(NXOpen.BlockStyler.Enumeration, top.FindBlock("name"))

            # Faces or components only. Set here rather than in the .dlx so the filter is readable.
            face = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type, 0,
                                               NXOpen.UF.UFConstants.UF_UI_SEL_FEATURE_ANY_FACE)
            component = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_component_type, 0, 0)
            selection.SetSelectionFilter(NXOpen.Selection.SelectionAction.ClearAndEnableSpecific,
                                         [face, component])
        except Exception as ex:
            self._error(ex)

    def update_cb(self, block: NXOpen.BlockStyler.UIBlock) -> int:
        try:
            if block == self.hello:
                pass
            elif block == self.name:
                pass
        except Exception as ex:
            self._error(ex)
        return 0

    def ok_cb(self) -> int:
        try:
            assert self.selection is not None and self.hello is not None and self.name is not None
            self.selected_objects = list(self.selection.GetSelectedObjects())
            self.hello_checked = self.hello.Value
            self.selected_name = self.name.ValueAsString
            self.accepted = True
            return 0
        except Exception as ex:
            self._error(ex)
            return 1

    def _error(self, ex: BaseException) -> None:
        nx.message_box("Hello Dialog", NXOpen.NXMessageBox.DialogType.Error, str(ex))


def _print(message: str) -> None:
    lw = NXOpen.Session.GetSession().ListingWindow
    lw.Open()
    lw.WriteLine(message)


def main() -> None:
    dialog: Optional[HelloDialog] = None
    try:
        dialog = HelloDialog()
        dialog.launch()

        if not dialog.accepted:
            return

        _print("hello: {}".format(dialog.hello_checked))
        _print("name: {}".format(dialog.selected_name))
        _print("selected {} object(s):".format(len(dialog.selected_objects)))

        for obj in dialog.selected_objects:
            if isinstance(obj, NXOpen.Assemblies.Component):
                _print("  component - {}".format(obj.DisplayName))
            elif isinstance(obj, NXOpen.NXObject):
                _print("  {} - {}".format(type(obj).__name__, obj.JournalIdentifier))
            else:
                _print("  {} - tag {}".format(type(obj).__name__, obj.Tag))
    except Exception as ex:
        nx.message_box("Hello Dialog", NXOpen.NXMessageBox.DialogType.Error, str(ex))
    finally:
        if dialog is not None:
            dialog.dispose()


if __name__ == "__main__":
    main()
