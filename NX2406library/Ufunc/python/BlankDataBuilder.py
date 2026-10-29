"""
The blank-data-builder UFunc: exports the picked objects of a blank to a new part named for the job, version and
Hot / Cold operation - one copy in %TMP% and one in {job}\\Outgoing\\{date}-Blank-{version} - adds the latter to the
display part as a component (layer 103 Hot, 101 Cold), saves, and starts the DXF translator on the temp part.

ALL PYTHON since 2026-10-23: the blank-data-builder menu button runs this file. main() records the run
(usage_db.run("blank-data-builder")) and shows a Block UI Styler dialog (BlankDataBuilder.dlx, built by
tools\\make-dlx.py) in place of the WinForms form. It replaced src\\UFuncs\\BlankDataBuilder.cs (the form, with
.Designer.cs and .resx) and src\\Static\\BlankDataBuilder.cs (its version guess, name builder and replace prompt) -
all in git at f108562. This file used to be src\\python\\BlankDataBuilder.py, the port of the export alone. The
dialog has NEVER BEEN RUN IN NX, nor has the export.

Ported from:
  - BlankDataBuilder.InitializeFormData (the form)  -> _BlankDataBuilderDialog.shown
  - BlankDataBuilder.ComboBoxOperation_SelectedIndexChanged -> _BlankDataBuilderDialog._guess_version
  - BlankDataBuilder.ButtonSelect_Click            -> _BlankDataBuilderDialog.ok + _export
  - BlankDataBuilder.ButtonSetAttribute_Click      -> _set_revision_text (the Set REVISION TEXT Attribute button)
  - Static.BlankDataBuilderVersionText             -> version_text
  - Static.BlankDataBuilderNameBuilder             -> name_builder
  - Static.BlankDataBuilderReplaceExisting         -> _replace_existing
  - Static.BlankDataBuilderBuildFilesExportDxf     -> BlankDataBuilder.build_files_export_dxf
  - GFolder.create_or_null(Part) / DirOutgoing     -> _GFolder (only the members this module reads)
  - Extensions.TodaysDate                          -> _todays_date

Differences from the C#:
  - The form stayed open: Select exported and the form could be used again. The dialog's OK exports the picked
    objects and closes it; Set REVISION TEXT Attribute acts at once and leaves it open. The Select button's
    UF_UI_select_with_class_dialog is the dialog's own selection block (every object type, in the work part).
  - The form opened with no operation and no version (and the export refused an empty version with "Invalid version
    number."); the dialog always has both - Operation remembers the last run (Hot the first time), and the version
    is guessed from it when the dialog opens as well as when the operation changes. A guess the list does not hold
    (V26 and up) leaves the version as it was and says so; an empty guess (no -V components) leaves it too, where the
    form cleared its combo.
  - The form had a Reset button; the dialog re-fills Job # and clears the description every time it opens, which
    is what Reset did, and NX's own Reset (title bar) puts the blocks back to the .dlx defaults.
  - The name shows live under the Create Name group (the Revision Text box showed it only after the button).
  - "Replace file?" is an NX Question box (Yes / No) where it was a WinForms OK / Cancel MessageBox.
  - The DXF batch file pointed at C:\\Program Files\\Siemens\\NX 11.0\\DXFDWG, which no longer exists, so the DXF
    never came out on NX2306. It now uses the running NX's own DXFDWG folder (UGII_BASE_DIR, else NX2306.6001).
  - Set REVISION TEXT Attribute does what the C# did - writes the name only when the display part already has a
    non-empty REVISION TEXT attribute, then refreshes layout L1's work view - but prints why when it writes nothing
    (no attribute, or an empty one) instead of saying nothing.

Unconfirmed bindings (from the old port): NXOpen.UF.Part.ExportOptions is built with no arguments and passed by
value to ExportWithOptions (the C# passes it by ref); PartCollection.OpenBase returns (BasePart, PartLoadStatus).
"""

from __future__ import annotations

import datetime
import os
import re
import subprocess
import sys
from typing import List, Optional, Sequence, cast

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
from tsg_dialog import Dialog, title_with_version  # noqa: E402

# _UFunc.ufunc_blank_data_builder (deleted with the form)
ufunc_blank_data_builder = "blank-data-builder"

# Extensions.RegexSimulation - the job number of a {job}-simulation work part (case-sensitive, as in the C#).
_RegexSimulation = r"^(?P<customerNum>\d+)-simulation$"

# The DXF translator's folder in the NX that is running this (the C# had NX 11.0's hard-coded).
_DxfDwgFolderFallback = "C:\\Program Files\\Siemens\\NX2306.6001\\DXFDWG"

# Extensions.RefsetEntirePart
_RefsetEntirePart = "Entire Part"

# The layer the exported blank's component goes on, by operation (anything else: 1).
_OperationLayers = {"Cold": 101, "Hot": 103}

_RevisionTextAttribute = "REVISION TEXT"

# NX will not build a Block Styler dialog from inside some callbacks (a menu or toolbar launch, it seems).
_ErrorCannotLaunchDialog = 3520048


class BlankDataBuilder(object):

    @staticmethod
    def build_files_export_dxf(part_file: str, tag_objects: Sequence[NXOpen.TaggedObject], version_number: str,
                               operation: str, display_part: NXOpen.Part, name_builder: str) -> None:
        """Static.BlankDataBuilderBuildFilesExportDxf - exports the picked objects to a temp part and to
        {DirOutgoing}\\{date}-Blank-{version}\\{name}.prt, adds the latter to the display part, saves, and (Hot/Cold)
        writes and launches a dxfdwg batch file."""
        try:
            if not version_number:
                raise Exception("Invalid version number.")

            folder = _GFolder.create_or_null(display_part.FullPath)

            if folder is None:
                raise Exception("The current display part does not reside within in a GFolder.")

            if os.path.isfile(part_file + ".prt"):
                os.remove(part_file + ".prt")

            tags: List[NXOpen.Tag] = [obj.Tag for obj in tag_objects]

            # Binding not confirmed in NX - see the module docstring.
            export_options = NXOpen.UF.Part.ExportOptions()
            export_options.NewPart = True
            export_options.ExpressionMode = NXOpen.UF.Part.ExportExpMode.COPY_EXP_DEEPLY
            export_options.ParamsMode = NXOpen.UF.Part.ExportParamsMode.REMOVE_PARAMS

            uf_part = nx.ufsession_.Part
            uf_part.ExportWithOptions(part_file, len(tags), tags, export_options)
            nx.syslog("BlankDataBuilder: {} objects exported to {}.prt".format(len(tags), part_file))

            # get path to blank location, check directory structure

            output_directory = "{}\\{}-Blank-{}".format(folder.DirOutgoing, _todays_date(), version_number)

            if not os.path.isdir(output_directory):
                os.makedirs(output_directory)

            comp_blanks_path = output_directory + "\\" + name_builder + ".prt"

            if os.path.isfile(comp_blanks_path):
                os.remove(comp_blanks_path)

            uf_part.ExportWithOptions(comp_blanks_path, len(tags), tags, export_options)
            nx.syslog("BlankDataBuilder: exported to {}".format(comp_blanks_path))

            # add  component to Blanks file

            base_part1, base_part_load_status = nx.session_.Parts.OpenBase(comp_blanks_path)
            base_part_load_status.Dispose()

            layer = _OperationLayers.get(operation, 1)

            surface_part = cast(NXOpen.Part, base_part1)
            _, s_part_load_status = display_part.ComponentAssembly.AddComponent(
                surface_part, _RefsetEntirePart, name_builder, NXOpen.Point3d(0.0, 0.0, 0.0), nx.identity_matrix(),
                layer)
            s_part_load_status.Dispose()
            nx.syslog("BlankDataBuilder: added {} to {} on layer {}".format(name_builder, display_part.Leaf, layer))

            display_part.Save(NXOpen.BasePart.SaveComponents.TrueValue, NXOpen.BasePart.CloseAfterSave.FalseValue)
            nx.print_("Created \"{}\".".format(comp_blanks_path))

            # export blank dxf data

            if operation not in _OperationLayers:
                return
            # Path.ChangeExtension(compBlanksPath, "dxf")
            blank_dxf = os.path.splitext(comp_blanks_path)[0] + ".dxf"
            dxf_batch = part_file + ".bat"
            dxf_folder = _dxfdwg_folder()
            dxf_arguments = "dxfdwg.cmd /c \"{}.prt\" o=\"{}\" d=\"{}\"".format(
                part_file, blank_dxf, os.path.join(dxf_folder, "dxfdwg.def"))

            with open(dxf_batch, "w", encoding="utf-8", newline="\r\n") as writer:
                writer.write(dxf_folder[:2] + "\n")
                writer.write("cd \"{}\"\n".format(dxf_folder))
                writer.write(dxf_arguments + "\n")
                writer.write("\n")

            # Process.Start(dxfBatch): shell-execute, new console window, not waited on.
            subprocess.Popen([dxf_batch], creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
            nx.syslog("BlankDataBuilder: DXF translator started for {}".format(blank_dxf))
            nx.print_("Writing \"{}\" (the DXF translator runs in its own window).".format(blank_dxf))
        # Handle this exception somehow - Duane
        except Exception as ex:
            nx.print_exception(ex)


def _dxfdwg_folder() -> str:
    """The running NX's DXFDWG folder (holding dxfdwg.cmd and dxfdwg.def), else NX2306.6001's."""
    try:
        base = nx.session_.GetEnvironmentVariableValue("UGII_BASE_DIR")
    except Exception:
        base = ""
    if base and os.path.isfile(os.path.join(base, "DXFDWG", "dxfdwg.cmd")):
        return os.path.join(base, "DXFDWG")
    return _DxfDwgFolderFallback


# ---------------------------------------------------------------------------------------------------
# Static.BlankDataBuilder* - the version guess, the name and the replace prompt
# ---------------------------------------------------------------------------------------------------

def version_text(work_part: NXOpen.Part, next_version: bool) -> Optional[str]:
    """Static.BlankDataBuilderVersionText - the highest -Vnn among the work part's children (plus one for the next
    version, Cold) as "Vnn"; "" with no such child, None when there is no assembly or the number is not 1-99."""
    root = work_part.ComponentAssembly.RootComponent
    if root is None:
        return None

    names: List[int] = []
    for comp in root.GetChildren():
        index_of = comp.DisplayName.rfind("-V")
        if index_of == -1:
            continue
        # The two characters after the V, up to the first non-digit; int.TryParse leaves 0 on failure.
        digits = re.match(r"\d*", comp.DisplayName[index_of + 2:index_of + 4])
        text = digits.group(0) if digits else ""
        names.append(int(text) if text else 0)

    if not names:
        return ""

    last_version_number = max(names) + (1 if next_version else 0)

    if 0 < last_version_number < 100:
        return "V{:02d}".format(last_version_number)

    return None


def name_builder(job_number: str, version: str, operation: str, custom_text: str, current_date: str) -> str:
    """Static.BlankDataBuilderNameBuilder - {job}-{version}-{Hot|Cold}-Blank-{date}-{custom}, each part only when
    set."""
    name = job_number

    if version:
        name += "-" + version

    if operation in _OperationLayers:
        name += "-{}-Blank-{}".format(operation, current_date)

    if custom_text:
        name += "-" + custom_text

    return name


def _replace_existing(display_part: NXOpen.Part, name: str) -> bool:
    """Static.BlankDataBuilderReplaceExisting - when the display part has a child named name (upper case, as NX
    stores component names), asks to replace it, then closes its part and deletes the component. False: keep it."""
    root = display_part.ComponentAssembly.RootComponent
    if root is None:
        return True

    existing = [c for c in root.GetChildren() if c.Name == name.upper()]
    if not existing:
        return True

    if nx.message_box("File Exist", NXOpen.NXMessageBox.DialogType.Question,
                      "Replace file {}?".format(name)) != nx.MessageBoxYes:
        nx.mark_cancelled("the replace-file question")
        return False

    for sim_comp in existing:
        close_sim_part = sim_comp.Prototype
        if isinstance(close_sim_part, NXOpen.Part):
            close_sim_part.Close(NXOpen.BasePart.CloseWholeTree.FalseValue,
                                 NXOpen.BasePart.CloseModified.CloseModified, None)
        mark_id = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "")
        nx.session_.UpdateManager.AddObjectsToDeleteList([sim_comp])
        nx.session_.UpdateManager.DoUpdate(mark_id)
        nx.syslog("BlankDataBuilder: replaced the existing {} component".format(name))

    return True


def _export(objects: Sequence[NXOpen.TaggedObject], job_number: str, version: str, operation: str,
            custom_text: str) -> None:
    """BlankDataBuilder.ButtonSelect_Click after the pick: the name, the replace prompt, then the export."""
    display_part = nx.display_part()
    name = name_builder(job_number, version, operation, custom_text, _todays_date())
    temp_part = "{}\\{}".format(os.environ.get("TMP") or os.environ.get("TEMP") or ".", name)
    nx.syslog("BlankDataBuilder: {} objects, name {}, operation {}, version {}".format(
        len(objects), name, operation, version))

    if not _replace_existing(display_part, name):
        return

    BlankDataBuilder.build_files_export_dxf(temp_part, objects, version, operation, display_part, name)


def _set_revision_text(name: str) -> None:
    """BlankDataBuilder.ButtonSetAttribute_Click - writes name to the display part's REVISION TEXT attribute, but
    only when it already has a non-empty one, then refreshes layout L1's work view."""
    display_part = nx.display_part()
    work_part = nx.work_part()

    attribute = next((a for a in display_part.GetUserAttributes() if a.Title == _RevisionTextAttribute), None)
    if attribute is None:
        nx.print_("{} has no {} attribute - nothing set.".format(display_part.Leaf, _RevisionTextAttribute))
        return

    if display_part.GetUserAttributeAsString(_RevisionTextAttribute, NXOpen.NXObject.AttributeType.String, -1) == "":
        nx.print_("{}'s {} attribute is empty - left empty.".format(display_part.Leaf, _RevisionTextAttribute))
        return

    display_part.SetUserAttribute(_RevisionTextAttribute, -1, name, NXOpen.Update.Option.Now)
    layout1 = work_part.Layouts.FindObject("L1")
    layout1.ReplaceView(work_part.ModelingViews.WorkView, work_part.ModelingViews.WorkView, True)
    nx.print_("{} {} = {}".format(display_part.Leaf, _RevisionTextAttribute, name))


# ---------------------------------------------------------------------------------------------------
# The blank-data-builder UFunc: a modal dialog (BlankDataBuilder.dlx) in place of the WinForms form
# ---------------------------------------------------------------------------------------------------

class _BlankDataBuilderDialog(Dialog):
    """The form's Create Name group, the Select button's pick and the Set RevisionText Attribute button. OK exports
    the picked objects and is greyed out until there are some."""

    dlx_name = "BlankDataBuilder.dlx"

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__()
        # Captured in ok(): the blocks are gone once Launch returns.
        self.objects: List[NXOpen.TaggedObject] = []
        self.job_number = ""
        self.operation = ""
        self.version = ""
        self.custom_text = ""

    def initialize(self) -> None:
        # UF_UI_select_with_class_dialog: any type of object.
        self.block("objects").SetSelectionFilter(NXOpen.Selection.SelectionAction.EnableAll, [])

    def shown(self) -> None:
        # InitializeFormData: the job number of a {job}-simulation work part, else "JOB #"; no description.
        match = re.match(_RegexSimulation, nx.work_part().Leaf)
        self.set_string_value(self.block("job_number"), match.group("customerNum") if match else "JOB #")
        self.set_string_value(self.block("custom_text"), "")
        self._guess_version()
        self._show_name()

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        if block == self.block("operation"):
            self._guess_version()
        if block == self.block("set_revision_text"):
            _set_revision_text(self._name())
        self._show_name()

    def enable_ok(self) -> bool:
        return len(self.selected(self.block("objects"))) > 0

    def ok(self) -> bool:
        self.objects = self.selected(self.block("objects"))
        if not self.objects:
            self.message("Select the objects to export.")
            return False
        self.job_number = self.string_value(self.block("job_number"))
        self.operation = self.block("operation").ValueAsString
        self.version = self.block("version").ValueAsString
        self.custom_text = self.string_value(self.block("custom_text"))
        return True

    def _guess_version(self) -> None:
        """ComboBoxOperation_SelectedIndexChanged - Hot: the highest version among the work part's children, Cold:
        the one after it."""
        operation = self.block("operation").ValueAsString
        guess = version_text(nx.work_part(), operation == "Cold")
        if not guess:
            return
        try:
            self.block("version").ValueAsString = guess
        except Exception:
            nx.print_("Blank Data Builder: the next version would be {}, which the Version # list does not hold - "
                      "pick one.".format(guess))

    def _name(self) -> str:
        return name_builder(self.string_value(self.block("job_number")), self.block("version").ValueAsString,
                            self.block("operation").ValueAsString, self.string_value(self.block("custom_text")),
                            _todays_date())

    def _show_name(self) -> None:
        self.block("name").Label = "Name: " + self._name()


def _run() -> None:
    """The blank-data-builder UFunc: the dialog, then the export with what it captured."""
    title = "Blank Data Builder"

    if nx.display_part() is None:
        nx.show_error("{} needs a displayed part.".format(title))
        return

    try:
        dialog = _BlankDataBuilderDialog(title_with_version(title))
        accepted = dialog.run()
    except NXOpen.NXException as ex:
        if ex.ErrorCode != _ErrorCannotLaunchDialog:
            raise
        nx.print_exception(ex)
        nx.show_error("NX would not open the {} dialog (error {} - it will not create a dialog from inside a "
                      "callback).\n\nTry running it from File -> Execute -> NX Open rather than from a menu or "
                      "toolbar button.".format(title, _ErrorCannotLaunchDialog))
        return

    if not accepted:
        nx.print_("{} dialog was not accepted - nothing exported.".format(title))
        return

    _export(dialog.objects, dialog.job_number, dialog.version, dialog.operation, dialog.custom_text)


def main() -> None:
    """The blank-data-builder UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_blank_data_builder):
        try:
            _run()
        except Exception as ex:
            nx.print_exception(ex)


# ---------------------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------------------

def _todays_date() -> str:
    """Extensions.TodaysDate - yyyy-MM-dd."""
    today = datetime.date.today()
    return "{}-{:02d}-{:02d}".format(today.year, today.month, today.day)


class _GFolder(object):
    """GFolder (src\\Utilities\\GFolder.cs) - only the members BlankDataBuilder reads."""

    def __init__(self, dir_job: str, customer_number: str) -> None:
        self.DirJob = dir_job
        self.CustomerNumber = customer_number

    @property
    def DirOutgoing(self) -> str:
        """GFolder.DirOutgoing"""
        return "{}\\Outgoing".format(self.DirJob)

    @staticmethod
    def create(job_folder: str) -> "_GFolder":
        """GFolder.Create(string)"""
        split = job_folder.split("\\")

        if len(split) < 3:
            # C#: IndexOutOfRangeException(jobFolder)
            raise IndexError(job_folder)

        directory = "{}\\{}\\{}".format(split[0], split[1], split[2])
        number = _GFolder._job_number(directory, split[2])
        if number:
            return _GFolder(directory, number)

        # Not the C#: a job copied below the usual depth (G:\CTS\junk\Mark B\006073\006073-010\...) has no job
        # number in the third piece, so the job folder is the first deeper folder whose name starts with one.
        for i in range(3, len(split) - 1):
            deeper = "\\".join(split[:i + 1])
            number = _GFolder._job_number(deeper, split[i])
            if number:
                return _GFolder(deeper, number)

        if "\\cts\\" not in directory.lower():
            return _GFolder(directory, "")

        raise ValueError("Could not make GFolder from '{}'".format(job_folder))

    @staticmethod
    def _job_number(directory: str, leaf: str) -> Optional[str]:
        """GFolder.Create's rules for the job folder `directory` named `leaf`: its customer number, or None."""
        if "\\cts\\" not in directory.lower():
            match0 = re.match(r"^(?P<num_0>\d{2,})", leaf)
            return match0.group("num_0") if match0 else None

        if _int_try_parse(leaf):
            return leaf

        match = re.match(r"^(?P<cts_number>\d{2,}) \([A-Z]+-[xX]+\)", leaf)
        if match:
            return match.group("cts_number")

        match = re.match(r"^(?P<cts_number>\d{2,}) \([A-Za-z]+-(?P<customer_number>\d+)\)", leaf)
        if match:
            return match.group("customer_number")

        match = re.match(r"^(?P<customer_number>\d{2,})", leaf)
        if match:
            return match.group("customer_number")

        return None

    @staticmethod
    def create_or_null(work_part_path: str) -> Optional["_GFolder"]:
        """GFolder.create_or_null(Part) - prints the exception and returns None."""
        try:
            return _GFolder.create(work_part_path)
        except Exception as ex:
            nx.print_exception(ex, "Exception caught for GFolder '{}'".format(work_part_path))
            return None


def _int_try_parse(text: str) -> bool:
    """int.TryParse(string, out _) with the default NumberStyles.Integer: optional surrounding whitespace, an
    optional sign, digits, and the value must fit in an Int32."""
    match = re.match(r"^\s*([+-]?\d+)\s*$", text)
    if match is None:
        return False
    try:
        value = int(match.group(1))
    except ValueError:
        return False
    return -2147483648 <= value <= 2147483647


if __name__ == "__main__":
    main()
