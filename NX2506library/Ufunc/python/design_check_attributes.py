"""
The design-check validators that read attributes, the AutoSize UDO status, linked-body timestamps and SHCS
lengths - ports of src\\UFuncs\\DesignCheck\\Validators\\AttributeCheck.cs, RequiredAttributes.cs,
DescriptionNXAttribute.cs, AutoUpdateStatus.cs, TimeStamps.cs and ShcsIncrements.cs over the design_check.Check
contract (src\\python\\design_check.py).

Ported from:
  - AttributeCheck                               -> AttributeCheck
  - AttributeCheck.CheckAutoUpdate               -> AttributeCheck._check_auto_update
  - AttributeCheck.CheckRequiredAttribute        -> AttributeCheck._check_required_attribute
  - AttributeCheck.AutoSizeUdoOrNull / AutoSizeUdoClass -> AttributeCheck._auto_size_udo_or_null / _auto_size_udo_class
  - RequiredAttributes                           -> RequiredAttributes
  - DescriptionNXAttribute                       -> DescriptionNXAttribute
  - AutoUpdateStatus                             -> AutoUpdateStatus
  - TimeStamps                                   -> TimeStamps (AskString -> ask_string)
  - ShcsIncrements                               -> ShcsIncrements
  - Extensions.AutoUpdateAttribute               -> AUTO_UPDATE_ATTRIBUTE
  - NXObject.__TryGetAtt                         -> _try_get_att
  - Extensions.__UdoAutoSizeClass                -> _udo_auto_size_class
  - BasePart.__UdoAutoSizeOrNull                 -> _udo_auto_size_or_null
  - BasePart.__IsUdoAutoSize                     -> _is_udo_auto_size
  - BasePart.__UdoAutoSizeUpdateStatus()         -> _udo_auto_size_update_status
  - BasePart.__TryUdoAutoSize                    -> _try_udo_auto_size
  - ExtractFace.__IsFixedTimeStamp               -> _is_fixed_time_stamp
  - string.__IsOffIncrementShcs                  -> _is_off_increment_shcs
  - string.__IsDetail                            -> design_check.is_detail
  - NXObject.__HasAttribute / __GetAttribute     -> nx.has_attribute / nx.get_attribute
  - ExtractFace.__IsLinkedBody                   -> nx.is_linked_body

Differences from the C#:
  - The UdoAutoSizeComponent class cannot be registered from Python. Where the C# (__UdoAutoSizeClass and
    AttributeCheck.AutoSizeUdoClass) calls AutoSizeComponent.initializeUDO on NX error 1535022 and looks the class
    up again, this port treats the class as missing: every part then has no AutoSize UDO, so AttributeCheck and
    AutoUpdateStatus check nothing in a session where the C# library never registered it. (In the C# the freshly
    registered class would also find no UDOs on parts loaded before, so the outcome should mostly be the same.)
  - _udo_auto_size_class lets any other NXException escape, like the C# __UdoAutoSizeClass; AutoUpdateStatus's
    get_objects therefore raises out of the part loop (the runner prints it and counts one validator error), as the
    C# GetObjects would.
  - _try_udo_auto_size catches every Exception (the C# catch (Exception)); the C# __UdoAutoSizeUpdateStatus's
    ArgumentOutOfRangeException / "not a UdoAutoSizeComponent" NXException become a ValueError there.
  - _is_off_increment_shcs: .NET Path.GetFileNameWithoutExtension on a name holding "\\" is done with ntpath, and
    the .NET named groups (?<mm>...) are Python's (?P<mm>...). int.Parse of a long digit run cannot overflow in
    Python (the C# would throw OverflowException for an absurd length).
  - String comparisons: C# string.Equals(..., OrdinalIgnoreCase) / ToUpper() become .lower() / .upper();
    string.IsNullOrWhiteSpace becomes "not value.strip()" (None, from a stub-less attribute API, also counts as
    empty).
  - DescriptionNXAttribute: UFAssem.AskOccsOfPart returns (occurrence tags, count) in NXOpen Python (as
    CloneStrip.py / CopyAttributes.py unpack it); each tag becomes its Component through
    NXOpen.TaggedObjectManager.GetTaggedObject (nx.tagged_object), for Tag.__ToTaggedObject. Kept from the C#: the
    "Ignored" node is always added and always empty, the C# typo "eqaul" in its message, the exact (case-sensitive)
    DESCRIPTION comparison, and node.add on the part node before returning Ignore.
  - TimeStamps: __IsFixedTimeStamp builds an ExtractFaceBuilder in the feature's OwningPart and destroys it in a
    finally (sess.UsingBuilderDestroyer). Kept from the C#: suppressed linked bodies are checked too (the
    suppressed filter is only in the commented-out AskNXObjects).
  - get_objects returns plain lists (C# TaggedObject[]).

NEVER RUN IN NX. The C# validators stay until this is confirmed.
"""

from __future__ import annotations

import ntpath
import os
import re
import sys
from typing import Any, List, Optional, Tuple, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.Features  # noqa: E402
import NXOpen.UserDefinedObjects  # noqa: E402

import tsg_nx as nx  # noqa: E402
import design_check as dc  # noqa: E402
from design_check import Item, Result  # noqa: E402

# Extensions.AutoUpdateAttribute - stamped beside the AutoSize UDO's update status as "ON" / "OFF".
AUTO_UPDATE_ATTRIBUTE = "AUTO UPDATE"

_UDO_AUTO_SIZE_CLASS_NAME = "UdoAutoSizeComponent"

# NXException.ErrorCode when the UdoAutoSizeComponent class is not registered in the session.
_ERROR_UDO_CLASS_NOT_REGISTERED = 1535022


# ---------------------------------------------------------------------------------------------------
# Helpers (C# extension methods with no tsg_nx port)
# ---------------------------------------------------------------------------------------------------

def _try_get_att(obj: NXOpen.NXObject, title: str, to_upper: bool = False) -> Tuple[bool, str]:
    """NXObject.__TryGetAtt - (True, value) when the string attribute exists, else (False, "")."""
    if nx.has_attribute(obj, title):
        value = nx.get_attribute(obj, title)
        if to_upper:
            value = value.upper()
        return True, value
    return False, ""


def _is_blank(value: Optional[str]) -> bool:
    """string.IsNullOrWhiteSpace"""
    return value is None or not value.strip()


def _udo_auto_size_class() -> Optional[NXOpen.UserDefinedObjects.UserDefinedClass]:
    """Extensions.__UdoAutoSizeClass - the UdoAutoSizeComponent class; None when it is not registered (the C#
    registers it then, which Python cannot - see the module docstring). Other NXExceptions escape."""
    try:
        return nx.session_.UserDefinedClassManager.GetUserDefinedClassFromClassName(_UDO_AUTO_SIZE_CLASS_NAME)
    except NXOpen.NXException as ex:
        if ex.ErrorCode != _ERROR_UDO_CLASS_NOT_REGISTERED:
            raise
        return None


def _udo_auto_size_or_null(part: NXOpen.BasePart) -> Optional[NXOpen.UserDefinedObjects.UserDefinedObject]:
    """BasePart.__UdoAutoSizeOrNull - the part's UdoAutoSizeComponent UDO, or None."""
    udo_class = _udo_auto_size_class()
    if udo_class is None:
        return None
    udos = part.UserDefinedObjectManager.GetUdosOfClass(udo_class)
    return udos[0] if len(udos) > 0 else None


def _is_udo_auto_size(part: NXOpen.BasePart) -> bool:
    """BasePart.__IsUdoAutoSize"""
    return _udo_auto_size_or_null(part) is not None


def _udo_auto_size_update_status(part: NXOpen.BasePart) -> bool:
    """BasePart.__UdoAutoSizeUpdateStatus() - True for status 1, False for 0; raises otherwise or without a UDO."""
    udo = _udo_auto_size_or_null(part)
    if udo is None:
        raise ValueError("{} is not a UdoAutoSizeComponent".format(part.Leaf))
    integers = udo.GetIntegers()
    status = -1 if len(integers) == 0 else integers[0]
    if status == 1:
        return True
    if status == 0:
        return False
    raise ValueError("{} - AutoSize UDO update status must be 0 or 1 (was {})".format(part.Leaf, status))


def _try_udo_auto_size(part: NXOpen.BasePart) -> Tuple[bool, bool]:
    """BasePart.__TryUdoAutoSize - (True, status) for an AutoSize part whose status is 0 or 1, else (False, False)."""
    try:
        if not _is_udo_auto_size(part):
            return False, False
        return True, _udo_auto_size_update_status(part)
    except Exception:
        return False, False


def _is_fixed_time_stamp(extract_face: NXOpen.Features.ExtractFace) -> bool:
    """ExtractFace.__IsFixedTimeStamp - the ExtractFaceBuilder's FixAtCurrentTimestamp."""
    owning_part = cast(Any, extract_face.OwningPart)
    builder = owning_part.Features.CreateExtractFaceBuilder(extract_face)
    try:
        return bool(builder.FixAtCurrentTimestamp)
    finally:
        builder.Destroy()


def _is_off_increment_shcs(file: str) -> bool:
    """
    string.__IsOffIncrementShcs - an SHCS (lock-washer and -2x included) whose length is off the standard
    increments: metric over 50 mm ending in 5, or english (hundredths of an inch) over 2" not a multiple of .250".
    False for anything that is not an SHCS.
    """
    if "\\" in file:
        file = ntpath.splitext(ntpath.basename(file))[0]

    match = re.match(r"^\d+(?P<mm>mm)?-shcs-(?:lw-)?(?P<length>\d+)(?:-2x)?$", file, re.IGNORECASE)
    if match is None:
        return False

    length = int(match.group("length"))

    if match.group("mm") is not None:
        return length > 50 and length % 10 == 5
    return length > 200 and length % 25 != 0


# ---------------------------------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------------------------------

class AttributeCheck(dc.Check):
    """
    Fails an AutoSize detail whose bookkeeping attributes disagree with the part. Two rules: AUTO UPDATE has to
    match the AutoSize UDO's status integer (1 -> "ON", 0 -> "OFF"), and MATERIAL / DETAIL NAME / DESCRIPTION each
    have to carry a real value - not missing, not empty, not the FILL IN placeholder the Merlin builders stamp.
    Every problem is added as a child node, so a failing part lists its reasons.
    """

    _AutoUpdateAttribute = "AUTO UPDATE"
    _OnValue = "ON"
    _OffValue = "OFF"

    # The placeholder the Merlin builders stamp into DETAIL NAME / MATERIAL / DESCRIPTION.
    _FillInPlaceholder = "FILL IN"

    # The attributes every AutoSize detail has to carry a real value for.
    _RequiredAttributes = ["MATERIAL", "DETAIL NAME", "DESCRIPTION"]

    assembly_part_only = False

    def __init__(self) -> None:
        self._udo_class: Optional[NXOpen.UserDefinedObjects.UserDefinedClass] = None
        self._udo_class_resolved = False

    def get_objects(self, part: NXOpen.Part) -> List[Any]:
        """The part itself, but only when it carries an AutoSize UDO; a part without one is unmanaged rather than
        failing (the Static.CycleComponentsIsAutoUpdateOff rule)."""
        return [] if self._auto_size_udo_or_null(part) is None else [part]

    def check(self, obj: Any) -> Tuple[str, Optional[Item]]:
        part = cast(NXOpen.Part, obj)
        node = Item(part.Leaf, part)

        self._check_auto_update(part, node)

        for title in self._RequiredAttributes:
            self._check_required_attribute(part, title, node)

        # Every child node added above is a problem, so an empty node is a clean part.
        return (Result.Fail if len(node.children) > 0 else Result.Pass), node

    def _check_auto_update(self, part: NXOpen.Part, node: Item) -> None:
        """Compares the AUTO UPDATE attribute against the UDO's first integer (1 on, 0 off). No integer, an
        unrecognised status, or a missing, empty or disagreeing attribute is reported."""
        udo = self._auto_size_udo_or_null(part)

        # get_objects already filtered these out; check does not assume it was the caller.
        if udo is None:
            return

        integers = udo.GetIntegers()

        if len(integers) == 0:
            node.add("AutoSize UDO carries no status integer, so {} cannot be verified".format(
                self._AutoUpdateAttribute))
            return

        status = integers[0]

        if status == 1:
            expected = self._OnValue
        elif status == 0:
            expected = self._OffValue
        else:
            node.add("Unknown AutoSize UDO status: {}".format(status))
            return

        found, value = _try_get_att(part, self._AutoUpdateAttribute)

        if not found:
            node.add("Missing {} attribute (UDO status {}, should be \"{}\")".format(
                self._AutoUpdateAttribute, status, expected))
            return

        if _is_blank(value):
            node.add("{} attribute is empty (UDO status {}, should be \"{}\")".format(
                self._AutoUpdateAttribute, status, expected))
            return

        if value.strip().lower() != expected.lower():
            node.add("{} attribute is \"{}\" but the UDO status is {}, so it should be \"{}\"".format(
                self._AutoUpdateAttribute, value, status, expected))

    @classmethod
    def _check_required_attribute(cls, part: NXOpen.Part, title: str, node: Item) -> None:
        """Reports title when it is absent, blank, or still the FILL IN placeholder."""
        found, value = _try_get_att(part, title)

        if not found:
            node.add("Missing {} attribute".format(title))
            return

        if _is_blank(value):
            node.add("{} attribute is empty".format(title))
            return

        if value.strip().lower() == cls._FillInPlaceholder.lower():
            node.add("{} attribute is still {}".format(title, cls._FillInPlaceholder))

    def _auto_size_udo_or_null(self, part: NXOpen.Part) -> Optional[NXOpen.UserDefinedObjects.UserDefinedObject]:
        """The part's AutoSize UDO, or None when it has none."""
        udo_class = self._auto_size_udo_class()

        if udo_class is None:
            return None

        udos = part.UserDefinedObjectManager.GetUdosOfClass(udo_class)
        return None if len(udos) == 0 else udos[0]

    def _auto_size_udo_class(self) -> Optional[NXOpen.UserDefinedObjects.UserDefinedClass]:
        """The UdoAutoSizeComponent class, resolved once per run so a failure reports itself once. Not registered
        (1535022) -> None (the C# registers it - see the module docstring); any other failure is printed -> None."""
        if self._udo_class_resolved:
            return self._udo_class

        self._udo_class_resolved = True

        try:
            self._udo_class = nx.session_.UserDefinedClassManager.GetUserDefinedClassFromClassName(
                _UDO_AUTO_SIZE_CLASS_NAME)
        except NXOpen.NXException as ex:
            if ex.ErrorCode == _ERROR_UDO_CLASS_NOT_REGISTERED:
                self._udo_class = None
            else:
                nx.print_exception(ex)
                self._udo_class = None
        except Exception as ex:
            nx.print_exception(ex)
            self._udo_class = None

        return self._udo_class


class RequiredAttributes(dc.Check):
    """
    Fails a detail whose MATERIAL, DESCRIPTION or DETAIL NAME attribute is missing, blank, or still the FILL IN
    placeholder the builders stamp on new details. A detail is a part whose leaf matches {job}-{op}-{detail}
    (__IsDetail); assemblies and library parts are not checked.
    """

    _Titles = ["MATERIAL", "DESCRIPTION", "DETAIL NAME"]

    # The value the component builders write until someone fills the attribute in.
    _Placeholder = "FILL IN"

    assembly_part_only = False

    def get_objects(self, part: NXOpen.Part) -> List[Any]:
        return [part] if dc.is_detail(part.Leaf) else []

    def check(self, obj: Any) -> Tuple[str, Optional[Item]]:
        part = cast(NXOpen.Part, obj)
        problems: List[str] = []

        for title in self._Titles:
            if not nx.has_attribute(part, title):
                problems.append("{} missing".format(title))
                continue

            value = nx.get_attribute(part, title).strip()

            if value == "":
                problems.append("{} is empty".format(title))
            elif value.upper() == self._Placeholder:
                problems.append("{} = {}".format(title, self._Placeholder))

        text = "MATERIAL, DESCRIPTION and DETAIL NAME set" if len(problems) == 0 else "; ".join(problems)
        node = Item(text, part)

        return (Result.Pass if len(problems) == 0 else Result.Fail), node


class DescriptionNXAttribute(dc.Check):
    """
    Gets the DESCRIPTION attribute of the current part, then the occurrences of the part in the top level
    assembly part. Each must have a DESCRIPTION attribute, and it must equal the part's.
    """

    assembly_part_only = False

    def __init__(self, assembly_part: NXOpen.Part) -> None:
        self._assembly_part = assembly_part

    def check(self, obj: Any) -> Tuple[str, Optional[Item]]:
        part = cast(NXOpen.Part, obj)
        node = Item(part.Leaf, part)

        pass_node = Item("Passed")
        fail_node = Item("Failed")
        ignore_node = Item("Ignored")

        if not nx.has_attribute(part, "DESCRIPTION"):
            node.add("No DESCRIPTION attribute")
            return Result.Ignore, node

        description_value = nx.get_attribute(part, "DESCRIPTION")
        part_occs, _count = cast(Any, nx.ufsession_).Assem.AskOccsOfPart(self._assembly_part.Tag, part.Tag)

        for c_tag in part_occs:
            comp = cast(NXOpen.Assemblies.Component, nx.tagged_object(c_tag))
            comp_node = Item(comp.Name, comp)

            if not nx.has_attribute(comp, "DESCRIPTION"):
                comp_node.add("No DESCRIPTION attribute")
                fail_node.add(comp_node)
                continue

            comp_desc_value = nx.get_attribute(comp, "DESCRIPTION")

            if comp_desc_value != description_value:
                comp_node.add("DESCRIPTION attribute does not eqaul: {} != {}".format(
                    description_value, comp_desc_value))
                fail_node.add(comp_node)
                continue

            pass_node.add(comp_node)

        node.add(pass_node)
        node.add(fail_node)
        node.add(ignore_node)

        return (Result.Fail if len(fail_node.children) > 0 else Result.Pass), node

    def get_objects(self, part: NXOpen.Part) -> List[Any]:
        return [part]


class AutoUpdateStatus(dc.Check):
    """
    Fails an AutoSize part whose AUTO UPDATE attribute disagrees with its UdoAutoSizeComponent UDO: status 1 must
    read ON and status 0 OFF. The UDO integer is what NX's update callback honours; the attribute is what people and
    the other tools read. __UdoAutoSizeUpdateStatus(int) writes both together, which is the fix for a failing part.
    """

    assembly_part_only = False

    def get_objects(self, part: NXOpen.Part) -> List[Any]:
        """The part itself when it carries an AutoSize UDO; parts without one are not checked."""
        return [part] if _is_udo_auto_size(part) else []

    def check(self, obj: Any) -> Tuple[str, Optional[Item]]:
        part = cast(NXOpen.Part, obj)
        node = Item("", part)

        ok, is_on = _try_udo_auto_size(part)

        if not ok:
            node.text = "AutoSize UDO status is neither 0 nor 1"
            return Result.Fail, node

        expected = "ON" if is_on else "OFF"
        status = 1 if is_on else 0

        if not nx.has_attribute(part, AUTO_UPDATE_ATTRIBUTE):
            node.text = "UDO status {}, {} attribute missing (expected {})".format(
                status, AUTO_UPDATE_ATTRIBUTE, expected)
            return Result.Fail, node

        actual = nx.get_attribute(part, AUTO_UPDATE_ATTRIBUTE).strip().upper()
        node.text = "UDO status {}, {} = {}".format(status, AUTO_UPDATE_ATTRIBUTE, actual)

        return (Result.Pass if actual == expected else Result.Fail), node


class TimeStamps(dc.Check):
    """Fails each linked body (an ExtractFace whose FeatureType is LINKED_BODY) fixed at the current timestamp."""

    assembly_part_only = False

    def ask_string(self, nxobject: Optional[NXOpen.Features.ExtractFace]) -> str:
        """TimeStamps.AskString - the feature name; raises on None (ArgumentNullException)."""
        if nxobject is None:
            raise ValueError("Value cannot be null.\nParameter name: nxobject")
        return nxobject.GetFeatureName()

    def check(self, obj: Any) -> Tuple[str, Optional[Item]]:
        linked_body = cast(NXOpen.Features.ExtractFace, obj)
        node = Item(linked_body.GetFeatureName(), linked_body)

        return (Result.Fail if _is_fixed_time_stamp(linked_body) else Result.Pass), node

    def get_objects(self, part: NXOpen.Part) -> List[Any]:
        return [feature for feature in part.Features
                if isinstance(feature, NXOpen.Features.ExtractFace) and nx.is_linked_body(feature)]


class ShcsIncrements(dc.Check):
    """
    Fails each SHCS in a detail ({job}-{op}-{detail}, the -000 excepted) whose length is off the standard increments
    (__IsOffIncrementShcs): a metric one over 50 mm ending in 5 (12mm-shcs-055 fails, 12mm-shcs-015 and
    12mm-shcs-060 pass), or an english one over 2" that is not a multiple of .250". The SHCS are the detail's
    unsuppressed direct children, by component name. AddFasteners leaves the same lengths out of its list.
    """

    assembly_part_only = False

    def get_objects(self, part: NXOpen.Part) -> List[Any]:
        root = part.ComponentAssembly.RootComponent
        if not dc.is_detail(part.Leaf) or part.Leaf.endswith("-000") or root is None:
            return []

        return [child for child in root.GetChildren()
                if not child.IsSuppressed and "-shcs-" in child.DisplayName.lower()]

    def check(self, obj: Any) -> Tuple[str, Optional[Item]]:
        component = cast(NXOpen.Assemblies.Component, obj)
        off = _is_off_increment_shcs(component.DisplayName)

        text = ("{}: length off the standard increments".format(component.DisplayName) if off
                else component.DisplayName)
        node = Item(text, component)

        return (Result.Fail if off else Result.Pass), node
