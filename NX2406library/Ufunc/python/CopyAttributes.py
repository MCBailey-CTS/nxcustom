"""
Python port of the NX work behind the CopyAttributes form (src\\UFuncs\\CopyAttributes.cs), whose static
methods now live in src\\Static\\CopyAttributes.cs:

- CopyAttributesToComponents (was CopyAttributes_)  -> CopyAttributes.copy_attributes
- CopyAttributesUpdateQuantity / UpdateDetail       -> _update_quantity / _update_detail
- CopyAttributesShouldSkipPart / IsNameValid        -> _should_skip_part / _is_name_valid
- CopyAttributesGetChildComponents                  -> _get_child_components
- CopyAttributesGetOneComponentOfMany               -> _get_one_component_of_many

**Wired (2026-10-21)**: buttonCopyApply_Click calls copy_attributes (see below). **Never run in NX.**

Not ported: CopyAttributesInputFromUcf. It only reads the .ucf lists that fill the form's SHOP / SHOP 1 NAME /
UNITS combos - no NX work, and the form stays C#. The selection (Select / Select All) also stays C#; the
Select All gather (_get_child_components + _get_one_component_of_many) is ported for when that button's
post-pick work moves, but no entry point calls it yet.

buttonCopyApply_Click calls
    PythonLibrary.Execute("CopyAttributes.py", "CopyAttributes", "copy_attributes",
        _selectedComponents.Cast<TaggedObject>().ToArray(),
        attributes.Select(a => a.Title).ToArray(), chkUpdate4Views.Checked);
NXObject.AttributeInformation cannot cross Session.Execute, so the attributes go across by title and are
re-read from the display part here (see copy_attributes).
"""

from __future__ import annotations

import ntpath
import os
import re
import sys
from typing import List, Optional, Sequence, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402

import tsg_nx as nx  # noqa: E402

# Globals.cs regexes behind string.__IsAssemblyHolder (all matched with RegexOptions.IgnoreCase).
_RegexLsh = r"^(?P<customerNum>\d+)-(?P<opNum>\d+)-lsh$"
_RegexUsh = r"^(?P<customerNum>\d+)-(?P<opNum>\d+)-ush$"
_RegexLwr = r"^(?P<customerNum>\d+)-(?P<opNum>\d+)-lwr$"
_RegexUpr = r"^(?P<customerNum>\d+)-(?P<opNum>\d+)-upr$"
_RegexLsp = r"^(?P<customerNum>\d+)-(?P<opNum>\d+)-lsp(?P<extraOpNum>\d+)?.*$"
_RegexUsp = r"^(?P<customerNum>\d+)-(?P<opNum>\d+)-usp(?P<extraOpNum>\d+)?.*$"
_RegexOp000Holder = r"^(?P<customerNum>\d+)-(?P<opNum>\d+)-000$"

# string.__TryAskDetailNumber / __AskDetailNumber
_RegexDetailNumber = r"^\d+-\d+-(?P<detail>\d+)$"

_Int32Max = 2147483647


# ---------------------------------------------------------------------------------------------------
# Private ports of the Globals.cs string helpers the copy uses (not in tsg_nx yet)
# ---------------------------------------------------------------------------------------------------

def _file_name_without_extension(path: str) -> str:
    """Path.GetFileNameWithoutExtension - Windows separators, like .NET."""
    return ntpath.splitext(ntpath.basename(path))[0]


def _is_assembly_holder(path_or_leaf: str) -> bool:
    """string.__IsAssemblyHolder"""
    s = _file_name_without_extension(path_or_leaf) if "\\" in path_or_leaf else path_or_leaf
    s = s.upper()
    return (any(re.search(pattern, s, re.IGNORECASE) for pattern in
                (_RegexLsh, _RegexUsh, _RegexLwr, _RegexUpr, _RegexLsp, _RegexUsp, _RegexOp000Holder))
            or "UPPER" in s
            or "LOWER" in s)


def _try_ask_detail_number(path_or_leaf: str) -> Optional[str]:
    """string.__TryAskDetailNumber - the detail number, or None where the C# returns false."""
    leaf = path_or_leaf
    if "\\" in path_or_leaf or "/" in path_or_leaf:
        leaf = _file_name_without_extension(path_or_leaf)
    match = re.search(_RegexDetailNumber, leaf)
    return match.group("detail") if match else None


def _ask_detail_number(file: str) -> str:
    """string.__AskDetailNumber - raises where the C# throws FormatException."""
    match = re.search(_RegexDetailNumber, _file_name_without_extension(file))
    if not match:
        raise ValueError("Could not find detail number.")
    return match.group("detail")


def _cs_int_try_parse(text: str) -> bool:
    """int.TryParse (invariant enough for a \\d+ capture): ASCII digits with optional sign/whitespace, in Int32 range."""
    if not re.fullmatch(r"\s*[+-]?[0-9]+\s*", text):
        return False
    return -_Int32Max - 1 <= int(text) <= _Int32Max


# ---------------------------------------------------------------------------------------------------
# Ported Static methods
# ---------------------------------------------------------------------------------------------------

def _should_skip_part(part: NXOpen.BasePart) -> bool:
    """Static.CopyAttributesShouldSkipPart"""
    return ("strip" in part.Leaf.lower()
            or "layout" in part.Leaf.lower()
            or "press" in part.Leaf.lower()
            or _is_assembly_holder(part.Leaf))


def _update_quantity(part: NXOpen.BasePart) -> None:
    """Static.CopyAttributesUpdateQuantity - QTY = unsuppressed occurrences under the display part with a
    3/4-character name whose owning component isn't on the Empty reference set."""
    part_occs, _count = nx.ufsession_.Assem.AskOccsOfPart(nx.display_part().Tag, part.Tag)

    quantity = 0
    for tag in part_occs:
        component = cast(NXOpen.Assemblies.Component, nx.tagged_object(tag))
        if (component.IsSuppressed is False
                and (len(component.Name) == 3 or len(component.Name) == 4)
                and component.OwningComponent.ReferenceSet != "Empty"):
            quantity += 1

    part.SetUserAttribute("QTY", -1, "{}".format(quantity), NXOpen.Update.Option.Later)


def _update_detail(part: NXOpen.BasePart, detail: str) -> None:
    """Static.CopyAttributesUpdateDetail"""
    if not _cs_int_try_parse(detail):
        return

    # if (compNumber <= 0 || compNumber >= 1000)
    #     return;

    part.SetUserAttribute("DETAIL NUMBER", -1, detail, NXOpen.Update.Option.Later)


def _is_name_valid(comp: NXOpen.Assemblies.Component) -> bool:
    """Static.CopyAttributesIsNameValid"""
    # Revision 1.3 - 2017 - 06 - 26
    # Changed IsNameValid method so that it can include different op numbers
    return (re.search(r"^([0-9]{4,})-([0-9]{3})-([0-9]{3,4}|lsh|ush|lsp|usp|lwr|upr)$", comp.DisplayName.lower())
            is not None
            and not comp.DisplayName.endswith("000"))


def _get_child_components(assembly: NXOpen.Assemblies.Component,
                          child_components: List[NXOpen.Assemblies.Component]) -> None:
    """
    Static.CopyAttributesGetChildComponents - adds every valid, loaded (or quietly opened) descendant to
    child_components, recursing through invalid names; a suppressed valid one is only printed.
    """
    for child in assembly.GetChildren():
        if child.IsSuppressed is not False:
            if not _is_name_valid(child):
                continue

            nx.print_("{} is suppressed".format(child.DisplayName))
            continue

        if not _is_name_valid(child):
            _get_child_components(child, child_components)
            continue

        instance = nx.ufsession_.Assem.AskInstOfPartOcc(child.Tag)

        if instance == 0:
            continue

        # The pyd docstring gives AskPartNameOfChild's rtype as "list of str"; accept either a str or a list.
        part_name_result = nx.ufsession_.Assem.AskPartNameOfChild(instance)
        part_name = part_name_result if isinstance(part_name_result, str) else part_name_result[0]

        if nx.ufsession_.Part.IsLoaded(part_name) == 1:
            child_components.append(child)
            _get_child_components(child, child_components)
            continue

        # pyd: AskFileExist(fileSpec) -> int status (0 = exists).
        status = nx.ufsession_.Cfi.AskFileExist(part_name)

        if status != 0:
            continue

        # pyd: OpenQuiet(partName) -> (part, errorStatus); part is None (or the null tag) on failure.
        part_open, _load_status = nx.ufsession_.Part.OpenQuiet(part_name)

        if not part_open:
            continue

        child_components.append(child)
        _get_child_components(child, child_components)


def _get_one_component_of_many(
        comp_list: Sequence[NXOpen.Assemblies.Component]) -> Optional[List[NXOpen.Assemblies.Component]]:
    """Static.CopyAttributesGetOneComponentOfMany - first component per DisplayName. Raises on an empty list,
    like the C# compList[0]."""
    one_comp = [comp_list[0]]

    for comp in comp_list:
        if next((c for c in one_comp if c.DisplayName == comp.DisplayName), None) is None:
            one_comp.append(comp)

    return one_comp if len(one_comp) != 0 else None


def _attributes_by_title(part: NXOpen.BasePart, titles: Sequence[str]) -> List[NXOpen.NXObject.AttributeInformation]:
    """
    The display part's attributes whose Title is in titles, in GetUserAttributes order - the order the form's
    list box shows them in, so the same order the C# applies them in.
    """
    wanted = set(titles)
    return [info for info in part.GetUserAttributes() if info.Title in wanted]


class CopyAttributes(object):

    @staticmethod
    def copy_attributes(selected_components: Sequence[NXOpen.TaggedObject], titles: Sequence[str],
                        update_4_views: bool) -> None:
        """
        Static.CopyAttributesToComponents. selected_components is the form's _selectedComponents and
        update_4_views its chkUpdate4Views.Checked.

        Difference: the C# gets the AttributeInformation values the list box captured when it was last
        refreshed; here they are re-read from the display part by title at run time. The form refreshes the
        list after every edit it makes, so the values only differ if the display part's attributes were
        changed outside the form since then.
        """
        attributes = _attributes_by_title(nx.display_part(), list(titles or []))
        comps = nx.distinct_by(
            [cast(NXOpen.Assemblies.Component, c) for c in (selected_components or [])],
            lambda c: c.DisplayName)
        mark = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "copy-attributes")

        with nx.display_part_reset():
            for i, comp in enumerate(comps):
                nx.prompt("{} of {} -> {}".format(i, len(comps), comp.DisplayName))

                try:
                    part = comp.Prototype

                    if _should_skip_part(part):
                        continue

                    for attribute in attributes:
                        # SetUserAttribute(AttributeInformation, Update.Option) overload - not confirmed in Python.
                        part.SetUserAttribute(attribute, NXOpen.Update.Option.Later)

                    _update_quantity(part)

                    if _try_ask_detail_number(comp.DisplayName) is not None:
                        _update_detail(part, _ask_detail_number(comp.DisplayName))

                except Exception as ex:
                    nx.print_exception(ex)

        nx.session_.UpdateManager.DoUpdate(mark)

        mark = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "copy-attributes")

        if update_4_views:
            with nx.display_part_reset():
                for i, comp in enumerate(comps):
                    nx.prompt("{} of {} -> {}".format(i, len(comps), comp.DisplayName))

                    try:
                        # Prototype is typed BasePart; the drafting collections are on Part (as in the C#).
                        part = cast(NXOpen.Part, comp.Prototype)

                        if _should_skip_part(part):
                            continue

                        for drawing in list(part.DraftingDrawingSheets):
                            # if (!drawing.IsOutOfDate)
                            #     continue;

                            nx.set_display_part(nx.prototype(comp))
                            nx.session_.ApplicationSwitchImmediate("UG_APP_DRAFTING")

                            nx.display_part().Drafting.EnterDraftingApplication()

                            nx.display_part().Views.WorkView.UpdateCustomSymbols()
                            drawing.Open()

                            part.DraftingViews.UpdateSheetsAndViews([nx.display_part().Views.WorkView])

                            nx.session_.ApplicationSwitchImmediate("UG_APP_MODELING")

                            nx.display_part().Drafting.ExitDraftingApplication()
                    except Exception as ex:
                        nx.print_exception(ex)

        nx.session_.UpdateManager.DoUpdate(mark)
        nx.prompt("Complete")
