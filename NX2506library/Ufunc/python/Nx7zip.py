"""
The nx-7-zip UFunc: 7-Zips every part file of an assembly - the displayed one, or a .prt picked from disk.

ALL PYTHON since 2026-10-23: the nx-7-zip menu button runs this file. main() records the run
(usage_db.run("nx-7-zip")) and shows a Block UI Styler dialog (Nx7zip.dlx, built by tools\\make-dlx.py) in place of the
WinForms form; the dialog, the load options and the part list are shared with nx-win-zip in
src\\python\\zip_assembly.py (its docstring has the differences from the C#). It replaced src\\UFuncs\\Nx7zip.cs (the
form, with .Designer.cs and .resx) and src\\Static\\Nx7zip.cs - in git at f108562. This file used to be
src\\python\\Nx7zip.py, the port of the form's non-form half. The dialog has NEVER BEEN RUN IN NX, nor has the zip.

    7z a -t7z "<archive>" "@<list>" <compression>       compression -mx9 Ultra / -mx7 Maximum / -mx5 Normal / -mx3 Auto
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

# _UFunc.ufunc_nx_7_zip (deleted with the form)
ufunc_nx_7_zip = "nx-7-zip"


class _SevenZip(zip_assembly.Archiver):

    def __init__(self) -> None:
        super().__init__(ufunc_nx_7_zip, "NX 7-Zip", "Nx7zip.dlx", "C:\\Program Files\\7-Zip\\7z", [
            # The form's Nx7ZipCompression items, in its order.
            ("Ultra", "-mx9", ".7z"),
            ("Maximum", "-mx7", ".7z"),
            ("Normal", "-mx5", ".7z"),
            ("Auto", "-mx3", ".7z"),
        ])

    def arguments(self, archive: str, list_file: str, compression: str, include_path: bool) -> str:
        return "a -t7z \"{}\" \"@{}\" {}".format(archive, list_file, compression)


def main() -> None:
    """The nx-7-zip UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_nx_7_zip):
        try:
            zip_assembly.run(_SevenZip())
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
