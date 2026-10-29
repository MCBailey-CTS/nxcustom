"""
Python port of the clean-job-directory UFunc (CleanJobDirectory, src\\UFuncs\\CleanJobDirectory.cs).
The C# wrapper was deleted 2026-10-22 (in git at f32694f): the UFunc's menu button runs this file's main().

Run from a fully loaded {job}-{op}-000 (op not 900, at most 3 digits). Every *.prt in the display part's folder
that is not the prototype of a component in the display assembly is 7-zipped into
{GFolder}\\[Design Information\\]FileCleanup\\{yyyy-MM-dd}-{op}-{n}-Cleanup.7z and then DELETED.

Run standalone: File -> Execute -> NX Open on this file runs main().

The delete conditions are the C#'s, deliberately including its sharp edges:
  - A file survives only when its path, built as Path.Combine(GetDirectoryName(display FullPath), file name), is
    EXACTLY (case-sensitive, ordinal) the FullPath of some loaded prototype in the assembly - a HashSet<string>
    with the default comparer.
  - The folder listing is Directory.GetFiles(dir, "*.prt", TopDirectoryOnly). It goes through the same Win32
    FindFirstFileW/FindNextFileW calls .NET Framework uses, so it matches exactly the same files (including the
    8.3 short-name quirk where "*.prt" also matches e.g. ".prtx" files).
  - The files are deleted after 7-Zip exits whether or not the archive was created; the C# only prints
    "Unsuccessfully created ...".

Differences from the C#:
  - The WinForms Yes/No MessageBox is the NX Question box; anything but Yes (including closing it) stops.
"""

from __future__ import annotations

import datetime
import os
import re
import subprocess
import sys
from typing import Iterator, List, Optional

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# From the source tree (src\UFuncs) the shared modules are in src\python; deployed, they are beside this file.
_shared_python = os.path.join(os.path.dirname(_here), "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402

import tsg_nx as nx  # noqa: E402

ufunc_name = "clean-job-directory"

# Globals.cs RegexDetail
RegexDetail = r"^(?P<customerNum>\d+)-(?P<opNum>\d+)-(?P<detailNum>\d+)$"

# NXMessageBox.Show return value for "Yes" on a Question dialog.
_MessageBoxYes = 1

_NewLine = "\r\n"

_FileCleanUp = "FileCleanup"


class CleanJobDirectory(object):

    @staticmethod
    def execute() -> None:
        """CleanJobDirectory.execute"""
        # Creates an instance of GFolderWithCtsNumber using the current Displayed Part as it's source.
        folder = _GFolder.create_or_null(nx.work_part().FullPath)

        if folder is None:
            nx.print_("{} - Clean Job Directory".format(nx.assembly_file_version()))
            nx.print_("The current work part does not reside within a GFolder.")
            return

        result = nx.message_box(
            "{} - Clean Job Directory".format(nx.assembly_file_version()),
            NXOpen.NXMessageBox.DialogType.Question,
            "Are you sure you want to run Clean Job Directory?")

        if result != _MessageBoxYes:
            return

        match = re.match(RegexDetail, nx.display_part().Leaf)

        if match is None or match.group(3) != "000":
            raise RuntimeError("Clean Job Directory must be ran from a -000 not located in a 900 folderWithCtsNumber.")

        displayed_part_op = match.group(2)

        if displayed_part_op == "900":
            raise RuntimeError("Clean Job Directory must be ran from a -000 not located in a 900 folderWithCtsNumber.")

        if len(displayed_part_op) > 3:
            raise RuntimeError("Clean Job Directory must be ran from a -000 not located in a 900 folderWithCtsNumber.")

        # Does two operations here.
        # 1. It gets all the part paths that define the currently displayed assembly.
        # 2. It is also checking to make sure that the assembly is fully loaded.
        # Throws exception if assembly is not fully loaded.
        # Creates a hashset of the part paths in the currently displayed assembly.
        hashed_assembly_part_paths = set(
            component.Prototype.FullPath
            for component in _find(nx.display_part().ComponentAssembly.RootComponent)
            if isinstance(component.Prototype, NXOpen.Part))

        # Gets the directory the Displayed Part resides in.
        displayed_part_directory = _get_directory_name(nx.display_part().FullPath)

        if displayed_part_directory is None:
            raise FileNotFoundError(nx.display_part().FullPath)

        part_files_in_directory = _get_files(displayed_part_directory, "*.prt")

        # Represents the part file paths in the displayed part directory that are not in the current assembly.
        # A list stands in for the HashSet (the listing has no duplicates) so the order is the insertion order.
        file_clean_up_set: List[str] = []

        for path in part_files_in_directory:
            flag = path in hashed_assembly_part_paths
            _syslog("Checking if {} is in displayed assembly. Result: {}.{}".format(path, _cs_bool(flag), _NewLine))

            if flag:
                continue

            flag = path not in file_clean_up_set
            if flag:
                file_clean_up_set.append(path)
            _syslog("{} was {} successfully added to the file cleanup set.{}".format(
                path, "" if flag else "not ", _NewLine))

        if len(file_clean_up_set) == 0:
            _syslog("Did not find any parts in current folderWithCtsNumber that are not loaded in current assembly. "
                    "Program terminated.")
            nx.print_("Did not find any parts in current folderWithCtsNumber that are not loaded in current assembly.")
            return

        # Check for a fileCleanup folder in the current GFolder.
        cleanup_directory = ("{}\\{}".format(folder.DirDesignInformation, _FileCleanUp)
                             if len(folder.CustomerNumber) == 6
                             else "{}\\{}".format(folder.DirJob, _FileCleanUp))

        if not os.path.isdir(cleanup_directory):
            _syslog("Directory {} does not exist.{}".format(cleanup_directory, _NewLine))
            _syslog("Creating directory {}.{}".format(cleanup_directory, _NewLine))
            os.makedirs(cleanup_directory, exist_ok=True)
            _syslog("Directory {} was successfully created.{}".format(cleanup_directory, _NewLine))

        start_directory = "{}-{}".format(_todays_date(), displayed_part_op)

        i = 0
        while True:
            temp_path = "{}\\{}-{}-Cleanup.7z".format(cleanup_directory, start_directory, i)

            if os.path.isfile(temp_path):
                i += 1
                continue

            zip_path = temp_path
            break

        for path in file_clean_up_set:
            _syslog("File to be zipped: {}.{}".format(path, _NewLine))

        _syslog("Creating zip file {}.{}".format(zip_path, _NewLine))
        _seven_zip(zip_path, True, file_clean_up_set)

        for path in file_clean_up_set:
            _syslog("Deleting file: {}.{}".format(path, _NewLine))
            _file_delete(path)


def _find(snap_comp: Optional[NXOpen.Assemblies.Component]) -> Iterator[NXOpen.Assemblies.Component]:
    """CleanJobDirectory.Find - the unsuppressed components under snap_comp (itself included), raising on any
    unsuppressed component whose prototype is not a loaded Part."""
    if snap_comp is None:
        raise ValueError("Value cannot be null.\r\nParameter name: snapComp")

    if not isinstance(snap_comp.Prototype, NXOpen.Part) and not snap_comp.IsSuppressed:
        # C# reads OwningComponent.DisplayName, which throws NullReferenceException on the root; same here.
        raise ValueError("Please fully load your assembly. {}{} .\r\nParameter name: snapComp".format(
            snap_comp.DisplayName, snap_comp.OwningComponent.DisplayName))

    if snap_comp.IsSuppressed:
        return

    yield snap_comp

    for child in snap_comp.GetChildren():
        for descendant in _find(child):
            yield descendant


def _get_directory_name(path: str) -> Optional[str]:
    """Path.GetDirectoryName - '/' normalised to '\\'; None for a root (or a bare file name gives "")."""
    normalized = path.replace("/", "\\")
    directory = os.path.dirname(normalized)
    if directory == normalized or (len(normalized) <= 3 and normalized.endswith("\\")):
        return None
    return directory


def _get_files(directory: str, search_pattern: str) -> List[str]:
    """
    Directory.GetFiles(directory, search_pattern, SearchOption.TopDirectoryOnly) - .NET Framework lists with
    FindFirstFileW/FindNextFileW and keeps the non-directories, returning Path.Combine(directory, name). This
    makes the same calls through ctypes so it matches exactly the same files (case-insensitive, 8.3 short names
    included).
    """
    import ctypes
    from ctypes import wintypes

    class _Win32FindDataW(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("dwReserved0", wintypes.DWORD),
            ("dwReserved1", wintypes.DWORD),
            ("cFileName", wintypes.WCHAR * 260),
            ("cAlternateFileName", wintypes.WCHAR * 14),
        ]

    file_attribute_directory = 0x10
    error_file_not_found = 2
    error_no_more_files = 18
    invalid_handle_value = ctypes.c_void_p(-1).value

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    find_first = kernel32.FindFirstFileW
    find_first.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(_Win32FindDataW)]
    find_first.restype = wintypes.HANDLE
    find_next = kernel32.FindNextFileW
    find_next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Win32FindDataW)]
    find_next.restype = wintypes.BOOL
    find_close = kernel32.FindClose
    find_close.argtypes = [wintypes.HANDLE]
    find_close.restype = wintypes.BOOL

    if not os.path.isdir(directory):
        raise FileNotFoundError("Could not find a part of the path '{}'.".format(directory))

    data = _Win32FindDataW()
    handle = find_first(os.path.join(directory, search_pattern), ctypes.byref(data))

    if handle is None or handle == invalid_handle_value:
        error = ctypes.get_last_error()
        if error == error_file_not_found:
            return []
        raise ctypes.WinError(error)

    files: List[str] = []
    try:
        while True:
            name = data.cFileName
            if name not in (".", "..") and not (data.dwFileAttributes & file_attribute_directory):
                files.append(os.path.join(directory, name))

            if not find_next(handle, ctypes.byref(data)):
                error = ctypes.get_last_error()
                if error != error_no_more_files:
                    raise ctypes.WinError(error)
                break
    finally:
        find_close(handle)

    return files


def _seven_zip(path: str, wait: bool, file_names: List[str]) -> None:
    """
    AssemblyExportDesignData.Export1.SevenZip(string path, bool wait, params string[] fileNames) and the
    SevenZip(path, wait, textFileToRead) overload it calls: writes the names to zipData.txt beside the archive,
    runs "7z a -t7z <path> @zipData.txt -mx9", optionally waits and prints whether the archive exists, and always
    deletes zipData.txt.
    """
    directory = _get_directory_name(path)
    list_file = "{}\\{}".format(directory, "zipData.txt")

    try:
        # File.Open(FileMode.Create) then a StreamWriter: UTF-8 without a BOM, CRLF line ends.
        with open(list_file, "w", encoding="utf-8", newline="\r\n") as stream_writer:
            for file_name in file_names:
                stream_writer.write(file_name + "\n")

        if not path:
            raise ValueError("Invalid path.\r\nParameter name: path")

        if os.path.isfile(path):
            raise IOError("The specified output_path already exists.")

        if not os.path.isfile(list_file):
            raise FileNotFoundError(list_file)

        file_to_read = "a -t7z \"" + path + "\" \"@" + list_file + "\" -mx9"

        process = subprocess.Popen('"C:\\Program Files\\7-Zip\\7z" ' + file_to_read)

        if not wait:
            return

        process.wait()

        nx.print_('Successfully created "{}".'.format(path) if os.path.isfile(path)
                  else 'Unsuccessfully created "{}".'.format(path))
    finally:
        _file_delete(list_file)


def _file_delete(path: str) -> None:
    """File.Delete - no error when the file does not exist."""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _syslog(message: str) -> None:
    """ufsession_.UF.PrintSyslog(message, false). The Python binding's class is NXOpen.UF.Uf, so the session
    attribute is Uf, not the C# UF."""
    nx.ufsession_.Uf.PrintSyslog(message, False)


def _cs_bool(value: bool) -> str:
    """bool.ToString() - "True"/"False"."""
    return "True" if value else "False"


def _todays_date() -> str:
    """Extensions.TodaysDate - yyyy-MM-dd."""
    today = datetime.date.today()
    return "{}-{:02d}-{:02d}".format(today.year, today.month, today.day)


class _GFolder(object):
    """GFolder (src\\Utilities\\GFolder.cs) - only the members CleanJobDirectory reads."""

    def __init__(self, dir_job: str, customer_number: str) -> None:
        self.DirJob = dir_job
        self.CustomerNumber = customer_number

    @property
    def DirDesignInformation(self) -> str:
        """GFolder.DirDesignInformation"""
        return "{}\\Design Information".format(self.DirJob)

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
        """GFolder.create_or_null(string) - prints the exception and returns None."""
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
    """The clean-job-directory UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("clean-job-directory"):
        try:
            CleanJobDirectory.execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()
