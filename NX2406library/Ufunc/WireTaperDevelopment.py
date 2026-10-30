"""
Python port of the WireTaperDevelopment form's static helpers (src\\Static\\WireTaperDevelopment.cs, moved
out of src\\UFuncs\\WireTaperDevelopment.cs): Static.WireTaperImportNote, WireTaperSetImportNoteLayers and
WireTaperSetDefaultLayers.

PYTHON ONLY since 2026-10-30: the wire-taper-development UFunc's menu button runs this file's main(), a Block Styler
dialog (WireTaperDevelopment.dlx, _WireTaperDialog) in place of the WinForms form, and apply() is
Static.WireTaperDevelopmentApply (the Select button's per-part pass). The form and src\\Static\\WireTaperDevelopment.cs
are in git at 97eb2a6; this module moved from src\\python the same day. Never run in NX.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Sequence

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# The shared modules are in the python folder beside this file (src\UFuncs\python; deployed, Ufunc\python).
_shared_python = os.path.join(_here, "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.Annotations  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.Layer  # noqa: E402

import tsg_nx as nx  # noqa: E402
from tsg_dialog import Dialog, components_of, title_with_version  # noqa: E402


def _hide_category_all(part: NXOpen.Part) -> None:
    """The shared middle of both layer setups: hides every layer in the "ALL" category, in one SetStates."""
    layer_state = part.Layers.GetStates()

    for category in part.LayerCategories:
        if category.Name == "ALL":
            layer_state.SetStateOfCategory(category, NXOpen.Layer.State.Hidden)

    part.Layers.SetStates(layer_state, True)
    layer_state.Dispose()


class WireTaperDevelopment(object):

    @staticmethod
    def import_note(note_path: str, import_scale: float) -> None:
        """Static.WireTaperImportNote - imports a note part into the work part at the work csys, on the work
        layer, scaled by import_scale."""
        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "Import Part")
        # The C# casts the Importer to PartImporter; Python gets the concrete type back already.
        part_importer1 = nx.work_part().ImportManager.CreatePartImporter()
        part_importer1.FileName = note_path
        part_importer1.Scale = import_scale
        part_importer1.CreateNamedGroup = False
        part_importer1.ImportViews = False
        part_importer1.ImportCamObjects = False
        part_importer1.LayerOption = NXOpen.PartImporter.LayerOptionType.Work
        part_importer1.DestinationCoordinateSystemSpecification = \
            NXOpen.PartImporter.DestinationCoordinateSystemSpecificationType.Work
        n_x_matrix1 = nx.work_part().NXMatrices.Create(nx.identity_matrix())
        part_importer1.DestinationCoordinateSystem = n_x_matrix1
        destination_point1 = NXOpen.Point3d(0.0, 0.0, 0.0)
        part_importer1.DestinationPoint = destination_point1
        mark_id2 = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "Import Part Commit")
        part_importer1.Commit()
        nx.session_.DeleteUndoMark(mark_id2, None)
        part_importer1.Destroy()

    @staticmethod
    def set_import_note_layers(part: NXOpen.Part) -> None:
        """Static.WireTaperSetImportNoteLayers - work layer 200, category ALL hidden, 1/94/231 selectable."""
        part.Layers.SetState(200, NXOpen.Layer.State.WorkLayer)
        _hide_category_all(part)
        part.Layers.SetState(1, NXOpen.Layer.State.Selectable)
        part.Layers.SetState(94, NXOpen.Layer.State.Selectable)
        part.Layers.SetState(231, NXOpen.Layer.State.Selectable)

    @staticmethod
    def set_default_layers(part: NXOpen.Part) -> None:
        """Static.WireTaperSetDefaultLayers - work layer 1, category ALL hidden, 94/99/200/230 selectable."""
        part.Layers.SetState(1, NXOpen.Layer.State.WorkLayer)
        _hide_category_all(part)
        part.Layers.SetState(94, NXOpen.Layer.State.Selectable)
        part.Layers.SetState(99, NXOpen.Layer.State.Selectable)
        part.Layers.SetState(200, NXOpen.Layer.State.Selectable)
        part.Layers.SetState(230, NXOpen.Layer.State.Selectable)


# ---------------------------------------------------------------------------------------------------
# Static.WireTaperDevelopmentApply and the dialog (2026-10-30)
# ---------------------------------------------------------------------------------------------------

ufunc_name = "wire-taper-development"

# The two radios' values (WireTaperDevelopment.dlx).
NoteNone, NoteAdd, NoteRemove = "None", "Add", "Remove"

_WireNotePath = "G:\\0Library\\Drafting\\wire-note.prt"
_TrimNotePath = "G:\\0Library\\Drafting\\trim-note.prt"
_WireNoteText = "TSG STANDARD"
_TrimNoteText = "WAITING FOR FINAL TRIM"
_NoteLayer = 200
# UF_DRAW_set_display_state: 1 = modeling.
_DisplayStateModeling = 1
# Drafting / rendering members the hand-written NXOpen stubs lack.
_NX: Any = NXOpen


def _first_line(note: Any) -> str:
    text = note.GetText()
    return text[0] if text else ""


def apply(components: Sequence[NXOpen.Assemblies.Component], wire_taper_note: str, trim_note: str) -> None:
    """
    Static.WireTaperDevelopmentApply - for each picked component's part (displayed in turn): the import-note layers,
    modeling view in static wireframe, every drafting view on the 4-VIEW sheet updated, WTN / WFTD set to YES (Add) or
    NO (Remove); then, on a part with a 4-VIEW sheet, the layer-200 notes of a changed kind deleted ("TSG STANDARD"
    for the wire taper note, "WAITING FOR FINAL TRIM" for the trim one) and, for Add, the note part imported again at
    the borderScale expression's value (1 without one), then the default layers. A failure ends the pass, as in the C#.
    """
    add_wtn, remove_wtn = wire_taper_note == NoteAdd, wire_taper_note == NoteRemove
    add_wftd, remove_wftd = trim_note == NoteAdd, trim_note == NoteRemove

    with nx.display_part_reset():
        for comp in components:
            nx.set_display_part(nx.prototype(comp))
            disp: Any = nx.display_part()
            WireTaperDevelopment.set_import_note_layers(disp)
            nx.ufsession_.Draw.SetDisplayState(_DisplayStateModeling)
            disp.ModelingViews.WorkView.RenderingStyle = _NX.View.RenderingStyleType.StaticWireframe

            is_4_view = False
            for sheet in disp.DrawingSheets:
                if sheet.Name != "4-VIEW":
                    continue
                sheet.Open()
                is_4_view = True
                for view in sheet.GetDraftingViews():
                    view.Update()

            if add_wtn:
                nx.set_attribute(disp, "WTN", "YES")
            if add_wftd:
                nx.set_attribute(disp, "WFTD", "YES")
            if remove_wtn:
                nx.set_attribute(disp, "WTN", "NO")
            if remove_wftd:
                nx.set_attribute(disp, "WFTD", "NO")

            if not is_4_view:
                continue

            to_delete: List[NXOpen.TaggedObject] = []
            for note in disp.Notes:
                if note.Layer != _NoteLayer:
                    continue
                line = _first_line(note)
                if ((add_wtn or remove_wtn) and _WireNoteText in line) or \
                        ((add_wftd or remove_wftd) and _TrimNoteText in line):
                    to_delete.append(note)
            if to_delete:
                nx.delete_objects(to_delete)

            scale = 1.0
            for expression in disp.Expressions:
                if expression.Name == "borderScale":
                    scale = expression.GetValueUsingUnits(_NX.Expression.UnitsOption.Expression)

            if add_wtn:
                WireTaperDevelopment.import_note(_WireNotePath, scale)
            if add_wftd:
                WireTaperDevelopment.import_note(_TrimNotePath, scale)

            WireTaperDevelopment.set_default_layers(disp)

    nx.ufsession_.Draw.SetDisplayState(_DisplayStateModeling)


class _WireTaperDialog(Dialog):
    """
    WireTaperDevelopment.dlx, in place of the WinForms form: the Wire Taper Note and Trim Development Note radios
    (None / Add / Remove) and the components (the Select button's pick, now in the dialog; one per display name, as
    the C#'s DistinctBy). OK runs the pass and closes; Apply runs it, clears the pick and sets both radios back to
    None, as the form's finally did.
    """

    dlx_name = "WireTaperDevelopment.dlx"

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__()

    def initialize(self) -> None:
        self.component_filter(self.block("components"))
        self.assembly_scope(self.block("components"))

    def shown(self) -> None:
        # MainForm_Load: both radios on None.
        self._reset_radios()

    def enable_ok(self) -> bool:
        return len(self._picked()) > 0

    def ok(self) -> bool:
        picked = self._picked()
        if not picked:
            self.message("Select the components.")
            return False
        unique: Dict[str, NXOpen.Assemblies.Component] = {}
        for comp in picked:
            unique.setdefault(comp.DisplayName, comp)
        try:
            apply(list(unique.values()), str(self.block("wire_taper_note").ValueAsString),
                  str(self.block("trim_note").ValueAsString))
        except Exception as ex:
            # ButtonSelect_Click's catch.
            nx.print_exception(ex)
        return True

    def apply(self) -> bool:
        if not self.ok():
            return False
        self.block("components").SetSelectedObjects([])
        self._reset_radios()
        return True

    def _picked(self) -> List[NXOpen.Assemblies.Component]:
        return components_of(self.selected(self.block("components")))

    def _reset_radios(self) -> None:
        self.block("wire_taper_note").ValueAsString = NoteNone
        self.block("trim_note").ValueAsString = NoteNone


def main() -> None:
    """The wire-taper-development UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            _WireTaperDialog(title_with_version("Wire Taper Development")).run()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
