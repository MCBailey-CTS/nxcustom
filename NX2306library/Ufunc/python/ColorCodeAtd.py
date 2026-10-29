"""
Python port of the NX work in the ColorCodeAtd form (src\\UFuncs\\ColorCodes\\ColorCodeAtd.cs,
assembly-color-code-atd), whose one static method now lives in src\\Static\\ColorCodeAtd.cs:

- Static.ColorCodeAtdChooseColoring(color, featureChecked, triples, message) - the part after the picks:
  - the Feature-radio branch (SelectFeatures, then color every DisplayableObject entity) -> color_features
  - every other branch (SelectTaggedObjects over the radio's mask triples, then color)  -> color_objects

**Wired (2026-10-21), never run in NX** - ColorCodeAtdChooseColoring keeps the picks and calls these; the replaced
C# sits commented out in place.

Not ported, deliberately:
- The two picks (SelectionManager.SelectFeatures / SelectTaggedObjects with the form's MaskTriple arrays) and
  the "Triples were null" guard in front of them - selection stays C# (see python\\README.md).
- LoadColors, the radio-button and settings handlers, and ButtonReset_Click - WinForms (or one assignment),
  not moved to Static.

Differences: the C# set the "Assembly Color" undo mark before the pick; here it is set after, when the picked
objects arrive. Picks change nothing in the part, so the mark rolls back the same colors. An empty pick no longer
sets a mark at all - the C# skips the call then, since an empty array may not cross Session.Execute.

The calls, in ColorCodeAtdChooseColoring after each pick:
    PythonLibrary.Execute("ColorCodeAtd.py", "ColorCodeAtd", "color_features",
        color, features.Cast<TaggedObject>().ToArray());
    PythonLibrary.Execute("ColorCodeAtd.py", "ColorCodeAtd", "color_objects",
        color, objects.Cast<TaggedObject>().ToArray());
"""

from __future__ import annotations

import os
import sys
from typing import Sequence

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.Features  # noqa: E402

import tsg_nx as nx  # noqa: E402


class ColorCodeAtd(object):

    @staticmethod
    def color_features(color: int, features: Sequence[NXOpen.Features.Feature]) -> None:
        """
        Static.ColorCodeAtdChooseColoring, Feature branch after SelectFeatures: colors every displayable entity
        of each picked feature.
        """
        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Assembly Color")

        # Like the C# (no try/catch inside the loop), the first failure ends the run; the C# caller prints it.
        for feature in features:
            for entity in feature.GetEntities():
                if isinstance(entity, NXOpen.DisplayableObject):
                    nx.set_color(entity, color)

    @staticmethod
    def color_objects(color: int, objects: Sequence[NXOpen.TaggedObject]) -> None:
        """
        Static.ColorCodeAtdChooseColoring, mask-triple branch after SelectTaggedObjects: colors every picked
        object that is a DisplayableObject (OfType<DisplayableObject>), skipping the rest silently.
        """
        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Assembly Color")

        for obj in objects:
            if isinstance(obj, NXOpen.DisplayableObject):
                nx.set_color(obj, color)
