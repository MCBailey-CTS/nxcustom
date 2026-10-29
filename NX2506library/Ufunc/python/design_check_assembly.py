"""
The Python design check's assembly / structure validators: wave links, component names, folder locations, interpart
expressions, position overrides, guide suppliers and casting lift lugs. The framework they plug into is
design_check.py beside this module (design_check.validators() builds them).

Ported from (src\\UFuncs\\DesignCheck\\Validators\\):
  - BrokenLinks.cs                       -> BrokenLinks
  - ComponentNames.cs                    -> ComponentNames (the dead Validate(Part), which only throws, is not ported)
  - FolderLocations.cs                   -> FolderLocations
  - InterpartExpressions.cs              -> InterpartExpressions
  - PositionOverride.cs                  -> PositionOverride
  - BushingsAndPins.cs                   -> BushingsAndPins
      AttributeValue / Contains          -> _attribute_value / _contains
  - CastingChildren.cs                   -> CastingChildren (its unused PartNode TreeNode subclass is not ported)
  - ExtractFace.__IsLinkedBody / __IsBroken -> tsg_nx.is_linked_body / tsg_nx.is_link_broken
  - Component.__Descendants()            -> tsg_nx.descendants(root) (include root, skip suppressed and unloaded)
  - BasePart.__Children / __DescendantParts -> tsg_nx.children / design_check.descendant_parts
  - Component.__Prototype                -> tsg_nx.prototype
  - string.__TryAskDetailNumber          -> _try_ask_detail_number (None where the C# returns false)
  - NXObject.__OwningPart                -> _owning_part
  - GFolder.Create                       -> ExportStrip._GFolder.create
  - new GFolder(Part)                    -> _GFolderOfPart (the C# constructor is empty: DirJob stays null)

Differences from the C#:
  - FolderLocations keeps the C# quirk: `new GFolder(part)` has an empty body, so its DirJob is always null and every
    part outside G:\\0Library\\, G:\\0Press\\ and W:\\ fails, wherever it is. _GFolderOfPart reproduces that (DirJob
    None) rather than guessing what the constructor was meant to do.
  - FolderLocations(display) lets _GFolder.create raise (a plain ValueError / IndexError where the C# threw
    ArgumentException / IndexOutOfRangeException); as in the C#, a display part that is not in a job folder makes
    the constructor - so design_check.validators() - raise.
  - InterpartExpressions' constructor builds a GFolder from the work part and swallows any failure, as the C# does;
    the folder is never read (the C# Folder property and _hasGfolder are unused), so it is kept only for parity.
    Check builds a GFolder from the expression's owning part and lets its exception propagate, as the C# did.
  - BushingsAndPins sorts with Python's ordinal str ordering keyed (lower, swapcase) - case-insensitive with
    lowercase first - as an approximation of .NET's culture-sensitive default OrderBy (which also ignores some
    punctuation such as hyphens). Distinct(OrdinalIgnoreCase) keeps the first spelling per str.lower().
  - ComponentNames keeps the C# quirk that it can never fail: __TryAskDetailNumber only matches
    ^\\d+-\\d+-(?<detail>\\d+)$, so a matching name always ends with "-{detail}"; everything else is Ignore.
  - PositionOverride and ComponentNames check the root component too (C# __Descendants() includes the root).
  - NXOpen Python APIs not in the stubs, reached through Any: Expression.IsInterpartExpression,
    Expression.GetInterpartExpressionNames() (C# out params -> a (partName, expressionName) tuple),
    Component.GetPositionOverrideType(), NXOpen.Assemblies.PositionOverrideType.Explicit and
    NXObject.AttributeInformation.StringValue.

NEVER RUN IN NX. The C# validators stay until this is confirmed.
"""

from __future__ import annotations

import ntpath
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

# In the source tree ExportStrip.py is in the sibling src\UFuncs folder; deployed, everything is in one folder.
_shared_ufuncs = os.path.join(os.path.dirname(_here), "UFuncs")
if os.path.isdir(_shared_ufuncs) and _shared_ufuncs not in sys.path:
    sys.path.insert(1, _shared_ufuncs)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.Features  # noqa: E402

import tsg_nx as nx  # noqa: E402
import design_check  # noqa: E402
from design_check import Check, Item, Result  # noqa: E402
import ExportStrip as exportstrip  # noqa: E402


# ---------------------------------------------------------------------------------------------------
# Helpers (C# extension methods with no port in tsg_nx)
# ---------------------------------------------------------------------------------------------------

def _try_ask_detail_number(path_or_leaf: str) -> Optional[str]:
    """string.__TryAskDetailNumber - the detail number, or None where the C# returns false."""
    leaf = path_or_leaf
    if "\\" in path_or_leaf or "/" in path_or_leaf:
        # Path.GetFileNameWithoutExtension
        leaf = ntpath.splitext(ntpath.basename(path_or_leaf))[0]
    match = re.match(r"^\d+-\d+-(?P<detail>\d+)$", leaf)
    return match.group("detail") if match else None


def _owning_part(obj: NXOpen.NXObject) -> NXOpen.Part:
    """NXObject.__OwningPart - (Part)OwningPart."""
    return cast(NXOpen.Part, obj.OwningPart)


def _root_descendants(part: NXOpen.Part) -> List[NXOpen.Assemblies.Component]:
    """part.ComponentAssembly.RootComponent?.__Descendants().ToArray() ?? new Component[0]"""
    root = nx.root_component(part)
    return list(nx.descendants(root)) if root is not None else []


class _GFolderOfPart(object):
    """new GFolder(Part) - the C# constructor's body is empty, so DirJob and CustomerNumber stay null."""

    def __init__(self, part: NXOpen.Part) -> None:
        self.DirJob: Optional[str] = None
        self.CustomerNumber: Optional[str] = None


# ---------------------------------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------------------------------

class BrokenLinks(Check):
    """Fails each linked body (a LINKED_BODY ExtractFace) in the part whose wave link is broken."""

    assembly_part_only = False

    def get_objects(self, part: NXOpen.Part) -> List[Any]:
        return [extract for extract in part.Features
                if isinstance(extract, NXOpen.Features.ExtractFace) and nx.is_linked_body(extract)]

    def check(self, obj: Any) -> Tuple[str, Optional[Item]]:
        linked_body = cast(NXOpen.Features.ExtractFace, obj)

        node = Item(linked_body.GetFeatureName(), linked_body)

        if nx.is_link_broken(linked_body):
            return Result.Fail, node

        return Result.Pass, node


class ComponentNames(Check):
    """Each component under the part's root (root included): a {job}-{op}-{detail} display name must end with
    -{detail}; any other name is ignored."""

    assembly_part_only = False

    def get_objects(self, part: NXOpen.Part) -> List[Any]:
        return list(_root_descendants(part))

    def check(self, obj: Any) -> Tuple[str, Optional[Item]]:
        component = cast(NXOpen.Assemblies.Component, obj)

        node = Item(component.DisplayName, component)

        display_name = component.DisplayName.lower()

        detail = _try_ask_detail_number(display_name)
        if detail is None:
            return Result.Ignore, node

        return (Result.Pass if display_name.endswith("-{}".format(detail)) else Result.Fail), node


class FolderLocations(Check):
    """
    Checks every part contained within the assembly is being pulled from a valid location: G:\\0Library\\,
    G:\\0Press\\ and W:\\ pass, anything else must be in the assembly part's job folder.
    """

    assembly_part_only = False

    def __init__(self, assembly_part: NXOpen.Part) -> None:
        self._folder = exportstrip._GFolder.create(assembly_part.FullPath)

    def get_objects(self, part: NXOpen.Part) -> List[Any]:
        return [part]

    def check(self, obj: Any) -> Tuple[str, Optional[Item]]:
        part = cast(NXOpen.Part, obj)

        node = Item(part.Leaf, part)

        path = part.FullPath.lower()

        # sql
        if path.startswith("g:\\0library\\"):
            return Result.Pass, node

        # sql
        if path.startswith("g:\\0press\\"):
            return Result.Pass, node

        # sql
        if path.startswith("w:\\"):
            return Result.Pass, node

        folder = _GFolderOfPart(part)

        return (Result.Pass if folder.DirJob == self._folder.DirJob else Result.Fail), node


class InterpartExpressions(Check):
    """Each interpart expression in the part must come from a part named {customer number}-..., the customer
    number of the expression's own part's job folder; other expressions are ignored."""

    assembly_part_only = False

    def __init__(self) -> None:
        self._has_gfolder = True
        self._folder: Optional[exportstrip._GFolder] = None
        try:
            # Will try and construct a GFolder from the parent assembly.
            self._folder = exportstrip._GFolder.create(nx.work_part().FullPath)
        except Exception:
            self._has_gfolder = False

    def get_objects(self, part: NXOpen.Part) -> List[Any]:
        return list(part.Expressions)

    def check(self, obj: Any) -> Tuple[str, Optional[Item]]:
        exp = cast(Any, obj)

        node = Item(exp.Name, exp)

        if not exp.IsInterpartExpression:
            return Result.Ignore, node

        part_name, _ = exp.GetInterpartExpressionNames()

        folder = exportstrip._GFolder.create(_owning_part(exp).FullPath)

        if str(part_name).startswith("{}-".format(folder.CustomerNumber)):
            return Result.Pass, node

        return Result.Fail, node


class PositionOverride(Check):
    """Each component under the part's root (root included) passes when its position override type is Explicit."""

    assembly_part_only = False

    def get_objects(self, part: NXOpen.Part) -> List[Any]:
        return list(_root_descendants(part))

    def check(self, obj: Any) -> Tuple[str, Optional[Item]]:
        component = cast(NXOpen.Assemblies.Component, obj)

        node = Item(component.Name, component)

        explicit = cast(Any, NXOpen.Assemblies).PositionOverrideType.Explicit

        return (Result.Pass if cast(Any, component).GetPositionOverrideType() == explicit else Result.Fail), node


_LibraryPathTitle = "LibraryPath"
_MaterialTitle = "MATERIAL"
_GuideFolders = ("GuideBushings", "GuidePins")


def _sort_key(text: str) -> Tuple[str, str]:
    """An approximation of .NET's culture-sensitive string order: ignoring case, lowercase first on a tie."""
    return text.lower(), text.swapcase()


class BushingsAndPins(Check):
    """
    Fails an assembly whose guide pins and guide bushings come from different suppliers, so a pin may not fit its
    bushing. A guide part is any part whose LibraryPath attribute names GuideBushings or GuidePins, and its MATERIAL
    attribute holds the supplier or standard (Danly, NAAMS, Misumi, Sankyo), not a steel.
      - The main guides and the stripper guides (a Stripper library folder) are compared separately: each set must be
        one supplier, but the two may differ.
      - Attribute titles are matched ignoring case, values ignoring case and surrounding blanks.
      - A guide part with no MATERIAL value fails.
      - An assembly with no guide parts is ignored.
    One result for the whole display assembly.
    """

    assembly_part_only = True

    def get_objects(self, part: NXOpen.Part) -> List[Any]:
        return [part]

    def check(self, obj: Any) -> Tuple[str, Optional[Item]]:
        display = cast(NXOpen.Part, obj)

        # A piece part has no root component, so its tree is just itself.
        parts = [display] if nx.root_component(display) is None else design_check.descendant_parts(display)

        # (part, set, material)
        guides: List[Tuple[NXOpen.Part, str, str]] = []
        for part in parts:
            path = _attribute_value(part, _LibraryPathTitle)
            if not any(_contains(path, folder) for folder in _GuideFolders):
                continue
            guides.append((part,
                           "stripper guides" if _contains(path, "Stripper") else "main guides",
                           _attribute_value(part, _MaterialTitle)))

        if not guides:
            return Result.Ignore, Item("no guide pins or bushings", display)

        node = Item("", display)
        summaries: List[str] = []
        failed = False

        sets: Dict[str, List[Tuple[NXOpen.Part, str, str]]] = {}
        for guide in guides:
            sets.setdefault(guide[1], []).append(guide)

        for key in sorted(sets, key=_sort_key):
            members = sets[key]

            distinct: Dict[str, str] = {}
            for _, _, material in members:
                if len(material) > 0 and material.lower() not in distinct:
                    distinct[material.lower()] = material
            materials = sorted(distinct.values(), key=_sort_key)

            any_missing = any(len(material) == 0 for _, _, material in members)
            text = "{}: {}".format(key, "no MATERIAL" if len(materials) == 0 else ", ".join(materials)) \
                + (", some without MATERIAL" if any_missing and len(materials) > 0 else "")

            summaries.append("{} ({})".format(text, len(members)))

            if len(materials) <= 1 and not any_missing:
                continue

            failed = True
            set_node = Item(text)

            for part, _, material in sorted(members, key=lambda g: (_sort_key(g[2]), _sort_key(g[0].Leaf))):
                set_node.add(Item("{}: {}".format(part.Leaf, "MATERIAL missing" if len(material) == 0 else material),
                                  part))

            node.add(set_node)

        node.text = ("mixed guide suppliers - " if failed else "") + "; ".join(summaries)

        return (Result.Fail if failed else Result.Pass), node


def _attribute_value(part: NXOpen.Part, title: str) -> str:
    """The trimmed string value of the part's attribute titled title, ignoring case; "" when there is none."""
    for attribute in part.GetUserAttributes():
        if attribute.Type != NXOpen.NXObject.AttributeType.String:
            continue
        if attribute.Title.lower() != title.lower():
            continue
        value = (cast(Any, attribute).StringValue or "").strip()
        if len(value) > 0:
            return value
    return ""


def _contains(text: str, value: str) -> bool:
    """text.IndexOf(value, OrdinalIgnoreCase) >= 0"""
    return value.lower() in text.lower()


class CastingChildren(Check):
    """A part with children fails when a loaded LiftLugs child (not on the Empty reference set) is on Entire Part;
    a piece part, or an assembly with no children, is ignored."""

    assembly_part_only = False

    def get_objects(self, part: NXOpen.Part) -> List[Any]:
        return [part]

    def check(self, obj: Any) -> Tuple[str, Optional[Item]]:
        part = cast(NXOpen.Part, obj)

        node = Item(part.Leaf, part)

        if nx.root_component(part) is None:
            return Result.Ignore, node

        if len(nx.children(part)) == 0:
            return Result.Ignore, node

        lift_lugs = [child for child in nx.children(part)
                     if isinstance(child.Prototype, NXOpen.Part)
                     # sql
                     and "LiftLugs" in nx.prototype(child).FullPath
                     and child.ReferenceSet != "Empty"]

        if all(child.ReferenceSet != "Entire Part" for child in lift_lugs):
            return Result.Pass, node

        return Result.Fail, node
