"""
The component-assign-name UFunc: a standalone Python UFunc (no C# class, 2026-10-29); its menu button runs this
file's main(). From the "Assign Detail Number Program" spec (Assign Detail Number Program 1.docx): give the
components of a design their detail numbers for ordering, by Save As.

Run from the -000 ({job}-{op}-000). It finds the components still without a detail number - a part whose leaf is not
{job}-{op}-NNN / -NNNN - and saves each as the next free number of its station's range:
  - Only parts in the -000's own folder are renamed, which leaves out the library fasteners and keys (G:\\0Library),
    and the strip / layout / simulation parts (their own folders). A leaf holding strip, layout, sim or press is
    skipped anyway, and so is any {job}-{op}-... leaf (the details and the station assemblies themselves).
  - A part's station is its nearest ancestor named {job}-{op}-{station} (lsh, lad01, lad02, lftr, ush, uad01, ...).
    A part with none is listed and skipped.
  - Each station's range is its part's DETAIL NUMBER RANGE attribute ("21-200"; the title is matched ignoring
    case). The dialog lists the stations found with their ranges for the designer to enter or change; with GM picked,
    a station without the attribute starts with the GM range from the spec (GmRanges). A range entered is written
    back to the station's attribute, so the next run starts from it.
  - The numbers follow the range in order, skipping 001-014 (lower / upper die shoe 001 / 002, castings 3-14) and
    every number already taken: the file exists in the folder, a part with that leaf is loaded, or this run used it.
    When a station runs out, its remaining parts are skipped (listed) - the designer Saves As them by hand.
  - A part is renamed once, however many times it is used; it takes the first station it is found under.
    Components whose name was the old leaf are renamed to the new one.

The plan is listed and a Question box asks before any Save As. Save As writes the new file and leaves the old one on
disk; the assemblies above the renamed parts are modified, not saved - save the assembly to keep the new names.
NEVER RUN IN NX.

The spec starts with the GM version: TSG has no range table yet, so with TSG picked the ranges come from the
attribute (or what is typed) only.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

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
import NXOpen.BlockStyler  # noqa: E402

import tsg_nx as nx  # noqa: E402
from tsg_dialog import CustomerGm, CustomerTsg, Dialog, title_with_version  # noqa: E402

ufunc_name = "component-assign-name"

# NX will not create a dialog from inside another dialog's callback.
_ErrorCannotLaunchDialog = 3520048

RangeAttribute = "DETAIL NUMBER RANGE"

# The spec's GM table, in its order (the dialog lists stations in this order, the rest after them alphabetically).
GmRanges: List[Tuple[str, int, int]] = [
    ("LSH", 15, 230),
    ("LAD01", 231, 300),
    ("LAD02", 301, 500),
    ("LFTR", 1001, 2000),
    ("USH", 500, 550),
    ("UAD01", 551, 650),
    ("UAD02", 651, 800),
    ("UPD01", 801, 850),
    ("UPD02", 851, 980),
]

# Never used: 001 / 002 the lower / upper die shoe, 3-14 the castings.
ReservedNumbers = range(1, 15)

# Leaves never renamed (the strip, layouts, simulation, presses).
_SkipWords = ("strip", "layout", "sim", "press")

# The dialog's range rows (ComponentAssignName.dlx: range_00 .. range_19).
MaxStations = 20

_RangePattern = re.compile(r"^\s*(\d+)\s*(?:-|to|TO|To)\s*(\d+)\s*$")


class _Station(object):
    """A {job}-{op}-{station} assembly and the parts found under it to number."""

    def __init__(self, part: NXOpen.BasePart, name: str) -> None:
        self.part = part
        self.name = name
        self.attribute_title = _range_attribute_title(part)
        self.attribute_range = (nx.get_attribute(part, self.attribute_title) or "").strip() \
            if self.attribute_title else ""
        self.parts: List[NXOpen.BasePart] = []


class _Job(object):
    """What the scan of the -000 found."""

    def __init__(self, folder: str, prefix: str) -> None:
        self.folder = folder
        # "{job}-{op}-"
        self.prefix = prefix
        self.stations: List[_Station] = []
        # Parts to number with no station above them.
        self.orphans: List[NXOpen.BasePart] = []


def _range_attribute_title(part: NXOpen.BasePart) -> str:
    """The part's DETAIL NUMBER RANGE attribute title as spelled on it (any case), or "" when it has none."""
    try:
        for info in part.GetUserAttributes():
            if info.Title.strip().upper() == RangeAttribute:
                return str(info.Title)
    except Exception as ex:
        nx.print_exception(ex)
    return ""


def gm_range(station: str) -> str:
    """The spec's GM range for a station name ("LAD01" -> "231-300"), or ""."""
    return next(("{}-{}".format(low, high) for name, low, high in GmRanges if name == station.upper()), "")


def parse_range(text: str) -> Optional[Tuple[int, int]]:
    """ "21-200" / "21 to 200" -> (21, 200); None for blank or anything else."""
    match = _RangePattern.match(text or "")
    if match is None:
        return None
    low, high = int(match.group(1)), int(match.group(2))
    return (low, high) if low <= high else None


def scan(display: NXOpen.Part) -> _Job:
    """The stations under the -000 and the parts under each that need a detail number (see the module docstring)."""
    match = re.match(r"^(?P<job>\d+)-(?P<op>\d+)-000$", display.Leaf)
    if match is None:
        raise RuntimeError("Component Assign Name must be run from the -000 ({job}-{op}-000), not " + display.Leaf)
    prefix = "{}-{}-".format(match.group("job"), match.group("op"))
    job = _Job(os.path.dirname(display.FullPath), prefix)
    station_pattern = re.compile(r"^" + re.escape(prefix) + r"(?P<station>[a-z]+\d*)$", re.IGNORECASE)

    stations: Dict[int, _Station] = {}
    seen: Set[int] = set()
    root = nx.root_component(display)
    if root is None:
        return job

    def walk(component: NXOpen.Assemblies.Component, station: Optional[_Station]) -> None:
        for child in component.GetChildren():
            if child.IsSuppressed or not nx.is_loaded(child):
                continue
            part = nx.prototype(child)
            leaf = part.Leaf
            here = station
            station_match = station_pattern.match(leaf)
            if station_match is not None:
                here = stations.get(part.Tag)
                if here is None:
                    here = _Station(part, station_match.group("station").upper())
                    stations[part.Tag] = here
                    job.stations.append(here)
            elif part.Tag not in seen and _needs_number(part, job):
                seen.add(part.Tag)
                if here is None:
                    job.orphans.append(part)
                else:
                    here.parts.append(part)
            walk(child, here)

    walk(root, None)

    order = [name for name, _low, _high in GmRanges]
    job.stations.sort(key=lambda s: (order.index(s.name) if s.name in order else len(order), s.name))
    return job


def _needs_number(part: NXOpen.BasePart, job: _Job) -> bool:
    """A part in the -000's folder whose leaf is not a {job}-{op}-... name and holds none of the skip words."""
    if os.path.normcase(os.path.dirname(part.FullPath)) != os.path.normcase(job.folder):
        return False
    leaf = part.Leaf.lower()
    if leaf.startswith(job.prefix.lower()) or re.match(r"^\d+-\d+-\d{3,4}$", leaf):
        return False
    return not any(word in leaf for word in _SkipWords)


def plan(job: _Job, ranges: Dict[str, Tuple[int, int]]
         ) -> Tuple[List[Tuple[NXOpen.BasePart, str, _Station]], List[Tuple[NXOpen.BasePart, str]]]:
    """
    ([(part, new path, station)], [(part, why skipped)]): each station's parts take its range's free numbers in turn;
    a station without a range, or out of numbers, skips its remaining parts.
    """
    loaded = {part.Leaf.lower() for part in nx.session_.Parts}
    used: Set[int] = set()
    assigned: List[Tuple[NXOpen.BasePart, str, _Station]] = []
    skipped: List[Tuple[NXOpen.BasePart, str]] = [(part, "no station assembly above it") for part in job.orphans]

    for station in job.stations:
        bounds = ranges.get(station.name)
        if bounds is None:
            skipped.extend((part, "{} has no range".format(station.name)) for part in station.parts)
            continue
        numbers = (n for n in range(bounds[0], bounds[1] + 1) if n not in ReservedNumbers and n not in used)
        for index, part in enumerate(station.parts):
            path = None
            for number in numbers:
                leaf = "{}{:03d}".format(job.prefix, number)
                candidate = os.path.join(job.folder, leaf + ".prt")
                if leaf.lower() in loaded or os.path.exists(candidate):
                    continue
                used.add(number)
                path = candidate
                break
            if path is None:
                skipped.extend((p, "{} ran out of numbers ({}-{})".format(station.name, bounds[0], bounds[1]))
                               for p in station.parts[index:])
                break
            assigned.append((part, path, station))

    return assigned, skipped


def rename(assigned: List[Tuple[NXOpen.BasePart, str, _Station]]) -> int:
    """Saves each part as its new path and renames the components that carried the old leaf. Returns the count."""
    display = nx.display_part()
    root = nx.root_component(display)
    occurrences: Dict[int, List[NXOpen.Assemblies.Component]] = {}
    for component in (nx.descendants(root, include_root=False) if root is not None else []):
        if nx.is_loaded(component):
            occurrences.setdefault(nx.prototype(component).Tag, []).append(component)

    done = 0
    for part, path, station in assigned:
        old_leaf = part.Leaf
        try:
            status = part.SaveAs(path)
            if status is not None:
                status.Dispose()
            new_leaf = os.path.splitext(os.path.basename(path))[0]
            for component in occurrences.get(part.Tag, []):
                if component.Name.strip().upper() == old_leaf.upper():
                    component.SetName(new_leaf.upper())
            nx.print_("Component Assign Name: {} -> {} ({})".format(old_leaf, new_leaf, station.name))
            done += 1
        except Exception as ex:
            nx.print_exception(ex, "Component Assign Name: Save As of {} failed".format(old_leaf))
    return done


class _AssignDialog(Dialog):
    """ComponentAssignName.dlx: the Customer radio and one range row per station found."""

    dlx_name = "ComponentAssignName.dlx"

    def __init__(self, title: str, job: _Job) -> None:
        self.title = title
        self.job = job
        self.stations = job.stations[:MaxStations]
        super().__init__()
        # Captured in ok(): the blocks are gone once Launch returns.
        self.ranges: Dict[str, Tuple[int, int]] = {}
        self.texts: Dict[str, str] = {}

    def _row(self, index: int) -> Any:
        return self.block("range_{:02d}".format(index))

    def shown(self) -> None:
        self.reset_customer()
        count = sum(len(s.parts) for s in self.job.stations) + len(self.job.orphans)
        self.block("summary").Label = "{} part(s) to number under {} station(s){}".format(
            count, len(self.job.stations),
            " ({} with no station, skipped)".format(len(self.job.orphans)) if self.job.orphans else "")
        # reset_customer may have checked GM from the assembly, which fires no update(): fill its defaults here too.
        gm = self.customer() == CustomerGm
        for index in range(MaxStations):
            row = self._row(index)
            if index >= len(self.stations):
                row.Show = False
                continue
            station = self.stations[index]
            row.Label = "{} ({}, {} part(s))".format(station.name, station.part.Leaf, len(station.parts))
            self.set_string_value(row, station.attribute_range or (gm_range(station.name) if gm else ""))

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        if block == self.block("customer"):
            # GM: a station without its attribute starts on the spec's GM range; otherwise back to the attribute.
            gm = self.customer() == CustomerGm
            for index, station in enumerate(self.stations):
                if station.attribute_range:
                    continue
                self.set_string_value(self._row(index), gm_range(station.name) if gm else "")

    def enable_ok(self) -> bool:
        return self.customer() in (CustomerGm, CustomerTsg)

    def ok(self) -> bool:
        ranges: Dict[str, Tuple[int, int]] = {}
        texts: Dict[str, str] = {}
        for index, station in enumerate(self.stations):
            text = self.string_value(self._row(index)).strip()
            if not text:
                continue
            bounds = parse_range(text)
            if bounds is None:
                self.message("{}: \"{}\" is not a range like 21-200.".format(station.name, text), error=True)
                return False
            ranges[station.name] = bounds
            texts[station.name] = "{}-{}".format(bounds[0], bounds[1])
        if not ranges:
            self.message("Enter a range for at least one station.")
            return False
        self.ranges, self.texts = ranges, texts
        return True


def _save_ranges(job: _Job, texts: Dict[str, str]) -> None:
    """Writes each entered range back to its station's DETAIL NUMBER RANGE attribute when it changed."""
    for station in job.stations:
        text = texts.get(station.name)
        if text and text != station.attribute_range:
            try:
                nx.set_attribute(station.part, station.attribute_title or RangeAttribute, text)
            except Exception as ex:
                nx.print_exception(ex)


def execute() -> None:
    display = nx.display_part()
    if display is None or not re.match(r"^\d+-\d+-000$", display.Leaf):
        nx.show_error("Component Assign Name must be run from the -000 ({job}-{op}-000).")
        return

    job = scan(display)
    if not job.stations and not job.orphans:
        nx.show_error("Every component in {}'s folder already has a detail number - nothing to do.".format(display.Leaf))
        return
    if len(job.stations) > MaxStations:
        nx.warn("Component Assign Name: {} stations found; only the first {} fit the dialog - the rest are skipped."
                .format(len(job.stations), MaxStations))

    title = title_with_version("Component Assign Name")
    try:
        dialog = _AssignDialog(title, job)
        if not dialog.run():
            return
    except NXOpen.NXException as ex:
        if ex.ErrorCode != _ErrorCannotLaunchDialog:
            raise
        nx.print_exception(ex)
        nx.show_error("NX would not open the {} dialog (error {} - it will not create a dialog from inside a "
                      "callback).\n\nTry running it from File -> Execute -> NX Open rather than from a menu or "
                      "toolbar button.".format(title, _ErrorCannotLaunchDialog))
        return

    _save_ranges(job, dialog.texts)
    assigned, skipped = plan(job, dialog.ranges)

    for part, why in skipped:
        nx.print_("Component Assign Name: skipped {} - {}".format(part.Leaf, why))
    if not assigned:
        nx.show_error("No part could be given a number - see the listing window.")
        return

    lines = ["{} -> {}".format(part.Leaf, os.path.splitext(os.path.basename(path))[0])
             for part, path, _station in assigned]
    shown = "\n".join(lines[:25]) + ("\n... and {} more".format(len(lines) - 25) if len(lines) > 25 else "")
    if nx.message_box(title, NXOpen.NXMessageBox.DialogType.Question,
                      "Save As {} part(s){}?\n\n{}".format(
                          len(assigned), " ({} skipped, listed)".format(len(skipped)) if skipped else "", shown)
                      ) != nx.MessageBoxYes:
        nx.mark_cancelled("the Save As question")
        return

    done = rename(assigned)
    nx.print_("Component Assign Name: {} of {} part(s) renamed, {} skipped. Save the assembly to keep the new names."
              .format(done, len(assigned), len(skipped)))


def main() -> None:
    """The component-assign-name UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
