"""
Python port of the WireTaperDevelopment form's static helpers (src\\Static\\WireTaperDevelopment.cs, moved
out of src\\UFuncs\\WireTaperDevelopment.cs): Static.WireTaperImportNote, WireTaperSetImportNoteLayers and
WireTaperSetDefaultLayers.

WIRED (2026-10-21), never run in NX. Static.WireTaperDevelopmentApply (the Select button's per-part pass) calls
all three through its WireTaperPython wrapper, e.g.
    PythonLibrary.Execute("WireTaperDevelopment.py", "WireTaperDevelopment", "import_note", path, scale);
passing the display part as (Part)disp. A failure is not caught there: as with the C# helpers, it ends the pass and
ButtonSelect_Click prints it. The replaced C# sits commented out in src\\Static\\WireTaperDevelopment.cs.

Not ported: WireTaperDevelopmentApply itself (the 4-VIEW update, the WTN/WFTD attributes and the note deletes)
and the component pick; they stay C#. Only the three helpers it calls are here.
"""

from __future__ import annotations

import os
import sys

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.Layer  # noqa: E402

import tsg_nx as nx  # noqa: E402


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
