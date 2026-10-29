"""
The bill-of-material UFunc as a Block UI Styler dialog: a port of the C# Bom form (src\\UFuncs\\Bom.cs) and its
Static methods (src\\Static\\Bom.cs). Its menu button runs this file's main().

The dialog (BillOfMaterial.dlx, tools\\make-dlx.py) replaces the form's company buttons, Select / Clear Selection /
Bom Castings buttons and the Preselect step:
  - Company     - ATS, CTS, DTS, ETS, RTS, UGS (the TSG stocklist into BillOfMaterial.ucf's {company}_EXCEL template),
                  ATD (atdbom.xlsx: the form's Atd check box plus its ATD button's offset of 18) or GM (gm.xlsx, every
                  detail of the display part - the details picker and the stocklist toggles are hidden).
  - 3 / 4 Digits - which component names count as details, as before.
  - Castings only - the details picker holds only the details whose DESCRIPTION contains CAST, and the workbook is
                  {display}-casting-stocklist.xlsx with no checker sheet (the form's Bom Castings button).
  - Details     - opens holding every valid detail under the display part (Preselect.GetUserSelections did the same
                  in a selection dialog); deselect or add, then OK. Refilled when a digit or the castings toggle
                  changes.
  - Checker Sheet, Show MM Dimensions, Round MM - as the form's check boxes. The form's "Exact Sizes Mnt" check box
                  and "ATS new" button did nothing and are gone.

Python in NX has no Excel library, so the rows are gathered here, written to a temp JSON file, and
BillOfMaterialExcel.ps1 fills the copied templates through Excel COM (centered Verdana 10, green purchased cells -
the template formatting is kept). The vendor check list (CheckBoxDialog) is BillOfMaterialVendors.ps1, seeded from
and written back to the job's NX Stocklist\\previous.txt.

Kept from the C#: the overwrite / MATERIAL / DETAIL NAME-MATERIAL-DESCRIPTION checks, the row build (quantity rules,
ATTRIBUTE_TO_POPULATE_WITH, casting weights, ATD columns), the MM description rewrite and weight, the mixed
metric / english fastener warning, the fastener rows (layer 99 + BODY refset members, nest block subtracted,
dowel / english-screw / PAINT BLUE names), the checker sheet's UsedRange-relative rows and the GM sheets.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Sequence, Set, Tuple, cast

# Session.Execute does not put the script's folder on sys.path, so the shared modules would not import.
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
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
from ExportStrip import _GFolder  # noqa: E402
from tsg_dialog import Dialog, components_of, title_with_version  # noqa: E402

ufunc_name = "bill-of-material"

BillOfMaterialUcf = "U:\\nxFiles\\UfuncFiles\\BillOfMaterial.ucf"
AtdTemplate = "U:\\nxFiles\\Excel\\atdbom.xlsx"
GmTemplate = "U:\\nxFiles\\Excel\\gm.xlsx"
CheckerTemplate = "U:\\nxFiles\\Excel\\CheckerTemplate.xlsx"

# The dialog's Company items (tools\make-dlx.py); the TSG ones name their template in BillOfMaterial.ucf.
Companies = ["ATS", "CTS", "DTS", "ETS", "RTS", "UGS", "ATD", "GM"]

# RowColumnIndexes
TsgStartRow = 14
AtdStartRow = 5
NameColumn = 1
QtyColumn = 2
DescriptionColumn = 3
MaterialColumn = 4
WeightColumn = 8

# The form's offset after its ATD button: the ATD size columns are 8 + offset.
AtdOffset = 18

# BomProperties column -> CheckProperties column on the checker sheet.
CheckerColumns = {1: 5, 2: 6, 3: 7, 4: 8}

# The ATD purchased materials (hard-coded in BomBuildNxExcelList, not the .ucf list).
AtdPurchasedMaterials = {
    "DAYTON", "MOELLER", "KALLER", "LANE", "MISUMI", "DADCO", "FORWARD", "HYSON", "STANDFAST", "STANDARD LIFTERS",
    "AJACS", "JOLICO", "LAMINA", "DANLY", "DANLY/IEM", "SELFLUBE", "MDL", "SANKYO", "REID", "STOCK", "SYRON",
    "TURCK", "STRUCTURAL", "IMP", "ARGON", "AMCOR", "DESTACO", "BOHLER UDDERHOLM", "BALLUFF", "PUR", "VOESTALPINE",
    "STOCK NPA", "DADCO NPA",
}

FillInPlaceholder = "FILL IN"
NestBlockAssemblyName = "WIRE BURN NEST BLOCK ASSEMBLY"
RefsetBody = "BODY"

# The thread callout the small english screws are ordered by (BomEnglishScrewThreads).
EnglishScrewThreads = {"0004": "#4-40", "0006": "#6-32", "0008": "#8-32", "0010": "#10-24"}

RegexDetail = r"^(?P<customerNum>\d+)-(?P<opNum>\d+)-(?P<detailNum>\d+)$"

_ErrorCannotLaunchDialog = 3520048


class Cell(object):
    """NXExcelData - one cell of the stocklist sheet."""

    def __init__(self, row: int, column: int, data: str) -> None:
        self.row = row
        self.column = column
        self.data = data
        self.green = False


# ---------------------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------------------

def _try_att(obj: NXOpen.NXObject, title: str) -> Optional[str]:
    """__TryGetAtt - the string user attribute, or None when it is not there."""
    try:
        if obj.HasUserAttribute(title, NXOpen.NXObject.AttributeType.String, -1):
            return obj.GetUserAttributeAsString(title, NXOpen.NXObject.AttributeType.String, -1)
    except NXOpen.NXException:
        pass
    return None


def _attributes_titled(obj: NXOpen.NXObject, title: str) -> List[NXOpen.NXObject.AttributeInformation]:
    """The user attributes whose title is title, ignoring case."""
    return [a for a in obj.GetUserAttributes() if a.Title.upper() == title.upper()]


def _read_ucf(path: str) -> Dict[str, List[str]]:
    """Ucf(path) - :KEY: ... :END: sections, skipping blank and // lines."""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as reader:
        lines = [line.rstrip("\r\n") for line in reader]
    lines = [line for line in lines if line.strip() and not line.startswith("//")]
    sections: Dict[str, List[str]] = {}
    index = 0
    while index < len(lines):
        start = lines[index]
        if start.startswith(":") and start.endswith(":") and len(start) > 1 and start != ":END:":
            values = []
            index += 1
            while index < len(lines) and lines[index] != ":END:":
                values.append(lines[index])
                index += 1
            sections[start[1:-1]] = values
        index += 1
    return sections


def _int_or_none(text: str) -> Optional[int]:
    return int(text) if re.match(r"^\d+$", text or "") else None


def _detail_number_or_max(leaf: str) -> int:
    """BomDetailNumberOrMax - the detail number as a sort key; a leaf that is not a detail sorts last."""
    match = re.match(r"^\d+-\d+-(?P<detail>\d+)$", leaf)
    return int(match.group("detail")) if match else sys.maxsize


def _order_by_detail_number(parts: Iterable[NXOpen.Part]) -> List[NXOpen.Part]:
    return sorted(parts, key=lambda p: (_detail_number_or_max(p.Leaf), p.Leaf))


def _is_part_detail(part: NXOpen.BasePart) -> bool:
    return re.match(RegexDetail, part.Leaf) is not None


def _is_fastener_name(name: str) -> bool:
    """string.__IsFastener - a SHCS, dowel or jack screw."""
    return nx.is_shcs(name) or nx.is_dwl(name) or nx.is_jck_screw(name) or nx.is_jck_screw_tsg(name)


def _question(message: str) -> bool:
    return nx.message_box("Bill of Material", NXOpen.NXMessageBox.DialogType.Question, message) == nx.MessageBoxYes


def _descendant_parts(part: NXOpen.Part) -> List[NXOpen.Part]:
    """BasePart.__DescendantParts - the part and every loaded part under it (suppressed included), each once."""
    root = part.ComponentAssembly.RootComponent
    if root is None:
        return [part]
    parts: Dict[str, NXOpen.Part] = {}
    for component in nx.descendants(root, True, True):
        proto = component.Prototype
        if isinstance(proto, NXOpen.Part):
            parts.setdefault(component.DisplayName, proto)
    return list(parts.values())


def _distinct_by_display_name(components: Iterable[NXOpen.Assemblies.Component]) -> List[NXOpen.Assemblies.Component]:
    seen: Set[str] = set()
    result = []
    for component in components:
        if component.DisplayName not in seen:
            seen.add(component.DisplayName)
            result.append(component)
    return result


def _occurrences(display: NXOpen.Part, part: NXOpen.BasePart) -> List[NXOpen.Assemblies.Component]:
    return nx.occurrences_of_part_in(display, part)


def _units(work: NXOpen.Part) -> List[NXOpen.Unit]:
    return [work.UnitCollection.FindObject(name)
            for name in ("SquareInch", "CubicInch", "PoundMass", "Inch", "PoundForce")]


def _measure(body: NXOpen.Body) -> Any:
    """A MeasureBodies (Part.MeasureManager / MeasureBodies are not in the stubs)."""
    work = cast(Any, nx.work_part())
    return work.MeasureManager.NewMassProperties(_units(work), 0.99, [body])


def _AnalysisUnit() -> Any:
    return cast(Any, NXOpen).MeasureBodies.AnalysisUnit


def _layer1_solid(part: NXOpen.Part) -> Optional[NXOpen.Body]:
    """__SolidBodyLayer1OrNull - the single solid body on layer 1, else None."""
    solids = [b for b in part.Bodies if b.IsSolidBody and b.Layer == 1]
    return solids[0] if len(solids) == 1 else None


def _g15(value: float) -> str:
    """double.ToString() on .NET Framework - 15 significant digits."""
    return format(value, ".15g")


# ---------------------------------------------------------------------------------------------------
# Details (BuildComponentList / BomGetChildComponents)
# ---------------------------------------------------------------------------------------------------

def is_name_valid(component: NXOpen.Assemblies.Component, four: bool, three: bool) -> bool:
    """BomIsNameValid - a detail-numbered display name under a 3- or 4-digit component name."""
    if re.match(r"^\d+-\d+-\d+$", component.DisplayName) is None or _int_or_none(component.Name) is None:
        return False
    return (four and len(component.Name) == 4) or (three and len(component.Name) == 3)


def detail_components(display: NXOpen.Part, four: bool, three: bool) -> List[NXOpen.Assemblies.Component]:
    """__LoadedDescendants(BomIsNameValid) - every unsuppressed, loaded detail component, each display name once."""
    found: List[NXOpen.Assemblies.Component] = []

    def walk(component: NXOpen.Assemblies.Component) -> None:
        for child in component.GetChildren():
            if child.IsSuppressed:
                continue
            if is_name_valid(child, four, three) and nx.is_loaded(child):
                found.append(child)
            walk(child)

    root = display.ComponentAssembly.RootComponent
    if root is not None:
        walk(root)
    return _distinct_by_display_name(found)


def is_casting_component(component: NXOpen.Assemblies.Component) -> bool:
    """ButtonLoadCastings_Click - a DESCRIPTION containing CAST."""
    for attribute in _attributes_titled(component, "DESCRIPTION"):
        value = _try_att(component, attribute.Title)
        if value and ("CAST" in value or "cast" in value):
            return True
    return False


# ---------------------------------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------------------------------

def confirm_overwrite(path: str) -> bool:
    """BomConfirmOverwrite"""
    return not os.path.isfile(path) or _question("{} already exists, would you like to overwrite it.".format(path))


def confirm_detail_attributes(parts: Iterable[NXOpen.Part]) -> bool:
    """BomConfirmDetailAttributes - DETAIL NAME, MATERIAL, DESCRIPTION missing, empty or FILL IN prompts."""
    failed = 0
    for part in parts:
        try:
            part_failed = False
            for title in ("DETAIL NAME", "MATERIAL", "DESCRIPTION"):
                value = _try_att(part, title)
                if value is None:
                    nx.print_("WARNING: {} has no {} attribute.".format(part.Leaf, title))
                elif not value.strip():
                    nx.print_("WARNING: {} {} attribute is EMPTY.".format(part.Leaf, title))
                elif value.strip().upper() == FillInPlaceholder:
                    nx.print_("WARNING: {} {} attribute is still \"{}\".".format(part.Leaf, title, FillInPlaceholder))
                else:
                    continue
                part_failed = True
            if part_failed:
                failed += 1
        except Exception as ex:
            nx.print_exception(ex, part.Leaf)

    if failed == 0:
        return True

    return _question(
        "{} part(s) have a DETAIL NAME, MATERIAL or DESCRIPTION attribute that is missing, empty or still \"{}\".\n"
        "See the info window for the list.\n\nDo you want to continue anyway?".format(failed, FillInPlaceholder))


def check_materials(parts: Iterable[NXOpen.Part]) -> bool:
    """BomCheckMaterials - a hard stop on a missing or blank MATERIAL."""
    all_passed = True
    for part in parts:
        try:
            titles = [a.Title for a in _attributes_titled(part, "MATERIAL")]
            if not titles:
                all_passed = False
                nx.print_("{} doesn't have a MATERIAL attribute.".format(part.Leaf))
                continue
            value = _try_att(part, titles[0])
            if value is None:
                all_passed = False
                nx.print_("{} MATERIAL attribute has value of NULL.".format(part.Leaf))
            elif value == "":
                all_passed = False
                nx.print_("{} MATERIAL attribute has value of EMPTY.".format(part.Leaf))
            elif not value.strip():
                all_passed = False
                nx.print_("{} MATERIAL attribute has value of WHITESPACE.".format(part.Leaf))
        except Exception as ex:
            nx.print_exception(ex, part.Leaf)
    return all_passed


def confirm_mixed_fasteners(parts: Iterable[NXOpen.Part]) -> bool:
    """BomCreateStocklist's warning for a detail with both unsuppressed english and metric fasteners."""
    owners = []
    for part in parts:
        root = part.ComponentAssembly.RootComponent
        if not _is_part_detail(part) or root is None:
            continue
        fasteners = [c for c in root.GetChildren() if not c.IsSuppressed and _is_fastener_name(c.DisplayName)]
        metric = [f for f in fasteners if "mm" in f.DisplayName.lower()]
        if metric and len(metric) < len(fasteners):
            owners.append(part)

    if not owners:
        return True

    nx.print_("/////////////////////////////")
    nx.print_("The following parts have both unsuppressed english and metric fasteners")
    for part in owners:
        nx.print_(part.Leaf)
    if not _question("The following parts have both unsuppressed english and metric fasteners do you want to "
                     "continue"):
        return False
    nx.print_("/////////////////////////////")
    return True


# ---------------------------------------------------------------------------------------------------
# Rows (BomBuildNxExcelList)
# ---------------------------------------------------------------------------------------------------

def try_parse_detail_name(display_name: str, four: bool, three: bool) -> Optional[Tuple[str, str, int]]:
    """BomTryParseDetailName - (op, detail, detail value), or None."""
    match = re.match(RegexDetail, display_name)
    if not match:
        return None
    detail = match.group("detailNum")
    if not (four and len(detail) == 4) and not (three and len(detail) == 3):
        return None
    return match.group("opNum"), detail, int(detail)


def quantity(display: NXOpen.Part, part: NXOpen.BasePart, four: bool, three: bool) -> int:
    """BomBuildNxExcelList's quantity: numbered, unsuppressed occurrences (and parents) whose parent is not Empty."""
    count = 0
    for component in _occurrences(display, part):
        name = component.Name
        if not (re.match(r"^\d+-\d+$", name) or (len(name) == 3 and three) or (len(name) == 4 and four)):
            continue
        parent = component.Parent
        if parent is None or parent.IsSuppressed or component.IsSuppressed:
            continue
        if parent.ReferenceSet != nx.RefsetEmpty:
            count += 1
    return count


def build_rows(display: NXOpen.Part, components: List[NXOpen.Assemblies.Component], start_row: int, four: bool,
               three: bool, atd: bool, offset: int, attribute_columns: List[Tuple[str, int]]) -> List[Cell]:
    """BomBuildNxExcelList - one row per detail that writes anything, sorted by detail number."""
    cells: List[Cell] = []
    components = sorted(components, key=lambda c: (_detail_number_or_max(c.DisplayName), c.DisplayName))
    row = start_row

    for i, component in enumerate(components):
        nx.prompt("Building NX Excel List: {} of {}".format(i + 1, len(components)))
        before = len(cells)
        proto = cast(NXOpen.Part, component.Prototype)
        parsed = try_parse_detail_name(component.DisplayName, four, three)

        if parsed is None:
            nx.print_("{} is not a valid detail name".format(component.DisplayName))

        if atd:
            cells.extend(_atd_cells(proto, row, offset))

        if parsed is not None:
            op, detail, number = parsed
            if 0 < number < 10000:
                cells.append(Cell(row, 24 if atd else NameColumn, "{}-{}".format(op, detail)))
                cells.append(Cell(row, 25 if atd else QtyColumn, str(quantity(display, proto, four, three))))

                if not atd:
                    for title, column in attribute_columns:
                        attributes = [a for a in proto.GetUserAttributes() if a.Title.upper() == title.upper()]
                        if len(attributes) == 1:
                            cells.append(Cell(row, column, _try_att(proto, attributes[0].Title) or ""))

                descriptions = _attributes_titled(proto, "DESCRIPTION")
                if len(descriptions) == 1 and "CAST" in (_try_att(proto, descriptions[0].Title) or "").upper():
                    cells.extend(_casting_weight(proto, row, component.DisplayName))
            else:
                nx.print_("{} is not a valid component name".format(component.DisplayName))

        # Only a row that was written to uses up a row number.
        if len(cells) > before:
            row += 1

    return cells


def _atd_cells(proto: NXOpen.Part, row: int, offset: int) -> List[Cell]:
    """The ATD columns: DETAIL NAME, REVISION, and MATERIAL with its size, or a purchased MATERIAL / DESCRIPTION."""
    cells = []
    detail_name = _try_att(proto, "DETAIL NAME")
    if detail_name is not None:
        cells.append(Cell(row, 23, detail_name))
    revision = _try_att(proto, "REVISION")
    if revision is not None:
        cells.append(Cell(row, 35, revision))

    material = _try_att(proto, "MATERIAL")
    if material is None:
        return cells

    if material in AtdPurchasedMaterials:
        cells.append(Cell(row, 33, material))
        description = _try_att(proto, "DESCRIPTION")
        if description is not None:
            cells.append(Cell(row, 34, description))
        return cells

    cells.append(Cell(row, 29, material))
    if detail_name is not None:
        cells.append(Cell(row, 27, detail_name))

    solids = [b for b in proto.Bodies if b.IsSolidBody and b.Layer == 1]
    if len(solids) == 1:
        try:
            box = nx.body_box(solids[0])
            sizes = sorted(abs(d) for d in (box.MaxX - box.MinX, box.MaxY - box.MinY, box.MaxZ - box.MinZ))
            for index, size in enumerate(sizes):
                cells.append(Cell(row, 8 + offset + index, _g15(size)))
        except Exception as ex:
            nx.print_exception(ex, proto.Leaf)
    return cells


def _casting_weight(proto: NXOpen.Part, row: int, display_name: str) -> List[Cell]:
    """A casting's weight (lbf) in the weight column, from its layer-1 solid body."""
    bodies = [b for b in proto.Bodies if b.IsSolidBody and b.Layer == 1]
    if not bodies:
        return []
    if len(bodies) > 1:
        nx.print_("More than one solid body on layer one in casting : {}".format(display_name))
    measure = _measure(bodies[-1])
    try:
        measure.InformationUnit = _AnalysisUnit().PoundInch
        return [Cell(row, WeightColumn, _g15(measure.Weight))]
    finally:
        measure.Dispose()


def apply_mm(cells: List[Cell], folder: _GFolder, round_mm: bool) -> None:
    """BomWriteData's Show MM Dimensions: the weight in kg (column 6) and the size description in mm."""
    names = {c.row: c for c in cells if c.column == 1}
    sizes = {c.row: c for c in cells if c.column == 3}

    for row, name in names.items():
        try:
            part = nx.find_or_open("{}-{}".format(folder.CustomerNumber, name.data))
            body = _layer1_solid(part)
            if body is None:
                continue

            measure = _measure(body)
            try:
                measure.InformationUnit = _AnalysisUnit().KilogramMillimeter
                cells.append(Cell(row, 6, "{:.3f}".format(measure.Mass / 2.2)))
            finally:
                measure.Dispose()

            description = sizes.get(row)
            if description is None:
                continue
            match = re.search(r"(?P<num0>\d+\.\d+) X (?P<num1>\d+\.\d+) X (?P<num2>\d+\.\d+)(?P<append>.*)",
                              description.data)
            if not match:
                continue

            if round_mm:
                box = nx.body_box(body)
                mm = [abs(box.MaxX - box.MinX) * 25.4, abs(box.MaxY - box.MinY) * 25.4,
                      abs(box.MaxZ - box.MinZ) * 25.4]
                mm = sorted(float(int(s)) if abs(s - int(s)) < .001 else float(int(s) + 1) for s in mm)
                description.data = "{:.0f} X {:.0f} X {:.0f}{}".format(mm[0], mm[1], mm[2], match.group("append"))
            else:
                mm = sorted(float(match.group(g)) * 25.4 for g in ("num0", "num1", "num2"))
                description.data = "{:.3f} X {:.3f} X {:.3f}{}".format(mm[0], mm[1], mm[2], match.group("append"))
        except Exception as ex:
            nx.print_exception(ex, str(row))


# ---------------------------------------------------------------------------------------------------
# Fasteners (shared by the TSG and GM sheets)
# ---------------------------------------------------------------------------------------------------

def is_fastener_part(part: NXOpen.BasePart) -> bool:
    """BomIsFastenerPart - anything under the 0Library fasteners folder except jack screws."""
    return part.FullPath.lower().startswith("g:\\0library\\fasteners") and "jck" not in part.Leaf


class _FastenerCounter(object):
    """BomCountedFastenerInstances and its per-run BODY reference set cache."""

    def __init__(self, display: NXOpen.Part) -> None:
        self.display = display
        self._body_members: Dict[int, Set[int]] = {}

    def _body_member_tags(self, owning_part: NXOpen.BasePart) -> Set[int]:
        key = int(owning_part.Tag)
        if key not in self._body_members:
            refset = next((r for r in owning_part.GetAllReferenceSets() if r.Name == RefsetBody), None)
            self._body_members[key] = set() if refset is None else {int(m.Tag) for m in refset.AskAllDirectMembers()}
        return self._body_members[key]

    def counted(self, fastener: NXOpen.BasePart, scope: Optional[NXOpen.Assemblies.Component] = None) -> int:
        """Unsuppressed instances (and parents) on layer 99 in the owning detail and in its BODY reference set."""
        count = 0
        for component in _occurrences(self.display, fastener):
            try:
                parent = component.Parent
                if component.IsSuppressed or (parent is not None and parent.IsSuppressed):
                    continue
                if scope is not None and not _is_under(component, scope):
                    continue
                proto = nx.proto_child_comp(component)
                if proto.Layer != nx.LayerFastener:
                    continue
                if int(proto.Tag) not in self._body_member_tags(proto.OwningPart):
                    continue
                count += 1
            except Exception as ex:
                nx.print_exception(ex, "{} occurrence {}".format(fastener.Leaf, component.Tag))
        return count


def _is_under(component: NXOpen.Assemblies.Component, ancestor: NXOpen.Assemblies.Component) -> bool:
    parent = component.Parent
    while parent is not None:
        if parent.Tag == ancestor.Tag:
            return True
        parent = parent.Parent
    return False


def count_fasteners(display: NXOpen.Part, fasteners: Sequence[NXOpen.BasePart]) -> Dict[str, int]:
    """BomCountFasteners, less the wire burn nest block's (BomSubtractNestBlockFasteners), named by BomFastenerRowNames."""
    ordered = sorted(fasteners, key=lambda p: p.Leaf)

    # The nest block first, with its own cache, as the C# cleared the cache when each count started.
    nest_block = _find_nest_block(display)
    nested: Dict[str, int] = {}
    if nest_block is None:
        nx.print_("No component named \"{}\" in this assembly.".format(NestBlockAssemblyName))
    else:
        counter = _FastenerCounter(display)
        for i, part in enumerate(ordered):
            nx.prompt("{} fasteners -> {} of {}".format(NestBlockAssemblyName, i + 1, len(ordered)))
            count = counter.counted(part, nest_block)
            if count:
                nested[part.Leaf] = nested.get(part.Leaf, 0) + count
        nx.print_("{} ({}) fasteners, subtracted from the fastener rows:".format(
            NestBlockAssemblyName, nest_block.DisplayName))
        if not nested:
            nx.print_("    (none)")
        for key in sorted(nested):
            nx.print_("    {} -> {}".format(key, nested[key]))

    counter = _FastenerCounter(display)
    counts: Dict[str, int] = {}
    for i, part in enumerate(ordered):
        nx.prompt("Fasteners -> {} of {}".format(i + 1, len(ordered)))
        count = counter.counted(part)
        if count:
            key = part.Leaf.replace("-2x", "")
            counts[key] = counts.get(key, 0) + count

    for leaf, value in nested.items():
        key = leaf.replace("-2x", "")
        if key not in counts:
            nx.print_("WARNING: {} is in the {} but not in the job wide fastener count. Not subtracted.".format(
                leaf, NestBlockAssemblyName))
            continue
        remaining = counts[key] - value
        if remaining < 0:
            nx.print_("WARNING: {} counted {} job wide but {} in the {}. Clamped to 0.".format(
                key, counts[key], value, NestBlockAssemblyName))
            remaining = 0
        if remaining == 0:
            del counts[key]
        else:
            counts[key] = remaining

    return fastener_row_names(counts)


def _find_nest_block(display: NXOpen.Part) -> Optional[NXOpen.Assemblies.Component]:
    root = display.ComponentAssembly.RootComponent
    if root is None:
        return None
    return next((c for c in nx.descendants(root) if (c.Name or "").strip().upper() == NestBlockAssemblyName), None)


def fastener_row_names(counts: Dict[str, int]) -> Dict[str, int]:
    """BomFastenerRowNames - english screws get their thread, dowels become pull dowels, the rest PAINT BLUE."""
    rows: Dict[str, int] = {}
    for leaf, count in counts.items():
        dash = leaf.find("-")
        if dash > 0 and leaf[:dash] in EnglishScrewThreads:
            name = EnglishScrewThreads[leaf[:dash]] + leaf[dash:]
        elif "-dwl-" in leaf:
            name = leaf.replace("-dwl-", "-pull-dwl-with-flat-")
            if name.endswith("-025") and name.startswith("10mm-"):
                name = name.replace("-025", "-024")
        else:
            name = "{} PAINT BLUE".format(leaf)
        rows[name] = rows.get(name, 0) + count
    return rows


# ---------------------------------------------------------------------------------------------------
# Excel (BillOfMaterialExcel.ps1, BillOfMaterialVendors.ps1)
# ---------------------------------------------------------------------------------------------------

def _temp_json(prefix: str, payload: object) -> str:
    temp = os.environ.get("TMP") or os.environ.get("TEMP") or "."
    path = os.path.join(temp, "TSG_{}_{}_{}.json".format(prefix, os.getpid(), int(time.time() * 1000)))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return path


def _powershell(script: str, json_path: str) -> Tuple[int, List[str]]:
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File",
         nx.library_file(script, __file__), "-Path", json_path],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    lines = result.stdout.decode("utf-8", errors="replace").splitlines()
    return result.returncode, [line for line in lines if line.strip()]


def write_workbooks(workbooks: List[dict]) -> bool:
    """Runs BillOfMaterialExcel.ps1 over the already-copied workbooks; prints what it reports."""
    nx.prompt("Writing the workbook in Excel.")
    json_path = _temp_json("BillOfMaterial", {"workbooks": workbooks})
    try:
        code, lines = _powershell("BillOfMaterialExcel.ps1", json_path)
    finally:
        try:
            os.remove(json_path)
        except OSError:
            pass
    for line in lines:
        nx.print_(line)
    if code != 0:
        nx.show_error("Excel could not write the bill of material - see the info window.")
    return code == 0


def choose_vendors(cells: Sequence[Cell], folder: _GFolder, ucf: Dict[str, List[str]]) -> Optional[List[str]]:
    """BomShowVendorDialog - the purchased materials in the rows, ticked from previous.txt. None when cancelled."""
    purchased = [m for m in ucf.get("PURCHASED_MATERIALS", []) if m.upper() not in ("PUR", "STOCK")]
    found: List[str] = []
    for cell in cells:
        for material in purchased:
            if cell.data.upper() == material.upper() and cell.data.upper() not in found:
                found.append(cell.data.upper())

    previous = "{}\\previous.txt".format(folder.DirStocklist)
    checked: List[str] = []
    if os.path.isfile(previous):
        with open(previous, "r", encoding="utf-8-sig", errors="replace") as reader:
            checked = [line.rstrip("\r\n") for line in reader]

    chosen: List[str] = []
    if found:
        json_path = _temp_json("BillOfMaterialVendors",
                               {"title": "Select Required Vendors", "items": found, "checked": checked})
        try:
            code, chosen = _powershell("BillOfMaterialVendors.ps1", json_path)
        finally:
            try:
                os.remove(json_path)
            except OSError:
                pass
        if code != 0:
            return None

    with open(previous, "w", encoding="utf-8") as writer:
        writer.write("".join(line + "\r\n" for line in chosen))
    return chosen


def _sheet(name: Optional[str], cells: List[list], green: Optional[List[list]] = None, fmt: bool = False,
           used_range: bool = False) -> dict:
    return {"name": name, "format": fmt, "used_range": used_range, "cells": cells, "green": green or []}


def _excel_text(data: str) -> str:
    """NXExcelData.WriteData's cell text."""
    return data.upper().replace("-ALTER", "")


# ---------------------------------------------------------------------------------------------------
# The stocklists
# ---------------------------------------------------------------------------------------------------

class Options(NamedTuple):
    company: str
    three: bool
    four: bool
    castings: bool
    checker: bool
    mm: bool
    round_mm: bool
    components: List[NXOpen.Assemblies.Component]


def create_stocklist(options: Options) -> None:
    """ButtonCreateBom_Click + BomCreateStocklist + BomWriteData + BomWriteCheckSheet - the TSG and ATD stocklists."""
    display = nx.display_part()
    ucf = _read_ucf(BillOfMaterialUcf)
    atd = options.company == "ATD"
    template = AtdTemplate if atd else ucf["{}_EXCEL".format(options.company)][0]
    start_row = AtdStartRow if atd else TsgStartRow
    folder = _GFolder.create(nx.work_part().FullPath)

    path = "{}\\{}-{}stocklist.xlsx".format(folder.DirStocklist, display.Leaf, "casting-" if options.castings else "")

    if not confirm_overwrite(path):
        nx.mark_cancelled("the overwrite question")
        return

    components = _distinct_by_display_name(c for c in options.components if nx.is_loaded(c))
    parts: List[NXOpen.Part] = []
    for component in components:
        proto = cast(NXOpen.Part, component.Prototype)
        if all(p.Tag != proto.Tag for p in parts):
            parts.append(proto)

    if not parts:
        nx.print_("Didn't find any data")
        return

    if not check_materials(parts) or not confirm_detail_attributes(parts):
        nx.mark_cancelled("the attribute checks")
        return

    attribute_columns = []
    for text in ucf.get("ATTRIBUTE_TO_POPULATE_WITH", []):
        match = re.match(r"^{(?P<title>.+)}:{(?P<column>\d+)}$", text)
        if match:
            attribute_columns.append((match.group("title"), int(match.group("column"))))

    cells = build_rows(display, components, start_row, options.four, options.three, atd,
                       AtdOffset if atd else 0, attribute_columns)
    if not cells:
        nx.print_("Did not find any data to write.")
        return

    vendors = choose_vendors(cells, folder, ucf)
    if vendors is None:
        nx.mark_cancelled("the vendor list")
        return

    if not confirm_mixed_fasteners(parts):
        nx.mark_cancelled("the mixed fastener question")
        return

    os.makedirs(os.path.dirname(path), exist_ok=True)
    shutil.copyfile(template, path)
    max_row = max(c.row for c in cells)

    if options.mm:
        apply_mm(cells, folder, options.round_mm)

    fasteners = count_fasteners(display, [p for p in _descendant_parts(display) if is_fastener_part(p)])
    keys = sorted(fasteners)

    vendor_set = {v.upper() for v in vendors}
    for cell in cells:
        cell.green = cell.data.upper() in vendor_set

    main_cells: List[list] = [[c.row, c.column, _excel_text(c.data)] for c in cells]
    green = [[c.row, c.column] for c in cells if c.green]
    sheets = []

    if atd:
        for i, key in enumerate(keys):
            main_cells.append([max_row + 10 + i, 25, fasteners[key]])
            main_cells.append([max_row + 10 + i, 34, key])
        sheets.append(_sheet(None, main_cells, green, fmt=True))
    else:
        sheets.append(_sheet(None, main_cells, green, fmt=True))
        fastener_cells: List[list] = []
        for i, key in enumerate(keys):
            fastener_cells += [[start_row + i, 2, fasteners[key]], [start_row + i, 3, key], [start_row + i, 4, "PUR"]]
        sheets.append(_sheet("fasteners", fastener_cells))

    workbooks = [{"path": path, "sheets": sheets}]
    checker_path = None

    if options.checker and not options.castings:
        # BomWriteCheckSheet: rows counted from the template's UsedRange, as ExcelApplication.SetCell did.
        checker_path = "{}\\{}-checker-stocklist.xlsx".format(folder.DirStocklist, folder.CustomerNumber.upper())
        if os.path.isfile(checker_path):
            os.remove(checker_path)
        shutil.copyfile(CheckerTemplate, checker_path)
        checker_cells, checker_green = [], []
        for cell in cells:
            column = CheckerColumns.get(cell.column)
            if column is None:
                continue
            row = cell.row - (16 + 7) + 12
            checker_cells.append([row, column, _excel_text(cell.data)])
            if cell.green:
                checker_green.append([row, column])
        workbooks.append({"path": checker_path, "sheets": [_sheet(None, checker_cells, checker_green,
                                                                  used_range=True)]})

    if write_workbooks(workbooks):
        nx.print_("Wrote {}".format(path))
        if checker_path:
            nx.print_("Wrote {}".format(checker_path))
        os.startfile(path)


def gm_quantity(display: NXOpen.Part, part: NXOpen.BasePart, four: bool, three: bool) -> int:
    """BomGmQuantity - occurrences named entirely in digits, of the lengths asked for."""
    return sum(1 for c in _occurrences(display, part)
               if c.Name and c.Name.isdigit() and ((four and len(c.Name) == 4) or (three and len(c.Name) == 3)))


def create_gm_bom(options: Options) -> None:
    """BomCreateGmBom - gm.xlsx (eight part sheets and the fasteners) and the -bom-checker sheet."""
    started = time.monotonic()
    display = nx.display_part()
    folder = _GFolder.create(nx.work_part().FullPath)
    bom_path = "{}\\{}-bom.xlsx".format(folder.DirStocklist, display.Leaf)

    if not confirm_overwrite(bom_path):
        nx.mark_cancelled("the overwrite question")
        return

    all_parts = _descendant_parts(display)
    if not confirm_detail_attributes([p for p in all_parts if _is_part_detail(p)]):
        nx.mark_cancelled("the attribute checks")
        return

    import AssemblyExportDesignData as export  # the C# __IsCasting, already ported there

    sheets: Dict[str, Tuple[Dict[int, NXOpen.Part], str, str]] = {}

    def add(sheet: str, part: NXOpen.Part, desc: str = "DESCRIPTION", mat: str = "MATERIAL") -> None:
        sheets.setdefault(sheet, ({}, desc, mat))[0].setdefault(int(part.Tag), part)

    for name in ("Bom", "Castings", "Nitro Plates", "Burnouts", "Lifter", "GM Pierce Equipment",
                 "CTS Pierce Equipment", "See 3D Data"):
        sheets[name] = ({}, "GM_DESCRIPTION" if name == "GM Pierce Equipment" else "DESCRIPTION",
                        "GM_MATERIAL" if name == "GM Pierce Equipment" else "MATERIAL")

    fasteners: Dict[int, NXOpen.Part] = {}
    lifter: Dict[int, NXOpen.Part] = {}

    for part in all_parts:
        if is_fastener_part(part):
            fasteners[int(part.Tag)] = part
            continue
        if export._is_casting(part):
            add("Castings", part)
        if _is_part_detail(part):
            add("Bom", part)
        if _try_att(part, "GM_DESCRIPTION") is not None and _try_att(part, "GM_MATERIAL") is not None:
            add("GM Pierce Equipment", part)
        if part.Leaf.endswith("-lftr"):
            for lftr in _descendant_parts(part):
                lifter.setdefault(int(lftr.Tag), lftr)
        if _try_att(part, "DESCRIPTION") == "NITROGEN PLATE SYSTEM" and _try_att(part, "MATERIAL") == "DADCO":
            add("Nitro Plates", part)
        if "BURN" in (_try_att(part, "DESCRIPTION") or "").upper():
            add("Burnouts", part)
        if "DAYTON" in (_try_att(part, "MATERIAL") or "").upper():
            add("CTS Pierce Equipment", part)
        if "SEE 3D DATA" in (_try_att(part, "DESCRIPTION") or "").upper():
            add("See 3D Data", part)

    for tag, part in lifter.items():
        if tag not in fasteners:
            add("Lifter", part)

    today = datetime.date.today()
    date = "{}/{}/{}".format(today.month, today.day, today.year)
    user = os.environ.get("USERNAME", "")
    header: List[list] = [[10, 5, date], [11, 5, folder.CustomerNumber], [4, 6, user]]
    prefix = "{}-".format(folder.CustomerNumber)
    workbook_sheets = []
    quantities: Dict[int, int] = {}

    def qty(part: NXOpen.Part) -> int:
        key = int(part.Tag)
        if key not in quantities:
            quantities[key] = gm_quantity(display, part, options.four, options.three)
        return quantities[key]

    for name, (parts, desc_attr, mat_attr) in sheets.items():
        cells = list(header)
        row = 14
        ordered = _order_by_detail_number(parts.values())
        for i, part in enumerate(ordered):
            nx.prompt("{} -> {} of {}".format(name, i + 1, len(ordered)))
            count = qty(part)
            if count == 0:
                continue
            cells += [[row, 1, part.Leaf.replace(prefix, "")], [row, 2, count]]
            desc = _try_att(part, desc_attr)
            if desc is not None:
                cells.append([row, 3, desc])
            mat = _try_att(part, mat_attr)
            if mat is not None:
                cells.append([row, 4, mat])
            row += 1
        workbook_sheets.append(_sheet(name, cells))

    counts = count_fasteners(display, list(fasteners.values()))
    fastener_cells = list(header)
    for i, key in enumerate(sorted(counts)):
        fastener_cells += [[14 + i, 2, counts[key]], [14 + i, 3, key], [14 + i, 4, "PUR"]]
    workbook_sheets.append(_sheet("Fasteners", fastener_cells))

    # The checker sheet: every Bom part with a quantity, from row 7 of the template's active sheet.
    checker_path = "{}\\{}-bom-checker.xlsx".format(folder.DirStocklist, display.Leaf)
    checker_cells: List[list] = []
    row = 7
    for part in _order_by_detail_number(sheets["Bom"][0].values()):
        count = qty(part)
        if count == 0:
            continue
        checker_cells += [[row, 5, part.Leaf.replace(prefix, "")], [row, 6, count]]
        desc = _try_att(part, "DESCRIPTION")
        if desc is not None:
            checker_cells.append([row, 7, desc])
        mat = _try_att(part, "MATERIAL")
        if mat is not None:
            checker_cells.append([row, 8, mat])
        row += 1

    os.makedirs(folder.DirStocklist, exist_ok=True)
    shutil.copyfile(GmTemplate, bom_path)
    shutil.copyfile(CheckerTemplate, checker_path)

    if write_workbooks([{"path": bom_path, "sheets": workbook_sheets},
                        {"path": checker_path, "sheets": [_sheet(None, checker_cells)]}]):
        nx.print_("Wrote {}".format(bom_path))
        nx.print_("Wrote {}".format(checker_path))
        os.startfile(bom_path)

    span = int(time.monotonic() - started)
    nx.prompt("Complete -> {}:{:02d}".format(span // 60, span % 60))


# ---------------------------------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------------------------------

class _BillOfMaterialDialog(Dialog):
    dlx_name = "BillOfMaterial.dlx"

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__()
        # Captured in ok(): the blocks are gone once Launch returns.
        self.options: Optional[Options] = None

    def initialize(self) -> None:
        self.component_filter(self.block("components"))
        self.assembly_scope(self.block("components"))

    def shown(self) -> None:
        # The form ticked both on every open.
        self.block("three_digits").Value = True
        self.block("four_digits").Value = True
        self._refresh()

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        if block in (self.block("company"), self.block("three_digits"), self.block("four_digits"),
                     self.block("castings")):
            self._refresh()
        elif block == self.block("mm"):
            self.block("round_mm").Enable = self.block("mm").Value

    def enable_ok(self) -> bool:
        return self._company() == "GM" or len(self.selected(self.block("components"))) > 0

    def ok(self) -> bool:
        if self._company() != "GM" and not self.selected(self.block("components")):
            self.message("Select at least one detail.", error=True)
            return False
        self.options = Options(
            company=self._company(),
            three=self.block("three_digits").Value,
            four=self.block("four_digits").Value,
            castings=self.block("castings").Value,
            checker=self.block("checker_sheet").Value,
            mm=self.block("mm").Value,
            round_mm=self.block("mm").Value and self.block("round_mm").Value,
            components=components_of(self.selected(self.block("components"))))
        return True

    def _company(self) -> str:
        return str(self.block("company").ValueAsString)

    def _refresh(self) -> None:
        """Shows what the company uses, and fills the details picker with every valid detail (Preselect)."""
        gm = self._company() == "GM"
        for block_id in ("castings", "components", "checker_sheet", "mm", "round_mm"):
            self.block(block_id).Show = not gm
        self.block("round_mm").Enable = self.block("mm").Value
        if gm:
            return
        details = detail_components(nx.display_part(), self.block("four_digits").Value,
                                    self.block("three_digits").Value)
        if self.block("castings").Value:
            details = [c for c in details if is_casting_component(c)]
        self.block("components").SetSelectedObjects(details)


def execute() -> None:
    display = nx.display_part()
    if display is None or display.ComponentAssembly.RootComponent is None:
        nx.show_error("Bill of Material needs an assembly as the display part.")
        return

    title = title_with_version("Bill of Material")
    try:
        dialog = _BillOfMaterialDialog(title)
        accepted = dialog.run()
    except NXOpen.NXException as ex:
        if ex.ErrorCode != _ErrorCannotLaunchDialog:
            raise
        nx.print_exception(ex)
        nx.show_error("NX would not open the {} dialog (error {} - it will not create a dialog from inside a "
                      "callback).\n\nTry running it from File -> Execute -> NX Open rather than from a menu or "
                      "toolbar button.".format(title, _ErrorCannotLaunchDialog))
        return

    if not accepted or dialog.options is None:
        return

    if dialog.options.company == "GM":
        create_gm_bom(dialog.options)
    else:
        create_stocklist(dialog.options)


def main() -> None:
    """The bill-of-material UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
