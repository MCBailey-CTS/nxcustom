---
name: post
description: Build TSG_Library in Release and post the DLL into the Ufunc folder of every NX library (NX2306library, NX2406library, NX2506library), or just the versions given with --nx, under one or more plugin names (e.g. assembly-wavelink) using the rolling-backup convention. Does not commit.
---

# /post

Usage: `/post <name> [<name> ...] [--nx <version>[,<version> ...]] [--from <path>]`

- `<name>` is the plugin's DLL base name in `Ufunc/`, e.g. `assembly-wavelink`, `gm-seal`. Several may be given; they all receive the same build.
- **Libraries.** Each NX version has its own library at the repo root: `NX2306library`, `NX2406library`, `NX2506library` (launched by `NXstartup\NX<version>.bat`). By default `/post` posts to **every** `NX*library` folder at the repo root. `--nx 2406` or `--nx 2406,2506` limits it to those versions; an `--nx` version with no `NX<version>library` folder is an error — stop. Below, `<lib>` is each targeted library, and every step runs for every `<lib>`.
- Every plugin is the **same** `TSG_Library.dll` build, copied into `<lib>/Ufunc/` under the plugin's name. `/post` builds it itself in **Release**, and the source is the build output:

  `C:\Users\mcbailey\repos\tsg-library\TSG_Library\bin\Release\TSG_Library.dll`

  `--from <path>` skips the build and posts `<path>` instead. `<path>` may be a folder (use its `TSG_Library.dll`) or a full path to a `.dll`. The source file is **not** expected to be named `<name>.dll`.

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
   - `<lib>/Ufunc/<name>.dll` must be tracked in git. If not, stop — `/post` updates existing plugins; adding a new one also needs a ribbon button and bitmap. If the name looks like a typo of an existing plugin (e.g. `boss` for `gm-boss`), suggest the correction and ask.
   - `git status --short <lib>/Ufunc/<name>.dll` must be clean. If it's already modified, stop and ask: the previous release would then have to come from `git show HEAD:...`. If the user says to overwrite the uncommitted post, copy the new build over `<name>.dll` in place and keep the existing `<name>N.dll` (it still matches HEAD) — don't make another backup.

## For each `<lib>` and each `<name>`

3. Find the next free backup number `N` **in that library**: list files matching `^<name>[0-9]+\.dll$` in `<lib>/Ufunc/` (do not match `-dts` or other suffixed variants). `N` = highest + 1, or `1` if none. Never reuse or renumber a backup. Libraries number independently, so `N` may differ between them.
4. **Rename** (`mv`), do not copy, the current `<name>.dll` to `<name>N.dll`. The live DLL is often loaded by a running NX session; Windows allows renaming a loaded DLL but refuses to overwrite it, so a `cp` onto `<name>.dll` would fail. The renamed file is the rollback copy of the outgoing release.
5. Copy the source DLL to `<name>.dll` (a fresh file at the now-vacant name).
6. Sanity-check:
   - `git hash-object <lib>/Ufunc/<name>N.dll` equals `git rev-parse HEAD:<lib>/Ufunc/<name>.dll`.
   - `git hash-object <lib>/Ufunc/<name>.dll` differs from that. If it doesn't, the build hasn't changed since the last post — delete the new `<name>.dll`, `mv <name>N.dll` back to `<name>.dll`, and tell the user.
   - If step 4 or 5 fails partway (e.g. permission denied), restore the same way before stopping: the tree must never be left without a `<name>.dll`.
7. `grep -n '<name>\.dll' <lib>/ToolBars/startup/*.rtb` — informational; mention if nothing references it, but proceed.

## Once for all names

8. **Do not commit or push.** The user tests the posted build in NX first and will ask for the commit separately. Leave the files in the working tree and do not stage them.
9. Report: which libraries were posted to; per name, a table with one row per library giving the backup number and old → new byte sizes; the ribbon line(s) referencing each; and `git status --short <lib>/Ufunc/` for each library so the user can see exactly what is pending. Say plainly if any library was skipped.

When the user later asks to commit, stage only the `<name>.dll` / `<name>N.dll` pairs in each library (not `git add -A`), use the message `posted <name1>, <name2>, ...` (add `(NX2406 only)` or similar when not every library got it) plus the attribution trailer, and push only if asked.
