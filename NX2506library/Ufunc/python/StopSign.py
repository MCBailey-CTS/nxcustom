import math
import os
import sys

import NXOpen
import NXOpen.UF
import NXOpen.UserDefinedObjects as UDO

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tsg_nx as nx  # noqa: E402

theSession = NXOpen.Session.GetSession()
theUI = NXOpen.UI.GetUI()
theUFSession = NXOpen.UF.UFSession.GetUFSession()

CLASS_NAME = "StopSign"
stop_class = None  # keep a global reference so the callbacks stay alive


def draw_stop_sign(evt):
    d = evt.UserDefinedObject.GetDoubles()
    cx, cy, cz, r = d[0], d[1], d[2], d[3]

    # Octagon corners, flat top/bottom (start at 22.5 degrees), closed loop
    pts = []
    for i in range(9):
        a = math.radians(22.5 + 45.0 * (i % 8))
        pts.append(NXOpen.Point3d(cx + r * math.cos(a), cy + r * math.sin(a), cz))

    ctx = evt.DisplayContext
    ctx.DisplayPolyline(pts)
    ctx.DisplayText("STOP", NXOpen.Point3d(cx, cy, cz),
                    UDO.UserDefinedObjectDisplayContext.TextRef.Middlecenter)
    return 0


def on_stop_sign_clicked(evt):
    nx.message_box("Stop Sign",
                            NXOpen.NXMessageBox.DialogType.Information,
                            "You clicked the stop sign!")
    return 0


def get_stop_class():
    global stop_class
    mgr = theSession.UserDefinedClassManager

    # A class can only be registered once per NX session, so reuse it if it exists
    try:
        stop_class = mgr.GetUserDefinedClassFromClassName(CLASS_NAME)
    except Exception:
        stop_class = None

    if stop_class is None:
        stop_class = mgr.CreateUserDefinedObjectClass(CLASS_NAME, "Stop Sign")
        stop_class.AllowQueryClassFromName = UDO.UserDefinedClass.AllowQueryClass.On
        stop_class.AddDisplayHandler(draw_stop_sign)
        stop_class.AddSelectionHandler(draw_stop_sign)   # makes it clickable
        stop_class.AddFitHandler(draw_stop_sign)
        stop_class.AddAttentionPointHandler(draw_stop_sign)
        stop_class.AddEditHandler(on_stop_sign_clicked)
    return stop_class


def main():
    work_part = theSession.Parts.Work
    cls = get_stop_class()

    udo = work_part.UserDefinedObjectManager.CreateUserDefinedObject(cls)
    udo.SetDoubles([0.0, 0.0, 0.0, 25.0])  # x, y, z, radius

    # Force NX to draw the new UDO
    theUFSession.Disp.AddItemToDisplay(udo.Tag)


def get_unload_option(dummy):
    # Keep the journal loaded so the display/select/edit callbacks keep working
    return int(NXOpen.Session.LibraryUnloadOption.Explicitly)


if __name__ == "__main__":
    main()