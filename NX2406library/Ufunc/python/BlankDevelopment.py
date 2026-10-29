"""
Python port of the blank-development UFunc (BlankDevelopment, src\\UFuncs\\BlankDevelopment.cs).
The C# wrapper was deleted 2026-10-22 (in git at f32694f): the UFunc's menu button runs this file's main().

Select curves, then a line: the line is lengthened (non-associatively, the original replaced) by the total length
of the selected curves, at the end chosen by the help point that AskPositionOnObject puts on the line.

Run standalone: File -> Execute -> NX Open on this file runs main().

Differences from the C#:
  - Selection.SelectSingleLine is a UF single-select dialog with a filter proc; Python cannot host UF callbacks,
    so the line is picked through SelectionManager.SelectTaggedObject with a line mask (same prompt/title).
  - MapAbsoluteToView / MapViewToAbsolute build a UF_TRNS mapping matrix between the absolute csys and the last
    picked view's csys and map one point through it. With both origins at zero that is a pure rotation, so it is
    computed directly from the view matrix here (same numbers, no UF out-array plumbing).
  - AskPositionOnObject's temporary line is created with Part.Curves.CreateLine rather than UF_CURVE_create_line;
    it is deleted with UF_OBJ_delete_object either way.
  - AskCloserToStartOrEnd is a no-op here: the C# evaluates the curve's ends and the closest point, then discards
    every result (both Vec3.Distance outputs go to `out _`), so it has no effect to port.
"""

from __future__ import annotations

import os
import sys
from typing import Any, List, Optional, Sequence, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# From the source tree (src\UFuncs) the shared modules are in src\python; deployed, they are beside this file.
_shared_python = os.path.join(os.path.dirname(_here), "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.Features  # noqa: E402
import NXOpen.GeometricUtilities  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402

ufunc_name = "blank-development"


class BlankDevelopment(object):

    @staticmethod
    def execute() -> None:
        """BlankDevelopment.execute"""
        message = "{} - Blank Development".format(nx.assembly_file_version())

        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, nx.ufunc_rev_name(ufunc_name))
        length_objs = _select_curves(message, message)

        if len(length_objs) == 0:
            return

        # get total length of selected lines
        add_length = sum(curve.GetLength() for curve in length_objs)

        # get user input for the line to develop
        develop_obj = _select_single_line()

        if develop_obj is None:
            return

        # get user selection for which end of the line to extend
        cursor = [0.0, 0.0, 0.0]
        cursor = _ask_position_on_object(develop_obj.Tag, cursor)
        _ask_closer_to_start_or_end(develop_obj.Tag, cursor)
        # move closest point distance and direction
        _edit_curve_length(develop_obj, add_length, cursor)


def _select_curves(message: str = "Select Curves", title: str = "Select Curves") -> List[NXOpen.Curve]:
    """Selection.SelectCurves - SelectTaggedObjects(message, title, AnyInAssembly, false, [SelectionType.Curves]).
    The C# casts every pick to Curve; so does this (a non-curve raises)."""
    _response, objects = cast(Any, NXOpen.UI.GetUI().SelectionManager).SelectTaggedObjects(
        message,
        title,
        NXOpen.Selection.SelectionScope.AnyInAssembly,
        False,
        [NXOpen.Selection.SelectionType.Curves])

    curves: List[NXOpen.Curve] = []
    for obj in (objects or []):
        if not isinstance(obj, NXOpen.Curve):
            raise TypeError("Unable to cast object of type '{}' to type 'NXOpen.Curve'.".format(type(obj).__name__))
        curves.append(obj)
    return curves


def _select_single_line() -> Optional[NXOpen.Line]:
    """Selection.SelectSingleLine - "Select Single Line", line mask, any in assembly. None on cancel; the pick is
    unhighlighted."""
    mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_line_type, 0, 0)
    response, obj, _cursor = NXOpen.UI.GetUI().SelectionManager.SelectTaggedObject(
        "Select Single Line",
        "Select Single Line",
        NXOpen.Selection.SelectionScope.AnyInAssembly,
        NXOpen.Selection.SelectionAction.ClearAndEnableSpecific,
        False,
        False,
        [mask])

    if response not in (NXOpen.Selection.Response.Ok, NXOpen.Selection.Response.ObjectSelected,
                        NXOpen.Selection.Response.ObjectSelectedByName):
        return None

    if not isinstance(obj, NXOpen.Line):
        return None

    obj.Unhighlight()
    return obj


def _edit_curve_length(edit_line: NXOpen.Line, edit_length: float, cursor: Sequence[float]) -> None:
    """BlankDevelopment.EditCurveLength"""
    work_part = nx.work_part()
    section1 = work_part.Sections.CreateSection(0.0095, 0.01, 0.5)
    builder = work_part.Features.CreateCurvelengthBuilder(None)

    # using (__UsingDoUpdate("Edit Curve Length")) using (__UsingBuilderDestroyer(builder)) - the builder is
    # destroyed first, then the update runs.
    with nx.do_update("Edit Curve Length"):
        try:
            builder.Section = section1
            builder.DistanceTolerance = 0.01
            builder.CurveOptions.Associative = False
            builder.CurveOptions.InputCurveOption = NXOpen.GeometricUtilities.CurveOptions.InputCurve.Replace
            builder.CurvelengthData.ExtensionMethod = NXOpen.GeometricUtilities.ExtensionMethod.Incremental
            builder.CurvelengthData.ExtensionSide = NXOpen.GeometricUtilities.ExtensionSide.Symmetric
            builder.CurvelengthData.ExtensionDirection = NXOpen.GeometricUtilities.ExtensionDirection.Natural
            section1.DistanceTolerance = 0.01
            section1.ChainingTolerance = 0.0095
            section1.SetAllowedEntityTypes(NXOpen.Section.AllowTypes.OnlyCurves)
            builder.CurvelengthData.ExtensionSide = NXOpen.GeometricUtilities.ExtensionSide.StartEnd
            curves1: List[NXOpen.Curve] = [edit_line]
            curve_dumb_rule1 = work_part.ScRuleFactory.CreateRuleCurveDumb(curves1)
            section1.AllowSelfIntersection(True)
            rules1 = [curve_dumb_rule1]
            help_point1 = NXOpen.Point3d(cursor[0], cursor[1], cursor[2])
            section1.AddToSection(rules1, edit_line, None, None, help_point1, NXOpen.Section.Mode.Create, False)
            builder.CurvelengthData.SetStartDistance(nx.cs_double_str(edit_length))
            builder.CurvelengthData.SetEndDistance("0")
            builder.CurveOptions.InputCurveOption = NXOpen.GeometricUtilities.CurveOptions.InputCurve.Retain
            builder.Commit()
        finally:
            builder.Destroy()


def _ask_closer_to_start_or_end(curve: NXOpen.Tag, cursor_location: Sequence[float]) -> None:
    """BlankDevelopment.AskCloserToStartOrEnd - the C# evaluates the curve's limits, end points and the point
    closest to cursor_location, measures both distances and throws every result away. Nothing observable to port."""
    return None


def _last_picked_view_axes() -> List[List[float]]:
    """The view-matrix half of MapViewToAbsolute / MapAbsoluteToView: the X, Y and Z axes of the work part's
    modeling view named by UF_UI_ask_last_picked_view. Z is X x Y, as UF_TRNS derives it from a 9-value csys."""
    # The pyd documents the return as "list of str" (it is a char buffer in C); accept either form.
    view_name: Any = nx.ufsession_.Ui.AskLastPickedView()
    if not isinstance(view_name, str):
        view_name = "".join(view_name)
    last_view_picked = nx.work_part().ModelingViews.FindObject(view_name)
    m = last_view_picked.Matrix
    x = [m.Xx, m.Xy, m.Xz]
    y = [m.Yx, m.Yy, m.Yz]
    z = [x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0]]
    return [x, y, z]


def _map_view_to_absolute(cursor_location: Sequence[float]) -> List[float]:
    """BlankDevelopment.MapViewToAbsolute - a point in last-picked-view coordinates, in absolute coordinates."""
    axes = _last_picked_view_axes()
    return [sum(cursor_location[j] * axes[j][i] for j in range(3)) for i in range(3)]


def _map_absolute_to_view(cursor_location: Sequence[float]) -> List[float]:
    """BlankDevelopment.MapAbsoluteToView - a point in absolute coordinates, in last-picked-view coordinates."""
    axes = _last_picked_view_axes()
    return [sum(cursor_location[i] * axes[j][i] for i in range(3)) for j in range(3)]


def _ask_position_on_object(obj: NXOpen.Tag, cursor_location: Sequence[float]) -> List[float]:
    """
    BlankDevelopment.AskPositionOnObject - a line through cursor_location along the last picked view's Z (+/-10000
    either side), then the point on obj closest to it. The C# writes that point back into the cursor array; here it
    is returned.
    """
    view_point = _map_absolute_to_view(cursor_location)
    start_point = _map_view_to_absolute([view_point[0], view_point[1], view_point[2] + 10000])
    end_point = _map_view_to_absolute([view_point[0], view_point[1], view_point[2] - 10000])

    a_line = nx.work_part().Curves.CreateLine(
        NXOpen.Point3d(start_point[0], start_point[1], start_point[2]),
        NXOpen.Point3d(end_point[0], end_point[1], end_point[2]))

    cp = [0.0, 0.0, 0.0]
    try:
        result: Any = nx.ufsession_.Modeling.AskMinimumDist(obj, a_line.Tag, 0, cp, 0, cp)
    finally:
        nx.ufsession_.Obj.DeleteObject(a_line.Tag)

    # The pyd documents the return as (minDist, ptOnObj1, ptOnObj2); ptOnObj1 is the point on obj.
    _min_dist, pt_on_obj1, _pt_on_obj2 = result
    return [float(v) for v in pt_on_obj1]


def main() -> None:
    """The blank-development UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("blank-development"):
        try:
            # No dialog of its own: ask before doing anything (a logged Question box).
            if nx.confirm_execute("blank-development"):
                BlankDevelopment.execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
