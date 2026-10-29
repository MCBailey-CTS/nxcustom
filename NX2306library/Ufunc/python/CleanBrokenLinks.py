"""
Python port of the clean-broken-links UFunc (CleanBrokenLinks, src\\UFuncs\\CleanBrokenLinks.cs).
The C# wrapper was deleted 2026-10-22 (in git at f32694f): the UFunc's menu button runs this file's main().

For each picked component, display its part and delete every broken LINKED_BODY extract feature together
with all of its child features, printing a count per part.

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
import NXOpen.Features  # noqa: E402

import tsg_nx as nx  # noqa: E402

ufunc_name = "clean-broken-links"


class CleanBrokenLinks(object):

    @staticmethod
    def execute() -> None:
        """CleanBrokenLinks.execute"""
        selected_comps = nx.select_many_components(nx.ufunc_rev_name(ufunc_name))

        with nx.display_part_reset(), nx.suppress_display(), nx.do_update(), nx.regenerate_display():
            for comp in selected_comps:
                try:
                    nx.set_display_part(nx.prototype(comp))

                    to_delete: List[NXOpen.Features.Feature] = []

                    extracts = [f for f in nx.display_part().Features.GetFeatures()
                                if isinstance(f, NXOpen.Features.ExtractFace)]

                    for extract in extracts:
                        if not nx.is_linked_body(extract):
                            continue

                        if not nx.is_link_broken(extract):
                            continue

                        to_delete.append(extract)
                        to_delete.extend(extract.GetAllChildren())

                    _delete_objects(to_delete)
                    nx.print_("Deleted {} features in {}".format(len(to_delete), nx.display_part().Leaf))
                except Exception as ex:
                    nx.print_exception(ex)

        nx.ufsession_.Disp.Refresh()
        nx.ufsession_.Disp.RegenerateDisplay()


def _delete_objects(objects: Sequence[NXOpen.TaggedObject]) -> None:
    """Session.__DeleteObjects - adds the objects to the delete list inside a DoUpdate.

    Private on purpose: tsg_nx currently defines delete_objects twice with different signatures (*objects and
    a sequence), so calling it would depend on which definition survives.
    """
    with nx.do_update():
        nx.session_.UpdateManager.AddObjectsToDeleteList(list(objects))


def main() -> None:
    """The clean-broken-links UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("clean-broken-links"):
        try:
            # No dialog of its own: ask before doing anything (a logged Question box).
            if nx.confirm_execute("clean-broken-links"):
                CleanBrokenLinks.execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
