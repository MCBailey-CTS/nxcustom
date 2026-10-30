"""
Python port of the assembly-clearance-check UFunc (src\\UFuncs\\AssemblyClearanceCheck.cs, AssemblyClearanceCheck.Execute1).
The C# class was deleted 2026-10-30 (in git at 97eb2a6): the UFunc's menu button runs this file's main().

After the "Are you sure" box: a clearance set "InterferenceCheck" in the work part over all visible objects, between
components, exact if loaded, zero clearance zone (inches), interference geometry kept on layer 99 in Pure White.
It is analysed, then every point on layer 99 of the display part is deleted. NX lists the results in its
Clearance Browser.

Differences from the C#:
  - The C# class had no [UFunc] attribute or _Runner case, so its ribbon button (assembly-clearance-check.dll with
    "UFUNC", "AssemblyClearanceCheck") could not reach it from this library.
  - The points are deleted through UpdateManager under an undo mark rather than Points.DeletePoint one by one.

Never run in NX.
"""

from __future__ import annotations

import os
import sys
from typing import Any, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# The shared modules are in the python folder beside this file (src\UFuncs\python; deployed, Ufunc\python).
_shared_python = os.path.join(_here, "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402

import tsg_nx as nx  # noqa: E402

ClearanceSetName = "InterferenceCheck"
InterferenceLayer = 99

# The clearance API is not in the hand-written NXOpen stubs.
_Assemblies: Any = NXOpen.Assemblies


def check() -> None:
    """AssemblyClearanceCheck.Execute1"""
    work: Any = nx.work_part()
    disp = nx.display_part()
    builder = work.AssemblyManager.CreateClearanceAnalysisBuilder(cast(Any, None))
    try:
        zone = builder.CreateClearanceZoneExpression("0.0")
        zone.Units = work.UnitCollection.FindObject("Inch")
        builder.SetDefaultClearanceZone(zone)
        builder.CalculationMethod = _Assemblies.ClearanceAnalysisBuilder.CalculationMethodType.ExactifLoaded
        builder.CollectionOneRange = _Assemblies.ClearanceAnalysisBuilder.CollectionRange.AllVisibleObjects
        zone.RightHandSide = "0"
        builder.SaveInterferenceGeometry = True
        builder.Layer = InterferenceLayer
        builder.InterferenceColor = work.Colors.Find("Pure White")
        builder.ClearanceBetween = _Assemblies.ClearanceAnalysisBuilder.ClearanceBetweenEntity.Components
        builder.ClearanceSetName = ClearanceSetName
        clearance_set = builder.Commit()
    finally:
        builder.Destroy()

    clearance_set.PerformAnalysis(_Assemblies.ClearanceSet.ReanalyzeOutOfDateExcludedPairs.FalseValue)

    points = [p for p in disp.Points if p.Layer == InterferenceLayer]
    if points:
        mark = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "Delete clearance points")
        nx.session_.UpdateManager.AddObjectsToDeleteList(points)
        nx.session_.UpdateManager.DoUpdate(mark)


def main() -> None:
    """The assembly-clearance-check UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("assembly-clearance-check"):
        try:
            if nx.confirm_execute("assembly-clearance-check"):
                nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Assembly Clearance Check")
                check()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
