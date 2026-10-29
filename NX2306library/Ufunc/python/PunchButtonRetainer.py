"""
Python port of the punch-button-retainer UFunc (PunchButtonRetainer, src\\UFuncs\\PunchButtonRetainer.cs).

Select slug bodies. They are grouped by face count - 3 faces = round, 6 = oblong, 10 = rectangle with corner
radii (5 and anything else are skipped). Each distinct slug size gets the Smart Punch Metric seed added at the
slug, its style/size expressions set, and is saved as a new punch part next to the display part; the other slugs
of that size get the saved punch. Then, for each saved punch part, the Smart Ball Lock Retainer Metric and Smart
Button Metric seeds are copied next to it as retainer-/button- parts and dropped at every occurrence of the
punch, and each retainer is Touch-constrained (ALIGNPUNCH) to its punch's PUNCHTOPFACE.

The C# class carries [UFunc("punch-button-retainer")] but has no case in _Runner and no ufunc_* constant, so
Release builds cannot launch it by name. This module runs standalone: File -> Execute -> NX Open runs main().

Faithful-port notes (all inherited from the C#, kept on purpose):
  - The curves made by Edge.__ToCurve in the grouping loops (and the oblong's second arc and helper line) are
    never deleted, so each run leaves curves in the work part.
  - The button is added with the retainer's leaf as its component name.
  - The rectangle path writes D/valueP/valueW/valueR; the oblong writes D/valueP/valueW outside the update
    lock; the round writes valueP only (no D).
  - MaterialThickness is computed and never used - kept, since computing it can throw (single -Z face).
"""

from __future__ import annotations

import os
import sys
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable, Dict, Iterator, List, Optional, Sequence, TypeVar, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.Positioning  # noqa: E402

import tsg_nx as nx  # noqa: E402

_T = TypeVar("_T")

# Spreadsheet tabs of the Smart seeds (comment carried over from the C#):
# Main: 1, Lists: 2, Metalsa Callouts: 3, Exp-Data: 4, Validation: 5, Exp-Attr: 6, CTS Revision Log: 7,
# Images: 8, Images2: 9, Images3: 10

smart_punch_metric_path = "G:\\0Library\\PunchPilot\\Metric\\Smart Punch Metric.prt"

smart_retainer_metric_path = "G:\\0Library\\Retainers\\Metric\\Smart Ball Lock Retainer Metric.prt"

smart_button_metric_path = "G:\\0Library\\Button\\Smart Button Metric.prt"

punch_diameters = [10.0, 13.0, 16.0, 20.0, 25.0, 32.0, 40.0]

# PunchButtonRetainer.StyleType (declared in the C#, never used).
StyleBallLockRound = 1
StyleBallLockOblong = 2
StyleBallLockRectangle = 3
StyleBallLockRectangleRadius = 4
StyleBallLockOblongWithFlat = 5

# Every style selector on the Smart Punch seed, in the order the C# writes them.
_style_expressions = [
    "styleBallLockOblong",
    "styleBallLockOblongWithFlat",
    "styleBallLockRectangle",
    "styleBallLockRectangleRadius",
    "styleBallLockRound",
    "styleHeadedOblong",
    "styleHeadedOblongWithFlat",
    "styleHeadedRectangle",
    "styleHeadedRectangleRadius",
    "styleHeadedRound",
    "styleNoseLargeOblong",
    "styleNoseLargeOblongWithFlat",
    "styleNoseLargeRectangle",
    "styleNoseLargeRectangleRadius",
    "styleNoseLargeRound",
]


class PunchButtonRetainer(object):

    @staticmethod
    def execute() -> None:
        """PunchButtonRetainer.execute"""
        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Punch Button Retainer")
        try:
            _add_punch()
        except Exception as ex:
            nx.print_exception(ex)


def _add_punch() -> None:
    """PunchButtonRetainer.add_punch"""
    solid_bodies = nx.select_many_solid_bodies("Select Many Solid Bodies")

    # ToLookup(body => face count) - keys in first-seen order.
    lookup: Dict[int, List[NXOpen.Body]] = {}
    for body in solid_bodies:
        lookup.setdefault(len(body.GetFaces()), []).append(body)

    part_paths: List[str] = []

    for face_count, bodies in lookup.items():
        if face_count == 3:
            part_paths.extend(_create_ball_lock_round(bodies))
        elif face_count == 5:
            continue
        elif face_count == 6:
            part_paths.extend(_create_ball_lock_oblong(bodies))
        elif face_count == 10:
            part_paths.extend(_create_ball_lock_rectangle_radius(bodies))

    for path in part_paths:
        punch_part = nx.find_or_open(path)

        part_occs = nx.occurrences_of_part_in(nx.display_part(), punch_part)

        directory = nx.part_dir(nx.display_part())
        retainer_leaf = punch_part.Leaf.replace("punch", "retainer")
        retainer_path = "{}\\{}.prt".format(directory, retainer_leaf)

        button_leaf = punch_part.Leaf.replace("punch", "button")
        button_path = "{}\\{}.prt".format(directory, button_leaf)

        _file_copy(smart_retainer_metric_path, retainer_path)
        _file_copy(smart_button_metric_path, button_path)

        for punch in part_occs:
            origin = nx.component_origin(punch)
            orientaion = nx.component_orientation(punch)

            # retainer x should point in negative direction of punch y dir
            # reatiner y should point in positive direction of punch x dir

            retainer_orientation_x = nx.negate(nx.axis_y(orientaion))
            retainer_orientation_y = nx.axis_x(orientaion)

            retainer = nx.add_component(
                nx.display_part(),
                retainer_path,
                "BODY",
                retainer_leaf,
                origin,
                nx.matrix_from_axes(retainer_orientation_x, retainer_orientation_y))

            # The C# names the button component retainer_leaf too.
            nx.add_component(
                nx.display_part(),
                button_path,
                "BODY",
                retainer_leaf,
                origin,
                orientaion)

            punch_face = cast(NXOpen.Face, nx._single(
                [f for f in nx.members(punch) if isinstance(f, NXOpen.Face) and f.Name == "PUNCHTOPFACE"],
                "matching element"))
            reatiner_face = cast(NXOpen.Face, nx._single(
                [f for f in nx.members(retainer) if isinstance(f, NXOpen.Face) and f.Name == "ALIGNPUNCH"],
                "matching element"))
            _move_touch(punch_face, reatiner_face)


def _move_touch(non_movable_face: NXOpen.Face, movable_face: NXOpen.Face) -> None:
    """PunchButtonRetainer.__MoveTouch - Touch constraint (contra-aligned) of movable_face's component onto
    non_movable_face, solved and then made non-persistent. Recorded-journal shape kept, help point included.

    The C# also reads (and discards) Parts.Display and Preferences.Assemblies.InterpartPositioning; those
    no-op reads are left out.
    """
    work_part = nx.work_part()
    component_positioner1 = work_part.ComponentAssembly.Positioner
    component_positioner1.ClearNetwork()
    component_positioner1.PrimaryArrangement = work_part.ComponentAssembly.Arrangements.FindObject("Arrangement 1")

    component_positioner1.BeginMoveComponent()

    network1 = component_positioner1.EstablishNetwork()
    component_network1 = cast(NXOpen.Positioning.ComponentNetwork, network1)
    component_network1.MoveObjectsState = True
    component_network1.DisplayComponent = None
    component_network1.NetworkArrangementsMode = NXOpen.Positioning.ComponentNetwork.ArrangementsMode.Existing
    component_network1.RemoveAllConstraints()
    movable_objects1: List[NXOpen.NXObject] = [movable_face.OwningComponent]
    component_network1.SetMovingGroup(movable_objects1)
    component_network1.Solve()
    component_network1.MoveObjectsState = True
    constraint1 = component_positioner1.CreateConstraint(False)
    component_constraint1 = cast(NXOpen.Positioning.ComponentConstraint, constraint1)
    component_constraint1.ConstraintAlignment = NXOpen.Positioning.Constraint.Alignment.InferAlign
    component_constraint1.ConstraintType = NXOpen.Positioning.Constraint.Type.Touch

    constraint_reference1 = component_constraint1.CreateConstraintReference(
        movable_face.OwningComponent, movable_face, False, False, False)

    help_point1 = NXOpen.Point3d(2.3692319931220442, -6.9818234599540876, -4.5511811023689894)

    constraint_reference1.HelpPoint = help_point1

    constraint_reference2 = component_constraint1.CreateConstraintReference(
        non_movable_face.OwningComponent, non_movable_face, False, False, False)

    constraint_reference2.SetFixHint(True)

    component_constraint1.SetAlignmentHint(NXOpen.Positioning.Constraint.Alignment.ContraAlign)

    component_network1.Solve()

    with nx.do_update("Move Component"):
        component_network1.Solve()
        component_positioner1.ClearNetwork()
        nx.session_.UpdateManager.AddToDeleteList(component_network1)
        component_positioner1.DeleteNonPersistentConstraints()

    component_positioner1.EndMoveComponent()
    component_positioner1.PrimaryArrangement = None


def _set_styles(punch: NXOpen.Assemblies.Component, on: str) -> None:
    """The run of styleXxx.Value writes each Create* method does - on gets 1, every other selector 0."""
    expressions = nx.prototype(punch).Expressions
    for name in _style_expressions:
        expressions.FindObject(name).Value = 1.0 if name == on else 0.0


def _create_ball_lock_round(bodies: Sequence[NXOpen.Body]) -> Iterator[str]:
    """PunchButtonRetainer.CreateBallLockRound - an iterator, like the C#: each new punch path is yielded
    before its SaveAs, and the caller drains it."""
    slug_dict: Dict[float, List[NXOpen.Body]] = {}

    for body in nx.distinct_by(bodies, lambda b: b.Tag):
        circle_edge = _to_arc(_first(body.GetEdges(), lambda e: e.SolidEdgeType == NXOpen.Edge.EdgeType.Circular))

        radius = round(circle_edge.Radius * 2 * 25.4, 5)

        slug_dict.setdefault(radius, []).append(body)

    for rad in slug_dict:
        slugs = slug_dict[rad]

        body = slugs[0]

        circle_edge = _to_arc(nx.single_pos_z_face(body).GetEdges()[0])

        new_path: Optional[str] = None

        try:
            valueP = _cs_f2(circle_edge.Radius * 2 * 25.4)
            D = nx.cs_double_str(_first(punch_diameters, lambda d: d > float(valueP)))
            top_face = nx.single_pos_z_face(body)
            bot_face = nx.single_neg_z_face(body)

            MaterialThickness = nx.cs_double_str(  # noqa: F841 - unused in the C# as well
                nx.edge_start_point(top_face.GetEdges()[0]).Z - nx.edge_start_point(bot_face.GetEdges()[0]).Z)

            punch = nx.add_component(
                nx.display_part(),
                smart_punch_metric_path,
                reference_set="BODY",
                origin=nx.add_z(circle_edge.CenterPoint, .25),
                component_name="circle-punch-d{}-p{}".format(D, valueP))

            with nx.do_update(), nx.lock_updates():
                nx.prototype(punch).Expressions.FindObject("valueP").RightHandSide = valueP
                _set_styles(punch, "styleBallLockRound")

            path = nx.part_dir(nx.display_part())
            new_path = "{}\\circle-punch-d{}-p{}.prt".format(path, D, valueP)
            yield new_path
            nx.prototype(punch).SaveAs(new_path)
        finally:
            _delete(circle_edge)

        slugs.pop(0)

        for slug in slugs:
            circle_edge1 = _to_arc(nx.single_pos_z_face(slug).GetEdges()[0])
            try:
                nx.add_component(
                    nx.display_part(),
                    new_path,
                    reference_set="BODY",
                    origin=nx.add_z(circle_edge1.CenterPoint, .25),
                    component_name=_file_name_without_extension(new_path))
            except Exception as ex:
                nx.print_exception(ex)
            finally:
                _delete(circle_edge1)


def _create_ball_lock_oblong(bodies: Sequence[NXOpen.Body]) -> Iterator[str]:
    """PunchButtonRetainer.CreateBallLockOblong"""
    slug_dict: Dict[float, Dict[float, List[NXOpen.Body]]] = {}

    def circular(e: NXOpen.Edge) -> bool:
        return e.SolidEdgeType == NXOpen.Edge.EdgeType.Circular

    for body in nx.distinct_by(bodies, lambda b: b.Tag):
        first_edge = _to_arc(_first(nx.single_pos_z_face(body).GetEdges(), circular))

        last_edge = _to_arc(_last(nx.single_pos_z_face(body).GetEdges(), circular))

        if not nx.doubles_equal(first_edge.Radius, last_edge.Radius):
            continue

        circle_edge = first_edge

        diameter = round(circle_edge.Radius * 2 * 25.4, 5)

        slug_dict.setdefault(diameter, {})

        length = round(nx.distance(first_edge.CenterPoint, last_edge.CenterPoint) * 2 * 25.4, 5)

        slug_dict[diameter].setdefault(length, []).append(body)

    for rad in slug_dict:
        for length in slug_dict[rad]:
            body = slug_dict[rad][length][0]

            first_arc_edge = _to_arc(_first(nx.single_pos_z_face(body).GetEdges(), circular))
            last_arc_edge = _to_arc(_last(nx.single_pos_z_face(body).GetEdges(), circular))

            new_path: Optional[str] = None

            try:
                valueP = _cs_f2(
                    nx.distance(nx.curve_mid_point(first_arc_edge), nx.curve_mid_point(last_arc_edge)) * 25.4)

                # Created and never used or deleted, as in the C#.
                nx.display_part().Curves.CreateLine(
                    nx.curve_mid_point(first_arc_edge),
                    nx.curve_mid_point(last_arc_edge))

                valueW = _cs_f2(first_arc_edge.Radius * 2 * 25.4)

                D = nx.cs_double_str(_first(punch_diameters, lambda d: d > float(valueP)))
                top_face = nx.single_pos_z_face(body)
                bot_face = nx.single_neg_z_face(body)

                MaterialThickness = nx.cs_double_str(  # noqa: F841 - unused in the C# as well
                    nx.edge_start_point(top_face.GetEdges()[0]).Z - nx.edge_start_point(bot_face.GetEdges()[0]).Z)

                punch = nx.add_component(
                    nx.display_part(),
                    smart_punch_metric_path,
                    reference_set="BODY",
                    origin=nx.add_z(nx.mid_point(first_arc_edge.CenterPoint, last_arc_edge.CenterPoint), .25),
                    component_name="oblong-punch-d{}-p{}-w{}".format(D, valueP, valueW))

                with nx.display_part_reset():
                    nx.set_work_component(punch)

                    with nx.do_update(), nx.lock_updates():
                        _set_styles(punch, "styleBallLockOblong")

                nx.prototype(punch).Expressions.FindObject("D").RightHandSide = D

                nx.prototype(punch).Expressions.FindObject("valueP").RightHandSide = valueP

                nx.prototype(punch).Expressions.FindObject("valueW").RightHandSide = valueW

                path = nx.part_dir(nx.display_part())
                new_path = "{}\\oblong-punch-d{}-p{}-w{}.prt".format(path, D, valueP, valueW)
                yield new_path
                nx.prototype(punch).SaveAs(new_path)
            finally:
                _delete(first_arc_edge)

            slug_dict[rad][length].pop(0)

            for slug in slug_dict[rad][length]:
                first_arc_edge = _to_arc(_first(nx.single_pos_z_face(slug).GetEdges(), circular))

                last_arc_edge = _to_arc(_last(nx.single_pos_z_face(slug).GetEdges(), circular))
                try:
                    nx.add_component(
                        nx.display_part(),
                        new_path,
                        reference_set="BODY",
                        origin=nx.add_z(nx.mid_point(first_arc_edge.CenterPoint, last_arc_edge.CenterPoint), .25),
                        component_name=_file_name_without_extension(new_path))
                except Exception as ex:
                    nx.print_exception(ex)
                finally:
                    _delete(first_arc_edge)
                    _delete(last_arc_edge)


def _create_ball_lock_rectangle_radius(bodies: Sequence[NXOpen.Body]) -> Iterator[str]:
    """PunchButtonRetainer.CreateBallLockRectangleRadius"""
    slug_dict: Dict[str, str] = {}

    created: List[List[str]] = []

    for body in nx.distinct_by(bodies, lambda b: b.Tag):
        top_edges = nx.single_pos_z_face(body).GetEdges()
        arcs = [_to_arc(e) for e in top_edges if e.SolidEdgeType == NXOpen.Edge.EdgeType.Circular]

        top_edges = nx.single_pos_z_face(body).GetEdges()
        lines = [_to_line(e) for e in top_edges if e.SolidEdgeType == NXOpen.Edge.EdgeType.Linear]

        if len(arcs) != 4:
            continue

        if len(lines) != 4:
            continue

        if any(not nx.doubles_equal(a.Radius, arcs[0].Radius) for a in arcs):
            continue

        if any(not nx.doubles_equal(a.GetLength(), arcs[0].GetLength()) for a in arcs):
            continue

        first = arcs[0]
        last = _max_by([a for a in arcs if a.Tag != first.Tag],
                       lambda a: nx.distance(a.CenterPoint, first.CenterPoint))

        long_line = _max_by(lines, lambda line: round(line.GetLength(), 4))
        short_line = _min_by(lines, lambda line: round(line.GetLength(), 4))

        valueP = long_line.GetLength() * 25.4 + arcs[0].Radius * 2 * 25.4
        valueW = short_line.GetLength() * 25.4 + arcs[0].Radius * 2 * 25.4
        valueR = arcs[0].Radius * 25.4
        D = (valueP ** 2 + valueW ** 2) ** .5

        diagonal = D
        D = _first(punch_diameters, lambda d: d > diagonal)
        origin = nx.add_z(nx.mid_point(first.CenterPoint, last.CenterPoint), .25)
        part_leaf = "rounded-rectangle-punch-d{}-p{}-w{}-r{}".format(
            _cs_f2(D), _cs_f2(valueP), _cs_f2(valueW), _cs_f2(valueR))

        new_path: Optional[str] = None

        already_saved = False

        for old in created:
            if not nx.doubles_equal(float(old[0]), D):
                continue

            if not nx.doubles_equal(float(old[1]), valueP):
                continue

            if not nx.doubles_equal(float(old[2]), valueW):
                continue

            if not nx.doubles_equal(float(old[3]), valueR):
                continue

            new_path = old[4]

            already_saved = True

            break

        if already_saved:
            nx.add_component(
                nx.display_part(),
                cast(str, new_path),
                reference_set="BODY",
                origin=origin,
                component_name=_file_name_without_extension(cast(str, new_path)))

            continue

        punch = nx.add_component(
            nx.display_part(),
            smart_punch_metric_path,
            reference_set="BODY",
            origin=origin,
            component_name=part_leaf)

        with nx.display_part_reset():
            nx.set_work_component(punch)

            with nx.do_update(), nx.lock_updates():
                _set_styles(punch, "styleBallLockRectangleRadius")

                expressions = nx.prototype(punch).Expressions
                expressions.FindObject("D").RightHandSide = nx.cs_double_str(D)

                expressions.FindObject("valueP").RightHandSide = nx.cs_double_str(valueP)

                expressions.FindObject("valueW").RightHandSide = nx.cs_double_str(valueW)

                expressions.FindObject("valueR").RightHandSide = nx.cs_double_str(valueR)

            path = nx.part_dir(nx.display_part())
            new_path = "{}\\{}.prt".format(path, part_leaf)
            yield new_path
            nx.prototype(punch).SaveAs(new_path)

            slug_dict[part_leaf] = new_path

            created.append([
                nx.cs_double_str(D),
                nx.cs_double_str(valueP),
                nx.cs_double_str(valueW),
                nx.cs_double_str(valueR),
                new_path,
            ])


# ---------------------------------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------------------------------

def _first(items: Sequence[_T], predicate: Callable[[_T], bool]) -> _T:
    """Enumerable.First(predicate) - raises like InvalidOperationException when nothing matches."""
    for item in items:
        if predicate(item):
            return item
    raise RuntimeError("Sequence contains no matching element")


def _last(items: Sequence[_T], predicate: Callable[[_T], bool]) -> _T:
    """Enumerable.Last(predicate)"""
    for item in reversed(items):
        if predicate(item):
            return item
    raise RuntimeError("Sequence contains no matching element")


def _max_by(items: Sequence[_T], selector: Callable[[_T], float]) -> _T:
    """IEnumerable.__MaxBy - the first item with the largest value. (The C# returns default on an empty
    sequence; here that raises, since None would only fail one line later.)"""
    best: Optional[_T] = None
    best_value: Optional[float] = None
    for item in items:
        value = selector(item)
        if best_value is not None and not value > best_value:
            continue
        best_value = value
        best = item
    if best is None:
        raise RuntimeError("Sequence contains no elements")
    return best


def _min_by(items: Sequence[_T], selector: Callable[[_T], float]) -> _T:
    """IEnumerable.__MinBy - the first item with the smallest value."""
    best: Optional[_T] = None
    best_value: Optional[float] = None
    for item in items:
        value = selector(item)
        if best_value is not None and not value < best_value:
            continue
        best_value = value
        best = item
    if best is None:
        raise RuntimeError("Sequence contains no elements")
    return best


def _to_arc(edge: NXOpen.Edge) -> NXOpen.Arc:
    """(Arc)edge.__ToCurve()"""
    curve = nx.edge_to_curve(edge)
    if not isinstance(curve, NXOpen.Arc):
        raise TypeError("Unable to cast object of type '{}' to type 'NXOpen.Arc'.".format(type(curve).__name__))
    return curve


def _to_line(edge: NXOpen.Edge) -> NXOpen.Line:
    """(Line)edge.__ToCurve()"""
    curve = nx.edge_to_curve(edge)
    if not isinstance(curve, NXOpen.Line):
        raise TypeError("Unable to cast object of type '{}' to type 'NXOpen.Line'.".format(type(curve).__name__))
    return curve


def _cs_f2(value: float) -> str:
    """double.ToString("F2") as .NET Framework formats it: the double is first taken to 15 significant
    digits, then rounded half away from zero to 2 decimals. Negative zero prints as "0.00"."""
    rounded = Decimal(format(value, ".14E")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if rounded == 0:
        rounded = abs(rounded)
    return "{:.2f}".format(rounded)


def _delete(obj: NXOpen.TaggedObject) -> None:
    """TaggedObject.__Delete - session_.__DeleteObjects(obj): delete list inside a DoUpdate.

    Written out here because tsg_nx defines delete_objects twice with different signatures (*objects, then a
    sequence) and the later one wins at runtime.
    """
    with nx.do_update():
        nx.session_.UpdateManager.AddObjectsToDeleteList([obj])


def _file_name_without_extension(path: Optional[str]) -> str:
    """Path.GetFileNameWithoutExtension"""
    if path is None:
        raise TypeError("path is None")
    return os.path.splitext(os.path.basename(path))[0]


def _file_copy(source: str, destination: str) -> None:
    """File.Copy(source, destination) - no overwrite: raises when destination already exists."""
    if os.path.exists(destination):
        raise FileExistsError("The file '{}' already exists.".format(destination))
    import shutil
    shutil.copy2(source, destination)


def main() -> None:
    """Standalone entry (File -> Execute -> NX Open)."""
    PunchButtonRetainer.execute()


if __name__ == "__main__":
    main()
