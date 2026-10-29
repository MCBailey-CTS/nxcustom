"""
Python port of the work half of the ColorCodeTsg form (src\\UFuncs\\ColorCodeTsg.cs, assembly-color-code), from
the C# static in src\\Static\\ColorCodeTsg.cs: the coloring after the pick in ColorCodeTsgChooseColoring, split by
its two branches into color_objects (any filter but Feature) and color_body_features (the Feature filter).

**Wired (2026-10-21), never run in NX** - ColorCodeTsgChooseColoring keeps the undo mark and the pick, then calls
color_objects or color_body_features; the replaced C# sits commented out below the call.

Not ported:
- ColorCodeTsgSetFilterAndCue and the SNAP selection dialog in ColorCodeTsgChooseColoring. They are the pick,
  and selection stays C# (SNAP is .NET-only).
- The "Assembly Color" undo mark. The C# sets it with Snap.Globals.SetUndoMark before the pick, so it stays
  with the pick.

The call, after the `selected.Length == 0` return:
    if (!isFeature)
        PythonLibrary.Execute("ColorCodeTsg.py", "ColorCodeTsg", "color_objects", color,
            selected.Select(o => (TaggedObject)o.NXOpenDisplayableObject).ToArray());
    else
        PythonLibrary.Execute("ColorCodeTsg.py", "ColorCodeTsg", "color_body_features", color,
            selected.Select(o => o.NXOpenTaggedObject).ToArray());

Differences from the C#:
- The "no body features" message goes through tsg_nx.print_ (the listing window); the C# uses
  Snap.InfoWindow.WriteLine, which writes to the same window.
- The C# constructs a DisplayPartReset for the Feature branch too, but nothing in that branch changes the
  display or work part, so color_body_features doesn't take one.
"""

from __future__ import annotations

import os
import sys
from typing import List, Sequence, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.Features  # noqa: E402

import tsg_nx as nx  # noqa: E402


class ColorCodeTsg:
    """The post-selection half of Static.ColorCodeTsgChooseColoring."""

    @staticmethod
    def color_objects(color: int, objects: Sequence[NXOpen.TaggedObject]) -> None:
        """
        ColorCodeTsgChooseColoring when the Feature radio is not checked: makes each picked object's owning part the
        work part and colors the object's prototype, then colors the picked objects themselves. The display and work
        parts are restored afterwards (DisplayPartReset).
        """
        disp_objects = [cast(NXOpen.DisplayableObject, obj) for obj in objects]

        with nx.display_part_reset():
            # Colors the selected objects the {nxColor}.
            for nx_object in disp_objects:
                owning_part = nx_object.OwningPart

                nx.set_work_part(cast(NXOpen.Part, owning_part))

                disp_obj = nx_object
                if disp_obj.IsOccurrence:
                    disp_obj = cast(NXOpen.DisplayableObject, disp_obj.Prototype)
                nx.set_color(disp_obj, color)

            for obj in disp_objects:
                nx.set_color(obj, color)

    @staticmethod
    def color_body_features(color: int, objects: Sequence[NXOpen.TaggedObject]) -> None:
        """
        ColorCodeTsgChooseColoring when the Feature radio is checked: colors every face of the picked body features.
        Picks that aren't body features are ignored.
        """
        # Gets the {BodyFeature}'s from the selected objects.
        body_features: List[NXOpen.Features.BodyFeature] = \
            [obj for obj in objects if isinstance(obj, NXOpen.Features.BodyFeature)]

        # If there aren't any {BodyFeatures}, then we can inform the user and retu00Brn.
        if len(body_features) == 0:
            nx.print_("Could not find any body features in the selected list of features.")
            return

        # Colors the faces of the body features.
        for face in [face for body_feature in body_features for face in body_feature.GetFaces()]:
            nx.set_color(face, color)
