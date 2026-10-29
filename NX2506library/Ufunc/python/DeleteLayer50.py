"""
Python port of the delete-layer-50 UFunc (DeleteLayer50, src\\UFuncs\\DeleteLayer50.cs).
The C# wrapper was deleted 2026-10-22 (in git at f32694f): the UFunc's menu button runs this file's main().

After a Yes/No confirmation, visits every distinct loaded, unsuppressed component of the work part's assembly
and deletes the white (color 7), phantom-font bodies on layers 50-55 - the "previous revision" copies that
copy-to-layer-50 leaves behind. Prints a count per component.

Run standalone: File -> Execute -> NX Open on this file runs main().
"""

from __future__ import annotations

import os
import sys
from typing import List, Sequence

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# From the source tree (src\UFuncs) the shared modules are in src\python; deployed, they are beside this file.
_shared_python = os.path.join(os.path.dirname(_here), "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402

import tsg_nx as nx  # noqa: E402

ufunc_name = "delete-layer-50"

# NXMessageBox.Show return value for "Yes" on a Question dialog.
_MessageBoxYes = 1


class DeleteLayer50(object):

    @staticmethod
    def execute() -> None:
        """DeleteLayer50.execute"""
        if nx.display_part() is None:
            nx.print_("There is no displayed part loaded")
            return

        # C# uses a WinForms MessageBox (YesNo) and returns on No; the NX Question box is the nearest equivalent.
        result = nx.message_box(
            nx.ufunc_rev_name(ufunc_name),
            NXOpen.NXMessageBox.DialogType.Question,
            "Are you sure you want to delete all bodies on layer 50-55 in the current assembly")

        if result != _MessageBoxYes:
            return

        total_deleted = 0

        with nx.display_part_reset(), nx.suppress_display():
            root = nx.work_part().ComponentAssembly.RootComponent
            if root is None:
                # C#: NullReferenceException out of __Descendants on a part with no assembly.
                raise RuntimeError("The work part has no root component.")

            comps = nx.distinct_by(
                [c for c in nx.descendants(root) if not c.IsSuppressed and nx.is_loaded(c)],
                lambda c: c.DisplayName)

            components = nx.distinct_by(comps, lambda c: c.DisplayName)

            found_bodies = False
            message = ""

            for component in components:
                if component.IsSuppressed:
                    continue

                if not nx.is_loaded(component):
                    continue

                nx.set_display_part(nx.prototype(component))

                bodies_to_delete: List[NXOpen.Body] = [
                    body for body in nx.work_part().Bodies.ToArray()
                    if 50 <= body.Layer <= 55
                    and body.Color == 7
                    and body.LineFont == NXOpen.DisplayableObject.ObjectFont.Phantom]

                if len(bodies_to_delete) <= 0:
                    continue

                found_bodies = True
                message += "{}: {}\n".format(component.DisplayName, len(bodies_to_delete))
                total_deleted += len(bodies_to_delete)
                _delete_objects(bodies_to_delete)

            if not found_bodies:
                nx.print_("No solids on layers 50-55, "
                          "with white coloring, "
                          "and phantom lines found in current assembly.\n")
                return

            nx.print_("Deleted {} layer 50 bodies off of these components.".format(total_deleted))
            nx.print_(message)


def _delete_objects(objects: Sequence[NXOpen.TaggedObject]) -> None:
    """Session.__DeleteObjects - adds the objects to the delete list inside a DoUpdate.

    Private on purpose: tsg_nx currently defines delete_objects twice with different signatures (*objects and
    a sequence), so calling it would depend on which definition survives.
    """
    with nx.do_update():
        nx.session_.UpdateManager.AddObjectsToDeleteList(list(objects))


def main() -> None:
    """The delete-layer-50 UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("delete-layer-50"):
        try:
            DeleteLayer50.execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
