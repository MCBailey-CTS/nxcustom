"""
sim-data-delete: Simulation Data Builder's Sim Data Deletion button (Static.SimulationDataBuilderSimDataDeletion,
src\\Static\\SimulationDataBuilder.cs) and its SimDataDeleteConfirm WinForms file list, as one Block UI Styler dialog
(SimDataDelete.dlx, written by tools\\make-dlx.py) - 2026-10-23. The C# button is unchanged.

Select components; the dialog lists every file whose name (without extension) is a selected component's display
name, under the job folder on G: and under the job's folder in P:\\CTS_SIM\\Active (a 6-digit customer number:
"{job}-tsgN" from the name's -tsgN; otherwise "{job} 5xx" from an -5xx engineering change, else "{job}"). OK runs
SimulationDataBuilder.delete_sim_data: deletes the files, closes each component's part and deletes the component,
then saves the display part with its components.

Differences from the C#:
- A component whose display name holds "master" or "history" was only reported as forbidden and then deleted
  anyway; it is now left out of the files, the closing and the deleting.
- A sim folder that does not exist is skipped (Directory.EnumerateFiles threw, ending the UFunc).
- The job folder is walked once per run, not once per pick.
"""

from __future__ import annotations

import ntpath
import os
import re
import sys
from typing import Any, Dict, List, Optional, Set

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
import NXOpen.BlockStyler  # noqa: E402

import tsg_nx as nx  # noqa: E402
from SimulationDataBuilder import SimulationDataBuilder, _GFolder, _SimActive  # noqa: E402
from tsg_dialog import Dialog, components_of, title_with_version  # noqa: E402

ufunc_name = "sim-data-delete"

# NX will not create a dialog from inside another dialog's callback.
_ErrorCannotLaunchDialog = 3520048


def _stem(path: str) -> str:
    """Path.GetFileNameWithoutExtension"""
    return ntpath.splitext(ntpath.basename(path))[0]


def _forbidden(display_name: str) -> bool:
    lower = display_name.lower()
    return "master" in lower or "history" in lower


def _files_by_stem(folder: str) -> Dict[str, List[str]]:
    """Every file under folder (recursively), by its name without extension. A missing folder gives nothing."""
    found: Dict[str, List[str]] = {}
    if not os.path.isdir(folder):
        return found
    for root, _dirs, files in os.walk(folder):
        for name in files:
            found.setdefault(_stem(name), []).append(ntpath.join(root, name))
    return found


def _sim_folder(folder: _GFolder, display_name: str) -> Optional[str]:
    """The Active sim folder a component's files are in (the C# dictionary's value), or None for no match."""
    sim_dir = "{}\\{}".format(_SimActive, _stem(folder.DirJob))
    if len(folder.CustomerNumber) == 6:
        tsg = re.search(r"-(?P<tsgLevel>tsg\d+)", display_name)
        return "{}-{}".format(sim_dir, tsg.group("tsgLevel")) if tsg else None
    ec = re.search(r"-(?P<engineeringChange>5[0-9]{2})[-]*", display_name)
    return "{} {}".format(sim_dir, ec.group("engineeringChange")) if ec else sim_dir


class SimDataFinder(object):
    """The files to delete for a set of display names; folders are walked once and cached."""

    def __init__(self, folder: _GFolder) -> None:
        self.folder = folder
        self._cache: Dict[str, Dict[str, List[str]]] = {}

    def _index(self, path: str) -> Dict[str, List[str]]:
        if path not in self._cache:
            self._cache[path] = _files_by_stem(path)
        return self._cache[path]

    def files(self, display_names: Set[str]) -> List[str]:
        found: Set[str] = set()
        job = self._index(self.folder.DirJob)
        for name in display_names:
            found.update(job.get(name, []))
            sim = _sim_folder(self.folder, name)
            if sim is not None:
                found.update(self._index(sim).get(name, []))
        return sorted(found, key=str.lower)


class _SimDataDeleteDialog(Dialog):
    dlx_name = "SimDataDelete.dlx"

    def __init__(self, title: str, finder: SimDataFinder) -> None:
        self.title = title
        self.finder = finder
        self.components: List[NXOpen.Assemblies.Component] = []
        self.files: List[str] = []
        super().__init__()

    def initialize(self) -> None:
        self.component_filter(self.block("components"))

    def shown(self) -> None:
        self._refresh()

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        if block == self.block("components"):
            self._refresh()

    def enable_ok(self) -> bool:
        return bool(self.components)

    def _refresh(self) -> None:
        picked = components_of(self.selected(self.block("components")))
        forbidden = sorted({c.DisplayName for c in picked if _forbidden(c.DisplayName)})
        for name in forbidden:
            nx.print_("Deleting the {} is forbidden.".format(name))
        self.components = [c for c in picked if not _forbidden(c.DisplayName)]
        self.files = self.finder.files({c.DisplayName for c in self.components})

        listing: Any = self.block("files")
        listing.SetListItems((self.files or ["(no files found)"]) if self.components else [])
        label = "Files to delete: {}".format(len(self.files))
        if forbidden:
            label += " (left out: {})".format(", ".join(forbidden))
        self.block("count").Label = label

    def ok(self) -> bool:
        self._refresh()
        return bool(self.components)


def execute() -> None:
    display = nx.display_part()
    work = nx.work_part()
    if display is None or work is None:
        nx.show_error("Sim Data Delete needs a display part.")
        return

    folder = _GFolder.create_or_null(work.FullPath)
    if folder is None:
        return

    title = title_with_version("Sim Data Delete")
    try:
        dialog = _SimDataDeleteDialog(title, SimDataFinder(folder))
        accepted = dialog.run()
    except NXOpen.NXException as ex:
        if ex.ErrorCode != _ErrorCannotLaunchDialog:
            raise
        nx.print_exception(ex)
        nx.show_error("NX would not open the {} dialog (error {} - it will not create a dialog from inside a "
                      "callback).\n\nTry running it from File -> Execute -> NX Open rather than from a menu or "
                      "toolbar button.".format(title, _ErrorCannotLaunchDialog))
        return

    if not accepted:
        return

    for path in dialog.files:
        nx.print_("Deleting {}".format(path))
    SimulationDataBuilder.delete_sim_data(dialog.files, dialog.components)
    nx.print_("Deleted {} file(s) and {} component(s).".format(len(dialog.files), len(dialog.components)))


def main() -> None:
    """The sim-data-delete UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
