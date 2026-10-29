"""
Python port of the NX work in the Grid form (src\\UFuncs\\Grid.cs), whose static methods now live in
src\\Static\\Grid.cs (partial class Static):

- GridSetGrid(GridSize)              -> Grid.set_grid(size_name)
- GridTurnWorkPlaneOff()             -> Grid.turn_work_plane_off()
- GridSetSpacingFromText(text)       -> Grid.set_spacing_from_text(text)
- GridConvert(GridSize)              -> _convert (helper)
- GridIsValidString(expression)      -> _is_valid_string (helper)
- WorkPlane.__GridSpacing(spacing)   -> _set_grid_spacing (helper)

**Not wired** - the form still calls the C#. **Never run in NX.**

Not ported, deliberately:
- The form itself: the radio/check-box handlers (RdoIncrements_Click, ChkShowGrid/ChkSnapToGrid_CheckedChanged),
  TurnGridOff's and SetGridToTextBox's control writes, SetFormToGrid, ResetForm and the work-part-changed
  handler all read or write WinForms controls.
- _is_valid_string has no entry point: it only answers a bool for TxtGrid_KeyDown, and Session.Execute cannot
  hand a value back to C#. set_spacing_from_text raises on text it cannot read, as the C# throws.

The enum crosses Session.Execute by name ("Size0062" ... "Size6000"). To wire, the form would call
    PythonLibrary.Execute("Grid.py", "Grid", "turn_work_plane_off");                       // in TurnGridOff
    PythonLibrary.Execute("Grid.py", "Grid", "set_spacing_from_text", txtGrid.Text);       // in SetGridToTextBox
and GridSetGrid(size) would become
    PythonLibrary.Execute("Grid.py", "Grid", "set_grid", size.ToString());
(nothing calls GridSetGrid today).

Differences from the C#:
- The grid size is written by reading the work plane's current WorkPlaneGridSize_Struct, setting its three
  fields and writing it back, rather than constructing a new struct: the pyd names the type
  NXOpen.Preferences.WorkPlaneGridSize_Struct, and its Python constructor is unconfirmed. All three fields are
  overwritten, so the result is the same.
- The number is parsed with float(), not double.Parse: the regex's "." is any character, so text like "1,5" or
  "1_5" can reach the parse. double.Parse (current culture, thousands allowed) reads "1,5" as 15 and throws on
  "1_5"; float() raises ValueError on "1,5" and reads "1_5" as 15. Plain numbers ("0.125", ".5in", "3mm")
  parse the same.

Quirk kept: in a metric display part the C# conversion is inverted - inch text is used as-is (as millimetres)
and mm text is multiplied by 25.4. set_spacing_from_text does the same.
"""

from __future__ import annotations

import os
import re
import sys

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.Preferences  # noqa: E402

import tsg_nx as nx  # noqa: E402

GridSize0062 = 0.0625
GridSize0125 = 0.125
GridSize0250 = 0.250
GridSize0500 = 0.500
GridSize1000 = 1.000
GridSize6000 = 6.000

# Static.GridSize member name -> its spacing in inches (Static.GridConvert).
_GridSizes = {
    "Size0062": GridSize0062,
    "Size0125": GridSize0125,
    "Size0250": GridSize0250,
    "Size0500": GridSize0500,
    "Size1000": GridSize1000,
    "Size6000": GridSize6000,
}

_GridRegex = "^([0-9]{0,}.?[0-9]{0,})(in|mm)?$"


def _convert(size_name: str) -> float:
    """Static.GridConvert - a GridSize (by member name) to its spacing in inches."""
    if size_name not in _GridSizes:
        # C#: ArgumentOutOfRangeException(nameof(size), size, null)
        raise ValueError("Specified argument was out of the range of valid values.\nParameter name: size\n"
                         "Actual value was {}.".format(size_name))

    return _GridSizes[size_name]


def _is_valid_string(expression: str) -> bool:
    """Static.GridIsValidString - a digit somewhere, and a number optionally suffixed in/mm once spaces go."""
    if not any(c.isdigit() for c in expression):
        return False

    temp = expression.lower().replace(" ", "")
    return re.search(_GridRegex, temp) is not None


def _set_grid_spacing(work_plane: NXOpen.Preferences.WorkPlane, grid_spacing: float) -> None:
    """WorkPlane.__GridSpacing(spacing) - uniform rectangular grid, one minor line and one snap point per major."""
    # pyd: GetRectangularUniformGridSize() -> WorkPlaneGridSize_Struct; SetRectangularUniformGridSize(gridSize).
    grid_size = work_plane.GetRectangularUniformGridSize()
    grid_size.MajorGridSpacing = grid_spacing
    grid_size.MinorLinesPerMajor = 1
    grid_size.SnapPointsPerMinor = 1
    work_plane.SetRectangularUniformGridSize(grid_size)


def _display_work_plane() -> NXOpen.Preferences.WorkPlane:
    """__work_plane_ - the display part's work plane (what the Grid form's WorkPlane property reads)."""
    return nx.display_part().Preferences.Workplane


class Grid(object):

    @staticmethod
    def set_grid(size_name: str) -> None:
        """
        Static.GridSetGrid - sets the WORK part's grid spacing to size_name (a Static.GridSize member name), scaled
        to the display part's units, then puts the display part's root component on BODY. Kept as the C# has it,
        work-part work plane and all.
        """
        display_part = nx.display_part()
        multiplier = 1.0 if display_part.PartUnits == NXOpen.BasePart.Units.Inches else 25.4
        grid_spacing = _convert(size_name) * multiplier
        _set_grid_spacing(nx.work_part().Preferences.Workplane, grid_spacing)
        comp = display_part.ComponentAssembly.RootComponent

        if comp is None:
            # Like the C#, a display part with no assembly fails here - after the spacing is already set.
            raise AttributeError("Object reference not set to an instance of an object.")

        comp.DirectOwner.ReplaceReferenceSet(comp, "BODY")

    @staticmethod
    def turn_work_plane_off() -> None:
        """Static.GridTurnWorkPlaneOff - snap, grid, labels, on-top, major lines and non-uniform all off."""
        _display_work_plane().SnapToGrid = False
        _display_work_plane().ShowGrid = False
        _display_work_plane().ShowLabels = False
        _display_work_plane().GridOnTop = False
        _display_work_plane().RectangularShowMajorLines = False
        _display_work_plane().PolarShowMajorLines = False
        _display_work_plane().GridIsNonUniform = False

    @staticmethod
    def set_spacing_from_text(text: str) -> None:
        """
        Static.GridSetSpacingFromText - parses the grid text box (a number, optionally suffixed in/mm, inches when
        unsuffixed), converts it to the display part's units and sets the display part's grid spacing. Raises on
        text it cannot read, before anything changes (C#: FormatException "Invalid Format in TextBox.").
        """
        if not any(c.isdigit() for c in text):
            raise ValueError("Invalid Format in TextBox.")

        expression = text.lower().replace(" ", "")
        match = re.search(_GridRegex, expression)

        if match is None:
            raise ValueError("Invalid Format in TextBox.")

        number = float(match.group(1))
        is_mm = expression.endswith("mm")
        display_is_inches = nx.display_part().PartUnits == NXOpen.BasePart.Units.Inches

        if display_is_inches:
            converted_value = number / 25.4 if is_mm else number
        else:
            converted_value = number * 25.4 if is_mm else number

        _set_grid_spacing(_display_work_plane(), converted_value)
