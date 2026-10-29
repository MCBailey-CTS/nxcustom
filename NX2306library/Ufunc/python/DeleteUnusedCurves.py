"""
Python port of the delete-unused-curves UFunc (DeleteUnusedCurves.execute, src\\UFuncs\\DeleteUnusedCurves.cs).
The C# wrapper was deleted 2026-10-22 (in git at f32694f): the UFunc's menu button runs this file's main().

Select curves in the work part; every one that does not belong to a feature (UF_MODL_ask_object_feat gives no
feature) is deleted, and the count is printed.

File -> Execute -> NX Open on this file runs main(), which does the selection itself like the C# UFunc.
"""

from __future__ import annotations

import os
import sys
from typing import List, cast

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


class DeleteUnusedCurves(object):

    @staticmethod
    def execute() -> None:
        """DeleteUnusedCurves.execute"""
        curves = _select_curves(
            nx.assembly_file_version(),
            nx.assembly_file_version(),
            NXOpen.Selection.SelectionScope.WorkPart)

        if not curves:
            nx.mark_cancelled("the curve selection")
            return

        deleted = 0

        for delete in curves:
            feat_tag = nx.ufsession_.Modeling.AskObjectFeat(delete.Tag)

            # The Python binding returns None (not Tag.Null) when the curve has no feature.
            if feat_tag:
                continue

            _delete(delete)
            deleted += 1

        nx.print_("Deleted {} unused curves in {}.".format(deleted, nx.work_part().Leaf))


def _select_curves(message: str = "Select Curves", title: str = "Select Curves",
                   selection_scope: NXOpen.Selection.SelectionScope = NXOpen.Selection.SelectionScope.AnyInAssembly
                   ) -> List[NXOpen.Curve]:
    """
    Selection.SelectCurves - SelectionManager.SelectTaggedObjects over SelectionType.Curves. Like the C#, the
    response is ignored; a cancel comes back as an empty selection.
    """
    _response, objects = NXOpen.UI.GetUI().SelectionManager.SelectTaggedObjects(
        message,
        title,
        selection_scope,
        False,
        [NXOpen.Selection.SelectionType.Curves])
    return [cast(NXOpen.Curve, obj) for obj in (objects or [])]


def _delete(obj: NXOpen.TaggedObject) -> None:
    """TaggedObject.__Delete (Session.__DeleteObjects) - adds obj to the delete list inside a DoUpdate."""
    with nx.do_update():
        nx.session_.UpdateManager.AddObjectsToDeleteList([obj])


def main() -> None:
    """The delete-unused-curves UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("delete-unused-curves"):
        try:
            # No confirm: the curve selection is the user's choice to run, and cancelling it does nothing.
            DeleteUnusedCurves.execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
