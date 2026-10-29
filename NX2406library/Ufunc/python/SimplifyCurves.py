"""
Python port of the simplify-curves form (src\\UFuncs\\SimplifyCurves.cs, a _UFuncForm with no [UFunc] attribute or
_Runner case), as a Block UI Styler dialog (SimplifyCurves.dlx, written by tools\\make-dlx.py) - 2026-10-23.

Pick splines in the work part and a tolerance; OK / Apply replace them with simplified curves
(UF_CURVE_create_simplified_curve) under a "Simplify" undo mark. Apply keeps the dialog open for the next pick, as
the form's Select button did.

Differences from the form:
- The C# form could not run: its Select button called Ui.Selection.SelectSplines(), which throws
  NotImplementedException. The dialog's own spline selection block replaces it.
- The tolerance combo box (system tolerance, then 0.002-0.005 in, or 0.0508-0.127 mm - with the system tolerance
  listed twice for mm) is a number box. It opens on 0.005 in / 0.127 mm, or the part's distance tolerance when that
  is larger, and is in the work part's units; the system tolerance is shown beside it.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# From the source tree (src\UFuncs) the shared modules are in src\python; deployed, they are beside this file.
_shared_python = os.path.join(os.path.dirname(_here), "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.BlockStyler  # noqa: E402

import tsg_nx as nx  # noqa: E402
from tsg_dialog import Dialog, title_with_version  # noqa: E402

ufunc_name = "simplify-curves"

# NX will not create a dialog from inside another dialog's callback.
_ErrorCannotLaunchDialog = 3520048

# The form's largest preset: .005" (0.127 mm).
_DefaultInches = 0.005
_MillimetersPerInch = 25.4


def _system_tolerance() -> float:
    return float(nx.distance_tolerance())


def _is_metric(part: NXOpen.Part) -> bool:
    return part.PartUnits == NXOpen.BasePart.Units.Millimeters


def simplify(splines: List[NXOpen.TaggedObject], tolerance: float) -> int:
    """Simplifies the splines under one undo mark; returns how many curves NX created (0 on failure)."""
    if not splines:
        return 0
    try:
        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Simplify")
        tags = [s.Tag for s in splines]
        _count, created = nx.ufsession_.Curve.CreateSimplifiedCurve(len(tags), tags, tolerance)
        made = len(created or [])
        nx.print_("Simplified {} spline(s) into {} curve(s), tolerance {}.".format(len(tags), made, tolerance))
        return made
    except Exception as ex:
        nx.print_exception(ex)
        return 0


class _SimplifyCurvesDialog(Dialog):
    dlx_name = "SimplifyCurves.dlx"

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__()

    def initialize(self) -> None:
        mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_spline_type, 0, 0)
        self.block("splines").SetSelectionFilter(NXOpen.Selection.SelectionAction.ClearAndEnableSpecific, [mask])

    def shown(self) -> None:
        system = _system_tolerance()
        metric = _is_metric(nx.work_part())
        default = _DefaultInches * (_MillimetersPerInch if metric else 1.0)
        self.block("tolerance").Value = max(default, system)
        self.block("units").Label = "Tolerance in {} (system tolerance {:g})".format("mm" if metric else "inches",
                                                                                     system)

    def enable_ok(self) -> bool:
        return bool(self.selected(self.block("splines"))) and float(self.block("tolerance").Value) > 0

    def ok(self) -> bool:
        tolerance = float(self.block("tolerance").Value)
        simplify(self.selected(self.block("splines")), tolerance)
        return True

    def apply(self) -> bool:
        self.ok()
        # The simplified splines are gone or replaced; start the next pick empty.
        self.block("splines").SetSelectedObjects([])
        return True


def execute() -> None:
    if nx.work_part() is None:
        nx.show_error("Simplify Curves needs a work part.")
        return

    title = title_with_version("Simplify Curves")
    dialog: Optional[_SimplifyCurvesDialog] = None
    try:
        dialog = _SimplifyCurvesDialog(title)
        dialog.run()
    except NXOpen.NXException as ex:
        if ex.ErrorCode != _ErrorCannotLaunchDialog:
            raise
        nx.print_exception(ex)
        nx.show_error("NX would not open the {} dialog (error {} - it will not create a dialog from inside a "
                      "callback).\n\nTry running it from File -> Execute -> NX Open rather than from a menu or "
                      "toolbar button.".format(title, _ErrorCannotLaunchDialog))


def main() -> None:
    """The simplify-curves UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
