"""
The right-click menu's Attributes (object-attributes, 2026-11-08, not yet run in NX): lists the title and value of
every user attribute on each selected object in the Information window. SessionRecord's TsgContextMenu adds it for any
selection; its button TSG_OBJECT_ATTRIBUTES (Menuscript\\startup\\tsg_context_menu.men) runs this file's main().

An occurrence (a component, a body or face in one) lists what NX reports for it, which takes in its part's attributes.
An array attribute lists each element as Title[i]. Read only, and no confirm box: the menu click is the choice. With
nothing selected (File -> Execute -> NX Open on this file) it says so.
"""

from __future__ import annotations

import os
import sys
from typing import Any, List

# Session.Execute does not put the script's folder on sys.path, so the shared modules would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# The shared modules are in the python folder beside this file (src\UFuncs\python; deployed, Ufunc\python).
_shared_python = os.path.join(_here, "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402

import tsg_nx as nx  # noqa: E402

ufunc_name = "object-attributes"


def _selected_objects() -> List[NXOpen.NXObject]:
    """The NXObjects in NX's global selection (the right-clicked ones)."""
    selection: Any = NXOpen.UI.GetUI().SelectionManager
    objects: List[NXOpen.NXObject] = []
    for i in range(selection.GetNumSelectedObjects()):
        picked = selection.GetSelectedTaggedObject(i)
        if isinstance(picked, NXOpen.NXObject):
            objects.append(picked)
    return objects


def _describe(obj: NXOpen.NXObject) -> str:
    """The object's header line: its type, then its name or journal identifier, if it has one."""
    kind = type(obj).__name__
    for read in (lambda: obj.Name, lambda: obj.JournalIdentifier):
        try:
            text = read()
            if text:
                return f"{kind} {text}"
        except Exception:
            pass
    return kind


def _value(obj: NXOpen.NXObject, info: Any) -> str:
    index = info.ArrayElementIndex if info.Array else -1
    try:
        return obj.GetUserAttributeAsString(info.Title, info.Type, index)
    except Exception as ex:
        return f"<unreadable: {ex}>"


def list_attributes(objects: List[NXOpen.NXObject]) -> None:
    """Writes each object's attributes (title = value) to the Information window."""
    if not objects:
        nx.print_("Attributes: nothing selected.")
        return

    for obj in objects:
        nx.print_(_describe(obj))
        try:
            infos = list(obj.GetUserAttributes())
        except Exception as ex:
            nx.print_(f"    <attributes unreadable: {ex}>")
            continue

        if not infos:
            nx.print_("    (no attributes)")
        rows = []
        for info in infos:
            title = f"{info.Title}[{info.ArrayElementIndex}]" if info.Array else info.Title
            rows.append((title, _value(obj, info)))
        width = max((len(title) for title, _ in rows), default=0)
        for title, value in sorted(rows, key=lambda row: row[0].upper()):
            nx.print_(f"    {title.ljust(width)} = {value}")
        nx.print_("")


def main() -> None:
    """The menu button runs this file. An escaping exception is printed."""
    import usage_db
    with usage_db.run(ufunc_name):
        try:
            list_attributes(_selected_objects())
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
