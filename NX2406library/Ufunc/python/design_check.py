"""
The Python design check: the validator framework, the run and the report - the port of
src\\UFuncs\\DesignCheck\\Validators\\IDesignCheck.cs, DesignCheck\\Result.cs and DesignCheck\\DesignCheckRunner.cs,
plus the validator list (Static.DesignCheckValidators). The Block Styler dialog over it is src\\UFuncs\\DesignCheck.py;
the validators are in the design_check_*.py modules beside this one.

The C# validators build WinForms TreeNodes; here they build Items (text, the NX object it reports on - the TreeNode's
Tag - an optional name and child Items), which the dialog turns into Block Styler tree nodes and the report into text.

    check.check(obj)            -> (Result.Fail, Item)      # Check(obj, out TreeNode node)
    run(display, validators())  -> [CheckRun]               # DesignCheckRunner.Run
    report()                    -> failure count            # DesignCheckRunner.Report

NEVER RUN IN NX. The C# design-check form and design-check-report stay until this is confirmed.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from typing import Any, List, Optional, Sequence, Tuple, Union

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402

import tsg_nx as nx  # noqa: E402


class Result(object):
    """DesignCheck.Result"""
    Pass = "Pass"
    Fail = "Fail"
    Ignore = "Ignore"


class Item(object):
    """
    A WinForms TreeNode as the validators use one: text (TreeNode.Text), obj (TreeNode.Tag - the part, component,
    body, expression, ... it reports on, or None), name (TreeNode.Name - BlockMaterialColor's AddX / AddY / AddZ) and
    children (TreeNode.Nodes). Also what the dialog keeps per tree node.
    """

    def __init__(self, text: str = "", obj: Any = None, name: str = "") -> None:
        self.text = text or ""
        self.obj = obj
        self.name = name or ""
        self.children: List["Item"] = []
        self.parent: Optional["Item"] = None

    def add(self, child: Union[str, "Item"], obj: Any = None) -> "Item":
        """TreeNode.Nodes.Add: a string becomes a new Item (with obj as its Tag); returns the child added."""
        item = Item(child, obj) if isinstance(child, str) else child
        item.parent = self
        self.children.append(item)
        return item

    def add_range(self, children: Sequence["Item"]) -> None:
        """TreeNode.Nodes.AddRange"""
        for child in children:
            self.add(child)

    def remove(self) -> None:
        """TreeNode.Remove"""
        if self.parent is not None:
            self.parent.children.remove(self)
            self.parent = None

    def clear(self) -> None:
        """TreeNode.Nodes.Clear"""
        for child in self.children:
            child.parent = None
        self.children = []

    def root(self) -> "Item":
        item = self
        while item.parent is not None:
            item = item.parent
        return item

    def walk(self) -> List["Item"]:
        """This item and every item under it, depth first."""
        items: List["Item"] = [self]
        for child in self.children:
            items.extend(child.walk())
        return items

    def __repr__(self) -> str:
        return "Item({!r}, {} children)".format(self.text, len(self.children))


class Check(object):
    """
    IDesignCheck. A validator overrides get_objects (what to check in a part) and check (one object: a Result and
    the Item to show, or None). An exception from check is printed and counted as an error by run, never thrown.
    """

    # IDesignCheck.CheckAssemblyPartOnly: True checks only the display part, not every part in its tree.
    assembly_part_only = False

    @property
    def name(self) -> str:
        """check.GetType().Name - the check's node text."""
        return type(self).__name__

    def get_objects(self, part: NXOpen.Part) -> List[Any]:
        raise NotImplementedError

    def check(self, obj: Any) -> Tuple[str, Optional[Item]]:
        raise NotImplementedError


class ListsPassedAndIgnored(Check):
    """
    IListsPassedAndIgnored: run adds a Pass and an Ignore node under the check, each holding a node per part (obj = the
    part) with the check's own node under it; a failing part's node holds the check's node directly, with no Fail node.
    """


class FixesFailures(Check):
    """
    IFixesFailures: a check that can repair its failures. The dialog gives each failing part node under it a menu item
    (fix_text) that calls fix with the obj of every failure node under that part's Fail node, then removes the part
    node - so the check's failure Items must carry the object fix needs.
    """

    @property
    def fix_text(self) -> str:
        raise NotImplementedError

    def fix(self, obj: Any) -> None:
        """Repairs one failure; raises when it cannot."""
        raise NotImplementedError


class CheckRun(object):
    """DesignCheckRunner.CheckRun: one validator's run - its tree, counts and failures as (part leaf, item text)."""

    def __init__(self, check: Check) -> None:
        self.name = check.name
        self.check = check
        self.node = Item(check.name)
        self.passed = 0
        self.failed = 0
        self.ignored = 0
        # Objects whose check raised, plus 1 when the validator itself raised.
        self.errors = 0
        self.failures: List[Tuple[str, str]] = []


def validators(display: Optional[NXOpen.Part] = None) -> List[Check]:
    """
    Static.DesignCheckValidators - the hand-picked set the form runs, in its order. The ones commented out there are
    not ported: LinkBodyParents, SizeDescription, SmartRevisions, Burnouts, CBoreDepths, WireTaperNotes.
    """
    import design_check_assembly as assembly
    import design_check_attributes as attributes
    import design_check_geometry as geometry
    import design_check_material as material

    display = display or nx.display_part()
    return [
        attributes.AttributeCheck(),
        assembly.BrokenLinks(),
        assembly.BushingsAndPins(),
        assembly.CastingChildren(),
        geometry.CastingHalfMoons(),
        assembly.ComponentNames(),
        attributes.DescriptionNXAttribute(display),
        geometry.Dimensions(),
        assembly.FolderLocations(display),
        assembly.InterpartExpressions(),
        geometry.JigJacks(),
        assembly.PositionOverride(),
        geometry.ThirtyPoundCheck(),
        attributes.TimeStamps(),
        attributes.AutoUpdateStatus(),
        attributes.RequiredAttributes(),
        material.TrimSteelMaterial(display),
        material.BlockMaterialColor(),
        attributes.ShcsIncrements(),
    ]


def assembly_parts(display: NXOpen.Part) -> List[NXOpen.Part]:
    """The parts run checks: the display part's __DescendantParts (one prototype per display name, loaded,
    suppressed included, the display part first), or just the display part when it is a piece part."""
    root = nx.root_component(display)
    if root is None:
        return [display]
    return descendant_parts(display)


def descendant_parts(part: NXOpen.BasePart) -> List[NXOpen.Part]:
    """BasePart.__DescendantParts: RootComponent.__Descendants(includeRoot, includeSuppressed), distinct by
    DisplayName (first wins), their prototypes that are Parts."""
    root = nx.root_component(part)
    if root is None:
        return []
    seen = set()
    parts: List[NXOpen.Part] = []
    for component in nx.descendants(root, True, True):
        if component.DisplayName in seen:
            continue
        seen.add(component.DisplayName)
        proto = component.Prototype
        if isinstance(proto, NXOpen.Part):
            parts.append(proto)
    return parts


def is_detail(path_or_leaf: str) -> bool:
    """string.__IsDetail - the leaf (no folder, no extension) is {job}-{op}-{detail}, all digits."""
    leaf = os.path.splitext(os.path.basename(path_or_leaf))[0]
    return re.match(r"^\d+-\d+-\d+$", leaf) is not None


def run(display: NXOpen.Part, checks: Sequence[Check]) -> List[CheckRun]:
    """
    DesignCheckRunner.Run: every check over every part in display's tree (just display for an assembly_part_only
    check). Every exception is printed and counted, never raised. A part only gets a node when something in it failed,
    except under a ListsPassedAndIgnored check, whose Pass and Ignore nodes list every part that passed or was
    ignored, and whose failing part nodes hold the failures directly, with no Fail node between.
    """
    parts_all = assembly_parts(display)
    runs: List[CheckRun] = []

    for check in checks:
        check_run = CheckRun(check)
        runs.append(check_run)

        try:
            parts = [display] if check.assembly_part_only else parts_all
            lists_all = isinstance(check, ListsPassedAndIgnored)
            passed_node = Item(Result.Pass) if lists_all else None
            ignored_node = Item(Result.Ignore) if lists_all else None

            for part in parts:
                part_node = Item(part.Leaf, part)
                failed_node = part_node if lists_all else part_node.add(Result.Fail)

                for obj in check.get_objects(part):
                    try:
                        result, node = check.check(obj)
                        if result == Result.Pass:
                            check_run.passed += 1
                            if passed_node is not None:
                                passed_node.add(listed_part_node(part, node))
                        elif result == Result.Fail:
                            check_run.failed += 1
                            failed_node.add(node if node is not None else Item())
                            check_run.failures.append((part.Leaf, node.text if node is not None else ""))
                        elif result == Result.Ignore:
                            check_run.ignored += 1
                            if ignored_node is not None:
                                ignored_node.add(listed_part_node(part, node))
                    except Exception as ex:
                        check_run.errors += 1
                        nx.print_exception(ex)

                if failed_node.children:
                    check_run.node.add(part_node)

            for listed in (passed_node, ignored_node):
                if listed is not None and listed.children:
                    check_run.node.add(listed)
        except Exception as ex:
            check_run.errors += 1
            nx.print_exception(ex)

    return runs


def listed_part_node(part: NXOpen.Part, node: Optional[Item]) -> Item:
    """A Pass / Ignore entry: the part, so a double click opens it, with the check's own node under it."""
    part_node = Item(part.Leaf, part)
    if node is not None:
        part_node.add(node)
    return part_node


def report_path() -> str:
    """DesignCheckRunner.ReportPath - %TEMP%\\design-check-report.txt (the Python run writes the same file)."""
    return os.path.join(tempfile.gettempdir(), "design-check-report.txt")


def build_report() -> Tuple[str, int]:
    """DesignCheckRunner.BuildReport: the report text and the failure count (-1 when the run raised)."""
    lines: List[str] = []
    failed = -1

    try:
        display = nx.display_part()
        runs = run(display, validators(display))
        failed = sum(r.failed for r in runs)

        lines.append("Design Check: {} ({})".format(display.Leaf, _version()))
        lines.append("{} failed in {} of {} checks.".format(failed, sum(1 for r in runs if r.failed > 0), len(runs)))

        for check_run in runs:
            errors = ", {} errors".format(check_run.errors) if check_run.errors > 0 else ""
            lines.append("{}: {} failed, {} passed, {} ignored{}".format(
                check_run.name, check_run.failed, check_run.passed, check_run.ignored, errors))
            for leaf, text in check_run.failures:
                lines.append("    {}: {}".format(leaf, text))
    except Exception as ex:
        nx.print_exception(ex)
        lines.append("Design Check failed: {}".format(ex))

    return "\n".join(lines) + "\n", failed


def report() -> int:
    """DesignCheckRunner.Report: build_report to the listing window and report_path(); returns the failure count."""
    text, failed = build_report()
    nx.print_(text)

    try:
        with open(report_path(), "w", encoding="utf-8") as writer:
            writer.write(text)
    except Exception as ex:
        nx.print_exception(ex)

    return failed


def _version() -> str:
    try:
        return nx.assembly_file_version()
    except Exception:
        return ""
