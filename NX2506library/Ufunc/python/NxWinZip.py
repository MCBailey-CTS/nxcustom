"""
The nx-win-zip UFunc: WinZips every part file of an assembly - the displayed one, or a .prt picked from disk.

ALL PYTHON since 2026-10-23: the nx-win-zip menu button runs this file. main() records the run
(usage_db.run("nx-win-zip")) and shows a Block UI Styler dialog (NxWinZip.dlx, built by tools\\make-dlx.py) in place
of the WinForms form; the dialog, the load options and the part list are shared with nx-7-zip in
src\\python\\zip_assembly.py (its docstring has the differences from the C#). It replaced src\\UFuncs\\NxWinZip.cs (the
form, with .Designer.cs) and src\\Static\\NxWinZip.cs - in git at f108562. This file used to be src\\python\\NxWinZip.py,
the port of the form's non-form half. The dialog has NEVER BEEN RUN IN NX, nor has the zip - and WinZip is not
installed on the development machine, so the run stops with an error box there.

    wzzip -a [-P] <compression> "<archive>" @"<list>"    compression -el Maximum (.zipx) / -en Normal / -ex Extra /
                                                         -ef FastenerType / -es SuperFast (.zip); -P Include Path
"""

from __future__ import annotations

import os
import sys

# Session.Execute does not put the script's folder on sys.path, so the shared modules would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# From the source tree (src\UFuncs) the shared modules are in src\python; deployed, they are beside this file.
_shared_python = os.path.join(os.path.dirname(_here), "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import tsg_nx as nx  # noqa: E402
import zip_assembly  # noqa: E402

# _UFunc.ufunc_nx_win_zip (deleted with the form)
ufunc_nx_win_zip = "nx-win-zip"


class _WinZip(zip_assembly.Archiver):

    def __init__(self) -> None:
        super().__init__(ufunc_nx_win_zip, "NX WinZip", "NxWinZip.dlx", "C:\\Program Files (x86)\\WinZip\\wzzip", [
            # The form's WinZipCompression items, in its order ("FastenerType" is the form's text for -ef, fast).
            ("Maximum (.zipx)", "-el", ".zipx"),
            ("Normal (.zip)", "-en", ".zip"),
            ("Extra (.zip)", "-ex", ".zip"),
            ("FastenerType (.zip)", "-ef", ".zip"),
            ("SuperFast (.zip)", "-es", ".zip"),
        ])

    def arguments(self, archive: str, list_file: str, compression: str, include_path: bool) -> str:
        # Static.NxWinZipCreateZipFile (its Arguments began with a space).
        if include_path:
            return " -a -P {} \"{}\" @\"{}\"".format(compression, archive, list_file)
        return " -a {} \"{}\" @\"{}\"".format(compression, archive, list_file)


def main() -> None:
    """The nx-win-zip UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_nx_win_zip):
        try:
            zip_assembly.run(_WinZip())
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
