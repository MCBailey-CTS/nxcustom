"""
Python port of the f-shape-exporter UFunc (FShapeExporter, src\\UFuncs\\FShapeExporter.cs), with its WinForms form
replaced by a modal dialog (FShapeExporter.dlx).
The C# wrapper was deleted 2026-10-22 (in git at f32694f): the UFunc's menu button runs this file's main().

The form asked for a "Sim Run#" and kept it in FShapeExporter.Answer, which nothing ever read - its Accept and Test
buttons were empty. The dialog asks the same question, refuses an empty answer the way the form did ("Please type a
Sim number"), and prints the number, so a run at least shows what was typed. The export itself was never written.

Two ways in:
  - File -> Execute -> NX Open on this file runs main().
  - Session.Execute("FShapeExporter.py", "FShapeExporter", "execute") from C# (the f-shape-exporter UFunc).
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
from tsg_dialog import Dialog  # noqa: E402


class _FShapeExporterDialog(Dialog):
    dlx_name = "FShapeExporter.dlx"
    title = "F-Shape Exporter"

    def __init__(self) -> None:
        super().__init__()
        self.answer = ""

    def ok(self) -> bool:
        text = self.string_value(self.block("sim_run"))

        if not text:
            self.message("Please type a Sim number")
            return False

        self.answer = text
        return True


class FShapeExporter(object):

    @staticmethod
    def execute() -> None:
        """FShapeExporter (the form): ask for the sim run number."""
        dialog = _FShapeExporterDialog()

        if dialog.run():
            nx.print_("Sim Run#: {}".format(dialog.answer))


def main() -> None:
    """The f-shape-exporter UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("f-shape-exporter"):
        try:
            FShapeExporter.execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
