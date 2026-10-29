"""
Python port of the copy-to-layer-50 UFunc (CopyToLayer50, src\\UFuncs\\CopyToLayer50.cs).
The C# wrapper was deleted 2026-10-22 (in git at f32694f): the UFunc's menu button runs this file's main().

For each picked component: copy its single layer-1 solid body to layer 50, name the copy's feature with
today's date, make it white (7) and phantom, and take it out of the BODY reference set. Whatever was on layer
50 before moves to layer 51.

Run standalone: File -> Execute -> NX Open on this file runs main().
"""

from __future__ import annotations

import datetime
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
import NXOpen.Assemblies  # noqa: E402

import tsg_nx as nx  # noqa: E402

LAYER = 50


class CopyToLayer50(object):

    @staticmethod
    def execute() -> None:
        """CopyToLayer50.execute"""
        message = "{} - Copy To Layer 50".format(nx.assembly_file_version())

        comp_list = nx.select_many_components(message)

        if len(comp_list) == 0:
            return

        total_copied = 0

        with nx.display_part_reset():
            for comp in comp_list:
                nx.print_("/////////////////")
                nx.set_work_component(comp)

                proto = cast(NXOpen.Part, nx.prototype(comp))

                # if body exists on layer 50, delete body
                bodies_on_layer_50 = [b for b in proto.Bodies.ToArray() if b.IsSolidBody and b.Layer == LAYER]

                solid_bodies_layer_1 = [b for b in proto.Bodies.ToArray() if b.IsSolidBody and b.Layer == 1]

                if len(solid_bodies_layer_1) == 0:
                    nx.print_("Did not a solid body on layer 1 in part {}".format(comp.DisplayName))
                    return
                if len(solid_bodies_layer_1) > 1:
                    nx.print_("There is more than one solid body on layer 1 in part {}".format(comp.DisplayName))
                    return

                now = datetime.datetime.now()
                date = "{}-{}-{}".format(now.year, now.month, now.day)

                layer_50_bodies: List[NXOpen.Body] = [
                    o for o in proto.Layers.GetAllObjectsOnLayer(LAYER) if isinstance(o, NXOpen.Body)]

                proto.Layers.CopyObjects(LAYER, solid_bodies_layer_1)

                # Enumerable.Except (distinct, set difference) then OfType<Body>; NXObjects compare by tag here.
                before = {b.Tag for b in layer_50_bodies}
                new_layer_50_bodies = nx.distinct_by(
                    [o for o in proto.Layers.GetAllObjectsOnLayer(LAYER)
                     if isinstance(o, NXOpen.Body) and o.Tag not in before],
                    lambda b: b.Tag)

                for body in new_layer_50_bodies:
                    body.OwningPart.Features.GetParentFeatureOfBody(body).SetName(date)
                    body.Color = 7
                    body.LineFont = NXOpen.DisplayableObject.ObjectFont.Phantom
                    body.RedisplayObject()

                try:
                    nx.reference_sets(proto, "BODY").RemoveObjectsFromReferenceSet(list(new_layer_50_bodies))
                except Exception as ex:
                    nx.print_exception(ex)

                proto.Layers.MoveDisplayableObjects(LAYER + 1, layer_50_bodies)

                for body in bodies_on_layer_50:
                    body.Color = 7
                    body.LineFont = NXOpen.DisplayableObject.ObjectFont.Phantom
                    body.RedisplayObject()

                    nx.print_("Copied solid body to "
                              "{} in part {}".format(proto.Features.GetAssociatedFeature(body).GetFeatureName(),
                                                     comp.DisplayName))

                total_copied += len(new_layer_50_bodies)

                try:
                    nx.reference_sets(proto, "BODY").RemoveObjectsFromReferenceSet(list(bodies_on_layer_50))
                except Exception as ex:
                    nx.print_exception(ex)

        nx.print_("Copied {} solid bodies to layer {}".format(total_copied, LAYER))


def main() -> None:
    """The copy-to-layer-50 UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("copy-to-layer-50"):
        try:
            # No dialog of its own: ask before doing anything (a logged Question box).
            if nx.confirm_execute("copy-to-layer-50"):
                CopyToLayer50.execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
