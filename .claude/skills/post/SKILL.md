---
name: post
description: Post the current TSG_Library.dll build into NX2306library/Ufunc under one or more plugin names (e.g. assembly-wavelink) using the rolling-backup convention. Does not commit.
---

# /post

Usage: `/post <name> [<name> ...] [--from <path>]`

- `<name>` is the plugin's DLL base name in `Ufunc/`, e.g. `assembly-wavelink`, `gm-seal`. Several may be given; they all receive the same build.
- Every plugin is the **same** `TSG_Library.dll` build, copied into `Ufunc/` under the plugin's name. The default source is:

  `C:\Users\mcbailey\repos\tsg-library\bin\DebugSignDotNet\TSG_Library.dll`

  `--from <path>` overrides it. `<path>` may be a folder (use its `TSG_Library.dll`) or a full path to a `.dll`. The source file is **not** expected to be named `<name>.dll`.

Work from the repo root; paths below are relative to it. Do the steps in order and stop with a report if any check fails — this tree is live for every NX user, so don't improvise around a failed check.

## Before touching anything

1. Resolve the source DLL and confirm it exists. Report its byte size and modified time so the user can see it is the build they just made. If it's older than an hour or so, say so — they may have forgotten to build — but proceed.
2. `git status --short NX2306library/Ufunc/` must be clean for every `<name>.dll` involved. If a `<name>.dll` is already modified in the working tree, stop: the previous release would then have to come from `git show HEAD:...`, so ask the user before continuing.

## For each `<name>`

3. `NX2306library/Ufunc/<name>.dll` must be tracked in git. If not, stop — `/post` updates existing plugins; adding a new one also needs a ribbon button and bitmap.
4. Find the next free backup number `N`: list files matching `^<name>[0-9]+\.dll$` in `Ufunc/` (do not match `-dts` or other suffixed variants). `N` = highest + 1, or `1` if none. Never reuse or renumber a backup.
5. **Rename** (`mv`), do not copy, the current `<name>.dll` to `<name>N.dll`. The live DLL is often loaded by a running NX session; Windows allows renaming a loaded DLL but refuses to overwrite it, so a `cp` onto `<name>.dll` would fail. The renamed file is the rollback copy of the outgoing release.
6. Copy the source DLL to `<name>.dll` (a fresh file at the now-vacant name).
7. Sanity-check:
   - `git hash-object NX2306library/Ufunc/<name>N.dll` equals `git rev-parse HEAD:NX2306library/Ufunc/<name>.dll`.
   - `git hash-object NX2306library/Ufunc/<name>.dll` differs from that. If it doesn't, the build hasn't changed since the last post — delete the new `<name>.dll`, `mv <name>N.dll` back to `<name>.dll`, and tell the user.
   - If step 5 or 6 fails partway (e.g. permission denied), restore the same way before stopping: the tree must never be left without a `<name>.dll`.
8. `grep -n '<name>\.dll' NX2306library/ToolBars/startup/*.rtb` — informational; mention if nothing references it, but proceed.

## Once for all names

9. **Do not commit or push.** The user tests the posted build in NX first and will ask for the commit separately. Leave the files in the working tree and do not stage them.
10. Report: per name, the backup number and old → new byte sizes; the ribbon line(s) referencing each; and `git status --short NX2306library/Ufunc/` so the user can see exactly what is pending.

When the user later asks to commit, stage only the `<name>.dll` / `<name>N.dll` pairs (not `git add -A`), use the message `posted <name1>, <name2>, ...` plus the attribution trailer, and push only if asked.
