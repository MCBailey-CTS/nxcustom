"""
Python port of the clean-body-ref-set UFunc (CleanBodyRefSet, src\\UFuncs\\CleanBodyRefSet.cs).

Select components; each distinct prototype behind them is cleaned: layer 1 is emptied of everything but its
solid bodies (points -> 7, curves -> 5, datum planes -> 11, datum axes / csys -> 255, sheet bodies -> 10, the
rest -> 11), published datum planes / points leave the BODY reference set, and then everything in BODY that
is not a component, a solid body or one of their edges / faces is removed from it.

Run it with File -> Execute -> NX Open on this file (main() calls execute(), selection included).
"""

from __future__ import annotations

import os
import sys
from typing import Iterable, List, TypeVar

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402

import tsg_nx as nx  # noqa: E402

# [UFunc("clean-body-ref-set")]
ufunc_clean_body_ref_set = "clean-body-ref-set"

# Layer that curves are parked on.
LayerCurve = 5

# Layer that points are parked on.
LayerPoint = 7

# Layer that datum planes are parked on. Same layer the catch-all sweep below uses, so anything left over on
# layer 1 lands with them.
LayerDatumPlane = 11


class CleanBodyRefSet(object):

    @staticmethod
    def execute_part(part: NXOpen.BasePart) -> None:
        """CleanBodyRefSet.execute(Part) - cleans one part (the C# overload of execute)."""
        nx.set_work_part(part)

        layer1_objects = _distinct(part.Layers.GetAllObjectsOnLayer(1))

        solid_bodies = _distinct([o for o in layer1_objects if isinstance(o, NXOpen.Body) and o.IsSolidBody])

        # __HasReferenceSet / __ReferenceSets are SingleOrDefault / Single, so a duplicate BODY raises here.
        body_refset = nx.try_get_refset(part, "BODY")

        refset_members: List[NXOpen.NXObject] = [] if body_refset is None else list(body_refset.AskAllDirectMembers())

        # Datum planes and points are gathered from layer 1 *and* from the BODY reference set, since one can be
        # published by the reference set while living on some other layer. They go to different layers, but
        # they leave the BODY reference set together, below.
        datums_and_points = _distinct([o for o in list(layer1_objects) + refset_members
                                       if isinstance(o, (NXOpen.DatumPlane, NXOpen.Point))])

        for p in datums_and_points:
            if isinstance(p, NXOpen.Point):
                nx.set_layer(p, LayerPoint)
        for d in datums_and_points:
            if isinstance(d, NXOpen.DatumPlane):
                nx.set_layer(d, LayerDatumPlane)

        # Only the ones that really are direct members are handed back, so nothing is removed twice.
        published_datums_and_points = [o for o in refset_members if isinstance(o, (NXOpen.DatumPlane, NXOpen.Point))]

        if len(published_datums_and_points) > 0 and body_refset is not None:
            body_refset.RemoveObjectsFromReferenceSet(published_datums_and_points)

        # sql
        # Add string version of NXOpen.Curve and other types.
        # That way you can add types to the database
        # with the corresponding layers.
        for c in layer1_objects:
            if isinstance(c, NXOpen.Curve):
                nx.set_layer(c, LayerCurve)
        for a in layer1_objects:
            if isinstance(a, NXOpen.DatumAxis):
                nx.set_layer(a, 255)
        for s in layer1_objects:
            if isinstance(s, NXOpen.CoordinateSystem):
                nx.set_layer(s, 255)

        for b in layer1_objects:
            if isinstance(b, NXOpen.Body) and b.IsSheetBody:
                nx.set_layer(b, 10)

        solid_tags = {body.Tag for body in solid_bodies}
        for o in _distinct(part.Layers.GetAllObjectsOnLayer(1)):
            if o.Tag in solid_tags:
                continue
            if isinstance(o, NXOpen.DisplayableObject):
                nx.set_layer(o, 11)

        if body_refset is None:
            return

        components = [m for m in body_refset.AskAllDirectMembers() if isinstance(m, NXOpen.Assemblies.Component)]

        bodies = [m for m in body_refset.AskAllDirectMembers() if isinstance(m, NXOpen.Body) and m.IsSolidBody]

        edges = [e for b in bodies for e in b.GetEdges()]
        faces = [f for b in bodies for f in b.GetFaces()]

        keep = {o.Tag for o in components}
        keep.update(o.Tag for o in bodies)
        keep.update(o.Tag for o in edges)
        keep.update(o.Tag for o in faces)

        # Enumerable.Except is a set difference, so the remainder is distinct as well.
        objects = _distinct([o for o in body_refset.AskAllDirectMembers()
                             if o.Tag not in keep and isinstance(o, NXOpen.NXObject)])

        if len(objects) == 0:
            return

        body_refset.RemoveObjectsFromReferenceSet(objects)

        nx.ufsession_.Disp.RegenerateDisplay()
        nx.ufsession_.Disp.Refresh()

    @staticmethod
    def execute() -> None:
        """
        CleanBodyRefSet.execute() - selects components and cleans each distinct prototype part behind them.
        Each part is cleaned in its own try, so a part that throws - a duplicate BODY reference set makes the
        Single lookups throw, for one - costs that part rather than the rest of the batch, and says so in the
        listing window.
        """
        ufunc_rev_name = nx.ufunc_rev_name(ufunc_clean_body_ref_set)

        # Same selection template the Merlin entry points use (TryBeginGmEntry / TryBeginPierce): a cue + title
        # carrying the assembly version and an explicit cancel check.
        selected_comps = nx.select_components(
            "Select components to clean: {}".format(ufunc_rev_name),
            ufunc_rev_name)

        if selected_comps is None:
            return

        # Distinct prototypes - two occurrences of the same detail would otherwise clean it twice.
        selected_parts = _distinct([nx.prototype(c) for c in selected_comps])

        with nx.display_part_reset(), nx.suppress_display(), nx.do_update(), nx.regenerate_display():
            for i in range(len(selected_parts)):
                part = selected_parts[i]

                # The cue line is the only progress the user gets - the display is suppressed for the whole
                # run, so a part that takes a while otherwise looks like a hang.
                nx.prompt("{} of {} -> {}".format(i + 1, len(selected_parts), part.Leaf))

                with nx.display_part_reset():
                    try:
                        CleanBodyRefSet.execute_part(part)
                    except Exception as ex:
                        nx.print_exception(ex, part.Leaf)


_TObj = TypeVar("_TObj", bound=NXOpen.TaggedObject)


def _distinct(objects: Iterable[_TObj]) -> List[_TObj]:
    """Enumerable.Distinct / ToHashSet over NX objects - the first of each Tag, in order."""
    return nx.distinct_by(objects, lambda obj: obj.Tag)


def main() -> None:
    """Standalone entry (File -> Execute -> NX Open)."""
    CleanBodyRefSet.execute()


if __name__ == "__main__":
    main()
