"""
Design check validators about material: TrimSteelMaterial and BlockMaterialColor (src\\UFuncs\\DesignCheck\\Validators\\),
plus the Block Attributer box helpers BlockMaterialColor and the dialog's box lines share (src\\Static\\BlockAtt.cs,
src\\Static\\BlockAttDialog.cs, src\\Utilities\\OrientedBox.cs). Framework: design_check.py.

Ported from:
  - TrimSteelMaterial (FindAssembly, ReadRequired, LinkAttribute, IsTrimSteel, Check, Fix) -> TrimSteelMaterial
  - BlockMaterialColor (Check, Check(part, extraInches), CheckStock, SideAxis, CyanCoversSide, Report)
                                                                   -> BlockMaterialColor, block_material_color_report
  - OrientedBox(tag, csys)                                         -> oriented_box
  - Body.__RoundedXyz                                              -> rounded_xyz
  - Static.BlockAttRoundAndTruncate / BlockAttRoundDistances       -> round_distances
  - Static.BlockAttDialogStockedBlockSize / ...StockValue          -> stocked_block_size
  - Static.BlockAttDialogDisplayTemporaryBlockEdges, BlockAttDisplayTemporaryLine, BlockAttShowTemporarySizeText
                                                                   -> display_temporary_block_edges

Differences from the C#:
  - The temporary lines and size text are drawn with UF Disp in the work view as the C# does; the Python enum names
    (NXOpen.UF.DispViewType / DispTextRef) are a guess from Measure.py's DisplayTemporaryLine call, so a failure to
    draw is printed once per box rather than raised.
  - BlockAttRoundDistances' `for (ii = .125; ii <= 1; ii += .125)` adds binary fractions, which are exact, so the
    Python loop over the eight eighths matches it.

NEVER RUN IN NX.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from typing import Any, List, Optional, Sequence, Tuple, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.Features  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
from design_check import (FixesFailures, Item, ListsPassedAndIgnored, Result, assembly_parts,  # noqa: E402
                          is_detail)

# Extensions.ColorTrim / ColorFinish
ColorTrim = 186
ColorFinish = 42


# ---------------------------------------------------------------------------------------------------
# Shared box helpers
# ---------------------------------------------------------------------------------------------------

class OrientedBox(object):
    """OrientedBox(tag, csys): the exact bounding box of an object in a csys (0 = the UF default)."""

    def __init__(self, obj_tag: Any, csys: Any = 0) -> None:
        min_corner, directions, distances = nx.ufsession_.ModlGeneral.AskBoundingBoxExact(obj_tag, csys)
        self.origin = NXOpen.Point3d(min_corner[0], min_corner[1], min_corner[2])
        flat = _flatten(directions)
        self.axes = [nx.unit(NXOpen.Vector3d(flat[i * 3], flat[i * 3 + 1], flat[i * 3 + 2])) for i in range(3)]
        self.distances = [float(distances[0]), float(distances[1]), float(distances[2])]

    @property
    def max_corner(self) -> NXOpen.Point3d:
        """OrientedBox.MaxCorner - the origin plus each distance along its own axis."""
        p = self.origin
        x, y, z = p.X, p.Y, p.Z
        for axis, distance in zip(self.axes, self.distances):
            x += axis.X * distance
            y += axis.Y * distance
            z += axis.Z * distance
        return NXOpen.Point3d(x, y, z)


def oriented_box(obj_tag: Any, csys: Any = 0) -> OrientedBox:
    return OrientedBox(obj_tag, csys)


def _flatten(values: Any) -> List[float]:
    """AskBoundingBoxExact's directions come back as 9 floats or as 3 rows of 3; either way, 9 floats."""
    flat: List[float] = []
    for value in values:
        if isinstance(value, (list, tuple)):
            flat.extend(float(v) for v in value)
        else:
            flat.append(float(value))
    return flat


def round_distances(distances: List[float]) -> None:
    """Static.BlockAttRoundDistances: each of the first three distances rounded to 3 places, then up to the next 1/8"
    (a whole number stays as it is). In place, like the C#."""
    for i in range(3):
        round_value = _cs_round(distances[i], 3)
        truncate_value = float(int(round_value))
        fraction_value = round_value - truncate_value

        if fraction_value == 0:
            distances[i] = round_value
            continue

        for eighth in range(1, 9):
            ii = eighth * .125
            if fraction_value > ii:
                continue
            distances[i] = truncate_value + ii
            break


def _cs_round(value: float, digits: int) -> float:
    """System.Math.Round(value, digits) - banker's rounding, as Python's round."""
    return round(value, digits)


def rounded_xyz(body: NXOpen.Body) -> List[float]:
    """Body.__RoundedXyz: the body's absolute X / Y / Z extents in inches, rounded up to 1/8"."""
    box = OrientedBox(body.Tag, 0)
    distances = list(box.distances)
    if body.OwningPart.PartUnits == NXOpen.BasePart.Units.Millimeters:
        distances = [d / 25.4 for d in distances]
    round_distances(distances)
    return distances


def _stock_value(part: NXOpen.Part, name: str) -> float:
    """Static.BlockAttDialogStockValue - the value of the part's last expression named name, 0 when none."""
    value = 0.0
    for expression in part.Expressions:
        if expression.Name == name:
            value = expression.Value
    return value


def stocked_block_size(body: NXOpen.Body, origin: NXOpen.Point3d, x_axis: NXOpen.Vector3d, y_axis: NXOpen.Vector3d,
                       stock_part: NXOpen.Part) -> List[float]:
    """
    Static.BlockAttDialogStockedBlockSize: the body's extents measured in a temporary csys at origin along x_axis /
    y_axis, plus stock_part's AddX / AddY / AddZ (0 when missing), each rounded up to the next 1/8" - in display-part
    units (a metric display part is rounded in inches and converted back).
    """
    ufs: Any = nx.ufsession_
    matrix = ufs.Mtx3.Initialize([x_axis.X, x_axis.Y, x_axis.Z], [y_axis.X, y_axis.Y, y_axis.Z])
    matrix_tag = ufs.Csys.CreateMatrix(list(matrix))
    csys = ufs.Csys.CreateTempCsys([origin.X, origin.Y, origin.Z], matrix_tag)

    distances = list(OrientedBox(body.Tag, csys).distances)
    distances[0] += _stock_value(stock_part, "AddX")
    distances[1] += _stock_value(stock_part, "AddY")
    distances[2] += _stock_value(stock_part, "AddZ")

    is_metric = nx.display_part().PartUnits == NXOpen.BasePart.Units.Millimeters
    if is_metric:
        distances = [d / 25.4 for d in distances]
    round_distances(distances)
    if is_metric:
        distances = [d * 25.4 for d in distances]
    return distances


def _add(point: NXOpen.Point3d, vector: NXOpen.Vector3d, length: float) -> NXOpen.Point3d:
    """Point3d.__Add(vector, length) - the axes need not be unit length, as in the C#."""
    return NXOpen.Point3d(point.X + vector.X * length, point.Y + vector.Y * length, point.Z + vector.Z * length)


def _disp_props(color: int) -> Any:
    props: Any = NXOpen.UF.UFObj.DispProps()
    props.Color = color
    return props


def _view_type() -> Any:
    """UFDisp.ViewType.UseWorkView, under either spelling the Python binding may use."""
    uf: Any = NXOpen.UF
    if hasattr(uf, "DispViewType"):
        return uf.DispViewType.UseWorkView
    return uf.Disp.ViewType.USE_WORK_VIEW


def _text_ref() -> Any:
    """UFDisp.TextRef.Middlecenter, under either spelling."""
    uf: Any = NXOpen.UF
    if hasattr(uf, "DispTextRef"):
        return uf.DispTextRef.Middlecenter
    return uf.Disp.TextRef.MIDDLECENTER


def display_temporary_block_edges(origin: NXOpen.Point3d, x_axis: NXOpen.Vector3d, y_axis: NXOpen.Vector3d,
                                  z_axis: NXOpen.Vector3d, length: float, width: float, height: float,
                                  display_part: NXOpen.Part) -> None:
    """
    Static.BlockAttDialogDisplayTemporaryBlockEdges: the block's twelve edges as temporary lines (color 7) in the
    work view, the three from the origin corner labelled with their sizes (BlockAttShowTemporarySizeText, color 31).
    Nothing is added to the part; the next view refresh clears them.
    """
    ufs: Any = nx.ufsession_
    view = display_part.Views.WorkView.Tag
    view_type = _view_type()
    line_props = _disp_props(7)
    sizes = [length, width, height]
    axes = [x_axis, y_axis, z_axis]
    inches = display_part.PartUnits == NXOpen.BasePart.Units.Inches

    def corner(i: int, j: int, k: int) -> NXOpen.Point3d:
        return _add(_add(_add(origin, x_axis, i * length), y_axis, j * width), z_axis, k * height)

    for i in range(2):
        for j in range(2):
            for k in range(2):
                start = corner(i, j, k)
                at = [i, j, k]
                for axis in range(3):
                    if at[axis] != 0:
                        continue
                    end = _add(start, axes[axis], sizes[axis])
                    ufs.Disp.DisplayTemporaryLine(view, view_type, [start.X, start.Y, start.Z],
                                                  [end.X, end.Y, end.Z], line_props)
                    if i == 0 and j == 0 and k == 0:
                        round_dim = round(sizes[axis], 3)
                        text = "{:.3f}".format(round_dim if inches else round_dim / 25.4)
                        middle = [(start.X + end.X) / 2.0, (start.Y + end.Y) / 2.0, (start.Z + end.Z) / 2.0]
                        ufs.Disp.DisplayTemporaryText(view, view_type, text, middle, _text_ref(), _disp_props(31),
                                                      .125 if inches else 3.175, 1)


def _solid_bodies_on_layer_1(part: NXOpen.Part) -> List[NXOpen.Body]:
    return [body for body in part.Bodies if body.IsSolidBody and body.Layer == 1]


def _find_expression_or_null(part: NXOpen.BasePart, name: str) -> Optional[NXOpen.Expression]:
    return nx.find_expression_or_null(part, name)


# ---------------------------------------------------------------------------------------------------
# TrimSteelMaterial
# ---------------------------------------------------------------------------------------------------

class TrimSteelMaterial(FixesFailures):
    """
    Fails a trim steel whose MATERIAL attribute is not the job's trim steel material: the trim_steel_material string
    expression on the {job}-{op}-000, or, when that is missing or empty, a trim_steel_material / TRIM STEEL MATERIAL
    string attribute on it. When none holds a value nothing is collected. A trim steel is a detail (the -000 itself
    excepted) with a layer-1 solid body carrying a face colored 186. MATERIAL is compared trimmed, ignoring case.
    When the expression is there, constructing the check also links a TRIM STEEL MATERIAL attribute on the -000 to
    it. The dialog's part menu "Set MATERIAL to {material}" runs fix.
    """

    ExpressionName = "trim_steel_material"
    AttributeTitle = "TRIM STEEL MATERIAL"

    assembly_part_only = False

    def __init__(self, display: Optional[NXOpen.Part]) -> None:
        self._assembly = TrimSteelMaterial.find_assembly(display)
        self._required: Optional[str] = None

        if self._assembly is None:
            nx.print_("TrimSteelMaterial: no {{job}}-{{op}}-000 found for {} - check skipped.".format(
                display.Leaf if display is not None else ""))
            return

        self._required = TrimSteelMaterial.read_required(self._assembly)
        if self._required is None:
            return

        try:
            TrimSteelMaterial.link_attribute(self._assembly)
        except Exception as ex:
            nx.print_("TrimSteelMaterial: could not link {} on {} to {}.".format(
                TrimSteelMaterial.AttributeTitle, self._assembly.Leaf, TrimSteelMaterial.ExpressionName))
            nx.print_exception(ex)

    def get_objects(self, part: NXOpen.Part) -> List[Any]:
        if (self._required is None or (self._assembly is not None and part.Tag == self._assembly.Tag)
                or not is_detail(part.Leaf) or not TrimSteelMaterial.is_trim_steel(part)):
            return []
        return [part]

    def check(self, obj: Any) -> Tuple[str, Optional[Item]]:
        part: NXOpen.Part = obj
        node = Item("", part)

        if not nx.has_attribute(part, "MATERIAL"):
            node.text = "MATERIAL missing (expected {})".format(self._required)
            return Result.Fail, node

        material = nx.get_attribute(part, "MATERIAL").strip()
        node.text = "MATERIAL = {} (expected {})".format(material, self._required)
        passes = material.lower() == (self._required or "").lower()
        return (Result.Pass if passes else Result.Fail), node

    @property
    def fix_text(self) -> str:
        return "Set MATERIAL to {}".format(self._required)

    def fix(self, obj: Any) -> None:
        """Sets the failing trim steel's MATERIAL to the required material (the failure Item's obj is the part)."""
        part: NXOpen.Part = obj
        nx.set_attribute(part, "MATERIAL", self._required or "")
        nx.print_("TrimSteelMaterial: {} MATERIAL set to {}.".format(part.Leaf, self._required))

    @staticmethod
    def is_trim_steel(part: NXOpen.Part) -> bool:
        """A solid body on layer 1 with at least one face colored 186."""
        return any(face.Color == ColorTrim for body in _solid_bodies_on_layer_1(part) for face in body.GetFaces())

    @staticmethod
    def find_assembly(display: Optional[NXOpen.Part]) -> Optional[NXOpen.Part]:
        """The display part when it is a {job}-{op}-000, otherwise the loaded {job}-{op}-000 its leaf names."""
        if display is None:
            return None
        match = re.match(r"^(?P<jobOp>\d+-\d+)-", display.Leaf)
        if not match:
            return None
        leaf = "{}-000".format(match.group("jobOp"))
        if display.Leaf == leaf:
            return display
        for part in nx.session_.Parts:
            if isinstance(part, NXOpen.Part) and part.Leaf == leaf:
                return part
        return None

    @staticmethod
    def read_required(assembly: NXOpen.Part) -> Optional[str]:
        """The trim_steel_material expression's value, else a trim_steel_material or TRIM STEEL MATERIAL string
        attribute's, trimmed; None when none holds a value."""
        expression = _find_expression_or_null(assembly, TrimSteelMaterial.ExpressionName)
        if expression is not None:
            raw = expression.StringValue if expression.Type == "String" else expression.RightHandSide
            value = (raw or "").strip()
            if value:
                return value

        for title in (TrimSteelMaterial.ExpressionName, TrimSteelMaterial.AttributeTitle):
            if not nx.has_attribute(assembly, title):
                continue
            value = (nx.get_attribute(assembly, title) or "").strip()
            if value:
                return value

        return None

    @staticmethod
    def link_attribute(assembly: NXOpen.Part) -> bool:
        """Gives the -000 a TRIM STEEL MATERIAL string attribute linked to its trim_steel_material expression,
        unless one already is. False when there is no expression."""
        expression = _find_expression_or_null(assembly, TrimSteelMaterial.ExpressionName)
        if expression is None:
            return False

        # Members missing from the stubs (GetUserAttribute, AttributeManager, AttributePropertiesBuilder).
        asm: Any = assembly
        nxopen: Any = NXOpen
        title = TrimSteelMaterial.AttributeTitle
        string_type = NXOpen.NXObject.AttributeType.String
        if asm.HasUserAttribute(title, string_type, -1):
            info: Any = asm.GetUserAttribute(title, string_type, -1)
            linked = getattr(info, "Expression", None)
            if linked is not None and linked.Tag == expression.Tag:
                return True

        manager: Any = cast(Any, nx.session_).AttributeManager
        builder = manager.CreateAttributePropertiesBuilder(
            assembly, [assembly], nxopen.AttributePropertiesBuilder.OperationType.NotSet)
        try:
            builder.Title = title
            builder.DataType = nxopen.AttributePropertiesBuilder.DataTypeOptions.String
            builder.Expression = expression
            builder.Commit()
        finally:
            builder.Destroy()

        nx.print_("TrimSteelMaterial: linked {} on {} to {}.".format(title, assembly.Leaf,
                                                                       TrimSteelMaterial.ExpressionName))
        return True


# ---------------------------------------------------------------------------------------------------
# BlockMaterialColor
# ---------------------------------------------------------------------------------------------------

class BlockMaterialColor(ListsPassedAndIgnored):
    """
    Fails a detail ({job}-{op}-{detail}, the -000 excepted) that is not ordered big enough for the material its face
    colors say gets cut away: its current feature is not its last; it lacks any of AddX / AddY / AddZ; it has not
    exactly one layer-1 solid body; or an absolute axis needs stock and has none. An axis needs stock when one of the
    body's sides square to it is a face colored 186, two opposite faces are colored 42 (yellow; not when the Burnout
    expression is yes), or a yellow face's opposite side is covered by cyan (3) faces. An axis has stock when its own
    Add expression is above 0, or when rounding the body's size along it up to 1/8" already adds some. A 186 face
    inside the block (a notch or pocket wall) needs no stock. Non-details and the -000 are ignored; passes and ignores
    are listed (ListsPassedAndIgnored).
    """

    ColorCyan = 3
    AddNames = ["AddX", "AddY", "AddZ"]
    AxisNames = ["X", "Y", "Z"]

    # Inches: how close a face must be to the body's side, and the least rounding that counts as stock.
    ToleranceInch = .001

    assembly_part_only = False

    def get_objects(self, part: NXOpen.Part) -> List[Any]:
        return [part]

    def check(self, obj: Any) -> Tuple[str, Optional[Item]]:
        return self.check_with_stock(obj, None)

    def check_with_stock(self, part: NXOpen.Part, extra_inches: Optional[Sequence[float]]) -> Tuple[str, Item]:
        """Check(part, extraInches): the result as if extra_inches (X / Y / Z, may be None) were added to AddX / AddY
        / AddZ - the stock picked in the dialog but not applied. Nothing in the part changes."""
        if not is_detail(part.Leaf) or part.Leaf.endswith("-000"):
            return Result.Ignore, Item("the -000" if is_detail(part.Leaf) else "not a detail", part)

        problems: List[str] = []
        sizes: List[Item] = []
        summary = ""

        features = list(part.Features)
        current = cast(Any, part).CurrentFeature

        if features and (current is None or current.Tag != features[-1].Tag):
            problems.append("current feature is {}, not the last feature {}".format(
                current.GetFeatureName() if current is not None else "none", features[-1].GetFeatureName()))

        adds = [_find_expression_or_null(part, name) for name in self.AddNames]

        for i in range(3):
            if adds[i] is None:
                problems.append("{} missing".format(self.AddNames[i]))

        bodies = _solid_bodies_on_layer_1(part)

        if len(bodies) != 1:
            problems.append("{} solid bodies on layer 1".format(len(bodies)))
        elif all(add is not None for add in adds):
            to_part = 25.4 if part.PartUnits == NXOpen.BasePart.Units.Millimeters else 1.0
            present = [add for add in adds if add is not None]
            add_values = [present[i].Value + ((extra_inches[i] if extra_inches is not None else 0.0) * to_part)
                          for i in range(3)]

            summary = self._check_stock(part, bodies[0], add_values, problems, sizes)

            if extra_inches is not None and any(extra > 0 for extra in extra_inches):
                summary += " (with picked stock, not applied)"

        node = Item("ordered big enough{}".format(summary) if not problems else "; ".join(problems) + summary, part)
        node.add_range(sizes)

        return (Result.Pass if not problems else Result.Fail), node

    def _check_stock(self, part: NXOpen.Part, body: NXOpen.Body, add_values: List[float], problems: List[str],
                     sizes: List[Item]) -> str:
        """CheckStock: a problem per face-color reason whose axes have no stock, and an X / Y / Z size Item each."""
        to_inches = 1 / 25.4 if part.PartUnits == NXOpen.BasePart.Units.Millimeters else 1.0
        tolerance = self.ToleranceInch / to_inches

        box = nx.body_box(body)
        min_ = [box.MinX, box.MinY, box.MinZ]
        max_ = [box.MaxX, box.MaxY, box.MaxZ]
        rounded = rounded_xyz(body)

        has_stock = [add_values[i] > tolerance or rounded[i] - (max_[i] - min_[i]) * to_inches > self.ToleranceInch
                     for i in range(3)]

        reasons: List[Tuple[str, List[int]]] = []
        faces = list(body.GetFaces())

        for face in faces:
            if face.Color != ColorTrim:
                continue
            axis, side = self._side_axis(face, min_, max_, tolerance)
            if axis >= 0 and side != 0:
                reasons.append(("trim face ({})".format(ColorTrim), [axis]))

        yellow: List[Tuple[int, int]] = []
        for face in faces:
            if face.Color != ColorFinish:
                continue
            axis, side = self._side_axis(face, min_, max_, tolerance)
            if axis >= 0 and side != 0:
                yellow.append((axis, side))

        cyan: List[Tuple[List[float], List[float]]] = []
        for face in faces:
            if face.Color != self.ColorCyan:
                continue
            b = OrientedBox(face.Tag, 0)
            lo, hi = b.origin, b.max_corner
            cyan.append(([min(lo.X, hi.X), min(lo.Y, hi.Y), min(lo.Z, hi.Z)],
                         [max(lo.X, hi.X), max(lo.Y, hi.Y), max(lo.Z, hi.Z)]))

        burnout = _find_expression_or_null(part, "Burnout")
        is_burnout = burnout is not None and \
            (burnout.RightHandSide or "").replace("\"", "").strip().lower() == "yes"

        for axis in range(3):
            if (not is_burnout and any(a == axis and s < 0 for a, s in yellow)
                    and any(a == axis and s > 0 for a, s in yellow)):
                reasons.append(("opposite yellow faces ({})".format(ColorFinish), [axis]))

            seen_sides: List[int] = []
            for a, s in yellow:
                if a != axis or s in seen_sides:
                    continue
                seen_sides.append(s)
                if self._cyan_covers_side(cyan, axis, -s, min_, max_, tolerance):
                    reasons.append(("yellow face ({}) opposite cyan ({})".format(ColorFinish, self.ColorCyan), [axis]))

        # GroupBy keeps the order each reason first appears in; Distinct keeps the order of the axes texts.
        grouped: List[Tuple[str, List[str]]] = []
        for text, axes in reasons:
            if any(has_stock[a] for a in axes):
                continue
            axes_text = "/".join(self.AxisNames[a] for a in axes)
            group = next((g for g in grouped if g[0] == text), None)
            if group is None:
                grouped.append((text, [axes_text]))
            elif axes_text not in group[1]:
                group[1].append(axes_text)

        for text, axes_texts in grouped:
            problems.append("{} without stock on {} (Add 0, size already a 1/8\")".format(text, ", ".join(axes_texts)))

        # As BlockAttRoundedSize: each Add on its own axis, then rounded up to 1/8".
        actual = [(max_[i] - min_[i]) * to_inches for i in range(3)]
        with_stock = [actual[i] + add_values[i] * to_inches for i in range(3)]
        round_distances(with_stock)

        for i in range(3):
            # The dialog finds the X / Y / Z items by their name, for their add-stock menu.
            sizes.append(Item("{}: actual {}, rounded {}, with stock {} ({} {})".format(
                self.AxisNames[i], _fmt(actual[i]), _fmt(rounded[i]), _fmt(with_stock[i]), self.AddNames[i],
                _fmt(add_values[i])), part, self.AddNames[i]))

        return " (Burnout yes)" if is_burnout else ""

    @staticmethod
    def _side_axis(face: NXOpen.Face, min_: List[float], max_: List[float], tolerance: float) -> Tuple[int, int]:
        """SideAxis: the absolute axis a planar face is square to (-1 when not planar or not square), and whether it
        lies on the body's min (-1) or max (1) side of it, or neither (0)."""
        if face.SolidFaceType != NXOpen.Face.FaceType.Planar:
            return -1, 0

        normal = nx.face_normal(face)
        values = [normal.X, normal.Y, normal.Z]
        axis = next((i for i, n in enumerate(values) if abs(abs(n) - 1) < 1e-6), -1)

        if axis < 0:
            return -1, 0

        origin = OrientedBox(face.Tag, 0).origin
        position = [origin.X, origin.Y, origin.Z][axis]

        side = 0
        if abs(position - min_[axis]) < tolerance:
            side = -1
        elif abs(position - max_[axis]) < tolerance:
            side = 1

        return axis, side

    @staticmethod
    def _cyan_covers_side(cyan: List[Tuple[List[float], List[float]]], axis: int, side: int, min_: List[float],
                          max_: List[float], tolerance: float) -> bool:
        """CyanCoversSide: whether the cyan faces between them reach the body's side of axis on side, spanning the
        other two axes."""
        if not cyan:
            return False

        cyan_min = [min(b[0][i] for b in cyan) for i in range(3)]
        cyan_max = [max(b[1][i] for b in cyan) for i in range(3)]

        reaches_side = (abs(cyan_min[axis] - min_[axis]) < tolerance if side < 0
                        else abs(cyan_max[axis] - max_[axis]) < tolerance)

        return reaches_side and all(cyan_min[i] - min_[i] < tolerance and max_[i] - cyan_max[i] < tolerance
                                    for i in range(3) if i != axis)


def _fmt(value: float) -> str:
    """C# {value:0.###}: up to three decimals, no trailing zeros, "0" for zero, no "-0"."""
    text = "{:.3f}".format(value).rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def block_material_color_report_path() -> str:
    """BlockMaterialColor.ReportPath - %TEMP%\\block-material-color.txt."""
    return os.path.join(tempfile.gettempdir(), "block-material-color.txt")


def block_material_color_report() -> int:
    """BlockMaterialColor.Report: this check alone on every part under the display part, each detail's result (and
    a count of the ignored parts) to the listing window and the report file; returns the failure count."""
    check = BlockMaterialColor()
    display = nx.display_part()
    lines = ["BlockMaterialColor: {}".format(display.Leaf)]
    failed = 0
    ignored = 0

    for part in assembly_parts(display):
        for obj in check.get_objects(part):
            try:
                result, node = check.check(obj)
                if result == Result.Ignore:
                    ignored += 1
                    continue
                if result == Result.Fail:
                    failed += 1
                assert node is not None
                lines.append("    {:<4} {}: {}".format(result, part.Leaf, node.text))
                lines.extend("         {}".format(size.text) for size in node.children)
            except Exception as ex:
                failed += 1
                lines.append("    ERR  {}: {}".format(part.Leaf, ex))

    lines.append("{} failed, {} ignored (not a detail, or the -000)".format(failed, ignored))
    nx.print_("\n".join(lines))

    try:
        with open(block_material_color_report_path(), "w", encoding="utf-8") as writer:
            writer.write("\n".join(lines) + "\n")
    except Exception as ex:
        nx.print_exception(ex)

    return failed
