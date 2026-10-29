"""
Python port of the delete-component UFunc (DeleteComponent, src\\UFuncs\\DeleteComponent.cs).

Pick children of the display part. For each one, find the live LINKED_BODY in the display part whose
assembly-context source is that child, delete the link and everything built on it, then delete the child.

Run standalone: File -> Execute -> NX Open on this file runs main().
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List, Sequence, Tuple

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.Features  # noqa: E402

import tsg_nx as nx  # noqa: E402

ufunc_name = "delete-component"


class DeleteComponent(object):

    @staticmethod
    def execute() -> None:
        """DeleteComponent.execute"""
        # 01. Select component. For now limit it to only children of the current Work Part.
        # The C# predicate runs as a UF filter proc inside the dialog, rejecting anything that is not a child
        # of the display part; Python cannot install a filter proc, so the picks are filtered afterwards.
        picked = nx.select_many_components(nx.ufunc_rev_name(ufunc_name))
        child_tags = {child.Tag for child in nx.children(nx.display_part())}
        selected_components = [c for c in picked if c.Tag in child_tags]

        # Keyed by tag (insertion-ordered, like the C# Dictionary). As in the C#, a second matching link for the
        # same component replaces the first one's list rather than adding to it.
        comp_feat_dict: Dict[NXOpen.Tag, Tuple[NXOpen.Assemblies.Component, List[NXOpen.Features.Feature]]] = {}

        for component in selected_components:
            for feature in list(nx.display_part().Features.GetFeatures()):
                try:
                    if not isinstance(feature, NXOpen.Features.ExtractFace):
                        continue

                    extract = feature

                    if nx.is_link_broken(extract):
                        continue

                    if not nx.is_linked_body(extract):
                        continue

                    xform_tag = nx.xform_tag(extract)

                    root = nx.root_component(nx.display_part())
                    if root is None:
                        # C#: NullReferenceException on __RootComponent().Tag, caught below.
                        raise RuntimeError("The display part has no root component.")

                    from_part_occ = nx.ufsession_.So.AskAssyCtxtPartOcc(xform_tag, root.Tag)

                    if component.Tag != from_part_occ:
                        continue

                    features: List[NXOpen.Features.Feature] = [feature]
                    features.extend(feature.GetAllChildren())
                    comp_feat_dict[component.Tag] = (component, features)
                except Exception as ex:
                    nx.print_exception(ex)

        for comp_key, features in comp_feat_dict.values():
            try:
                _delete_objects(list(features))
                _delete_objects([comp_key])
            except Exception as ex:
                nx.print_exception(ex)

        # 02. Therefore any linked body attached to the child must be a feature of the current work part.
        # 03. Detect the linked body.
        # 04. Get any children attached to the linked body. Most likely just a subtraction.
        # 05. Delete the children features in reverse order.
        # 06. Delete the linked body.
        # 07. Delete the child component.

        # You will need to make sure that the Component doesn't have any linked bodies else where.
        # For instance if the component is tapped or reamed.


def _delete_objects(objects: Sequence[NXOpen.TaggedObject]) -> None:
    """Session.__DeleteObjects - adds the objects to the delete list inside a DoUpdate.

    Private on purpose: tsg_nx currently defines delete_objects twice with different signatures (*objects and
    a sequence), so calling it would depend on which definition survives.
    """
    with nx.do_update():
        nx.session_.UpdateManager.AddObjectsToDeleteList(list(objects))


def main() -> None:
    """Standalone entry (File -> Execute -> NX Open)."""
    DeleteComponent.execute()


if __name__ == "__main__":
    main()
