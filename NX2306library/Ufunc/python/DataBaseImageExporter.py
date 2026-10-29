"""
Python port of the data-base-image-exporter UFunc (DataBaseImageExporter, src\\UFuncs\\DataBaseImageExporter.cs).
The C# wrapper was deleted 2026-10-22 (in git at f32694f): the UFunc's menu button runs this file's main().

Saves a 314 x 235 framed JPEG of the current display (white background) for the job database. The display part
must sit in a GFolder; the save dialog starts in G:\\CTS\\job-info\\pictures\\ named after the customer number,
or in the job folder when the part is on Q:\\.

Run standalone: File -> Execute -> NX Open on this file runs main().

Differences from the C#:
  - The WinForms SaveFileDialog is replaced by the NX file box (UF_UI_create_filebox, tsg_nx.select_file_or_none).
    The two SaveFileDialog defaults that matter are reproduced by hand: AddExtension (".jpg" is appended to a
    name with no extension) and OverwritePrompt (an existing file asks Yes/No; No re-opens the box).
"""

from __future__ import annotations

import os
import re
import sys
from typing import Optional

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# From the source tree (src\UFuncs) the shared modules are in src\python; deployed, they are beside this file.
_shared_python = os.path.join(os.path.dirname(_here), "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402

ufunc_name = "data-base-image-exporter"

# NXMessageBox.Show return value for "Yes" on a Question dialog.
_MessageBoxYes = 1


class DataBaseImageExporter(object):

    @staticmethod
    def execute() -> None:
        """DataBaseImageExporter.execute"""
        rev_name = nx.ufunc_rev_name(ufunc_name)
        nx.print_(rev_name)

        if nx.display_part() is None:
            nx.print_("There is no displayed part loaded")
            return

        folder = _GFolder.create_or_null(nx.display_part().FullPath)

        if folder is None:
            nx.print_("The current displayed part does not reside in a GFolder.")
            return

        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, rev_name)

        if "Q:\\" not in nx.display_part().FullPath:
            initial_directory = "G:\\CTS\\job-info\\pictures\\"
            file_name = folder.CustomerNumber
        else:
            initial_directory = folder.DirJob
            file_name = ""

        path = _save_jpg_dialog("{}: Save As".format(rev_name), initial_directory, file_name)

        if path is None:
            return

        # C# calls the obsolete UFDisp.CreateFramedImage (warning CS0618 suppressed); same call here.
        nx.ufsession_.Disp.CreateFramedImage(
            path,
            # The Python binding names the enums NXOpen.UF.Disp.* with the C-style members (JPEG, WHITE).
            NXOpen.UF.Disp.ImageFormat.JPEG,
            NXOpen.UF.Disp.BackgroundColor.WHITE,
            [0, 0],
            314,
            235)


def _save_jpg_dialog(title: str, initial_directory: str, file_name: str) -> Optional[str]:
    """
    The SaveFileDialog { Filter = "JPEG (.jpg)|*.jpg", Title = ..., InitialDirectory = ..., FileName = ... } in
    DataBaseImageExporter.execute. None unless the user accepts a file name.
    """
    filter_string = os.path.join(initial_directory, "*.jpg")

    while True:
        path = nx.select_file_or_none(title, title, filter_string, file_name)

        if path is None:
            return None

        # SaveFileDialog.AddExtension: the filter's extension goes on a name that has none.
        if not os.path.splitext(path)[1]:
            path += ".jpg"

        # SaveFileDialog.OverwritePrompt.
        if os.path.exists(path):
            answer = nx.message_box(
                title,
                NXOpen.NXMessageBox.DialogType.Question,
                "{} already exists.\nDo you want to replace it?".format(os.path.basename(path)))

            if answer != _MessageBoxYes:
                file_name = os.path.basename(path)
                continue

        return path


class _GFolder(object):
    """GFolder (src\\Utilities\\GFolder.cs) - only the members DataBaseImageExporter reads."""

    def __init__(self, dir_job: str, customer_number: str) -> None:
        self.DirJob = dir_job
        self.CustomerNumber = customer_number

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
        """GFolder.create_or_null(Part) / create_or_null(string) - prints the exception and returns None."""
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


def main() -> None:
    """The data-base-image-exporter UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("data-base-image-exporter"):
        try:
            # No dialog of its own: ask before doing anything (a logged Question box).
            if nx.confirm_execute("data-base-image-exporter"):
                DataBaseImageExporter.execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
