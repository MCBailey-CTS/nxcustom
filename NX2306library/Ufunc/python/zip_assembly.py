"""
The shared half of the nx-7-zip and nx-win-zip UFuncs (src\\UFuncs\\Nx7zip.py, src\\UFuncs\\NxWinZip.py): their Block
Styler dialog (Nx7zip.dlx / NxWinZip.dlx, tools\\make-dlx.py), the load options, and finding every part file of the
assembly. Each UFunc supplies its archiver, compression levels and archive extension through an Archiver.

Both forms (src\\UFuncs\\Nx7zip.cs and NxWinZip.cs, with their src\\Static halves - in git at f108562) were the same
apart from the archiver: Current Assembly (the displayed one) or Select Assembly (a .prt opened from disk, only with
nothing displayed), Save File (a SaveFileDialog), a compression combo, Zip File, and Close / Exit. The dialog folds
those into one page:

  - Assembly: the displayed part when there is one; otherwise an Assembly file box with Browse... (NX's own file
    box, UF_UI_create_filebox). An assembly opened from disk is closed again after the zip, as the form's OK did.
  - Archive: Save as (defaults to the assembly's folder and name with the archiver's extension) with Browse..., and
    the compression. NxWinZip adds Include Path.
  - OK writes the list of part files to %TEMP%\\zipData.txt and starts the archiver without waiting, as the forms
    did; Cancel does nothing. The Close button's "This will close the loaded assembly" question is gone: nothing is
    left open to close.

Differences from the C#:
  - The forms' Load Current "loaded" partially loaded parts with FindOrOpen (which only finds them) or Parts.Open
    (which fails on a loaded part); here each one is fully loaded (BasePart.LoadThisPartFully).
  - The part list is the display part plus one prototype per component DisplayName, unsuppressed and loaded (or
    quietly opened) - Nx7zip's GetAllChildComponents. NxWinZip's version also printed "Heer" for every loaded
    component and a line per unloaded one; those debug prints are gone.
  - An archiver that is not installed (WinZip is not, on this machine) is an error box, not a silent Popen failure.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Any, List, Optional, Sequence

import NXOpen
import NXOpen.Assemblies
import NXOpen.BlockStyler

import tsg_nx as nx
from tsg_dialog import Dialog, title_with_version

# NX will not build a Block Styler dialog from inside some callbacks (a menu or toolbar launch, it seems).
_ErrorCannotLaunchDialog = 3520048


class Archiver(object):
    """What differs between the two UFuncs."""

    def __init__(self, ufunc_name: str, title: str, dlx_name: str, exe: str,
                 compressions: Sequence[Any]) -> None:
        self.ufunc_name = ufunc_name
        self.title = title
        self.dlx_name = dlx_name
        # The executable without .exe, as the C# started it.
        self.exe = exe
        # (enum text in the .dlx, command-line switch, archive extension)
        self.compressions = list(compressions)

    def switch(self, compression: str) -> str:
        return next(c[1] for c in self.compressions if c[0] == compression)

    def extension(self, compression: str) -> str:
        return next(c[2] for c in self.compressions if c[0] == compression)

    def arguments(self, archive: str, list_file: str, compression: str, include_path: bool) -> str:
        raise NotImplementedError


def set_session_load_options() -> None:
    """Static.NxZipSetSessionLoadOptions - load as saved, all components, fully, with substitution."""
    # The LoadOptions property names and SetInterpartData(interpartOption, parentOption) are in the NXOpen.pyd
    # docstrings; the enum member names (AsSaved, All, Immediate) are assumed to match the .NET ones.
    load_options = nx.session_.Parts.LoadOptions
    load_options.ComponentLoadMethod = NXOpen.LoadOptions.LoadMethod.AsSaved
    load_options.ComponentsToLoad = NXOpen.LoadOptions.LoadComponents.All
    load_options.UsePartialLoading = False
    load_options.GenerateMissingPartFamilyMembers = False
    load_options.SetInterpartData(True, NXOpen.LoadOptions.Parent.Immediate)
    load_options.AbortOnFailure = False
    load_options.AllowSubstitution = True


def _load_fully() -> None:
    """The forms' loop over Session.Parts: every partially loaded part fully loaded."""
    parts = list(nx.session_.Parts)
    for index, part in enumerate(parts):
        nx.prompt("Loading parts {} of {}.".format(index + 1, len(parts)))
        if part.IsFullyLoaded:
            continue
        try:
            part.LoadThisPartFully()
        except Exception as ex:
            nx.print_exception(ex, "Could not fully load {}".format(part.FullPath))


def _all_child_components(assembly: NXOpen.Assemblies.Component,
                          all_components: List[NXOpen.Assemblies.Component]) -> None:
    """Static.Nx7zipGetAllChildComponents - every unsuppressed child under assembly that is loaded (or quietly
    opens), recursing into each."""
    try:
        for child in assembly.GetChildren():
            if child.IsSuppressed:
                continue

            instance = nx.ufsession_.Assem.AskInstOfPartOcc(child.Tag)
            if instance == 0:
                continue

            # The pyd docstring gives AskPartNameOfChild's rtype as "list of str"; accept either a str or a list.
            part_name_result = nx.ufsession_.Assem.AskPartNameOfChild(instance)
            part_name = part_name_result if isinstance(part_name_result, str) else part_name_result[0]

            if nx.ufsession_.Part.IsLoaded(part_name) != 1:
                # pyd: OpenQuiet(partName) -> (part, errorStatus); part is None (or the null tag) on failure.
                part_open, _load_status = nx.ufsession_.Part.OpenQuiet(part_name)
                if not part_open:
                    continue

            all_components.append(child)
            _all_child_components(child, all_components)
    except Exception as ex:
        nx.print_exception(ex)


def assembly_parts(display: NXOpen.Part) -> List[NXOpen.Part]:
    """ButtonLoadCurrent_Click - the display part and one prototype per component DisplayName under it."""
    root = display.ComponentAssembly.RootComponent
    if root is None:
        raise RuntimeError("Display Part is not an Assembly")

    components: List[NXOpen.Assemblies.Component] = []
    _all_child_components(root, components)

    parts = [display]
    names = set()
    for component in components:
        if component.DisplayName in names:
            continue
        names.add(component.DisplayName)
        if isinstance(component.Prototype, NXOpen.Part):
            parts.append(component.Prototype)
    return parts


def start_archiver(archiver: Archiver, archive: str, parts: Sequence[NXOpen.Part], compression: str,
                   include_path: bool) -> None:
    """Static.Nx7zipCreateZipFile / NxWinZipCreateZipFile - every part's FullPath into %TEMP%\\zipData.txt, then the
    archiver started on it, not waited on."""
    exe = archiver.exe + ".exe"
    if not os.path.isfile(exe):
        raise RuntimeError("{} is not installed here: {} is missing.".format(archiver.title, exe))

    # Path.GetTempPath() ends with a backslash.
    list_file = os.path.join(tempfile.gettempdir(), "") + "zipData.txt"
    # File.Open(FileMode.Create) truncates; StreamWriter writes UTF-8 without a BOM, WriteLine = CRLF.
    with open(list_file, "w", encoding="utf-8", newline="\r\n") as writer:
        for part in parts:
            writer.write(part.FullPath + "\n")

    arguments = archiver.arguments(archive, list_file, archiver.switch(compression), include_path)
    nx.syslog("{}: {} part files -> {}: {} {}".format(archiver.title, len(parts), archive, exe, arguments))
    subprocess.Popen('"{}" {}'.format(archiver.exe, arguments))
    nx.print_("{}: zipping {} part files into \"{}\" (the archiver runs on its own).".format(
        archiver.title, len(parts), archive))


def _file_box(title: str, pattern: str, default: str) -> Optional[str]:
    """NX's own file box (tsg_nx.select_file_or_none), opening in default's folder - the picked or typed path, None
    on Cancel."""
    folder = os.path.dirname(default) if default else ""
    filter_string = os.path.join(folder, pattern) if folder else pattern
    return nx.select_file_or_none(title, title, filter_string, os.path.basename(default) if default else "")


class ZipDialog(Dialog):
    """The assembly (displayed, or a file), the archive path and the compression. OK is greyed out until both
    paths are there."""

    def __init__(self, archiver: Archiver) -> None:
        self.archiver = archiver
        self.dlx_name = archiver.dlx_name
        self.title = title_with_version(archiver.title)
        super().__init__()
        # Captured in ok(): the blocks are gone once Launch returns.
        self.assembly_file = ""
        self.archive = ""
        self.compression = ""
        self.include_path = False
        self._default_archive = ""

    def initialize(self) -> None:
        displayed = nx.display_part() is not None
        self.block("assembly_file").Show = not displayed
        self.block("browse_assembly").Show = not displayed

    def shown(self) -> None:
        display = nx.display_part()
        if display is not None:
            self.block("assembly").Label = "Displayed: " + display.FullPath
        else:
            self.block("assembly").Label = "No part is displayed - pick the assembly file."
        self._refresh_archive()

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        if block == self.block("browse_assembly"):
            path = _file_box("Assembly to zip", "*.prt", self._assembly_path())
            if path:
                self.set_string_value(self.block("assembly_file"), path)
            self._refresh_archive()
        elif block == self.block("browse_zip"):
            current = self.string_value(self.block("zip_file"))
            path = _file_box("Save the archive as", "*" + self._extension(), current)
            if path:
                if not os.path.splitext(path)[1]:
                    path += self._extension()
                self.set_string_value(self.block("zip_file"), path)
        elif block in (self.block("assembly_file"), self.block("compression")):
            self._refresh_archive()

    def enable_ok(self) -> bool:
        return bool(self._assembly_path()) and bool(self.string_value(self.block("zip_file")))

    def ok(self) -> bool:
        self.assembly_file = self._assembly_path()
        self.archive = self.string_value(self.block("zip_file"))
        self.compression = self.block("compression").ValueAsString
        self.include_path = self._include_path()

        if nx.display_part() is None and not os.path.isfile(self.assembly_file):
            self.message("The assembly file \"{}\" does not exist.".format(self.assembly_file))
            return False

        folder = os.path.dirname(self.archive)
        if not folder or not os.path.isdir(folder):
            self.message("The folder \"{}\" does not exist.".format(folder))
            return False

        return True

    def _include_path(self) -> bool:
        try:
            return bool(self.block("dir_path").Value)
        except Exception:
            return False   # Nx7zip has no Include Path

    def _assembly_path(self) -> str:
        display = nx.display_part()
        return display.FullPath if display is not None else self.string_value(self.block("assembly_file"))

    def _extension(self) -> str:
        return self.archiver.extension(self.block("compression").ValueAsString)

    def _refresh_archive(self) -> None:
        """SaveZipFile's default - the assembly's folder and name - with this compression's extension. A path the
        user typed or browsed to keeps its folder and name; only its extension follows the compression."""
        current = self.string_value(self.block("zip_file"))
        assembly = self._assembly_path()
        default = os.path.splitext(assembly)[0] + self._extension() if assembly else ""

        if not current or current == self._default_archive:
            new = default
        else:
            stem, ext = os.path.splitext(current)
            known = {c[2] for c in self.archiver.compressions}
            new = stem + self._extension() if ext.lower() in known else current

        self._default_archive = default
        if new != current:
            self.set_string_value(self.block("zip_file"), new)


def run(archiver: Archiver) -> None:
    """The UFunc: the load options (MainForm_Load), the dialog, then the zip; an assembly opened from disk is closed
    again."""
    set_session_load_options()

    try:
        dialog = ZipDialog(archiver)
        accepted = dialog.run()
    except NXOpen.NXException as ex:
        if ex.ErrorCode != _ErrorCannotLaunchDialog:
            raise
        nx.print_exception(ex)
        nx.show_error("NX would not open the {} dialog (error {} - it will not create a dialog from inside a "
                      "callback).\n\nTry running it from File -> Execute -> NX Open rather than from a menu or "
                      "toolbar button.".format(archiver.title, _ErrorCannotLaunchDialog))
        return

    if not accepted:
        nx.print_("{} dialog was not accepted - nothing zipped.".format(archiver.title))
        return

    display = nx.display_part()
    opened: Optional[NXOpen.Part] = None

    if display is not None:
        # ButtonLoadCurrent_Click
        _load_fully()
        parts = assembly_parts(display)
    else:
        # ButtonSelectAssm_Click: open it, load it fully, and zip every part in the session.
        opened = nx.find_or_open(dialog.assembly_file)
        _load_fully()
        parts = [p for p in nx.session_.Parts if isinstance(p, NXOpen.Part)]

    try:
        if parts:
            start_archiver(archiver, dialog.archive, parts, dialog.compression, dialog.include_path)
    finally:
        if opened is not None:
            # Static.Nx7zipCloseAssembly: the whole tree, modified or not.
            opened.Close(NXOpen.BasePart.CloseWholeTree.TrueValue, NXOpen.BasePart.CloseModified.CloseModified,
                         None)
