"""
Python port of the copy-ref-sets UFunc (CopyRefSets.execute, src\\UFuncs\\CopyRefSets.cs).
The C# wrapper was deleted 2026-10-22 (in git at f32694f): the UFunc's menu button runs this file's main().

Pick the "from" components, then the "to" components. Every reference set of the first "from" component's
prototype other than BODY / SUB_TOOL / Entire Part / Empty is re-created (empty, at the WCS) in each "to"
component's prototype - inch parts only; anything else is skipped silently, like the C#.

Run it with File -> Execute -> NX Open on this file (main() calls execute(), selection included).
"""

from __future__ import annotations

import os
import sys
from typing import List

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
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402

# _UFunc.ufunc_copy_ref_sets
ufunc_copy_ref_sets = "copy-ref-sets"

# Globals.cs RefsetBody
RefsetBody = "BODY"


class CopyRefSets(object):

    @staticmethod
    def execute() -> None:
        """CopyRefSets.execute"""
        ufunc_rev_name = nx.ufunc_rev_name(ufunc_copy_ref_sets)

        try:
            with nx.display_part_reset():
                ref_set_name: List[str] = []
                nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, ufunc_rev_name)
                from_component = nx.select_many_components("{} - from".format(ufunc_rev_name))

                if len(from_component) == 0:
                    return

                to_components = nx.select_many_components("{} - to".format(ufunc_rev_name))

                if len(to_components) == 0:
                    return

                if len(from_component) == 0 or len(to_components) == 0:
                    return

                copy_from_part = nx.ufsession_.Assem.AskPrototypeOfOcc(from_component[0].Tag)

                for cycle_ref_set in nx.cycle_objs_in_part(copy_from_part,
                                                           NXOpen.UF.UFConstants.UF_reference_set_type):
                    name = nx.ufsession_.Obj.AskName(cycle_ref_set)

                    if not ((name != RefsetBody) and (name != "SUB_TOOL") and (name != nx.RefsetEntirePart)
                            and (name != nx.RefsetEmpty)):
                        continue

                    ref_set_name.append(name)

                # ------------------------------------------------------------------------------
                # Make each copy to component the work part
                # Create reference sets and add to current work part
                # ------------------------------------------------------------------------------

                if len(ref_set_name) == 0:
                    raise Exception("There are no reference sets other than the component defaults")

                for wp_component in to_components:
                    if not isinstance(wp_component.Prototype, NXOpen.Part):
                        continue

                    part = wp_component.Prototype

                    if part.PartUnits != NXOpen.BasePart.Units.Inches:
                        continue

                    nx.set_work_component(wp_component)
                    num_of_members = 0
                    ref_set_array: List[NXOpen.Tag] = []

                    for ref_name in ref_set_name:
                        # origin and matrix values of the current work coordinate system
                        origin, matrix_value = nx.wcs_origin_and_matrix_values()
                        nx.ufsession_.Assem.CreateRefSet(ref_name, origin, matrix_value, ref_set_array, num_of_members)
        except Exception as ex:
            nx.print_exception(ex)


def main() -> None:
    """The copy-ref-sets UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("copy-ref-sets"):
        try:
            # No dialog of its own: ask before doing anything (a logged Question box).
            if nx.confirm_execute("copy-ref-sets"):
                CopyRefSets.execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
