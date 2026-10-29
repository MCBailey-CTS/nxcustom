"""
The NX usage tables in CTSAPP on tsgapps2, written from Python the way the C# writes them (SessionRecord\\UsageDb.cs
and src\\Utilities\\UFuncUsage.cs): tblUFuncsExe (one row per UFunc run), tblExceptions, and the tblUsers /
tblUFuncs lookups they point at. Launch and close dates come from the server's clock. Tables:
tools\\sql\\usage-tables.sql.

For a UFunc an NX menu button runs as a .py, with no C# UFunc around it to record the run:

    with usage_db.run("split-form"):
        ...

Talks to SQL Server through pyodbc - pyodbc.cp310-win_amd64.pyd, which sits beside this file (NX's Python is
3.10 x64 and ships no SQL driver of its own) - over whichever Microsoft SQL Server ODBC driver the machine has. The
plain "SQL Server" driver comes with every Windows install, so there is always one.

Nothing here raises. A failure is written to the NX syslog, and after a failed connection every call is skipped for
_RetryAfterFailure, so a database outage costs one connect timeout rather than one per caught exception in a batch
loop.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import sys
import time
import traceback
from typing import Any, Callable, Iterator, Optional, TypeVar

# Session.Execute does not put the script's folder on sys.path, so pyodbc (beside this file) would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402

_T = TypeVar("_T")

# The same ADO.NET connection string as _UFunc.conn_str / SessionRecord's ConnectionString.CtsApp, hard-coded as
# the C# has it.
_ConnectionString = ("Data Source=tsgapps2.toolingsystemsgroup.com;Initial Catalog=CTSAPP;User ID=CTSAPP;"
                     "Password=RI4SU9d2JxH8LcrxSDPS")

# Newest first. ODBC Driver 18 encrypts by default, which needs TrustServerCertificate for tsgapps2's certificate.
_Drivers = ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server Native Client 11.0",
            "SQL Server")

# Short timeouts: NX waits on these calls at UFunc launch and close.
_ConnectTimeoutSeconds = 3
_CommandTimeoutSeconds = 5

_RetryAfterFailure = 5 * 60.0

# UsageDb.SessionIdVariable: SessionRecord publishes its tblSessions id in this process environment variable.
_SessionIdVariable = "TSG_NX_SESSION_ID"

_skip_until = 0.0

# The tblUsers id for this Windows user, cached once found: it cannot change within a process.
_user_id = 0

# The most recently started run: where an exception goes (NULL when none is open).
_current = 0

# What the innermost run() block's END banner reports: the dialog it was cancelled at, and the exceptions logged.
_cancelled_at: Optional[str] = None
_exceptions = 0

_BannerRule = "/" * 62


@contextlib.contextmanager
def run(ufunc_name: str) -> Iterator[int]:
    """
    Begin / End around the block; yields the tblUFuncsExe id (0 when it could not be written). Also writes the
    START / END banners to the NX syslog - written whether or not the database is reachable - and the END line says
    how the run ended: DONE (with the count of exceptions logged along the way), CANCELLED at the confirm or dialog
    that was declined (mark_cancelled), or FAILED when an exception escaped the block.
    """
    global _cancelled_at, _exceptions

    outer = (_cancelled_at, _exceptions)
    _cancelled_at, _exceptions = None, 0
    started = time.monotonic()
    name = ufunc_name.strip().lower()
    run_id = begin(ufunc_name)
    _start_banner(name, run_id)
    escaped: Optional[BaseException] = None
    try:
        yield run_id
    except BaseException as ex:
        escaped = ex
        raise
    finally:
        end(run_id)
        if escaped is not None:
            outcome = "FAILED ({})".format(type(escaped).__name__)
        elif _cancelled_at is not None:
            outcome = "CANCELLED at {}".format(_cancelled_at)
        else:
            outcome = "DONE" + (", {} exception(s) logged".format(_exceptions) if _exceptions else "")
        _log("<<< {} END  run {}  {}  elapsed {}".format(name, run_id, outcome, _elapsed(started)))
        _log(_BannerRule)
        _cancelled_at, _exceptions = outer


def mark_cancelled(where: str) -> None:
    """The user declined a confirm or cancelled a dialog: the current run's END banner says CANCELLED at where."""
    global _cancelled_at
    if _cancelled_at is None:
        _cancelled_at = where or "a dialog"


def begin(ufunc_name: str) -> int:
    """
    UFuncUsage.Begin - inserts a tblUFuncsExe row for ufunc_name, adding the name to tblUFuncs the first time it is
    seen, and returns the row's id, or 0 when it could not be written.
    """
    global _current

    def body(cursor: Any) -> int:
        cursor.execute(
            "SET NOCOUNT ON; "
            "DECLARE @ufunc_id int = (SELECT id FROM dbo.tblUFuncs WHERE name = ?); "
            "IF @ufunc_id IS NULL BEGIN "
            "    INSERT INTO dbo.tblUFuncs (name) VALUES (?); "
            "    SET @ufunc_id = SCOPE_IDENTITY(); "
            "END; "
            "INSERT INTO dbo.tblUFuncsExe (session_id, user_id, ufunc_id, process_id, syslog_path) "
            "OUTPUT INSERTED.id "
            "VALUES (?, ?, @ufunc_id, ?, ?)",
            _cut(name, 100), _cut(name, 100), _session_id(), _user(cursor), os.getpid(), _cut(_syslog_path(), 260))
        return int(cursor.fetchone()[0])

    name = ufunc_name.strip().lower()
    run_id = _run("begin '{}'".format(name), body, 0)
    if run_id > 0:
        _current = run_id
    return run_id


def end(run_id: int) -> None:
    """UFuncUsage.End - stamps date_closed on a tblUFuncsExe row. Does nothing for 0 or an already closed run."""
    global _current

    if run_id <= 0:
        return
    if _current == run_id:
        _current = 0

    def body(cursor: Any) -> int:
        # "date_closed IS NULL" keeps the first close.
        cursor.execute("UPDATE dbo.tblUFuncsExe SET date_closed = GETDATE() WHERE id = ? AND date_closed IS NULL",
                       run_id)
        return 0

    _run("end {}".format(run_id), body, 0)


def log_exception(ex: BaseException, user_message: Optional[str] = None) -> None:
    """
    UFuncUsage.LogException - inserts a tblExceptions row for ex, filed under the most recently started run (NULL
    when none is open). nx_error_code is the NXException code, NULL for any other type.
    """
    global _exceptions
    _exceptions += 1

    def body(cursor: Any) -> int:
        cursor.execute(
            "INSERT INTO dbo.tblExceptions "
            "(ufunc_exe_id, user_id, exception_type, message, user_message, nx_error_code, stack_trace) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            _current if _current > 0 else None, _user(cursor), _cut(exception_type, 200), str(ex), user_message,
            nx_error_code, stack_trace)
        return 0

    exception_type = "{}.{}".format(type(ex).__module__, type(ex).__qualname__)
    nx_error_code = ex.ErrorCode if isinstance(ex, NXOpen.NXException) else None
    stack_trace = "".join(traceback.format_exception(type(ex), ex, ex.__traceback__))
    _run("log_exception", body, 0)


def log_dialog(kind: str, title: Optional[str], dialog_type: Optional[str], message: Optional[str],
               response: Optional[str]) -> None:
    """
    UFuncUsage.LogDialog - inserts a tblDialogs row for a Block dialog ("block-dialog") or NXMessageBox
    ("message-box") that was shown, filed under the most recently started run (NULL when none is open).
    """
    def body(cursor: Any) -> int:
        cursor.execute(
            "INSERT INTO dbo.tblDialogs (ufunc_exe_id, user_id, kind, title, dialog_type, message, response) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            _current if _current > 0 else None, _user(cursor), _cut(kind, 20), _cut(title, 400),
            _cut(dialog_type, 40), message, _cut(response, 40))
        return 0

    _run("log_dialog", body, 0)


# ----- helpers -----

def _start_banner(name: str, run_id: int) -> None:
    """The START banner: run and session ids, version, user, process, the script and the display / work parts."""
    try:
        import tsg_nx
        version = tsg_nx.assembly_file_version()
    except Exception:
        version = ""
    script = getattr(sys.modules.get("__main__"), "__file__", None) or ""
    _log(_BannerRule)
    _log(">>> {} START  run {}  session {}".format(name, run_id, _session_id()))
    _log("    version {}   user {}   pid {}".format(version or "?", os.environ.get("USERNAME") or "?", os.getpid()))
    if script:
        _log("    script  {}".format(script))
    for label, part in (("display", _part("Display")), ("work", _part("Work"))):
        _log("    {} {}".format(label.ljust(7), "{}  ({})".format(part.Leaf, part.FullPath) if part else "(none)"))
    _log(_BannerRule)


def _part(which: str) -> Any:
    try:
        return getattr(NXOpen.Session.GetSession().Parts, which)
    except Exception:
        return None


def _elapsed(started: float) -> str:
    seconds = int(time.monotonic() - started)
    return "{:02d}:{:02d}:{:02d}".format(seconds // 3600, seconds // 60 % 60, seconds % 60)


def _run(what: str, body: Callable[[Any], _T], failed: _T) -> _T:
    """Connects and runs body on a cursor, committing, and returns failed instead of raising."""
    global _skip_until

    if time.monotonic() < _skip_until:
        return failed

    try:
        import pyodbc

        try:
            connection = pyodbc.connect(_connection_string(pyodbc.drivers()), timeout=_ConnectTimeoutSeconds)
        except Exception:
            _skip_until = time.monotonic() + _RetryAfterFailure
            raise

        try:
            connection.timeout = _CommandTimeoutSeconds
            cursor = connection.cursor()
            result = body(cursor)
            connection.commit()
            return result
        finally:
            connection.close()
    except Exception as ex:
        _log("usage_db: {} failed: {}".format(what, ex))
        return failed


def _connection_string(installed: Any) -> str:
    """_ConnectionString's ADO.NET keywords as an ODBC connection string for the newest installed driver."""
    ado = dict(part.split("=", 1) for part in _ConnectionString.split(";") if "=" in part)
    keys = {k.strip().lower(): v.strip() for k, v in ado.items()}

    driver = next((d for d in _Drivers if d in installed), _Drivers[-1])
    extra = "TrustServerCertificate=yes;" if driver == "ODBC Driver 18 for SQL Server" else ""
    return "DRIVER={{{}}};SERVER={};DATABASE={};UID={};PWD={{{}}};{}".format(
        driver, keys["data source"], keys["initial catalog"], keys["user id"], keys["password"].replace("}", "}}"),
        extra)


def _user(cursor: Any) -> int:
    """The tblUsers id for this Windows user, inserting the user the first time they are seen."""
    global _user_id

    if _user_id > 0:
        return _user_id

    user_name = _cut(os.environ.get("USERNAME") or "", 100)

    cursor.execute("SELECT id FROM dbo.tblUsers WHERE user_name = ?", user_name)
    row = cursor.fetchone()
    if row is not None and row[0] is not None:
        _user_id = int(row[0])
        return _user_id

    # Only a new user pays for the directory lookup.
    cursor.execute("INSERT INTO dbo.tblUsers (name, user_name) OUTPUT INSERTED.id VALUES (?, ?)",
                   _cut(_display_name() or user_name, 200), user_name)
    _user_id = int(cursor.fetchone()[0])
    return _user_id


def _display_name() -> Optional[str]:
    """The user's full name from Active Directory (GetUserNameEx NameDisplay), or None off the domain."""
    try:
        name_display = 3
        size = ctypes.c_ulong(0)
        get_user_name_ex: Any = getattr(ctypes, "windll").secur32.GetUserNameExW
        get_user_name_ex(name_display, None, ctypes.byref(size))
        if not size.value:
            return None
        buffer = ctypes.create_unicode_buffer(size.value)
        if not get_user_name_ex(name_display, buffer, ctypes.byref(size)):
            return None
        return buffer.value.strip() or None
    except Exception:
        return None


def _session_id() -> int:
    """
    The tblSessions id SessionRecord published for this process, or 0 when it isn't loaded. Read through the Win32
    call, not os.environ: that is a copy taken when NX started Python, and SessionRecord may publish after it.
    """
    try:
        buffer = ctypes.create_unicode_buffer(32)
        kernel32: Any = getattr(ctypes, "windll").kernel32
        if not kernel32.GetEnvironmentVariableW(_SessionIdVariable, buffer, len(buffer)):
            return 0
        value = int(buffer.value)
        return value if value > 0 else 0
    except Exception:
        return 0


def _syslog_path() -> Optional[str]:
    try:
        return NXOpen.Session.GetSession().LogFile.FileName
    except Exception:
        return None


def _log(message: str) -> None:
    try:
        NXOpen.Session.GetSession().LogFile.WriteLine(message)
    except Exception:
        pass  # Nowhere left to report it.


def _cut(value: Optional[str], size: int) -> Optional[str]:
    """A string cut to its column's length, as UsageDb.AddString does."""
    return value[:size] if value is not None and len(value) > size else value
