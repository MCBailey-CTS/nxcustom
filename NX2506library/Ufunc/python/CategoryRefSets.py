"""
Python port of the category-ref-sets UFunc (CategoryRefSets, src\\UFuncs\\CategoryRefSets.cs).
The C# wrapper was deleted 2026-10-22 (in git at f32694f): the UFunc's menu button runs this file's main().

Works on the work part. With a BODY reference set: empty it and refill it with the layer-1 body plus the
layer-99 children (undoing the run when there is not exactly one layer-1 body). Without one: create the
standard layer categories when the part has only one, then create BODY and SUB_TOOL reference sets at the WCS.

Run it with File -> Execute -> NX Open on this file (main() calls execute()).
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
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402

# _UFunc.ufunc_category_ref_sets
ufunc_category_ref_sets = "category-ref-sets"


class CategoryRefSets(object):

    @staticmethod
    def execute() -> None:
        """CategoryRefSets.execute"""
        nx.print_(nx.ufunc_rev_name(ufunc_category_ref_sets))
        body_ref_set: NXOpen.Tag = 0
        mark_id1 = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Category Reference Sets")
        is_body_ref_set = False
        body_ref_set_name = "BODY"
        sub_ref_set_name = "SUB_TOOL"
        num_of_body_members = 0
        num_of_sub_members = 0

        ref_set_tag = nx.cycle_objs_in_part(nx.work_part().Tag, NXOpen.UF.UFConstants.UF_reference_set_type)

        for ref_set in ref_set_tag:
            ref_set_name = nx.ufsession_.Obj.AskName(ref_set)

            if ref_set_name != "BODY":
                continue

            is_body_ref_set = True
            body_ref_set = ref_set
            break

        if is_body_ref_set:
            # ----------------------------------------------
            # remove all but body and fasteners from body refset
            # ----------------------------------------------

            # get the body ref set tag
            # get a list of all members of the body ref set and remove all
            # get the body.tag from the body on layer 1
            # add body
            # add fasteners

            members = nx.ask_ref_set_members(body_ref_set)
            nx.ufsession_.Assem.RemoveRefSetMembers(body_ref_set, len(members), members)

            wp_body = _layer1_body_tags()

            if len(wp_body) == 1:
                nx.ufsession_.Assem.AddRefSetMembers(body_ref_set, len(wp_body), wp_body)

                if nx.work_part().ComponentAssembly.RootComponent is None:
                    return

                comp_list = _layer99_child_tags()

                nx.ufsession_.Assem.AddRefSetMembers(body_ref_set, len(comp_list), comp_list)
            else:
                nx.print_("You have more than one solid body on layer one")
                nx.session_.SetUndoMarkVisibility(mark_id1, "", NXOpen.Session.MarkVisibility.Invisible)
                nx.session_.UndoToMark(mark_id1, "Category Reference Sets")

            return

        if len(list(nx.work_part().Bodies)) == 0:
            if len(list(nx.work_part().LayerCategories)) != 1:
                return

            CategoryRefSets.create_category_names(nx.work_part())
            # origin and matrix values of the current work coordinate system
            origin, matrix_value = nx.wcs_origin_and_matrix_values()
            body_ref_set = nx.ufsession_.Assem.CreateRefSet(body_ref_set_name, origin, matrix_value, [],
                                                            num_of_body_members)
            nx.ufsession_.Assem.CreateRefSet(sub_ref_set_name, origin, matrix_value, [], num_of_sub_members)
            return

        if len(list(nx.work_part().LayerCategories)) == 1:
            CategoryRefSets.create_category_names(nx.work_part())
            origin, matrix_value = nx.wcs_origin_and_matrix_values()

            body_array = _layer1_body_tags()

            if len(body_array) != 1:
                nx.print_("You have more than one solid body on layer one")
                return

            # As in the C#, num_of_body_members is 0 while the members array holds the body.
            body_ref_set = nx.ufsession_.Assem.CreateRefSet(body_ref_set_name, origin, matrix_value, body_array,
                                                            num_of_body_members)
            nx.ufsession_.Assem.CreateRefSet(sub_ref_set_name, origin, matrix_value, [], num_of_sub_members)
            return

        # ----------------------------------------------
        #  CreateProgressive Body and Sub Tool reference sets
        # ----------------------------------------------
        origin, matrix_value = nx.wcs_origin_and_matrix_values()

        body_array = _layer1_body_tags()

        if len(body_array) != 1:
            nx.print_("You have more than one solid body on layer one")
            return

        body_ref_set = nx.ufsession_.Assem.CreateRefSet(body_ref_set_name, origin, matrix_value, body_array,
                                                        num_of_body_members)
        nx.ufsession_.Assem.CreateRefSet(sub_ref_set_name, origin, matrix_value, [], num_of_sub_members)

        if nx.work_part().ComponentAssembly.RootComponent is None:
            return

        comp_list = _layer99_child_tags()

        nx.ufsession_.Assem.AddRefSetMembers(body_ref_set, len(comp_list), comp_list)

    @staticmethod
    def create_category_names(wp: NXOpen.BasePart) -> None:
        """CategoryRefSets.CreateCategoryNames"""
        wp.LayerCategories.CreateCategory("BODY", "", [1])
        wp.LayerCategories.CreateCategory("BURNOUT", "", [100, 101, 102, 103, 104, 105])
        wp.LayerCategories.CreateCategory("CONSTRUCTION", "", [2, 3, 4, 5, 6, 7, 8, 9, 10])
        wp.LayerCategories.CreateCategory("DATUM", "", [255])
        wp.LayerCategories.CreateCategory("FASTENERS", "", [99])
        wp.LayerCategories.CreateCategory("HANDLINGHOLES", "", [98])
        wp.LayerCategories.CreateCategory("HOLECHARTTEXT", "", [230])
        wp.LayerCategories.CreateCategory("NESTEDBLOCKS", "", [96])
        wp.LayerCategories.CreateCategory("ORDERBLOCK", "", [250])
        wp.LayerCategories.CreateCategory("SUBTOOL", "", [15, 16, 17, 18, 19, 20])
        wp.LayerCategories.CreateCategory("TITLEBLOCK", "", [200])
        wp.LayerCategories.CreateCategory("TOOLINGHOLES", "", [97])
        wp.LayerCategories.CreateCategory("WIRESTARTHOLE", "", [94])


def _layer1_body_tags() -> List[NXOpen.Tag]:
    """from Body body in __work_part_.Bodies where body.Layer == 1 && body.Tag != Tag.Null select body.Tag"""
    return [body.Tag for body in nx.work_part().Bodies if body.Layer == 1 and body.Tag != 0]


def _layer99_child_tags() -> List[NXOpen.Tag]:
    """The work part's root children on layer 99, as tags."""
    root = nx.work_part().ComponentAssembly.RootComponent
    if root is None:
        return []
    return [component.Tag for component in root.GetChildren() if component.Layer == 99 and component.Tag != 0]


def main() -> None:
    """The category-ref-sets UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("category-ref-sets"):
        try:
            # No dialog of its own: ask before doing anything (a logged Question box).
            if nx.confirm_execute("category-ref-sets"):
                CategoryRefSets.execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
