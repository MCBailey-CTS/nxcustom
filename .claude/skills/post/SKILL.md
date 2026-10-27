---
name: post
description: Build TSG_Library in Release and post the DLL into the Ufunc folder of every NX library (NX2306library, NX2406library, NX2506library), or just the versions given with --nx, under one or more plugin names (e.g. assembly-wavelink) using the rolling-backup convention. Also does first posts of new plugins that already have a ribbon button, and checks each name against TSG_Library's UFunc registry. Does not commit.
---

# /post

Usage: `/post <name> [<name> ...] [--nx <version>[,<version> ...]] [--from <path>]`

- `<name>` is the plugin's DLL base name in `Ufunc/`, e.g. `assembly-wavelink`, `gm-seal`. Several may be given; they all receive the same build.
- **Libraries.** Each NX version has its own library at the repo root: `NX2306library`, `NX2406library`, `NX2506library` (launched by `NXstartup\NX<version>.bat`). By default `/post` posts to **every** `NX*library` folder at the repo root. `--nx 2406` or `--nx 2406,2506` limits it to those versions; an `--nx` version with no `NX<version>library` folder is an error — stop. Below, `<lib>` is each targeted library, and every step runs for every `<lib>`.
- Every plugin is the **same** `TSG_Library.dll` build, copied into `<lib>/Ufunc/` under the plugin's name. `/post` builds it itself in **Release**, and the source is the build output:

  `C:\Users\mcbailey\repos\tsg-library\TSG_Library\bin\Release\TSG_Library.dll`

  `--from <path>` skips the build and posts `<path>` instead. `<path>` may be a folder (use its `TSG_Library.dll`) or a full path to a `.dll`. The source file is **not** expected to be named `<name>.dll`.
- **Python companions.** Some plugins call Python scripts through `PythonLibrary.Execute`, which loads them from a `python\` folder beside the DLL — so they go in `<lib>/Ufunc/python/`, shared by every plugin in that library. The source is the `python\` folder beside the source DLL (`...\bin\Release\python\`, or beside the `--from` DLL). When a posted name is in this table, its scripts are posted with it:

  | Plugin | Scripts |
  |---|---|
  | `point-component` | `PointComponent.py`, `tsg_nx.py` (imported by `PointComponent.py`) |
  | `auto-design` *(Python only)* | `AutoDesign.py`, `AutoDesign.dlx`, `DeadStrike.py`, `DeadStrike.dlx`, `DrawDie.py`, `GmBlankStation.py`, `GmBlankStationDialog.py`, `GmBlankStationDialog.dlx`, `GmCastPost.py`, `GmCastTrimPad.py`, `GmPierce.py`, `GmSplitForm.py`, `GmSplitFormDialog.py`, `GmSplitFormDialog.dlx`, `GmSplitFormWithPlateBackside.py`, `PointComponent.py`, `WireStartHole.py`, `progress_window.py`, `ProgressWindow.ps1`, `tsg_dialog.py`, `tsg_nx.py`, `usage_db.py`, `pyodbc.cp310-win_amd64.pyd` |
  | `dead-hit` *(Python only)* | `DeadStrike.py`, `DeadStrike.dlx`, `DrawDie.py`, `GmCastTrimPad.py`, `GmSplitForm.py`, `GmSplitFormDialog.py`, `GmSplitFormDialog.dlx`, `GmSplitFormWithPlateBackside.py`, `PointComponent.py`, `tsg_dialog.py`, `tsg_nx.py`, `usage_db.py`, `pyodbc.cp310-win_amd64.pyd` |
  | `profile-subtract` *(Python only)* | `ProfileSubtract.py`, `ProfileSubtract.dlx`, `GmBoss.py`, `DrawDie.py`, `PointComponent.py`, `tsg_dialog.py`, `tsg_nx.py`, `usage_db.py`, `pyodbc.cp310-win_amd64.pyd` |
  | `gm-boss` *(Python only; the Merlin "Cast Boss" button)* | `GmBoss.py`, `DrawDie.py`, `PointComponent.py`, `tsg_nx.py`, `usage_db.py`, `pyodbc.cp310-win_amd64.pyd` |
  | `gm-cast-post` *(Python only; the Merlin "Restrike" button)* | `GmCastPost.py`, `DrawDie.py`, `GmCastTrimPad.py`, `PointComponent.py`, `WireStartHole.py`, `tsg_nx.py`, `usage_db.py`, `pyodbc.cp310-win_amd64.pyd` |
  | `delete-wavelink-label` *(Python only)* | `DeleteWavelinkLabel.py`, `tsg_nx.py`, `usage_db.py`, `pyodbc.cp310-win_amd64.pyd` |
  | `gm-split-form` *(Python only; Backing Plate / SHCS From Backside are dialog checkboxes)* | `GmSplitForm.py`, `GmSplitFormDialog.py`, `GmSplitFormDialog.dlx`, `DrawDie.py`, `GmCastTrimPad.py`, `PointComponent.py`, `tsg_dialog.py`, `tsg_nx.py`, `usage_db.py`, `pyodbc.cp310-win_amd64.pyd` |
  | `nine-99-block` *(Python only)* | `Nine99.py`, `DrawDie.py`, `GmCastTrimPad.py`, `GmSplitForm.py`, `GmSplitFormDialog.py`, `GmSplitFormDialog.dlx`, `PointComponent.py`, `tsg_dialog.py`, `tsg_nx.py`, `usage_db.py`, `pyodbc.cp310-win_amd64.pyd` |

  When a plugin gains a script, add it here along with any module it imports from the `python\` folder (check its `import` lines, including imports inside functions), any `.dlx` dialog it names, and anything those load in turn.

  A *(Python only)* name has no DLL: its ribbon `ACTION` runs `${NXCUSTOM_LIB}\ufunc\python\<Script>.py` directly. For such a name, skip the `_Runner.cs` check and the DLL steps (post modes and steps 3–7); build as usual (the build refreshes `python\`), then do step 8 for its scripts. When committing, stage just those scripts.

Work from the repo root; paths below are relative to it. Do the steps in order and stop with a report if any check fails — this tree is live for every NX user, so don't improvise around a failed check.

## Build (skipped with `--from`)

0. Build the `TSG_Library` project in Release:

   ```powershell
   & 'C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe' `
       'C:\Users\mcbailey\repos\tsg-library\TSG_Library\TSG_Library.csproj' `
       /t:Build /p:Configuration=Release /p:Platform=AnyCPU /v:minimal /nologo /m
   ```

   The Release post-build step signs the DLL with `SignDotNet.exe`; NX won't load it unsigned. If MSBuild exits non-zero, or the output shows an error (including a signing failure), stop and report the errors — post nothing. Mention, but don't stop for, uncommitted changes in the tsg-library repo (`git -c safe.directory=C:/Users/mcbailey/repos/tsg-library -C C:/Users/mcbailey/repos/tsg-library status --short` — the repo is owned by a different Windows account than this session), since they are going into the posted build.

## Before touching anything

1. Resolve the source DLL and confirm it exists. Report its byte size and modified time. After a build, its modified time must be from the build just run; if it isn't, the build didn't write it — stop. With `--from`, if it's older than an hour or so, say so but proceed.
2. Check every `<name>` in every `<lib>` before changing anything, so a failure never leaves the libraries half-posted:
   - **The name must be one TSG_Library knows.** `Program.Main` picks the UFunc from its first argument, or, with none, from the DLL's file name, and looks it up in the `switch` in `C:\Users\mcbailey\repos\tsg-library\TSG_Library\src\UFuncs\_Runner.cs` (case labels are lowercase; lookup is case-insensitive). The name NX will pass is the first quoted argument of the ribbon `ACTION` that runs `<name>.dll` (e.g. `block-att-dialog.dll("block-att-dialog")`), or `<name>` itself when the `ACTION` passes none or no ribbon references it. That name must appear as `case "<that name>":` in `_Runner.cs`; if it doesn't, NX fails with "No UFunc is registered" — stop, and suggest the closest case label (e.g. `nine-99-block` for `nine99`). Older buttons pass `("UFUNC", "<Name>")`, which the current build reads as the name `UFUNC` and rejects. Several plugins (e.g. `grid`, `simplify-curves`, `gm-seal`) are older builds whose names aren't in `_Runner.cs`, so posting today's build over them would break a working button. When that happens, say so; if the DLL name itself is a case label, offer to change the `ACTION` to drop the arguments. Skip this check when `--from` points at a DLL that isn't `TSG_Library.dll`.
   - **Decide the post mode** from git and the file on disk:
     - **Update** — `<lib>/Ufunc/<name>.dll` is tracked and `git status --short` shows it clean. Steps 3–6 apply.
     - **Tracked but modified** — stop and ask: the previous release would then have to come from `git show HEAD:...`. If the user says to overwrite the uncommitted post, treat it as a re-post (below) but keep the existing `<name>N.dll` (it still matches HEAD) — don't make another backup.
     - **First post** — untracked and absent. Allowed only if a ribbon in `<lib>` already has an `ACTION` that runs it (`grep -in '\\ufunc\\<name>\.dll' <lib>/ToolBars/startup/*.rtb`); a new plugin needs its button first. If none does, stop: suggest a correction if the name looks like a typo of an existing plugin (e.g. `boss` for `gm-boss`), otherwise ask whether to add a button.
     - **Re-post of an uncommitted first post** — untracked but present (a first post not yet committed). Replace it without a backup: it was never released, so git has no copy to protect.
   - For each Python companion script of `<name>`: the source script must exist, and `git status --short <lib>/Ufunc/python/<script>` must be clean (untracked-and-absent is fine — that's a first post). If it's modified, stop and ask, as for the DLL.

## First post, or re-post of an uncommitted first post

For a `<lib>`/`<name>` in one of these modes, do this instead of steps 3–6, then carry on at step 7:

- **First post:** copy the source DLL to `<name>.dll` and confirm `git hash-object` of it equals the source's.
- **Re-post:** if `git hash-object <name>.dll` already equals the source's, change nothing and say so. Otherwise `mv <name>.dll <name>.dll.old` (NX may have it loaded, so don't copy over it), copy the source to `<name>.dll`, then delete `<name>.dll.old`. If the copy fails, `mv` the `.old` back before stopping. If the delete fails because NX has it open, leave it and tell the user.

## For each `<lib>` and each `<name>`

3. Find the next free backup number `N` **in that library**: list files matching `^<name>[0-9]+\.dll$` in `<lib>/Ufunc/` (do not match `-dts` or other suffixed variants). `N` = highest + 1, or `1` if none. Never reuse or renumber a backup. Libraries number independently, so `N` may differ between them.
4. **Rename** (`mv`), do not copy, the current `<name>.dll` to `<name>N.dll`. The live DLL is often loaded by a running NX session; Windows allows renaming a loaded DLL but refuses to overwrite it, so a `cp` onto `<name>.dll` would fail. The renamed file is the rollback copy of the outgoing release.
5. Copy the source DLL to `<name>.dll` (a fresh file at the now-vacant name).
6. Sanity-check:
   - `git hash-object <lib>/Ufunc/<name>N.dll` equals `git rev-parse HEAD:<lib>/Ufunc/<name>.dll`.
   - `git hash-object <lib>/Ufunc/<name>.dll` differs from that. If it doesn't, the build hasn't changed since the last post — delete the new `<name>.dll`, `mv <name>N.dll` back to `<name>.dll`, and tell the user.
   - If step 4 or 5 fails partway (e.g. permission denied), restore the same way before stopping: the tree must never be left without a `<name>.dll`.
7. `grep -n '<name>\.dll' <lib>/ToolBars/startup/*.rtb` — informational; mention if nothing references it, but proceed.
8. Post `<name>`'s Python companion scripts, if any: create `<lib>/Ufunc/python/` if missing and copy each script over `<lib>/Ufunc/python/<script>` **in place** — no numbered backups; Python files aren't locked by NX and git holds the previous version. Post a script shared by several names (e.g. `tsg_nx.py`) once per library. Note whether each is new, changed, or unchanged versus HEAD (`git hash-object` vs `git rev-parse HEAD:<path>`). If the DLL was rolled back in step 6 as unchanged but a script changed, still post the script and say so.

## Once for all names

9. **Do not commit or push.** The user tests the posted build in NX first and will ask for the commit separately. Leave the files in the working tree and do not stage them.
10. Report: which libraries were posted to; per name, a table with one row per library giving the backup number (or "none — first post" / "none — replaced uncommitted post") and old → new byte sizes; the Python scripts posted and whether each was new/changed/unchanged; the ribbon line(s) referencing each; and `git status --short <lib>/Ufunc/` for each library so the user can see exactly what is pending. Say plainly if any library was skipped. If `tsg_nx.py` (or another imported module) changed, remind the user that NX caches imported modules, so NX must be restarted to pick it up.

When the user later asks to commit, stage only the `<name>.dll` / `<name>N.dll` pairs and any posted `python/<script>` files in each library (not `git add -A`), use the message `posted <name1>, <name2>, ...` (add `(NX2406 only)` or similar when not every library got it) plus the attribution trailer, and push only if asked. For a first post there is no `<name>N.dll`: stage the new `<name>.dll`, plus the ribbon `.rtb` that adds its button if that is still uncommitted, and mark it `(new)` in the message, e.g. `posted nine-99-block (new)`.
