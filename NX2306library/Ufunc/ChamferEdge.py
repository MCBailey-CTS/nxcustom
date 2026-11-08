"""
The right-click menu's Chamfer submenu (2026-11-07): a symmetric 45-degree chamfer of 1/16, 1/8 or 1/4 inch (the
same length in mm in a metric part) on the selected edges of one detail. Mirror Merlin's chamfer builder
(SymmetricOffsets, EdgesAlongFaces, an EdgeDumb rule on the edges), made in the edges' own part with their
component as the work component. The new faces take the color the two faces of each edge share; edges whose faces
differ keep NX's color. One undo mark, nothing saved.

C# runs it: the Chamfer buttons (TSG_CHAMFER_1_16 / _1_8 / _1_4 in Menuscript\\startup\\tsg_context_menu.men) launch
context-menu.dll, whose ContextMenuCommand calls ChamferEdge.chamfer_selected(inches). SessionRecord's TsgContextMenu
shows the submenu when the selection is edges of one solid body in a part with one DYNAMIC BLOCK. Nothing selected,
it asks for edges.
"""

from __future__ import annotations

import os
import sys
from typing import Any, List, Optional, Sequence, cast

# Session.Execute does not put the script's folder on sys.path, so the shared modules would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# The shared modules are in the python folder beside this file (src\UFuncs\python; deployed, Ufunc\python).
_shared_python = os.path.join(_here, "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.Features  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402

_Title = "Chamfer"
# UF_UI_SEL_FEATURE_ANY_EDGE (not in UFConstants' Python stubs).
_UF_UI_SEL_FEATURE_ANY_EDGE = 1
_Library = "g:" + chr(92) + "0library"


def _selected_edges() -> List[NXOpen.Edge]:
    selection: Any = NXOpen.UI.GetUI().SelectionManager
    count = selection.GetNumSelectedObjects()
    edges = [selection.GetSelectedTaggedObject(i) for i in range(count)]
    return [edge for edge in edges if isinstance(edge, NXOpen.Edge)]


def _pick_edges() -> List[NXOpen.Edge]:
    mask = [NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type, 0, _UF_UI_SEL_FEATURE_ANY_EDGE)]
    cue = "Select the edges to chamfer"
    nx.prompt(cue)
    response, picked = cast(Any, NXOpen.UI.GetUI().SelectionManager).SelectTaggedObjects(
        cue, _Title, NXOpen.Selection.SelectionScope.AnyInAssembly,
        NXOpen.Selection.SelectionAction.ClearAndEnableSpecific, False, False, mask)
    if response != NXOpen.Selection.Response.Ok:
        return []
    return [edge for edge in picked if isinstance(edge, NXOpen.Edge)]


def _label(inches: float) -> str:
    return {0.0625: "1/16", 0.125: "1/8", 0.25: "1/4"}.get(inches, nx.cs_double_str(inches)) + '"'


def _face_color(edge: NXOpen.Edge) -> Optional[int]:
    """The color both faces of edge share, or None."""
    colors = {face.Color for face in edge.GetFaces()}
    return colors.pop() if len(colors) == 1 else None


def chamfer(edges: Sequence[NXOpen.Edge], inches: float) -> bool:
    """
    A symmetric chamfer of inches on edges, which must be on one body; occurrence edges are chamfered in their own
    part. Returns whether it made one; an Information box says why not.
    """
    title = "{} {}".format(_Title, _label(inches))
    if not edges:
        return False
    component = edges[0].OwningComponent if edges[0].IsOccurrence else None
    prototypes: List[NXOpen.Edge] = [edge.Prototype if edge.IsOccurrence else edge for edge in edges]  # type: ignore
    bodies = {edge.GetBody().Tag for edge in prototypes}
    if len(bodies) != 1 or any((edge.OwningComponent if edge.IsOccurrence else None) != component for edge in edges):
        nx.message_box(title, NXOpen.NXMessageBox.DialogType.Information, "Select edges of one body.")
        return False
    part: Any = prototypes[0].OwningPart
    if part.FullPath.lower().startswith(_Library):
        nx.message_box(title, NXOpen.NXMessageBox.DialogType.Information, "{} is a library part.".format(part.Leaf))
        return False

    distance = inches * (25.4 if part.PartUnits == NXOpen.BasePart.Units.Millimeters else 1.0)
    colors = [_face_color(edge) for edge in prototypes]
    mark = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, title)
    previous_work = nx.session_.Parts.WorkComponent
    try:
        if component is not None:
            nx.set_work_component(component)
        else:
            nx.set_work_part(part)
        builder = part.Features.CreateChamferBuilder(None)
        try:
            builder.Option = NXOpen.Features.ChamferBuilder.ChamferOption.SymmetricOffsets
            builder.Method = NXOpen.Features.ChamferBuilder.OffsetMethod.EdgesAlongFaces
            builder.FirstOffset = nx.cs_double_str(distance)
            collector = part.ScCollectors.CreateCollector()
            collector.ReplaceRules([part.ScRuleFactory.CreateRuleEdgeDumb(prototypes)], False)
            builder.SmartCollector = collector
            feature = builder.CommitFeature()
        finally:
            builder.Destroy()
        nx.session_.UpdateManager.DoUpdate(mark)
        shared = {color for color in colors if color is not None}
        if len(shared) == 1:
            color = shared.pop()
            for face in feature.GetFaces():
                face.Color = color
                face.RedisplayObject()
    except Exception as ex:
        nx.print_exception(ex, "{}: could not chamfer {} edge(s) of {}".format(title, len(edges), part.Leaf))
        nx.session_.UndoToMark(mark, title)
        return False
    finally:
        nx.set_work_component(previous_work)

    nx.print_("{}: {} edge(s) of {}.".format(title, len(edges), part.Leaf))
    return True


class ChamferEdge(object):
    """For C# (ContextMenuCommand): PythonLibrary.Execute("ChamferEdge.py", "ChamferEdge", "chamfer_selected",
    inches)."""

    @staticmethod
    def chamfer_selected(inches: float) -> None:
        try:
            edges = _selected_edges() or _pick_edges()
            if not edges:
                nx.mark_cancelled("the edge pick")
                return
            chamfer(edges, float(inches))
        except Exception as ex:
            nx.print_exception(ex)
