"""
The contains-datum-plane UFunc: a standalone Python UFunc (no C# class); its menu button runs this file's main().

After the "Are you sure" box, walks the display part's assembly from the top down (run it with the -000 displayed) -
the display part itself, then every loaded, unsuppressed component in tree order, each part once - and prints to the
listing window every part that has a datum plane in it, with each plane's feature name. The three planes of a datum
csys do not count: every detail has one. A partially loaded part is loaded fully first (its datums are not there
otherwise). Read only: nothing is changed or saved.

Run standalone: File -> Execute -> NX Open on this file runs main().
"""

from __future__ import annotations

import os
import sys
from typing import List, Tuple

# Session.Execute does not put the script's folder on sys.path, so the shared modules would not import.
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

ufunc_name = "contains-datum-plane"


class ContainsDatumPlane(object):

    @staticmethod
    def execute() -> None:
        display = nx.display_part()
        if display is None:
            nx.print_("There is no displayed part loaded.")
            return
        if not display.Leaf.endswith("-000"):
            nx.print_("Note: the display part {} is not a -000; checking from it down.".format(display.Leaf))

        # Top down: the display part, then its components in tree order (descendants is pre-order).
        parts: List[NXOpen.BasePart] = [display]
        root = nx.root_component(display)
        if root is not None:
            for component in nx.descendants(root, include_root=False):
                parts.append(nx.prototype(component))

        seen = set()
        parts_scanned = 0
        found: List[Tuple[str, List[str]]] = []
        failures: List[Tuple[str, str]] = []

        for part in parts:
            if part is None or part.Tag in seen:
                continue
            seen.add(part.Tag)
            try:
                _load_fully(part)
                planes = _datum_planes(part)
            except Exception as ex:
                failures.append((part.Leaf, str(ex)))
                continue
            parts_scanned += 1
            if planes:
                found.append((part.Leaf, planes))

        nx.print_("Contains Datum Plane")
        nx.print_("====================")
        for leaf, planes in found:
            nx.print_("{} - {} datum plane(s): {}".format(leaf, len(planes), ", ".join(planes)))
        if not found:
            nx.print_("No part has a datum plane.")
        if failures:
            nx.print_("")
            nx.print_("Could not check ({}):".format(len(failures)))
            for leaf, message in failures:
                nx.print_("    {}: {}".format(leaf, message))
        nx.print_("")
        nx.print_("Parts checked:              {}".format(parts_scanned))
        nx.print_("Parts with a datum plane:   {}".format(len(found)))
        nx.syslog("Contains Datum Plane: {} of {} part(s) have a datum plane, {} failure(s)"
                  .format(len(found), parts_scanned, len(failures)))


def _load_fully(part: NXOpen.BasePart) -> None:
    """A partially loaded part has no datums to read: load it fully first."""
    if isinstance(part, NXOpen.Part) and not part.IsFullyLoaded:
        part.LoadThisPartFully()


def _datum_planes(part: NXOpen.BasePart) -> List[str]:
    """A label for each datum plane in part that is not one of a datum csys's three planes."""
    labels: List[str] = []
    if not isinstance(part, NXOpen.Part):
        return labels
    for datum in part.Datums:
        if not isinstance(datum, NXOpen.DatumPlane):
            continue
        feature = None
        try:
            feature = part.Features.GetAssociatedFeature(datum)
        except Exception:
            feature = None
        if feature is not None:
            if feature.FeatureType == "DATUM_CSYS":
                continue
            labels.append(str(feature.GetFeatureName()))
        else:
            labels.append(str(datum.Name or "Datum Plane (no feature)"))
    return labels


def main() -> None:
    """The contains-datum-plane UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            if nx.confirm_execute(ufunc_name):
                ContainsDatumPlane.execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
