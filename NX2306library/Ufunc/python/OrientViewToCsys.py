"""
Python port of the NX work in the OrientViewToCsys form (src\\UFuncs\\OrientViewToCsys.cs), whose static methods
now live in src\\Static\\OrientViewToCsys.cs (partial class Static):

- OrientViewToCsysTop()    (was NewMethod5) -> OrientViewToCsys.top()
- OrientViewToCsysRight()  (was NewMethod4) -> OrientViewToCsys.right()
- OrientViewToCsysLeft()   (was NewMethod3) -> OrientViewToCsys.left()
- OrientViewToCsysFront()  (was NewMethod2) -> OrientViewToCsys.front()
- OrientViewToCsysBottom() (was NewMethod1) -> OrientViewToCsys.bottom()
- OrientViewToCsysBack()   (was NewMethod)  -> OrientViewToCsys.back()

Each orients the display part's work view to the WCS turned to that side, puts the WCS back, and returns the
name the form shows as its title. Nothing else in the form does NX work: the constructor, the tooltips and the
button dispatch stay C#.

Quirks kept from the C#:
- The WCS is rotated through the *work* part (__work_part_.WCS) but read and restored through the *display*
  part. NX owns one WCS, on the display part, so the two are the same object whenever the display part is the
  work part; when they differ, the C# documentation says WCS methods need the display part to own the WCS.
- prev_csys is the WCS's own coordinate system, read before the rotation. If NX rotates that object in place
  rather than replacing it, its Origin/Orientation are read after the rotation, and the restore is a no-op.
  Unverified either way; the C# behaves identically, since it reads the same properties at the same point.

NOT WIRED: the form still calls the C# methods. NEVER RUN IN NX - untested. To wire, ViewButton_Clicked would
call e.g.
    Text = (string)PythonLibrary.Execute("OrientViewToCsys.py", "OrientViewToCsys", "top");
(assuming PythonLibrary.Execute hands back the Python return value; otherwise set Text from the button).

Binding notes: WCS.Rotate's pyd docstring types its axis as NXOpen.WCSAxis, while the enum is registered as
NXOpen.WCS.Axis (the name the C# uses). This uses NXOpen.WCS.Axis; if that attribute is missing in NX, try
NXOpen.WCSAxis. View.Orient(matrix) is confirmed in NXOpen.pyd. The stubs declare neither WCS.Rotate,
WCS.Axis nor View.Orient.
"""

from __future__ import annotations

import os
import sys

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402

import tsg_nx as nx  # noqa: E402


class OrientViewToCsys(object):

    @staticmethod
    def top() -> str:
        """Static.OrientViewToCsysTop - orients the work view to the WCS as it is."""
        display = nx.display_part()
        current_csys = display.WCS.CoordinateSystem
        display.Views.WorkView.Orient(current_csys.Orientation.Element)
        return "Top"

    @staticmethod
    def right() -> str:
        """Static.OrientViewToCsysRight"""
        _orient_rotated([(NXOpen.WCS.Axis.ZAxis, 90.0), (NXOpen.WCS.Axis.XAxis, 90.0)])
        return "Right"

    @staticmethod
    def left() -> str:
        """Static.OrientViewToCsysLeft"""
        _orient_rotated([(NXOpen.WCS.Axis.ZAxis, -90.0), (NXOpen.WCS.Axis.XAxis, 90.0)])
        return "Left"

    @staticmethod
    def front() -> str:
        """Static.OrientViewToCsysFront"""
        _orient_rotated([(NXOpen.WCS.Axis.XAxis, 90.0)])
        return "Front"

    @staticmethod
    def bottom() -> str:
        """Static.OrientViewToCsysBottom"""
        _orient_rotated([(NXOpen.WCS.Axis.XAxis, 180.0)])
        return "Bottom"

    @staticmethod
    def back() -> str:
        """Static.OrientViewToCsysBack"""
        _orient_rotated([(NXOpen.WCS.Axis.ZAxis, 180.0), (NXOpen.WCS.Axis.XAxis, 90.0)])
        return "Back"


def _orient_rotated(rotations: list[tuple[NXOpen.WCS.Axis, float]]) -> None:
    """The body every view but Top shares: rotate the WCS (in order), orient the work view to it, put it back.

    No try/finally around the restore, like the C#: if the orient throws, the WCS stays rotated.
    """
    prev_csys = nx.display_part().WCS.CoordinateSystem
    for axis, angle in rotations:
        nx.work_part().WCS.Rotate(axis, angle)
    view_csys = nx.display_part().WCS.CoordinateSystem
    nx.display_part().Views.WorkView.Orient(view_csys.Orientation.Element)
    nx.display_part().WCS.SetOriginAndMatrix(prev_csys.Origin, prev_csys.Orientation.Element)
