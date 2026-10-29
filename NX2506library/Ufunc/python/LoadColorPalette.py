"""
Python port of the load-color-palette UFunc (LoadColorPalette, src\\UFuncs\\LoadColorPalette.cs).
The C# wrapper was deleted 2026-10-22 (in git at f32694f): the UFunc's menu button runs this file's main().

Pick a .cdf color definition file, then for every distinct non-0Library part in the display assembly: display
it, set its selection/preselection colors (119/149) and load the .cdf into its color table.

Run standalone: File -> Execute -> NX Open on this file runs main().
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
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402

ufunc_name = "load-color-palette"

# OpenFileDialog InitialDirectory + the *.cdf filter, as a UF filebox filter pattern.
_CdfFilter = "U:\\nxFiles\\UfuncFiles\\*.cdf"


class LoadColorPalette(object):

    @staticmethod
    def execute() -> None:
        """LoadColorPalette.execute"""
        # sql
        # C# shows a WinForms OpenFileDialog (filters "cdf files (*.cdf)" and "All files (*.*)"); the NX filebox
        # takes one filter pattern, so only *.cdf is offered (the user can still edit the filter in the box).
        title = nx.ufunc_rev_name(ufunc_name)
        file_name = nx.select_file_or_none(title, title, _CdfFilter)

        if file_name is None:
            return

        with nx.display_part_reset():
            LoadColorPalette.process_assy(file_name)

    @staticmethod
    def process_assy(cdf_file: str) -> None:
        """LoadColorPalette.ProcessAssy"""
        try:
            root = nx.display_part().ComponentAssembly.RootComponent
            if root is None:
                # C#: NullReferenceException on RootComponent.__Descendants(), caught below.
                raise RuntimeError("The display part has no root component.")

            protos = [nx.prototype(c) for c in nx.descendants(root)]
            parts: List[NXOpen.Part] = [
                p for p in nx.distinct_by([p for p in protos if isinstance(p, NXOpen.Part)], lambda p: p.Leaf)
                if "0library" not in p.FullPath.lower()]

            for i, child in enumerate(parts):
                nx.prompt("({} of {}) -> {}".format(i + 1, len(parts), child.Leaf))

                try:
                    nx.set_display_part(child)
                    _process_part(nx.display_part(), cdf_file)
                except Exception as ex:
                    nx.print_exception(ex)
        except Exception as ex:
            nx.print_exception(ex)


def _substring(text: str, start: int, length: int) -> str:
    """string.Substring(int, int) - raises when the range runs past the end, where a Python slice would not."""
    if start < 0 or length < 0 or start + length > len(text):
        raise IndexError("Index and length must refer to a location within the string. "
                         "(Substring({}, {}) of a {}-character line)".format(start, length, len(text)))
    return text[start:start + length]


def _process_part(a_part: NXOpen.Part, cdf_file: str) -> None:
    """LoadColorPalette.ProcessPart - HandleSelectionColor can only be called on the displayed part."""
    load_status = nx.session_.Parts.SetDisplay(a_part, True, True)
    load_status.Dispose()

    # change the selection colours
    a_part.Preferences.ColorSettingVisualization.SelectionColor = 119
    a_part.Preferences.ColorSettingVisualization.PreselectionColor = 149

    line_counter = 0

    # StreamReader: UTF-8 with BOM detection, invalid bytes replaced; ReadLine strips the line terminator.
    with open(cdf_file, "r", encoding="utf-8-sig", errors="replace") as file:
        for raw_line in file:
            text_line = raw_line.rstrip("\r\n")

            if line_counter <= 3:
                line_counter += 1
                continue

            # A short line (a trailing blank line included) throws here, as Substring does in the C#: the part
            # is abandoned before LoadColorTable and ProcessAssy prints the exception.
            color_name = _substring(text_line, 0, 30)
            red = _substring(text_line, 34, 8)
            green = _substring(text_line, 45, 8)
            blue = _substring(text_line, 56, 8)
            rgb_color = [float(red), float(green), float(blue)]
            this_color = line_counter - 4
            nx.ufsession_.Disp.SetColor(this_color, NXOpen.UF.UFConstants.UF_DISP_rgb_model, color_name, rgb_color)
            line_counter += 1

    nx.ufsession_.Disp.LoadColorTable()


def main() -> None:
    """The load-color-palette UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("load-color-palette"):
        try:
            # No dialog of its own: ask before doing anything (a logged Question box).
            if nx.confirm_execute("load-color-palette"):
                LoadColorPalette.execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
