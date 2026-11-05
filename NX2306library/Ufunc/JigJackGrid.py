"""
The jig-jack-grid UFunc: a standalone Python UFunc (no C# class); its menu button runs this file's main().

Run from the -000, or with one part displayed. After the "Are you sure" box, walks the display part's assembly - the
display part, then every loaded, unsuppressed part under it, under any name so a detail not numbered yet (lts-...)
counts; the -000 and anything in G:\\0Library are left out, each part once - and looks at the unsuppressed, loaded
-jck-screw-tsg children of each. The JigJacks design check's rule, made strict: the jacks of a detail are on the grid
when each sits a whole number of inches from the anchor jack along both of the anchor's X and Y axes (the check also
passes a whole diagonal distance, and any one good distance).

  - Jacks are compared with the jacks that point the same way (or straight opposite). The offset along that axis is
    ignored, so a jack may sit at another height.
  - The anchor is the jack the most others are already on the grid with, the first of them on a tie, and it never
    moves. With the usual two jacks one jack moves; with more, only the ones off the grid do.
  - A jack that moves goes to the whole-inch offset nearer the block's centre on each axis, so it never gets closer to
    the block's edge. That can be up to just under 1" on an axis. It stays at its height and keeps its orientation.
  - A detail with one jack has nothing to line up with, and one with no block body has no centre to move towards; both
    are listed and left. So is a jack whose new spot would land on another jack.

The moves are listed, then one Question box asks before anything changes. Each part's jacks move with
ComponentAssembly.MoveComponent, then an update. One undo mark covers the run and nothing is saved. There is no check
that the new spot is clear of other holes in the block: look over the listed details.

Run standalone: File -> Execute -> NX Open on this file runs main().
"""

from __future__ import annotations

import math
import os
import sys
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

# Session.Execute does not put the script's folder on sys.path, so the shared modules would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# The shared modules are in the python folder beside this file (src\\UFuncs\\python; deployed, Ufunc\\python).
_shared_python = os.path.join(_here, "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.Features  # noqa: E402

import tsg_nx as nx  # noqa: E402

ufunc_name = "jig-jack-grid"

# Inches. The JigJacks design check's tolerance.
GridTolerance = .0001

# Two jacks point the same way when the dot product of their Z axes is at least this, ignoring its sign.
ParallelDot = .9999

# The Question box lists at most this many moves; the listing window has them all.
MaxMovesInBox = 15

# Parts in here are library parts, not details (lower case).
_LibraryFolder = "g:\\0library\\"

Offset = Tuple[float, float]


class PlannedMove(NamedTuple):
    """Where one jack goes: its offset from the anchor now and after, in inches, and the move in part units."""
    jack: NXOpen.Assemblies.Component
    anchor: NXOpen.Assemblies.Component
    offset: Offset
    target: Offset
    translation: NXOpen.Vector3d


def is_on_grid(offset: Offset) -> bool:
    """True when both of offset's distances are whole inches."""
    return all(abs(value - round(value)) < GridTolerance for value in offset)


def pick_anchor(offsets_between: Sequence[Sequence[Offset]]) -> int:
    """
    The index of the jack the most others are on the grid with, the first on a tie. offsets_between[i][j] is jack j's
    offset from jack i.
    """
    counts = [sum(1 for j, offset in enumerate(row) if j != i and is_on_grid(offset))
              for i, row in enumerate(offsets_between)]
    return counts.index(max(counts))


def snap_towards(value: float, centre: float) -> float:
    """value as whole inches: itself when it already is one, else the whole number either side nearer centre."""
    if abs(value - round(value)) < GridTolerance:
        return float(round(value))

    low = float(math.floor(value))
    high = float(math.ceil(value))
    return low if abs(low - centre) <= abs(high - centre) else high


def snap_offset(offset: Offset, centre: Offset) -> Offset:
    """offset moved onto the grid, towards centre on each axis."""
    return snap_towards(offset[0], centre[0]), snap_towards(offset[1], centre[1])


def _dot(a: NXOpen.Vector3d, b: NXOpen.Vector3d) -> float:
    return a.X * b.X + a.Y * b.Y + a.Z * b.Z


def _between(start: NXOpen.Point3d, end: NXOpen.Point3d) -> NXOpen.Vector3d:
    return NXOpen.Vector3d(end.X - start.X, end.Y - start.Y, end.Z - start.Z)


def _inches_per_part_unit(part: NXOpen.BasePart) -> float:
    return 1.0 / 25.4 if part.PartUnits == NXOpen.BasePart.Units.Millimeters else 1.0


def _offset_in_frame(origin: NXOpen.Point3d, point: NXOpen.Point3d, orientation: NXOpen.Matrix3x3,
                     scale: float) -> Offset:
    """point from origin along orientation's X and Y axes, in inches."""
    delta = _between(origin, point)
    return _dot(delta, nx.axis_x(orientation)) * scale, _dot(delta, nx.axis_y(orientation)) * scale


def jig_jacks(part: NXOpen.BasePart) -> List[NXOpen.Assemblies.Component]:
    """part's unsuppressed, loaded -jck-screw-tsg children (the JigJacks design check's list)."""
    return [component for component in nx.children(part)
            if not component.IsSuppressed and nx.is_loaded(component) and nx.is_jck_screw_tsg(component.DisplayName)]


def _groups_by_axis(jacks: Sequence[NXOpen.Assemblies.Component]) -> List[List[NXOpen.Assemblies.Component]]:
    """jacks grouped by the line their Z axes lie along."""
    groups: List[List[NXOpen.Assemblies.Component]] = []

    for jack in jacks:
        axis = nx.axis_z(nx.component_orientation(jack))

        for group in groups:
            if abs(_dot(axis, nx.axis_z(nx.component_orientation(group[0])))) >= ParallelDot:
                group.append(jack)
                break
        else:
            groups.append([jack])

    return groups


def _block_centre(part: NXOpen.BasePart) -> Optional[NXOpen.Point3d]:
    """The centre of the box of part's dynamic block, or else of its one solid body on layer 1. None without either."""
    bodies: List[NXOpen.Body] = []

    for feature in part.Features.GetFeatures():
        if isinstance(feature, NXOpen.Features.Block) and feature.Name == "DYNAMIC BLOCK":
            bodies = list(feature.GetBodies())
            break

    if not bodies:
        bodies = [body for body in part.Bodies if body.IsSolidBody and body.Layer == 1]

    if len(bodies) != 1:
        return None

    box = nx.body_box(bodies[0])
    return NXOpen.Point3d((box.MinX + box.MaxX) / 2, (box.MinY + box.MaxY) / 2, (box.MinZ + box.MaxZ) / 2)


def plan_group(part: NXOpen.BasePart, jacks: Sequence[NXOpen.Assemblies.Component], centre: NXOpen.Point3d,
               skipped: List[str]) -> List[PlannedMove]:
    """The moves that put jacks, which all point the same way, on one grid. A jack that cannot move joins skipped."""
    scale = _inches_per_part_unit(part)
    origins = [nx.component_origin(jack) for jack in jacks]
    orientations = [nx.component_orientation(jack) for jack in jacks]

    anchor_index = pick_anchor([[_offset_in_frame(origins[i], point, orientations[i], scale) for point in origins]
                                for i in range(len(jacks))])

    anchor = jacks[anchor_index]
    anchor_origin = origins[anchor_index]
    orientation = orientations[anchor_index]
    centre_offset = _offset_in_frame(anchor_origin, centre, orientation, scale)

    # Where every jack is staying, so a moved one does not land on it. The anchor is at (0, 0).
    taken = {(0.0, 0.0)}
    off_grid: List[Tuple[NXOpen.Assemblies.Component, Offset]] = []

    for i, jack in enumerate(jacks):
        if i == anchor_index:
            continue

        offset = _offset_in_frame(anchor_origin, origins[i], orientation, scale)

        if is_on_grid(offset):
            taken.add((float(round(offset[0])), float(round(offset[1]))))
        else:
            off_grid.append((jack, offset))

    moves: List[PlannedMove] = []
    x_axis = nx.axis_x(orientation)
    y_axis = nx.axis_y(orientation)

    for jack, offset in off_grid:
        target = snap_offset(offset, centre_offset)

        if target in taken:
            skipped.append("{}: {} would land on another jig jack - left where it is.".format(
                part.Leaf, jack.DisplayName))
            continue

        taken.add(target)
        along_x = (target[0] - offset[0]) / scale
        along_y = (target[1] - offset[1]) / scale
        moves.append(PlannedMove(jack, anchor, offset, target, NXOpen.Vector3d(
            x_axis.X * along_x + y_axis.X * along_y,
            x_axis.Y * along_x + y_axis.Y * along_y,
            x_axis.Z * along_x + y_axis.Z * along_y)))

    return moves


@nx.traced("Jig Jack Grid")
def plan_part(part: NXOpen.BasePart, skipped: List[str]) -> List[PlannedMove]:
    """The moves part's jig jacks need."""
    jacks = jig_jacks(part)

    if len(jacks) == 0:
        return []

    if len(jacks) == 1:
        skipped.append("{}: only one jig jack - nothing to line it up with.".format(part.Leaf))
        return []

    groups = [group for group in _groups_by_axis(jacks) if len(group) > 1]
    _load_fully(part)
    centre = _block_centre(part)

    if centre is None:
        if groups:
            skipped.append("{}: no dynamic block or single layer 1 solid body - left alone.".format(part.Leaf))
        return []

    moves: List[PlannedMove] = []

    for group in groups:
        moves.extend(plan_group(part, group, centre, skipped))

    return moves


def _details(display: NXOpen.BasePart) -> List[NXOpen.BasePart]:
    """
    The display part, then every part under it, each once, the -000 and library parts left out. Any name counts: a
    detail not numbered yet is still a lts-... part. nx.descendants skips unloaded branches.
    """
    parts: Dict[int, NXOpen.BasePart] = {}

    if not display.Leaf.endswith("-000"):
        parts[display.Tag] = display

    root = nx.root_component(display)

    if root is None:
        return list(parts.values())

    for component in nx.descendants(root, include_root=False):
        part = nx.prototype(component)

        if (part is not None and not part.Leaf.endswith("-000")
                and not part.FullPath.lower().startswith(_LibraryFolder)):
            parts.setdefault(part.Tag, part)

    return list(parts.values())


def _load_fully(part: NXOpen.BasePart) -> None:
    """A partially loaded part has no features to read: load it fully first."""
    if isinstance(part, NXOpen.Part) and not part.IsFullyLoaded:
        part.LoadThisPartFully()


def _inches(value: float) -> str:
    return "{:.4f}".format(value)


def _describe(part: NXOpen.BasePart, move: PlannedMove) -> str:
    return "{}: {} from X {} Y {} to X {} Y {} off {}".format(
        part.Leaf, move.jack.DisplayName, _inches(move.offset[0]), _inches(move.offset[1]), _inches(move.target[0]),
        _inches(move.target[1]), move.anchor.DisplayName)


@nx.traced("Jig Jack Grid")
def scan(display: NXOpen.BasePart) -> Tuple[int, List[Tuple[NXOpen.BasePart, List[PlannedMove]]], List[str]]:
    """Reads the assembly without changing it: (parts looked at, (part, moves) for each to change, what was left)."""
    details = _details(display)
    plans: List[Tuple[NXOpen.BasePart, List[PlannedMove]]] = []
    skipped: List[str] = []

    for part in details:
        try:
            moves = plan_part(part, skipped)

            if moves:
                plans.append((part, moves))
        except Exception as ex:
            nx.print_exception(ex, part.Leaf)

    return len(details), plans, skipped


def _print_plan(details: int, plans: Sequence[Tuple[NXOpen.BasePart, Sequence[PlannedMove]]],
                skipped: Sequence[str]) -> None:
    nx.print_("Jig Jack Grid")
    nx.print_("=============")
    nx.print_("Parts looked at:   {}".format(details))
    nx.print_("Off the 1\" grid:   {} jig jack(s) in {} detail(s)".format(sum(len(m) for _, m in plans), len(plans)))

    for part, moves in plans:
        for move in moves:
            nx.print_("    {}".format(_describe(part, move)))

    if skipped:
        nx.print_("")
        nx.print_("Left alone ({}):".format(len(skipped)))
        for line in skipped:
            nx.print_("    {}".format(line))


def _confirm_moves(plans: Sequence[Tuple[NXOpen.BasePart, Sequence[PlannedMove]]]) -> bool:
    lines = [_describe(part, move) for part, moves in plans for move in moves]
    shown = lines[:MaxMovesInBox]

    if len(lines) > len(shown):
        shown.append("... and {} more in the listing window".format(len(lines) - len(shown)))

    message = "Move {} jig jack(s) onto the 1\" grid? Nothing is saved.\n\n{}".format(len(lines), "\n".join(shown))

    if nx.message_box("Jig Jack Grid", NXOpen.NXMessageBox.DialogType.Question, message) == nx.MessageBoxYes:
        return True

    nx.mark_cancelled("the move question")
    return False


def apply_plans(plans: Sequence[Tuple[NXOpen.BasePart, Sequence[PlannedMove]]]) -> int:
    """Moves the jacks, one update per part, each part caught on its own. Returns how many moved."""
    moved = 0

    for part, moves in plans:
        try:
            with nx.do_update("Jig Jack Grid"):
                for move in moves:
                    part.ComponentAssembly.MoveComponent(move.jack, move.translation, nx.identity_matrix())
                    moved += 1
        except Exception as ex:
            nx.print_exception(ex, part.Leaf)

    return moved


class JigJackGrid(object):

    @staticmethod
    def execute() -> None:
        display = nx.display_part()

        if display is None:
            nx.print_("There is no displayed part loaded.")
            return

        details, plans, skipped = scan(display)
        _print_plan(details, plans, skipped)

        if not plans or not _confirm_moves(plans):
            return

        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Jig Jack Grid")
        moved = apply_plans(plans)
        nx.print_("")
        nx.print_("Moved {} jig jack(s). Nothing was saved.".format(moved))


def main() -> None:
    """The jig-jack-grid UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            if nx.confirm_execute(ufunc_name):
                JigJackGrid.execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
