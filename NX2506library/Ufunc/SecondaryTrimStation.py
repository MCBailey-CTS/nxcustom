"""
The secondary-trim-station UFunc: its menu button runs this file, whose main() runs BlankStation.execute(True)
(the -02 stations). The front end and the build are in BlankStation.py; this file exists because a menu button
runs one file's main(). The C# wrapper (src\\UFuncs\\MerlinUFuncs\\GmSecondaryTrimStation.cs) was deleted 2026-10-23
(in git at 41f2a7b).
"""

from __future__ import annotations

import os
import sys

# Session.Execute does not put the script's folder on sys.path, so the shared modules would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# The shared modules are in the python folder beside this file (src\UFuncs\python; deployed, Ufunc\python).
_shared_python = os.path.join(_here, "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import tsg_nx as nx  # noqa: E402
from BlankStation import BlankStation  # noqa: E402


def main() -> None:
    """The secondary-trim-station UFunc - its menu button runs this file. An escaping exception is printed."""
    with nx.merlin_run("secondary-trim-station"):
        try:
            BlankStation.execute(True)
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
