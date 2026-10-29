"""
Python port of the strip-ref-setter UFunc (StripRefSetter.execute, src\\UFuncs\\StripRefSetter.cs).
The C# wrapper was deleted 2026-10-22 (in git at f32694f): the UFunc's menu button runs this file's main().

On a displayed *-strip part: the root children and the non-occurrence curves / bodies on layers 100 / 101 / 102
(plus the PRESS children and the layer-235 grippers) get their used reference sets replaced and are gathered
into WORK_PARTS / LIFTED_PARTS / ALL_WITH_PRESSES / ALL_PARTS / TRANSFER_PARTS / PROG_ONLY_WORK.

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
import NXOpen.Assemblies  # noqa: E402

import tsg_nx as nx  # noqa: E402

# _UFunc.ufunc_strip_ref_setter
ufunc_strip_ref_setter = "strip-ref-setter"


class StripRefSetter(object):

    @staticmethod
    def execute() -> None:
        """StripRefSetter.execute"""
        ufunc_rev_name = nx.ufunc_rev_name(ufunc_strip_ref_setter)
        nx.print_(ufunc_rev_name)

        if nx.display_part() is None:
            nx.print_("There is no displayed part loaded")
            return

        # Need to remove the objects from the reference sets first.
        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, ufunc_rev_name)

        display = nx.display_part()

        if not display.Leaf.lower().endswith("-strip"):
            nx.print_("Strip Refsetter can only be used on a strip.")
            return

        # Like the C#, a strip with no root component fails here rather than being reported.
        root = display.ComponentAssembly.RootComponent
        assert root is not None

        layer100_components = _children_on_layer(root, 100)
        layer100_objects = _layer_objects(display, 100) + list(layer100_components)

        layer101_components = _children_on_layer(root, 101)
        layer101_objects = _layer_objects(display, 101) + list(layer101_components)

        layer102_components = _children_on_layer(root, 102)
        layer102_objects = _layer_objects(display, 102) + list(layer102_components)

        presses = [child for child in root.GetChildren() if "PRESS" in child.Name.upper()]

        nx.replace_ref_sets(display, layer101_components + layer102_components, "BODY_NO_SLUG")

        nx.replace_ref_sets(display, layer100_components + presses, "BODY")

        if len(layer100_objects) > 0:
            # WORK_PARTS
            work_parts_refset = _find_or_create(display, "WORK_PARTS")
            work_parts_refset.AddObjectsToReferenceSet(layer100_objects)

        if len(layer101_objects) > 0:
            # LIFTED_PARTS
            lifted_parts_refset = _find_or_create(display, "LIFTED_PARTS")

            # set children to body-with-no-slugs reference set before adding
            lifted_parts_refset.AddObjectsToReferenceSet(layer101_objects)

        # The C# tests layer100Objects twice (not layer101Objects); kept as written.
        if (len(layer100_objects) > 0
                or len(layer100_objects) > 0
                or len(layer102_objects) > 0
                or len(presses) > 0):
            # ALL_WITH_PRESSES
            all_with_presses_refset = _find_or_create(display, "ALL_WITH_PRESSES")

            # set children to body reference set before adding
            all_with_presses_refset.AddObjectsToReferenceSet(layer100_objects)
            # set children to body-no-slugs reference set before adding
            all_with_presses_refset.AddObjectsToReferenceSet(layer101_objects)
            # set children to body-no-slugs reference set before adding
            all_with_presses_refset.AddObjectsToReferenceSet(layer102_objects)
            # set children to body reference set before adding
            all_with_presses_refset.AddObjectsToReferenceSet(presses)

            grippers = _children_on_layer(root, 235)

            nx.replace_ref_sets(display, grippers, "BODY")
            all_with_presses_refset.AddObjectsToReferenceSet(grippers)

        if len(layer100_objects) > 0 or len(layer100_objects) > 0 or len(layer102_objects) > 0:
            # ALL_PARTS
            all_parts_refset = _find_or_create(display, "ALL_PARTS")

            # set children to body reference set before adding
            all_parts_refset.AddObjectsToReferenceSet(layer100_objects)
            # set children to body-no-slugs reference set before adding
            all_parts_refset.AddObjectsToReferenceSet(layer101_objects)
            # set children to body-no-slugs reference set before adding
            all_parts_refset.AddObjectsToReferenceSet(layer102_objects)

        # TRANSFER_PARTS
        if len(layer102_components) > 0 and display.Leaf.lower().endswith("-900-strip"):
            transfer_parts_refset = _find_or_create(display, "TRANSFER_PARTS")

            # set children to body-no-slugs reference set before adding
            transfer_parts_refset.AddObjectsToReferenceSet(layer102_components)

        if (not display.Leaf.lower().endswith("-010-strip")
                and (len(layer100_objects) > 0
                     or len(layer100_objects) > 0
                     or len(layer102_objects) > 0)):
            # PROG_ONLY_WORK
            prog_only_work_refset = _find_or_create(display, "PROG_ONLY_WORK")

            # set children to body reference set before adding
            prog_only_work_refset.AddObjectsToReferenceSet(
                [obj for obj in layer100_objects if not obj.Name.startswith("T")])

            # set children to body-no-slugs reference set before adding
            prog_only_work_refset.AddObjectsToReferenceSet(
                [obj for obj in layer101_objects if not obj.Name.startswith("T")])

            # set children to body-no-slugs reference set before adding
            prog_only_work_refset.AddObjectsToReferenceSet(
                [obj for obj in layer102_objects if not obj.Name.startswith("T")])

        nx.prompt("Complete")


def _children_on_layer(root: NXOpen.Assemblies.Component, layer: int) -> List[NXOpen.Assemblies.Component]:
    """RootComponent.GetChildren().Where(child => child.Layer == layer)"""
    return [child for child in root.GetChildren() if child.Layer == layer]


def _layer_objects(part: NXOpen.BasePart, layer: int) -> List[NXOpen.NXObject]:
    """Layers.GetAllObjectsOnLayer(layer) - the curves and bodies that are not occurrences."""
    return [obj for obj in part.Layers.GetAllObjectsOnLayer(layer)
            if isinstance(obj, (NXOpen.Curve, NXOpen.Body)) and not obj.IsOccurrence]


def _find_or_create(part: NXOpen.BasePart, name: str) -> NXOpen.ReferenceSet:
    """
    The __FindReferenceSetOrNull / CreateReferenceSet / SetName block StripRefSetter repeats per reference set.
    Unlike tsg_nx.find_or_create_reference_set it prints nothing, and (SingleOrDefault) raises on a duplicate.
    """
    refset = nx.try_get_refset(part, name)

    if refset is None:
        refset = part.CreateReferenceSet()
        refset.SetName(name)

    return refset


def main() -> None:
    """The strip-ref-setter UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("strip-ref-setter"):
        try:
            # No dialog of its own: ask before doing anything (a logged Question box).
            if nx.confirm_execute("strip-ref-setter"):
                StripRefSetter.execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
