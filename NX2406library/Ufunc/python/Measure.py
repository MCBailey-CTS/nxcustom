"""
The measure UFunc: a standalone Python UFunc (no C# class); its menu button runs this file's main().

Pick two objects - faces, edges, bodies, curves, points or datum planes, anywhere in the assembly - and it
prints the minimum distance between them (UF_MODL_ask_minimum_dist) in inches and millimeters, plus the
dX/dY/dZ from the first object's closest point to the second's, in the WCS. A temporary line is drawn between
the two closest points. It keeps asking for pairs until the first pick is cancelled; Back on the second pick
goes back to the first.

Read-only: nothing is created or changed in the part.

Run standalone: File -> Execute -> NX Open on this file runs main().
"""

from __future__ import annotations

import os
import sys
from typing import Any, List, Optional, Sequence

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

ufunc_name = "measure"

_MillimetersPerInch = 25.4

_Picked = (NXOpen.Selection.Response.Ok, NXOpen.Selection.Response.ObjectSelected,
           NXOpen.Selection.Response.ObjectSelectedByName)


def _masks() -> List[NXOpen.Selection.MaskTriple]:
    c = NXOpen.UF.UFConstants
    return [NXOpen.Selection.MaskTriple(c.UF_solid_type, 0, c.UF_UI_SEL_FEATURE_ANY_FACE),
            NXOpen.Selection.MaskTriple(c.UF_solid_type, 0, c.UF_UI_SEL_FEATURE_ANY_EDGE),
            NXOpen.Selection.MaskTriple(c.UF_solid_type, 0, c.UF_UI_SEL_FEATURE_BODY),
            NXOpen.Selection.MaskTriple(c.UF_line_type, 0, 0),
            NXOpen.Selection.MaskTriple(c.UF_circle_type, 0, 0),
            NXOpen.Selection.MaskTriple(c.UF_conic_type, 0, 0),
            NXOpen.Selection.MaskTriple(c.UF_spline_type, 0, 0),
            NXOpen.Selection.MaskTriple(c.UF_point_type, 0, 0),
            NXOpen.Selection.MaskTriple(c.UF_datum_plane_type, 0, 0),
            NXOpen.Selection.MaskTriple(c.UF_datum_axis_type, 0, 0)]


def _select(message: str):
    """(response, object) - the object is None unless something was picked. The pick stays highlighted."""
    result: Any = NXOpen.UI.GetUI().SelectionManager.SelectTaggedObject(
        message,
        nx.ufunc_rev_name(ufunc_name),
        NXOpen.Selection.SelectionScope.AnyInAssembly,
        NXOpen.Selection.SelectionAction.ClearAndEnableSpecific,
        False,
        True,
        _masks())
    response, obj, _cursor = result
    return response, (obj if response in _Picked else None)


def _describe(obj: NXOpen.TaggedObject) -> str:
    name = type(obj).__name__
    owner = getattr(obj, "OwningComponent", None)
    if owner is not None:
        return "{} in {}".format(name, owner.DisplayName)
    return name


def _to_wcs(delta: Sequence[float]) -> List[float]:
    """An absolute vector in WCS components (the matrix rows are the WCS X, Y and Z axes)."""
    _origin, m = nx.wcs_origin_and_matrix_values()
    return [m[0] * delta[0] + m[1] * delta[1] + m[2] * delta[2],
            m[3] * delta[0] + m[4] * delta[1] + m[5] * delta[2],
            m[6] * delta[0] + m[7] * delta[1] + m[8] * delta[2]]


def _show_line(start: Sequence[float], end: Sequence[float]) -> None:
    """A temporary line between the closest points; it goes on the next regenerate. Failures are ignored."""
    try:
        # The Python binding's names: NXOpen.UF.Obj.DispProps / NXOpen.UF.Disp.ViewType (UFObj / DispViewType are
        # the .NET names and do not exist here, so this line was never drawn before 2026-10-29).
        uf: Any = NXOpen.UF
        attrib = uf.Obj.DispProps()
        attrib.Color = 186
        attrib.LineWidth = uf.UFConstants.UF_OBJ_WIDTH_THICK
        attrib.Font = uf.UFConstants.UF_OBJ_FONT_SOLID
        attrib.HighlightStatus = False
        attrib.Layer = 1
        attrib.BlankStatus = uf.UFConstants.UF_OBJ_NOT_BLANKED
        disp: Any = nx.ufsession_.Disp
        disp.DisplayTemporaryLine(
            nx.display_part().Views.WorkView.Tag, uf.Disp.ViewType.USE_ACTIVE_PLUS, list(start), list(end), attrib)
    except Exception:
        pass


def _measure(first: NXOpen.TaggedObject, second: NXOpen.TaggedObject) -> None:
    guess = [0.0, 0.0, 0.0]
    result: Any = nx.ufsession_.Modeling.AskMinimumDist(first.Tag, second.Tag, 0, guess, 0, guess)
    distance, p1, p2 = result
    p1 = [float(v) for v in p1]
    p2 = [float(v) for v in p2]

    # The distance and points are in the display part's units.
    inches = nx.display_part().PartUnits == NXOpen.BasePart.Units.Inches
    to_inches = 1.0 if inches else 1.0 / _MillimetersPerInch
    d = _to_wcs([p2[i] - p1[i] for i in range(3)])

    nx.print_("{}  ->  {}".format(_describe(first), _describe(second)))
    nx.print_("  Minimum distance: {:.4f} in  ({:.3f} mm)".format(
        distance * to_inches, distance * to_inches * _MillimetersPerInch))
    nx.print_("  WCS  dX {:.4f}  dY {:.4f}  dZ {:.4f} in".format(*[v * to_inches for v in d]))
    nx.print_("")
    _show_line(p1, p2)


class Measure(object):

    @staticmethod
    def execute() -> None:
        """Pick pairs until the first pick is cancelled."""
        if nx.display_part() is None:
            nx.print_("There is no displayed part loaded")
            return

        nx.print_(nx.ufunc_rev_name(ufunc_name))
        while True:
            _response, first = _select("Select first object to measure from")
            if first is None:
                return

            second: Optional[NXOpen.TaggedObject] = None
            try:
                response, second = _select("Select second object to measure to")
                if second is None:
                    if response == NXOpen.Selection.Response.Back:
                        continue
                    return
                try:
                    _measure(first, second)
                except Exception as ex:
                    nx.print_exception(ex)
            finally:
                for obj in (first, second):
                    if obj is not None:
                        try:
                            obj.Unhighlight()
                        except Exception:
                            pass


def main() -> None:
    """The measure UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            # No dialog of its own: ask before doing anything (a logged Question box).
            if nx.confirm_execute(ufunc_name):
                Measure.execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
