"""
Python port of the circle-from-spline UFunc (CircleFromSpline.execute, src\\UFuncs\\CircleFromSpline.cs).
The C# wrapper was deleted 2026-10-22 (in git at f32694f): the UFunc's menu button runs this file's main().

Select a spline; an arc is made through three points on it (at the start parameter, and at .33 and .66 of
the parameter span), opened up to a full circle, and the spline and circle are listed with Information ->
Object. Repeats with a fresh spline pick until the user cancels.

File -> Execute -> NX Open on this file runs main(), which does the selection itself like the C# UFunc.

Difference from the C#: NX's Python UF layer has no UF_EVAL_evaluate (nor UF_EVAL_free - the evaluator
wrapper frees itself), so each point comes from UF_EVAL_evaluate_unit_vectors at the same (unnormalized)
parameter. The position it returns is the same point UF_EVAL_evaluate gives with derivative order 0.
"""

from __future__ import annotations

import math
import os
import sys
from typing import Any, Optional, cast

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

ufunc_circle_from_spline = "circle-from-spline"


class CircleFromSpline(object):

    @staticmethod
    def execute() -> None:
        """CircleFromSpline.execute"""
        if nx.display_part() is None:
            nx.print_("There is no displayed part loaded")
            return

        ufunc_rev_name = nx.ufunc_rev_name(ufunc_circle_from_spline)

        sel_object = _select_single_spline(ufunc_rev_name)

        if sel_object is None:
            return

        while True:
            nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, ufunc_rev_name)
            spline1 = sel_object
            evaluator = nx.ufsession_.Eval.Initialize(spline1.Tag)
            limits = nx.ufsession_.Eval.AskLimits(evaluator)
            # As in the C#, the .33/.66 parameters are fractions of the span, not offset by limits[0].
            point_on_curve1 = _evaluate_position(evaluator, limits[0])
            point_on_curve2 = _evaluate_position(evaluator, (limits[1] - limits[0]) * .33)
            point_on_curve3 = _evaluate_position(evaluator, (limits[1] - limits[0]) * .66)
            start_point1 = _to_point3d(point_on_curve1)
            point_on1 = _to_point3d(point_on_curve2)
            end_point1 = _to_point3d(point_on_curve3)
            arc1 = _create_arc(nx.work_part(), start_point1, point_on1, end_point1)
            arc_data = nx.ufsession_.Curve.AskArcData(arc1.Tag)
            arc_data.StartAngle = 0
            arc_data.EndAngle = 2 * math.pi
            nx.ufsession_.Curve.EditArcData(arc1.Tag, arc_data)
            selected_objects1 = [spline1, arc1]
            nx.session_.Information.DisplayObjectsDetails(selected_objects1)
            sel_object = _select_single_spline()

            if sel_object is None:
                break


def _evaluate_position(evaluator: Any, parameter: float) -> list:
    """
    ufsession_.Eval.Evaluate(evaluator, 0, parameter, point, derivatives) - the position only. Python has no
    Eval.Evaluate; EvaluateUnitVectors returns (point, tangent, normal, binormal) at the same parameter.
    """
    return list(nx.ufsession_.Eval.EvaluateUnitVectors(evaluator, parameter)[0])


def _to_point3d(array: list) -> NXOpen.Point3d:
    """double[].__ToPoint3d"""
    return NXOpen.Point3d(array[0], array[1], array[2])


def _create_arc(part: NXOpen.Part, start_point: NXOpen.Point3d, point_on: NXOpen.Point3d,
                end_point: NXOpen.Point3d) -> NXOpen.Arc:
    """CurveCollection.CreateArc(start, pointOn, end, alternateSolution: false, out flipped) - flipped discarded."""
    result: Any = part.Curves.CreateArc(start_point, point_on, end_point, False)
    # The C# out bool comes back alongside the arc in a tuple.
    if isinstance(result, (tuple, list)):
        result = result[0]
    return cast(NXOpen.Arc, result)


def _select_single_spline(message: str = "Select Single Spline") -> Optional[NXOpen.Spline]:
    """
    Selection.SelectSingleSpline(message) - single pick, any in assembly, spline mask. None on cancel.

    The C# rejects non-splines with a UF filter proc inside the dialog; here the mask does the filtering and
    anything that is not a Spline is treated as no selection.
    """
    mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_spline_type, 0, 0)
    result: Any = NXOpen.UI.GetUI().SelectionManager.SelectTaggedObject(
        message,
        message,
        NXOpen.Selection.SelectionScope.AnyInAssembly,
        NXOpen.Selection.SelectionAction.ClearAndEnableSpecific,
        False,
        False,
        [mask])
    # (response, object, cursor)
    obj = result[1] if isinstance(result, (tuple, list)) and len(result) > 1 else None

    if not isinstance(obj, NXOpen.Spline):
        return None

    obj.Unhighlight()
    return obj


def main() -> None:
    """The circle-from-spline UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("circle-from-spline"):
        try:
            # No dialog of its own: ask before doing anything (a logged Question box).
            if nx.confirm_execute("circle-from-spline"):
                CircleFromSpline.execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
