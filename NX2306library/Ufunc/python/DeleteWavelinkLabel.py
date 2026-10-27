"""
The delete-wavelink-label UFunc: a standalone Python UFunc (no C# class); its menu button runs this file's main().

After the "Are you sure" box, walks the display part's assembly from the top down - the display part itself, then
every loaded, unsuppressed component in tree order, each part once - and goes through every feature of each part.
A linked body (LINKED_BODY feature) whose name has a detail name in it ({job}-{op}-{detail}, all digits, as in
006969-010-012) has its name removed, so the feature goes back to NX's default "Linked Body (n)". The link itself is
left alone. Assembly Wavelink names its links "{linked}, {reference set}, {owner}" (Static.LinkedBodyName), which is
how detail names get onto them.

A partially loaded part is loaded fully first (its features are not there otherwise). Nothing is saved. One undo mark
covers the run. The listing window gets every renamed feature, grouped by part, then the totals: parts and linked
bodies looked at, labels removed, and any part or feature that failed.

Run standalone: File -> Execute -> NX Open on this file runs main().
"""

from __future__ import annotations

import os
import re
import sys
from typing import Dict, List, Tuple

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

ufunc_name = "delete-wavelink-label"

# A detail name anywhere in the feature name: {job}-{op}-{detail}, all digits (RegexDetail without the anchors). Not
# next to another letter, digit or hyphen, so a fastener like 8mm-shcs-020-2x or a longer run of numbers is not one.
_DetailInName = re.compile(r"(?<![\w-])\d+-\d+-\d+(?![\w-])")


def has_detail_name(name: str) -> bool:
    """True when name has a {job}-{op}-{detail} detail name in it."""
    return bool(name) and _DetailInName.search(name) is not None


class DeleteWavelinkLabel(object):

    @staticmethod
    def execute() -> None:
        display = nx.display_part()
        if display is None:
            nx.print_("There is no displayed part loaded.")
            return

        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Delete Wavelink Label")

        # Top down: the display part, then its components in tree order (descendants is pre-order).
        parts: List[NXOpen.BasePart] = [display]
        root = nx.root_component(display)
        if root is not None:
            for component in nx.descendants(root, include_root=False):
                parts.append(nx.prototype(component))

        seen = set()
        parts_scanned = 0
        linked_scanned = 0
        removed: Dict[str, List[str]] = {}
        failures: List[Tuple[str, str]] = []

        for part in parts:
            if part is None or part.Tag in seen:
                continue
            seen.add(part.Tag)

            try:
                _load_fully(part)
                features = list(part.Features.GetFeatures())
            except Exception as ex:
                failures.append((part.Leaf, "could not read its features: {}".format(ex)))
                continue

            parts_scanned += 1

            for feature in features:
                try:
                    if not nx.is_linked_body(feature):
                        continue
                    linked_scanned += 1
                    name = str(feature.Name or "")
                    if not has_detail_name(name):
                        continue
                    feature.SetName("")
                    removed.setdefault(part.Leaf, []).append(name)
                except Exception as ex:
                    failures.append((part.Leaf, "{}: {}".format(_feature_label(feature), ex)))

        _print_summary(parts_scanned, linked_scanned, removed, failures)


def _load_fully(part: NXOpen.BasePart) -> None:
    """A partially loaded part has no features to read: load it fully first."""
    if isinstance(part, NXOpen.Part) and not part.IsFullyLoaded:
        part.LoadThisPartFully()


def _feature_label(feature: NXOpen.Features.Feature) -> str:
    try:
        return str(feature.GetFeatureName())
    except Exception:
        return "a feature"


def _print_summary(parts_scanned: int, linked_scanned: int, removed: Dict[str, List[str]],
                   failures: List[Tuple[str, str]]) -> None:
    total = sum(len(names) for names in removed.values())

    nx.print_("Delete Wavelink Label")
    nx.print_("=====================")
    for leaf in removed:
        nx.print_("{} - {} label(s) removed:".format(leaf, len(removed[leaf])))
        for name in removed[leaf]:
            nx.print_("    {}".format(name))
    if not removed:
        nx.print_("No linked body had a detail name in its name.")

    if failures:
        nx.print_("")
        nx.print_("Failed ({}):".format(len(failures)))
        for leaf, message in failures:
            nx.print_("    {}: {}".format(leaf, message))

    nx.print_("")
    nx.print_("Parts looked at:          {}".format(parts_scanned))
    nx.print_("Linked bodies looked at:  {}".format(linked_scanned))
    nx.print_("Labels removed:           {} in {} part(s)".format(total, len(removed)))
    nx.print_("Failures:                 {}".format(len(failures)))
    nx.syslog("Delete Wavelink Label: {} label(s) removed in {} part(s), {} linked bodies in {} parts, {} failure(s)"
              .format(total, len(removed), linked_scanned, parts_scanned, len(failures)))


def main() -> None:
    """The delete-wavelink-label UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            if nx.confirm_execute(ufunc_name):
                DeleteWavelinkLabel.execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
