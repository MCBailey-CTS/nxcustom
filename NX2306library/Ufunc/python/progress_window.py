"""
A progress window for the Python UFuncs (Python in NX cannot show WinForms): ProgressWindow.ps1, a separate
PowerShell window that follows this run's own progress file in %TEMP%. Lifted out of AutoDesign.py's _ProgressLog
(2026-10-23) so Export Strip can use it too.

The file holds the UFunc's own lines (#LOG / #TITLE / #DONE) and, while follow() is in effect, every builder step
written through tsg_nx.progress. The window stays open after the run until closed, and deletes the file then.
"""

from __future__ import annotations

import os
import subprocess
import time

import tsg_nx as nx

# ProgressWindow.ps1's -Position values.
Center = "Center"
BottomRight = "BottomRight"


class ProgressWindow(object):
    """This run's progress file, and the ProgressWindow.ps1 window following it."""

    def __init__(self, title: str, file_prefix: str, position: str = Center) -> None:
        """position is Center or BottomRight (out of the way of NX's message boxes, which come up centered)."""
        temp = os.environ.get("TMP") or os.environ.get("TEMP") or "."
        self.path = os.path.join(temp, "TSG_{}_{}_{}.log".format(file_prefix, os.getpid(), int(time.time() * 1000)))
        with open(self.path, "w", encoding="utf-8"):
            pass
        self._start_window(title, position)

    def _start_window(self, title: str, position: str) -> None:
        script = nx.library_file("ProgressWindow.ps1", __file__)
        try:
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                 "-File", script, "-Path", self.path, "-Title", title, "-Position", position],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000), close_fds=True)
        except Exception as ex:
            # The run goes on without the window; everything is in the listing window as well.
            nx.print_("Could not open the progress window ({}): {}".format(script, ex))

    def _write(self, line: str) -> None:
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line.replace("\n", " ") + "\n")
        except OSError:
            pass

    def write_line(self, message: str) -> None:
        self._write("#LOG " + message)

    def set_title(self, title: str) -> None:
        self._write("#TITLE " + title)

    def follow(self) -> None:
        """Every tsg_nx.progress line (the builders' steps) goes to the window until stop_following."""
        nx.progress_path = self.path

    def stop_following(self) -> None:
        nx.progress_path = None
        self._write("#DONE")
