"""
The orient-view-to-csys UFunc, Python only since 2026-10-30: its menu button runs this file's main(), a Block Styler
dialog (OrientViewToCsys.dlx, _OrientDialog) in place of the WinForms OrientViewToCsys form. The form,
src\\Static\\OrientViewToCsys.cs and the older port of those statics (src\\python\\OrientViewToCsys.py) are in git
at 97eb2a6. The form had no [UFunc] attribute or _Runner case, so the name is new. Never run in NX.

The dialog is the form's six view buttons (Front / Top / Right, Back / Bottom / Left) and a label showing the last
side clicked (the form put it in its title bar). Each button is one of the form's Static methods:

- Top    (OrientViewToCsysTop, was NewMethod5): the work view oriented to the WCS as it is.
- Right  (OrientViewToCsysRight, NewMethod4): WCS turned Z +90, then X +90.
- Left   (OrientViewToCsysLeft, NewMethod3): Z -90, then X +90.
- Front  (OrientViewToCsysFront, NewMethod2): X +90.
- Bottom (OrientViewToCsysBottom, NewMethod1): X 180.
- Back   (OrientViewToCsysBack, NewMethod): Z 180, then X +90.

Every side but Top turns the display part's WCS, orients the display part's work view to it and puts the WCS back
(OrientViewToCsysTurned). The WCS origin and orientation are copied as values before the turn, as the C# did after
its fix: the old buttons kept WCS.CoordinateSystem, which can follow the WCS as it turns, and turned the work part's
WCS while reading the display part's. No undo mark and no try/finally around the restore, like the C#.

Close only: closing it is how it ends, so there is no confirm box and the run is not marked cancelled.
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List, Tuple

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# The shared modules are in the python folder beside this file (src\UFuncs\python; deployed, Ufunc\python).
_shared_python = os.path.join(_here, "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.BlockStyler  # noqa: E402

import tsg_nx as nx  # noqa: E402
from tsg_dialog import Dialog, title_with_version  # noqa: E402

ufunc_name = "orient-view-to-csys"

# Button id -> (the side, the WCS turns in order). Top turns nothing.
_Sides: Dict[str, Tuple[str, List[Tuple[NXOpen.WCS.Axis, float]]]] = {
    "top": ("Top", []),
    "right": ("Right", [(NXOpen.WCS.Axis.ZAxis, 90.0), (NXOpen.WCS.Axis.XAxis, 90.0)]),
    "left": ("Left", [(NXOpen.WCS.Axis.ZAxis, -90.0), (NXOpen.WCS.Axis.XAxis, 90.0)]),
    "front": ("Front", [(NXOpen.WCS.Axis.XAxis, 90.0)]),
    "bottom": ("Bottom", [(NXOpen.WCS.Axis.XAxis, 180.0)]),
    "back": ("Back", [(NXOpen.WCS.Axis.ZAxis, 180.0), (NXOpen.WCS.Axis.XAxis, 90.0)]),
}


def orient(turns: List[Tuple[NXOpen.WCS.Axis, float]]) -> None:
    """Static.OrientViewToCsysTop / OrientViewToCsysTurned: orient the display part's work view to its WCS turned by
    turns, then put the WCS back. With no turns the WCS is left alone."""
    display = nx.display_part()
    wcs = display.WCS
    if not turns:
        display.Views.WorkView.Orient(wcs.CoordinateSystem.Orientation.Element)
        return
    o = wcs.CoordinateSystem.Origin
    m = wcs.CoordinateSystem.Orientation.Element
    origin = NXOpen.Point3d(o.X, o.Y, o.Z)
    orientation = NXOpen.Matrix3x3()
    orientation.Xx, orientation.Xy, orientation.Xz = m.Xx, m.Xy, m.Xz
    orientation.Yx, orientation.Yy, orientation.Yz = m.Yx, m.Yy, m.Yz
    orientation.Zx, orientation.Zy, orientation.Zz = m.Zx, m.Zy, m.Zz
    for axis, angle in turns:
        wcs.Rotate(axis, angle)
    display.Views.WorkView.Orient(wcs.CoordinateSystem.Orientation.Element)
    wcs.SetOriginAndMatrix(origin, orientation)


class _OrientDialog(Dialog):
    """OrientViewToCsys.dlx: ViewButton_Clicked on each button; the label stands in for the form's Text."""

    dlx_name = "OrientViewToCsys.dlx"
    close_only = True

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__()

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        for block_id, (side, turns) in _Sides.items():
            if block == self.block(block_id):
                orient(turns)
                self.block("last").Label = "View: {}".format(side)
                return


def main() -> None:
    """The orient-view-to-csys UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            _OrientDialog(title_with_version("Orient View To Csys")).run()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
