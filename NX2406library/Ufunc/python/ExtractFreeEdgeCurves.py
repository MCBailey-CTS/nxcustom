"""
Python port of the extract-free-edge-curves UFunc (ExtractFreeEdgeCurves.execute,
src\\UFuncs\\ExtractFreeEdgeCurves.cs).
The C# wrapper was deleted 2026-10-22 (in git at f32694f): the UFunc's menu button runs this file's main().

Select bodies; every edge that is attached to exactly one face (a free edge of a sheet) gets a curve made from
it (UF_MODL_create_curve_from_edge), which is put on the work part's work layer.

File -> Execute -> NX Open on this file runs main(), which does the selection itself like the C# UFunc.
"""

from __future__ import annotations

import os
import sys
from typing import List

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# From the source tree (src\UFuncs) the shared modules are in src\python; deployed, they are beside this file.
_shared_python = os.path.join(os.path.dirname(_here), "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402

ufunc_extract_free_edge_curves = "extract-free-edge-curves"


class ExtractFreeEdgeCurves(object):

    @staticmethod
    def execute() -> None:
        """ExtractFreeEdgeCurves.execute"""
        nx.print_("Extract Free Edge Curves - 9/17/2025 - TSG")

        if nx.display_part() is None:
            nx.print_("There is no displayed part loaded")
            return

        ufunc_rev_name = nx.ufunc_rev_name(ufunc_extract_free_edge_curves)

        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, ufunc_rev_name)

        # Allows the user to select sheet bodies.
        selected_sheet_bodies = _select_many_sheet_bodies(ufunc_rev_name)

        # Gets the free edges, (the edges that are attached to one face).
        edges = [edge
                 for body in selected_sheet_bodies
                 for edge in body.GetEdges()
                 if len(edge.GetFaces()) == 1]

        for free_edge in edges:
            # creates a curve from the edge, and places it on the work layer.
            edge_curve = nx.edge_to_curve(free_edge)
            nx.set_layer(edge_curve, _work_layer())

        nx.print_("Created {} curves, on layer {}, off of free edges.".format(len(edges), _work_layer()))


def _work_layer() -> int:
    """Extensions.WorkLayer (get) - the work part's work layer."""
    return nx.work_part().Layers.WorkLayer


def _select_many_sheet_bodies(message: str = "Select Many Sheet Bodies") -> List[NXOpen.Body]:
    """
    Selection.SelectManySheetBodies(string) - multi-select, any in assembly.

    Despite the name, the C# passes Masks.SolidBody_Mask (UF_solid_type / UF_UI_SEL_FEATURE_BODY, i.e. any
    body), so the same mask is used here. The C# rejects non-bodies with a UF filter proc inside the dialog;
    here the mask does the filtering and anything that is not a Body is dropped afterwards. Like the C#, the
    response is ignored, so a cancel is just an empty selection.
    """
    mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type, 0,
                                       NXOpen.UF.UFConstants.UF_UI_SEL_FEATURE_BODY)
    _response, objects = NXOpen.UI.GetUI().SelectionManager.SelectTaggedObjects(
        message,
        message,
        NXOpen.Selection.SelectionScope.AnyInAssembly,
        NXOpen.Selection.SelectionAction.ClearAndEnableSpecific,
        False,
        False,
        [mask])
    bodies = [obj for obj in (objects or []) if isinstance(obj, NXOpen.Body)]
    for body in bodies:
        body.Unhighlight()
    return bodies


def main() -> None:
    """The extract-free-edge-curves UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("extract-free-edge-curves"):
        try:
            # No dialog of its own: ask before doing anything (a logged Question box).
            if nx.confirm_execute("extract-free-edge-curves"):
                ExtractFreeEdgeCurves.execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
