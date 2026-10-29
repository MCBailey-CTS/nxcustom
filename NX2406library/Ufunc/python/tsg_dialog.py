"""
Shared plumbing for the Python UFunc dialogs: a Block UI Styler dialog loaded from a .dlx beside this file.

A form UFunc that does not need to stay open becomes a modal dialog: the C# UFunc calls the Python module, which
shows the dialog, does the work in its OK callback and returns, so TSG_Library.dll unloads straight away (the
WinForms form kept it loaded until closed). The .dlx files are built by tools\\make-dlx.py from blocks NX itself
generated; HelloDialog.py is the original example.

Subclass Dialog, name its .dlx, look up the blocks in initialize(), set value properties in shown() (dialog memory
overwrites them when set from initialize()), react to changes in update(block), say whether OK can be pressed in
enable_ok(), and do the work in ok() - return False to keep the dialog open (a missing input, say). Run it with
    MyDialog().run()
which shows it, prints any exception from a callback to the listing window, and always disposes it.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any, List, Optional, Sequence, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.BlockStyler  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402

# UF_UI_SEL_SCOPE_ANY_IN_ASSEMBLY (Snap's SelectionScope.AnyInAssembly) - not in every UFConstants build.
_ScopeAnyInAssembly = 3

# The Merlin dialogs' Customer radio, ("enum", "customer", "Customer", Customers, "radio") in tools\make-dlx.py: when
# the dialog opens (reset_customer, from shown()) it is set from the display assembly's stations (detect_customer,
# 2026-10-29) - TSG for lsp / usp sub plates, GM for lad / uad / upd / lftr / las / uas / acum - and left on None
# when there are neither or both. OK stays greyed out until TSG or GM is checked.
# GM adds the GM library parts as children; TSG (the CTS parts) is not implemented yet - is_gm_customer throws.
CustomerNone, CustomerTsg, CustomerGm = "None", "TSG", "GM"
Customers = [CustomerNone, CustomerTsg, CustomerGm]

# {job}-{op}-{station}: the TSG sub plates and the GM die sets (ComponentAssignName's GM station table).
_TsgStation = re.compile(r"^\d+-\d+-(lsp|usp)", re.IGNORECASE)
_GmStation = re.compile(r"^\d+-\d+-(lad|uad|upd|lftr|las|uas|acum)", re.IGNORECASE)


def detect_customer(part: Optional[NXOpen.Part] = None) -> str:
    """
    TSG or GM by the stations in part's assembly (default the display part), the part itself included: TSG when
    only lsp / usp stations are found, GM when only lad / uad / upd / lftr / las / uas / acum, otherwise None.
    Unloaded components count (by display name). Never throws - None on any error.
    """
    try:
        root_part = part if part is not None else nx.display_part()
        if root_part is None:
            return CustomerNone
        names = [root_part.Leaf]
        root = root_part.ComponentAssembly.RootComponent
        stack = [root] if root is not None else []
        while stack:
            component = stack.pop()
            for child in component.GetChildren():
                names.append(child.DisplayName)
                stack.append(child)
        tsg = any(_TsgStation.match(name or "") for name in names)
        gm = any(_GmStation.match(name or "") for name in names)
        if tsg == gm:
            return CustomerNone
        return CustomerTsg if tsg else CustomerGm
    except Exception as ex:
        nx.syslog("detect_customer: {}".format(ex))
        return CustomerNone


class Dialog(object):
    """One Block UI Styler dialog. Subclasses set dlx_name and title, and override initialize / update / ok."""

    dlx_name = ""
    title = ""
    # A Close-only dialog (no OK): closing it is how it ends, so it is logged "close" and does not mark the run
    # cancelled.
    close_only = False

    def __init__(self) -> None:
        self.ui = NXOpen.UI.GetUI()
        # Beside the subclass's module first: a UFunc's own dialog sits with it in src\UFuncs in the source tree.
        near = getattr(sys.modules.get(type(self).__module__), "__file__", "") or ""
        self.dialog = self.ui.CreateDialog(nx.library_file(self.dlx_name, near))
        self.dialog.AddInitializeHandler(self._initialize_cb)
        self.dialog.AddDialogShownHandler(self._shown_cb)
        self.dialog.AddUpdateHandler(self._update_cb)
        self.dialog.AddOkHandler(self._ok_cb)
        self.dialog.AddApplyHandler(self._apply_cb)
        self.dialog.AddEnableOKButtonHandler(self._enable_ok_cb)
        # Set by OK. The blocks are gone once Launch returns, so anything the caller needs is captured in ok().
        self.accepted = False
        # Set by an accepted Apply (OkApplyCancel dialogs): the work was done even if the dialog is then cancelled.
        self.applied = False

    # ----- overridable -----

    def initialize(self) -> None:
        """Look up the blocks; set filters and visibility."""

    def shown(self) -> None:
        """The dialog is up, its remembered values applied - set value properties here."""

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        """A block changed."""

    def enable_ok(self) -> bool:
        """Whether OK can be pressed (NX greys it out otherwise)."""
        return True

    def ok(self) -> bool:
        """Do the work. False keeps the dialog open."""
        return True

    def apply(self) -> bool:
        """Apply in an OkApplyCancel dialog: do the work and stay open. Defaults to ok(); False reports a failure."""
        return self.ok()

    # ----- helpers -----

    def block(self, block_id: str) -> Any:
        return self.dialog.TopBlock.FindBlock(block_id)

    def reset_customer(self) -> None:
        """
        Sets the "customer" radio from the display assembly (detect_customer: TSG, GM, or None when it cannot tell).
        Call from shown(): the dialog memory would bring back the last pick.
        """
        self.block("customer").ValueAsString = detect_customer()

    def customer(self) -> str:
        """The "customer" radio's value: None, TSG or GM."""
        return str(self.block("customer").ValueAsString)

    def customer_picked(self) -> bool:
        """TSG or GM is checked - an enable_ok() condition."""
        return self.customer() in (CustomerTsg, CustomerGm)

    def run(self) -> bool:
        """
        Shows the dialog modally and disposes it, writing its tblDialogs row ("ok", "cancel", or "error" when NX
        would not build it). True when OK was pressed and ok() accepted.
        """
        response = "error"
        try:
            self.dialog.Launch()
            response = ("ok" if self.accepted else "apply" if self.applied
                        else "close" if self.close_only else "cancel")
        finally:
            self.dialog.Dispose()
            nx.log_dialog("block-dialog", self.title or self.dlx_name, None, None, response)
        if not self.accepted and not self.applied and not self.close_only:
            nx.mark_cancelled("the {} dialog".format(self.title or self.dlx_name))
        return self.accepted

    @staticmethod
    def component_filter(selection: NXOpen.BlockStyler.SelectObject) -> None:
        """Restrict a selection block to components."""
        mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_component_type, 0, 0)
        selection.SetSelectionFilter(NXOpen.Selection.SelectionAction.ClearAndEnableSpecific, [mask])

    @staticmethod
    def assembly_scope(selection: NXOpen.BlockStyler.SelectObject) -> None:
        """
        Let a selection block pick anywhere in the assembly, not just the work part - SNAP's
        MaximumScope = AnyInAssembly. tools\\make-dlx.py writes the .dlx scope enums as 0 (UF_UI_SEL_SCOPE_NO_CHANGE,
        which leaves NX on the work part); the property takes the UF scope value, as Snap's NxSetEnum passes it.
        Call from initialize().
        """
        properties = selection.GetProperties()
        try:
            # "Scope" is in the .dlx but is not a runtime property ("Invalid property name for the block"), so only
            # the names the block reports are set. Each step reports its own failure and the dialog still opens.
            try:
                names = list(properties.GetPropertyNames() or [])
            except NXOpen.NXException as ex:
                nx.print_("assembly_scope: GetPropertyNames failed: {}".format(ex))
                names = ["MaximumScope"]
            scopes = [n for n in names if "scope" in n.lower()]
            if not scopes:
                nx.print_("assembly_scope: the selection block has no scope property ({})".format(sorted(names)))
            for name in scopes:
                try:
                    current = properties.GetEnum(name)
                    members = list(properties.GetEnumMembers(name) or [])
                    properties.SetEnum(name, _ScopeAnyInAssembly)
                except NXOpen.NXException as ex:
                    nx.print_("assembly_scope: {} failed: {}".format(name, ex))
                    continue
                # Syslog only: what the property held, its members, and what it holds now.
                nx.syslog("assembly_scope: {} was {} of {}, now {}".format(name, current, members, properties.GetEnum(name)))
        finally:
            properties.Dispose()

    @staticmethod
    def string_value(block: Any) -> str:
        """A string block's text, stripped. tools\\make-dlx.py's string blocks allow international text, so what is
        shown and typed is WideValue and Value stays "" - reading Value alone made Export Strip's folder name empty
        (and its outgoing folder the Layout folder itself)."""
        return str(block.WideValue or block.Value or "").strip()

    @staticmethod
    def set_string_value(block: Any, text: str) -> None:
        """Sets both of a string block's values (see string_value)."""
        block.WideValue = text
        block.Value = text

    @staticmethod
    def selected(selection: NXOpen.BlockStyler.SelectObject) -> List[NXOpen.TaggedObject]:
        return list(selection.GetSelectedObjects() or [])

    def message(self, text: str, error: bool = False) -> None:
        kind = NXOpen.NXMessageBox.DialogType.Error if error else NXOpen.NXMessageBox.DialogType.Information
        nx.message_box(self.title or self.dlx_name, kind, text)

    def _set_window_title(self, title: str) -> None:
        """The dialog's title bar, in place of the Label the .dlx was saved with."""
        properties = self.dialog.GetBlockProperties("Dialog")
        try:
            properties.SetString("Label", title)
        finally:
            properties.Dispose()

    # ----- callbacks -----

    def _initialize_cb(self) -> None:
        try:
            if self.title:
                self._set_window_title(self.title)
            self.initialize()
        except Exception as ex:
            nx.print_exception(ex)

    def _shown_cb(self) -> None:
        try:
            self.shown()
        except Exception as ex:
            nx.print_exception(ex)

    def _enable_ok_cb(self) -> bool:
        try:
            return bool(self.enable_ok())
        except Exception as ex:
            nx.print_exception(ex)
            return False

    def _update_cb(self, block: NXOpen.BlockStyler.UIBlock) -> int:
        try:
            self.update(block)
        except Exception as ex:
            nx.print_exception(ex)
        return 0

    def _ok_cb(self) -> int:
        try:
            if not self.ok():
                return 1
            self.accepted = True
            return 0
        except Exception as ex:
            nx.print_exception(ex)
            # Close anyway: the failure is in the listing window and a retry would usually fail the same way.
            return 0

    def _apply_cb(self) -> int:
        try:
            if not self.apply():
                return 1
            self.applied = True
            return 0
        except Exception as ex:
            nx.print_exception(ex)
            return 1


def components_of(objects: Sequence[NXOpen.TaggedObject]) -> List[NXOpen.Assemblies.Component]:
    """The components among a selection block's objects."""
    return [cast(NXOpen.Assemblies.Component, o) for o in objects if isinstance(o, NXOpen.Assemblies.Component)]


def title_with_version(title: str) -> str:
    """'{AssemblyFileVersion} - title', the way the forms titled themselves."""
    try:
        version = nx.assembly_file_version()
    except Exception:
        version = ""
    return "{} - {}".format(version, title) if version else title


def is_gm_customer(customer: str) -> bool:
    """
    True for GM, False for TSG (2026-10-29: the builders' CTS branches - cts- names, the CTS keys / lift lugs / guided
    keepers - in the same stations; it used to throw NotImplementedError). None throws ValueError.
    """
    if customer == CustomerGm:
        return True
    if customer == CustomerTsg:
        return False
    raise ValueError("Pick TSG or GM, not '{}'.".format(customer))


class CustomerDialog(Dialog):
    """CustomerDialog.dlx: the Customer radio alone, for the Merlin UFuncs with no dialog of their own."""

    dlx_name = "CustomerDialog.dlx"

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__()
        # Captured in ok(): the blocks are gone once Launch returns.
        self.choice = CustomerNone

    def shown(self) -> None:
        self.reset_customer()

    def enable_ok(self) -> bool:
        return self.customer_picked()

    def ok(self) -> bool:
        self.choice = self.customer()
        return self.customer_picked()


def ask_is_gm(title: str) -> Optional[bool]:
    """
    The Customer dialog titled '{version} - title', in place of the "Are you sure" box: True once GM is picked, None
    when it is cancelled (Dialog.run marked the run cancelled). TSG uses the CTS parts.
    """
    dialog = CustomerDialog(title_with_version(title))
    if not dialog.run():
        return None
    return is_gm_customer(dialog.choice)
