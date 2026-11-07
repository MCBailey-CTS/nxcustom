"""
The repair-broken-links UFunc: a standalone Python UFunc (no C# class); its menu button runs this file's main().

Run from the -000. After the "Are you sure" box, walks every loaded, unsuppressed part under the display part, strips
and layouts left out, and looks for broken LINKED_BODY features. Each one's source is worked out by broken_links, which
changes nothing: the part NX names, found in the assembly (the strip at the base of the -000, for most) by its leaf, and
the one body in it with every corner of the link's Subtract or Intersect on its surface.

The plan goes to the listing window, then one Question box asks. Each link is relinked in its place in the feature
order and the part updated. A relink that NX refuses, that leaves the link broken or that moves the part's volume is
undone, so a relink never changes a part. A link with no exact match is left broken and listed with the closest body:
one with an Offset, Delete or Move Face on the link itself does not sit on its source, and needs fixing by hand.
So does one with a Chamfer on the cut's edge: it matches, but NX refuses the relink, and the undone line names the
Chamfer.

Unloaded parts are not looked at: the count is listed. One visible undo mark, "Repair Broken Links", covers the run and
nothing is saved. The progress window (progress_window.ProgressWindow) follows the relinks.

Run standalone: File -> Execute -> NX Open on this file runs main().
"""

from __future__ import annotations

import os
import sys
import time
from typing import Dict, List, NamedTuple, Tuple

# Session.Execute does not put the script's folder on sys.path, so the shared modules would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# The shared modules are in the python folder beside this file (src\UFuncs\python; deployed, Ufunc\python).
_shared_python = os.path.join(_here, "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.Features  # noqa: E402

import broken_links  # noqa: E402
import progress_window  # noqa: E402
import tsg_nx as nx  # noqa: E402
from tsg_dialog import title_with_version  # noqa: E402

ufunc_name = "repair-broken-links"

_Title = "Repair Broken Links"


class _Plan(NamedTuple):
    """What the walk found: the links with a source, the rest with the reason, and what it could not look at."""
    relinks: List[Tuple[NXOpen.Features.Feature, broken_links.Source]]
    left: List[str]
    unloaded: int
    partial: List[str]


def _is_strip_or_layout(leaf: str) -> bool:
    return "strip" in leaf.lower() or "layout" in leaf.lower()


def _label(part: NXOpen.BasePart, feature: NXOpen.Features.Feature) -> str:
    return "{} {}".format(part.Leaf, feature.GetFeatureName())


def plan(top: NXOpen.BasePart) -> _Plan:
    """Every broken link under top and where it goes. Changes nothing."""
    root = nx.root_component(top)
    by_part: Dict[int, List[NXOpen.Assemblies.Component]] = {}
    if root is not None:
        for occurrence in nx.descendants(root, include_root=False):
            by_part.setdefault(nx.prototype(occurrence).Tag, []).append(occurrence)
    all_occurrences = list(nx.descendants(root, include_root=False, include_unloaded=True)) if root is not None else []
    unloaded = sum(1 for c in all_occurrences if not nx.is_loaded(c))

    by_leaf = broken_links.occurrences_by_leaf(top)
    relinks: List[Tuple[NXOpen.Features.Feature, broken_links.Source]] = []
    left: List[str] = []
    partial: List[str] = []
    for components in by_part.values():
        part = nx.prototype(components[0])
        if _is_strip_or_layout(part.Leaf):
            continue
        if not part.IsFullyLoaded:
            partial.append(part.Leaf)
            continue
        for feature in part.Features.GetFeatures():
            if not broken_links.is_broken(feature):
                continue
            try:
                source = broken_links.find_source(feature, components, by_leaf)
                if isinstance(source, str):
                    left.append("{}: {}".format(_label(part, feature), source))
                else:
                    relinks.append((feature, source))
            except Exception as ex:
                nx.print_exception(ex, "Repair Broken Links: could not read {}".format(_label(part, feature)))
    return _Plan(relinks, left, unloaded, partial)


def _list(found: _Plan) -> None:
    nx.print_("{}: {} broken link(s) can be relinked, {} cannot.".format(_Title, len(found.relinks), len(found.left)))
    for feature, source in found.relinks:
        nx.print_("  {} -> {}".format(_label(nx.prototype(source.component), feature), source.occurrence.DisplayName))
    for line in found.left:
        nx.print_("  left broken: {}".format(line))
    if found.unloaded:
        nx.print_("  {} component(s) are not loaded, so their parts were not looked at.".format(found.unloaded))
    if found.partial:
        nx.print_("  partially loaded, not looked at: {}".format(", ".join(sorted(found.partial))))


def apply(found: _Plan) -> Tuple[int, List[str]]:
    """Each relink in turn, under one undo mark. Returns how many held, and each that was undone with why."""
    title = title_with_version(_Title)
    window = progress_window.ProgressWindow(title, "RepairBrokenLinks", progress_window.BottomRight)
    started = time.time()
    done = 0
    undone: List[str] = []
    nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, _Title)
    try:
        with nx.display_part_reset():
            for index, (feature, source) in enumerate(found.relinks):
                label = _label(nx.prototype(source.component), feature)
                window.write_line("{} of {}: {}".format(index + 1, len(found.relinks), label))
                try:
                    reason = broken_links.relink(feature, source)
                    if reason is None:
                        done += 1
                        nx.print_("  relinked {} to {}".format(label, source.occurrence.DisplayName))
                    else:
                        undone.append("{}: {}".format(label, reason))
                        nx.print_("  undone: {}: {}".format(label, reason))
                        window.write_line("  undone: {}".format(reason))
                except Exception as ex:
                    nx.print_exception(ex, "Repair Broken Links: could not relink {}".format(label))
                    undone.append("{}: {}".format(label, ex))
    finally:
        minutes, seconds = divmod(int(round(time.time() - started)), 60)
        window.set_title("{} - finished".format(title))
        window.write_line("Finished: {} of {} relinked in {}m {:02d}s".format(
            done, len(found.relinks), minutes, seconds))
        window.stop_following()
    return done, undone


def execute() -> None:
    top = nx.display_part()
    if top is None or nx.root_component(top) is None:
        nx.show_error("{}: display the -000 first.".format(_Title))
        return

    found = plan(top)
    _list(found)
    if not found.relinks:
        nx.print_("{}: nothing to relink.".format(_Title))
        return

    question = "Relink {} broken link(s)? {} cannot be relinked. The listing window has them all.".format(
        len(found.relinks), len(found.left))
    if nx.message_box(_Title, NXOpen.NXMessageBox.DialogType.Question, question) != nx.MessageBoxYes:
        nx.mark_cancelled("the relink question")
        return

    done, undone = apply(found)
    nx.print_("{}: {} relinked, {} undone, {} left broken. Nothing is saved.".format(
        _Title, done, len(undone), len(found.left)))


def main() -> None:
    """The repair-broken-links UFunc - its menu button runs this file. An escaping exception is printed."""
    with nx.merlin_run(ufunc_name):
        try:
            if nx.confirm_execute(ufunc_name):
                execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
