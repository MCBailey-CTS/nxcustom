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
# From the source tree (src\UFuncs) the shared modules are in src\python; deployed, they are beside this file.
_shared_python = os.path.join(os.path.dirname(_here), "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

from BlankStation import BlankStation  # noqa: E402


def main() -> None:
    """The secondary-trim-station UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("secondary-trim-station"):
        BlankStation.execute(True)


if __name__ == "__main__":
    main()
