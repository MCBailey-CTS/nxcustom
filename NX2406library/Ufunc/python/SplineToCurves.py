"""
Python port of the spline-to-curves UFunc (SplineToCurves.execute, src\\UFuncs\\SplineToCurves.cs).
The C# wrapper was deleted 2026-10-22 (in git at f32694f): the UFunc's menu button runs this file's main().

Select curves; each one longer than .050 is sampled into points (UF_MODL_ask_curve_points), the curves are
chained end to end (GetCurveOrder, run once from the first curve's start and once from its end), the chained
points are fed to one degree-3 spline through points, that spline is simplified into lines and arcs
(UF_CURVE_create_simplified_curve) and then deleted.

File -> Execute -> NX Open on this file runs main(), which does the selection itself like the C# UFunc.

Differences from the C#:
  - NX's Python UF layer has no Modl.AskCurvePoints, so _ask_curve_points calls UF_MODL_ask_curve_points
    in libufun.dll through ctypes - the same Open C function the .NET wrapper calls.
  - The fixed-size C# arrays (100000 points, 200 curves) are kept as lists of the same size, so running past
    them fails the same way (an IndexError, printed by the outer except).
  - RecallPointsFillArray is ported as written, including its loop that never ends if the chain does not
    lead back to endCurve - the C# hangs NX in the same case.
"""

from __future__ import annotations

import ctypes
import math
import os
import sys
from typing import Any, List, Sequence, Tuple

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

ufunc_spline_to_curves = "spline-to-curves"

MaxLength = 100000

# 8	the other curves start / end that is closest to this curve's end(3)
# 7	the other curves start / end that is closest to this curve's start(2)
# 6	the other curve's array loc that is closest to this curve's end(3)
# 5	the other curve's array loc that is closest to this curve's start(2)
# 4	this curve's tag
# 3	this curve's xyz (end)
# 2	this curve's xyz (start)
# 1	extracted  yes(1) / no(0), NOT used.
# 0	recall order, NOT used.


class SplineToCurves(object):

    @staticmethod
    def execute() -> None:
        """SplineToCurves.execute"""
        try:
            # generate curve pts tol \/
            tolerances = [0.005, 0.1, 1.0]  # 0.005,, was 0.01, 0.1, 1.0
            # create new geom tolerance \/
            tolerance = 0.05  # 0.05 was 0.125
            jump_gap = 1.0  # was 2.0
            pts: List[List[float]] = [[0.0, 0.0, 0.0] for _ in range(MaxLength)]
            xyz: List[List[float]] = [[0.0, 0.0, 0.0] for _ in range(MaxLength)]
            current_curve = 0
            current_curve_end = 2
            num_of_curves = 0
            num_of_lines = 0
            orig_line_data: List[List[float]] = [[0.0] * 7 for _ in range(200)]
            curves_se: List[List[int]] = [[0] * 9 for _ in range(200)]
            jump_gap, tolerance = _get_part_units(tolerances, jump_gap, tolerance)
            curves = [curve.Tag for curve in _select_curves(nx.ufunc_rev_name(ufunc_spline_to_curves))]

            if len(curves) == 0:
                return

            nx.ufsession_.Disp.Refresh()

            for cc in range(len(curves)):
                num_of_curves, num_of_lines = _process_curve(
                    tolerances, curves[cc], num_of_curves, curves_se, xyz, orig_line_data, num_of_lines)

            _get_curve_order(num_of_curves, current_curve, current_curve_end, jump_gap, curves_se, xyz)
            current_curve_end = 3
            _get_curve_order(num_of_curves, current_curve, current_curve_end, jump_gap, curves_se, xyz)
            ret, num_of_pts = _recall_points_fill_array(num_of_curves, curves_se, 0, pts, xyz)

            if ret != 0:
                return

            point_data = []

            for ii in range(num_of_pts):
                data: Any = NXOpen.UF.Curve.PtSlopeCrvatr()
                data.Point = list(pts[ii])
                data.SlopeType = (NXOpen.UF.UFConstants.UF_CURVE_SLOPE_AUTO
                                  if ii == 0 or ii == num_of_pts
                                  else NXOpen.UF.UFConstants.UF_CURVE_SLOPE_NONE)
                data.CrvatrType = NXOpen.UF.UFConstants.UF_CURVE_CRVATR_NONE
                # The C# leaves these null; NX ignores them for SLOPE_NONE/AUTO and CRVATR_NONE.
                data.Slope = [0.0, 0.0, 0.0]
                data.Crvatr = [0.0, 0.0, 0.0]
                point_data.append(data)

            spline = nx.ufsession_.Curve.CreateSplineThruPts(3, 0, num_of_pts, point_data, None, 0)
            nx.ufsession_.Curve.CreateSimplifiedCurve(1, [spline], tolerance)

            _delete(nx.tagged_object(spline))
        except Exception as ex:
            nx.print_exception(ex)


def _get_part_units(g_tolerances: List[float], jump_gap: float, tolerance: float) -> Tuple[float, float]:
    """SplineToCurves.GetPartUnits - the ref jumpGap/tolerance come back as (jump_gap, tolerance)."""
    part_tag = nx.ufsession_.Part.AskDisplayPart()
    part_units = nx.ufsession_.Part.AskUnits(part_tag)

    if part_units != NXOpen.UF.UFConstants.UF_PART_ENGLISH:
        return jump_gap, tolerance

    jump_gap = 0.07
    g_tolerances[0] = 0.0002
    tolerance = 0.001
    return jump_gap, tolerance


def _get_curve_order(num_of_curves: int, current_curve: int, current_curve_end: int, jump_gap: float,
                     curves_se: List[List[int]], xyz: List[List[float]]) -> None:
    """SplineToCurves.GetCurveOrder"""
    curve_match = 0
    done = 0

    while done == 0:
        dist = 1000000.0
        end_match = False
        start_match = False

        for jj in range(num_of_curves):
            if jj == current_curve:
                continue

            here = xyz[curves_se[current_curve][current_curve_end]]

            if curves_se[jj][7] == 0:  # Start of curve has NOT been matched up yet
                other = xyz[curves_se[jj][2]]
                tmp_dist = _check_distance(here[0], here[1], here[2], other[0], other[1], other[2])

                if tmp_dist < dist:
                    dist = tmp_dist
                    curve_match = jj
                    start_match = True
                    end_match = False

            if curves_se[jj][8] != 0:
                continue  # End of curve has NOT been matched up yet

            other = xyz[curves_se[jj][3]]
            tmp_dist = _check_distance(here[0], here[1], here[2], other[0], other[1], other[2])

            if not (tmp_dist < dist):
                continue

            dist = tmp_dist
            curve_match = jj
            end_match = True
            start_match = False

        if dist >= jump_gap:
            done = 1
            continue

        if start_match:
            curves_se[curve_match][7] = current_curve_end
            curves_se[curve_match][5] = current_curve

            if current_curve_end == 2:
                curves_se[current_curve][5] = curve_match
                curves_se[current_curve][7] = 2
            elif current_curve_end == 3:
                curves_se[current_curve][6] = curve_match
                curves_se[current_curve][8] = 2

            current_curve = curve_match
            current_curve_end = 3
            continue

        if not end_match:
            continue

        # set the curve we just matched to, = to curve number we compared to
        curves_se[curve_match][6] = current_curve
        # set the curve we just matches to, = to start(2) / end(3)
        curves_se[curve_match][8] = current_curve_end

        if current_curve_end == 2:
            # We have a match to other curves end, so set to (3) end
            curves_se[current_curve][7] = 3
            # number of curve closest to this end
            curves_se[current_curve][5] = curve_match
        elif current_curve_end == 3:
            #  We have a match to other curves end, so set to (3) end
            curves_se[current_curve][8] = 3
            #  number of curve closest to this end
            curves_se[current_curve][6] = curve_match

        # The NEW curve to match up end to
        current_curve = curve_match
        # we matched up the end(3) of this NEW curve, so we will look for match to start(2) of it
        current_curve_end = 2


def _check_distance(x1: float, y1: float, z1: float, x2: float, y2: float, z2: float) -> float:
    """SplineToCurves.CheckDistance"""
    return math.sqrt((x1 - x2) * (x1 - x2) + (y1 - y2) * (y1 - y2) + (z1 - z2) * (z1 - z2))


def _process_curve(p_tolerances: Sequence[float], curve: NXOpen.Tag, num_of_curves: int,
                   curves_se: List[List[int]], xyz: List[List[float]], orig_line_data: List[List[float]],
                   num_of_lines: int) -> Tuple[int, int]:
    """SplineToCurves.ProcessCurve - the ref numOfCurves/numOfLines come back as (num_of_curves, num_of_lines)."""
    arc_length = nx.ufsession_.Curve.AskArcLength(curve, 0.0, 1.0, NXOpen.UF.Modl.Units.UNITS_PART)

    if not (arc_length > 0.050):
        return num_of_curves, num_of_lines

    np_, pts = _ask_curve_points(curve, p_tolerances[0], p_tolerances[1], p_tolerances[2])
    curves_se[num_of_curves][4] = int(curve)  # curve tag
    curves_se[num_of_curves][3] = curves_se[num_of_curves][2] + (np_ - 1)  # end loc
    curves_se[num_of_curves + 1][2] = curves_se[num_of_curves][2] + np_  # next start loc
    curves_se[num_of_curves][0] = -1  # recall order
    evaluator = nx.ufsession_.Eval.Initialize(curve)
    is_line = nx.ufsession_.Eval.IsLine(evaluator)

    if is_line:
        line = nx.ufsession_.Eval.AskLine(evaluator)
        orig_line_data[num_of_lines][0] = line.Start[0]
        orig_line_data[num_of_lines][1] = line.Start[1]
        orig_line_data[num_of_lines][2] = line.Start[2]
        orig_line_data[num_of_lines][3] = line.End[0]
        orig_line_data[num_of_lines][4] = line.End[1]
        orig_line_data[num_of_lines][5] = line.End[2]
        orig_line_data[num_of_lines][6] = line.Length
        num_of_lines += 1

    for i in range(np_):
        j = i * 3
        xyz[curves_se[num_of_curves][2] + i][0] = pts[j]
        xyz[curves_se[num_of_curves][2] + i][1] = pts[j + 1]
        xyz[curves_se[num_of_curves][2] + i][2] = pts[j + 2]

    num_of_curves += 1
    return num_of_curves, num_of_lines


def _recall_points_fill_array(num_of_curves: int, curves_se: List[List[int]], num_of_pts: int,
                              pts: List[List[float]], xyz: List[List[float]]) -> Tuple[int, int]:
    """SplineToCurves.RecallPointsFillArray - returns (ret, num_of_pts); the C# numOfPts is a ref."""

    def copy(source: List[float], index: int) -> None:
        # ufsession_.Vec3.Copy(xyz[jj], pts[numOfPts])
        pts[index][0] = source[0]
        pts[index][1] = source[1]
        pts[index][2] = source[2]

    done = False
    enable_close = False
    make_start = False
    dist = 1.0
    end_cnt = 0
    start_cnt = 0
    start_end_cnt = 0
    end_curve = 0
    start_curve = 0
    start_curve_end = 0

    for ii in range(num_of_curves):
        if curves_se[ii][7] == 0:
            start_cnt += 1

        if curves_se[ii][8] == 0:
            end_cnt += 1

    if start_cnt == 2 and end_cnt == 0:
        pass
    elif end_cnt == 2 and start_cnt == 0:
        make_start = True

    for ii in range(num_of_curves):
        if curves_se[ii][7] == 0:
            start_end_cnt += 1
            start_curve = ii
            start_curve_end = 2

        if curves_se[ii][8] != 0:
            continue

        if make_start and start_end_cnt == 1:
            start_end_cnt += 1
            start_curve = ii
            start_curve_end = 3
            continue

        start_end_cnt += 1
        end_curve = ii

    if start_end_cnt != 0 and start_end_cnt != 2:
        return 1, num_of_pts  # 0 = Contour is closed, 2 = Contour is open

    if start_end_cnt == 0:
        # Contour is closed, so just start at 1st curve
        start_curve = 0
        # endCurve = 654321;        Added this
        start_curve_end = 2
        curves_se[0][0] = 0

    cc = start_curve
    cce = start_curve_end

    while not done:
        # current curve end is 0, as in there is NO end, we are on the last curve
        if cce == 0 and cc == end_curve:
            for jj in range(curves_se[cc][2], curves_se[cc][3] + 1):
                copy(xyz[jj], num_of_pts)
                num_of_pts += 1

            done = True
        # current curve end is 0, as in there is NO end, we are on the last curve
        elif (cce == 0 or enable_close) and cc == end_curve:
            done = True
        # current curve end is start(2), so go from start(2) to end(3)
        elif cce == 2:
            for jj in range(curves_se[cc][2], curves_se[cc][3] + 1):
                copy(xyz[jj], num_of_pts)
                num_of_pts += 1

            if curves_se[cc][8] == 0:
                done = True
            elif curves_se[cc][8] == 2:
                other = xyz[curves_se[curves_se[cc][6]][2]]
                last = pts[num_of_pts - 1]
                dist = _check_distance(last[0], last[1], last[2], other[0], other[1], other[2])
            elif curves_se[cc][8] == 3:
                other = xyz[curves_se[curves_se[cc][6]][3]]
                last = pts[num_of_pts - 1]
                dist = _check_distance(last[0], last[1], last[2], other[0], other[1], other[2])

            if enable_close and curves_se[cc][6] == 0:
                pass
            else:
                if dist < 0.70:
                    num_of_pts -= 1

            cce = curves_se[cc][8]  # Set cce to the end of next curve
            cc = curves_se[cc][6]  # Set cc to the next curve
        elif cce == 3:  # current curve end is end(3), so go from end(3) to start(2)
            for jj in range(curves_se[cc][3], curves_se[cc][2] - 1, -1):
                copy(xyz[jj], num_of_pts)
                num_of_pts += 1

            if curves_se[cc][7] == 2:
                other = xyz[curves_se[curves_se[cc][5]][2]]
                last = pts[num_of_pts - 1]
                dist = _check_distance(last[0], last[1], last[2], other[0], other[1], other[2])
            elif curves_se[cc][7] == 3:
                other = xyz[curves_se[curves_se[cc][5]][3]]
                last = pts[num_of_pts - 1]
                dist = _check_distance(last[0], last[1], last[2], other[0], other[1], other[2])

            if enable_close and curves_se[cc][5] == 0:
                pass
            elif dist < 0.70:
                num_of_pts -= 1

            cce = curves_se[cc][7]  # Set cce to the end of next curve
            cc = curves_se[cc][5]  # Set cc to the next curve

        if start_end_cnt == 0:
            enable_close = True

    return 0, num_of_pts


# ---------------------------------------------------------------------------------------------------
# UF_MODL_ask_curve_points through ctypes (no Python binding)
# ---------------------------------------------------------------------------------------------------

_libufun: Any = None


def _ufun() -> Any:
    """libufun.dll, already loaded in the NX process. Falls back to %UGII_BASE_DIR%\\NXBIN when the bare name
    does not resolve."""
    global _libufun
    if _libufun is None:
        try:
            _libufun = ctypes.CDLL("libufun.dll")
        except OSError:
            base = os.environ.get("UGII_BASE_DIR", "")
            _libufun = ctypes.CDLL(os.path.join(base, "NXBIN", "libufun.dll"))

        _libufun.UF_MODL_ask_curve_points.argtypes = [
            ctypes.c_uint, ctypes.c_double, ctypes.c_double, ctypes.c_double,
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.POINTER(ctypes.c_double))]
        _libufun.UF_MODL_ask_curve_points.restype = ctypes.c_int
        _libufun.UF_free.argtypes = [ctypes.c_void_p]
        _libufun.UF_free.restype = None
    return _libufun


def _ask_curve_points(curve: NXOpen.Tag, ctol: float, atol: float, stol: float) -> Tuple[int, List[float]]:
    """
    ufsession_.Modl.AskCurvePoints(curve, ctol, atol, stol, out numpts, out pts) - (numpts, flat x,y,z list).
    Raises on a non-zero UF return code, as the .NET wrapper throws an NXException.
    """
    lib = _ufun()
    numpts = ctypes.c_int(0)
    points = ctypes.POINTER(ctypes.c_double)()
    error = lib.UF_MODL_ask_curve_points(int(curve), ctol, atol, stol, ctypes.byref(numpts), ctypes.byref(points))

    if error != 0:
        raise RuntimeError("UF_MODL_ask_curve_points failed for curve {}: UF error {}".format(curve, error))

    try:
        return numpts.value, [points[i] for i in range(numpts.value * 3)]
    finally:
        if points:
            lib.UF_free(ctypes.cast(points, ctypes.c_void_p))


# ---------------------------------------------------------------------------------------------------
# Selection / delete
# ---------------------------------------------------------------------------------------------------

def _select_curves(message: str = "Select Curves", title: str = "Select Curves",
                   selection_scope: NXOpen.Selection.SelectionScope = NXOpen.Selection.SelectionScope.AnyInAssembly
                   ) -> List[NXOpen.Curve]:
    """
    Selection.SelectCurves - SelectionManager.SelectTaggedObjects over SelectionType.Curves. Like the C#, the
    response is ignored; a cancel comes back as an empty selection.
    """
    _response, objects = NXOpen.UI.GetUI().SelectionManager.SelectTaggedObjects(
        message,
        title,
        selection_scope,
        False,
        [NXOpen.Selection.SelectionType.Curves])
    return [obj for obj in (objects or []) if isinstance(obj, NXOpen.Curve)]


def _delete(obj: NXOpen.TaggedObject) -> None:
    """Tag.__Delete (Session.__DeleteObjects) - adds obj to the delete list inside a DoUpdate."""
    with nx.do_update():
        nx.session_.UpdateManager.AddObjectsToDeleteList([obj])


def main() -> None:
    """The spline-to-curves UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("spline-to-curves"):
        try:
            # No dialog of its own: ask before doing anything (a logged Question box).
            if nx.confirm_execute("spline-to-curves"):
                SplineToCurves.execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
