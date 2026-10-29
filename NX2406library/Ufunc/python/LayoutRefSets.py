"""
Python port of the layout-ref-sets UFunc (LayoutRefSets.execute, src\\UFuncs\\LayoutRefSets.cs).
The C# wrapper was deleted 2026-10-22 (in git at f32694f): the UFunc's menu button runs this file's main().

On a displayed *-layout part: delete every reference set except BODY / BODY_NO_SLUG / INCOMING_BODY / MATE, then
for each layer block 10/20/30/40/50 rebuild reference sets from the layer categories - the block's own layer
into its category's reference set, its bodies coloured layer + 3 into BODY_NO_SLUG, and layers block+2 ..
block+9 into the reference set named after the category holding each layer.

Run it with File -> Execute -> NX Open on this file (main() calls execute()).
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# From the source tree (src\UFuncs) the shared modules are in src\python; deployed, they are beside this file.
_shared_python = os.path.join(os.path.dirname(_here), "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.Layer  # noqa: E402

import tsg_nx as nx  # noqa: E402

# _UFunc.ufunc_layout_ref_sets
ufunc_layout_ref_sets = "layout-ref-sets"


class LayoutRefSets(object):

    @staticmethod
    def execute() -> None:
        """LayoutRefSets.execute"""
        ufunc_rev_name = nx.ufunc_rev_name(ufunc_layout_ref_sets)

        # Like the C#, the leaf is read before the null check below.
        nx.print_("{} - {}".format(ufunc_rev_name, nx.display_part().Leaf))
        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, ufunc_rev_name)

        if nx.display_part() is None:
            nx.print_("There is no displayed part loaded")
            return

        if not nx.display_part().Leaf.lower().endswith("-layout"):
            nx.print_("Layout Refset can only be used on layouts.")
            return

        refsets = [r for r in nx.display_part().GetAllReferenceSets()
                   if r.Name != "BODY"
                   and r.Name != "BODY_NO_SLUG"
                   and r.Name != "INCOMING_BODY"
                   and r.Name != "MATE"]

        for refset in refsets:
            refset_name = refset.Name
            nx.display_part().DeleteReferenceSet(refset)
            nx.print_("Deleted ref set {}".format(refset_name))

        for layer in [10, 20, 30, 40, 50]:
            _new_method(layer)


def _solid_bodies_on_layer(layer: int) -> List[NXOpen.Body]:
    """__display_part_.Bodies.Where(IsSolidBody).Where(Layer == layer)"""
    return [b for b in nx.display_part().Bodies if b.IsSolidBody and b.Layer == layer]


def _new_method(layer1: int) -> None:
    """LayoutRefSets.NewMethod - the reference sets for one layer block."""
    solid_bodies_layer_10 = _solid_bodies_on_layer(layer1)

    category = [c for c in nx.display_part().LayerCategories
                if c.Name != "ALL" and layer1 in c.GetMemberLayers()]

    if len(category) == 1:
        body_ref_set = nx.try_get_refset(nx.display_part(), category[0].Name)

        if body_ref_set is None:
            body_ref_set = nx.display_part().CreateReferenceSet()
            body_ref_set.SetName(category[0].Name)
            nx.print_("Created {} refset".format(category[0].Name))

        body_ref_set.AddObjectsToReferenceSet(solid_bodies_layer_10)
        nx.print_("Added {} body(s) to BODY refset.".format(len(solid_bodies_layer_10)))

    solid_bodies_layer_10_161 = [b for b in solid_bodies_layer_10 if b.Color == layer1 + 3]

    if len(solid_bodies_layer_10_161) > 0:
        body_no_slug_ref_set = nx.try_get_refset(nx.display_part(), "BODY_NO_SLUG")

        if body_no_slug_ref_set is None:
            body_no_slug_ref_set = nx.display_part().CreateReferenceSet()
            body_no_slug_ref_set.SetName("BODY_NO_SLUG")
            nx.print_("Created BODY_NO_SLUG refset")

        body_no_slug_ref_set.AddObjectsToReferenceSet(solid_bodies_layer_10_161)
        nx.print_("Added {} body(s) to BODY_NO_SLUG refset.".format(len(solid_bodies_layer_10_161)))

    cats = list(nx.display_part().LayerCategories)

    for layer in range(layer1 + 2, layer1 + 10):
        try:
            solid_bodies = _solid_bodies_on_layer(layer)

            if len(solid_bodies) == 0:
                continue

            cat: Optional[NXOpen.Layer.Category] = next(
                (c for c in cats if c.Name != "ALL" and layer in set(c.GetMemberLayers())), None)

            if cat is None and len(solid_bodies) > 0:
                nx.print_("Layer {} has {} but not layer category name".format(layer, len(solid_bodies)))
                continue

            assert cat is not None
            name = cat.Name

            # __HasReferenceSet (SingleOrDefault) then __ReferenceSets (Single).
            if nx.try_get_refset(nx.display_part(), name) is None:
                refset = nx.display_part().CreateReferenceSet()
                refset.SetName(name)
                nx.print_("Created Reference Set: {}".format(name))
            else:
                refset = nx.reference_sets(nx.display_part(), name)

            refset.AddObjectsToReferenceSet(solid_bodies)
            nx.print_("Added {} body(s) to ref set {}".format(len(solid_bodies), name))
        except Exception as ex:
            nx.print_exception(ex)


def main() -> None:
    """The layout-ref-sets UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("layout-ref-sets"):
        try:
            # No dialog of its own: ask before doing anything (a logged Question box).
            if nx.confirm_execute("layout-ref-sets"):
                LayoutRefSets.execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
