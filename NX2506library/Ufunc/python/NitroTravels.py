"""
Python port of the nitro-travels UFunc (NitroTravels, src\\UFuncs\\NitroTravels.cs).
The C# wrapper was deleted 2026-10-22 (in git at f32694f): the UFunc's menu button runs this file's main().

Lists, for every part in the display part's assembly whose LIBRARY attribute names a nitrogen cylinder in
G:\\0Library\\NitroCylinders, its TRAVEL expression. One line per occurrence, ordered by part leaf.

Run standalone: File -> Execute -> NX Open on this file runs main().

Differences from the C#:
  - The order is a case-insensitive ordinal sort on Leaf (stable, like OrderBy). C#'s OrderBy(p => p.Leaf) uses
    the culture comparer, which also weights punctuation such as '-' differently, so leaves that differ only
    there may list in another order.
  - The library scan matches *.prt case-insensitively on the long file name. Directory.GetFiles("*.prt") also
    matches extensions that merely start with "prt" (e.g. .prtx) through 8.3 short names; that only adds names
    to the lookup set.
"""

from __future__ import annotations

import os
import sys
from typing import List, Set

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# From the source tree (src\UFuncs) the shared modules are in src\python; deployed, they are beside this file.
_shared_python = os.path.join(os.path.dirname(_here), "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402

import tsg_nx as nx  # noqa: E402

ufunc_name = "nitro-travels"

_NitroCylindersDir = "G:\\0Library\\NitroCylinders"


class NitroTravels(object):

    @staticmethod
    def execute() -> None:
        """NitroTravels.execute"""
        try:
            nx.print_(nx.ufunc_rev_name(ufunc_name))

            part_files = _library_part_names(_NitroCylindersDir)

            root = nx.display_part().ComponentAssembly.RootComponent

            if root is None:
                nx.print_("Couldn't display part doesn't have a root component")
                return

            parts: List[NXOpen.Part] = [
                c.Prototype for c in nx.descendants(root) if isinstance(c.Prototype, NXOpen.Part)]
            parts.sort(key=lambda p: p.Leaf.lower())

            for part in parts:
                if not nx.has_attribute(part, "LIBRARY"):
                    continue

                att = nx.get_attribute(part, "LIBRARY").upper()

                if att not in part_files:
                    continue

                expression = nx.find_expression_or_null(part, "TRAVEL")

                if expression is None:
                    continue

                nx.print_('{}, Library: {}, Travel: "{}"'.format(part.Leaf, att, nx.cs_double_str(expression.Value)))
        except Exception as ex:
            nx.print_exception(ex)


def _library_part_names(directory: str) -> Set[str]:
    """Directory.GetFiles(directory, "*.prt", AllDirectories).Select(GetFileNameWithoutExtension).Select(ToUpper)
    .ToHashSet(). A missing folder raises, like DirectoryNotFoundException."""
    if not os.path.isdir(directory):
        raise FileNotFoundError("Could not find a part of the path '{}'.".format(directory))

    names: Set[str] = set()
    for dir_path, _dir_names, file_names in os.walk(directory):
        for file_name in file_names:
            if file_name.lower().endswith(".prt"):
                names.add(os.path.splitext(file_name)[0].upper())
    return names


def main() -> None:
    """The nitro-travels UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("nitro-travels"):
        try:
            # No dialog of its own: ask before doing anything (a logged Question box).
            if nx.confirm_execute("nitro-travels"):
                NitroTravels.execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
