# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

This is an **NXcustom deployment tree** for Siemens NX 2306, used by CTS / Tooling Systems Group. It is not an application project — there is no build, no test suite, and no linter. It is a directory of configuration files, ribbon/menu definitions, macros, and pre-compiled NXOpen .NET plugin DLLs that NX reads at startup.

**The working copy lives on the production network share** (`\\masterdesign1.toolingsystemsgroup.com\ugsystem\nxcustom`). Every designer's NX shortcut launches from this same tree. A committed — or even just saved — change is live for all users the next time they start NX. There is no staging environment; be deliberate about edits.

Remote: `https://github.com/MCBailey-CTS/nxcustom.git`

## Startup chain

Understanding this order is essential — most "my change didn't take effect" problems trace to a variable being consumed before it was set.

1. **`NXstartup/NX2306.bat`** — the user-facing launcher. Sets `NXCUSTOM_NUMBER=2306` and the package name, derives `NXCUSTOM_DIR` (repo root) and `NXCUSTOM_LIB` (`<root>\NX2306library`) from its own location, then `call`s NX_common.bat and finally `start`s `%UGII_BASE_DIR%\nxbin\ugraf`.
2. **`NX2306library/NX_common.bat`** — locates the NX install by reading the registry (`HKLM\...\Unigraphics Solutions\Installed Applications`), *verifies the installed NX version matches `NXCUSTOM_NUMBER` and aborts if not*, picks the per-user settings folder via `NXCUSTOM_USER_SETTINGS_LOCATION` (currently `2` = `%HOMEDRIVE%%HOMEPATH%\NXcustom\2306`), sets `UGII_ENV_FILE`, and echoes the resolved variables to the console window.
3. **`NX2306library/NX_env.dat`** — the main environment file. Points NX at Customer Defaults, drafting standards, Menuscript, ToolBars, KF, Tables, and sets assorted `UGII_*` behavior flags. It `#include`s `NX_CAM_auto_env.dat` and `NX_env_routing.dat`, and — at the very bottom — optional includes guarded by `#if FILE`: `NX_env_routing.dat`, per-user overrides from `%HOMEDRIVE%%HOMEPATH%\NX\NX_env.dat` and `${UGII_USER_PROFILE_DIR}\NX_env.dat`, and `NX_env_internal.dat` (not present in this repo). `NXstartup/load_options.def` alongside the launcher holds the assembly load options.
4. **`NX2306library/custom_dirs.dat`** (located via `UGII_CUSTOM_DIRECTORY_FILE`) — lists the directories NX scans for menus, toolbars, dialogs, and UDO libraries: `$NXCUSTOM_MENUS`, `$NXCUSTOM_TOOL_BARS` (+ `\bitmaps`), `$NXCUSTOM_LIB\AutoLoad`, `$NXCUSTOM_DIR`, `$NXCUSTOM_LIB\KF`, `$NXCUSTOM_LIB\Templates`. Non-existent entries are silently ignored, which is how the same file works across sites.

### The `startup/` vs `application/` convention

Within each directory listed in `custom_dirs.dat`, NX auto-loads files from a `startup/` subfolder at session start, and from `application/<APP>/` only when the user enters that application. This is why `ToolBars/startup/rbn_cts.rtb` is always present but `ToolBars/application/ug_cam_geometry.tbr` only appears in Manufacturing. **A new ribbon or menu file must go in a `startup/` folder to be picked up.**

## Key environment variables

| Variable | Set in | Meaning |
|---|---|---|
| `NXCUSTOM_DIR` | NX2306.bat | repo root |
| `NXCUSTOM_LIB` | NX2306.bat | `<root>\NX2306library` — used in almost every path reference |
| `NXCUSTOM_MENUS` | NX_env.dat | `${NXCUSTOM_LIB}\Menuscript` |
| `NXCUSTOM_TOOL_BARS` | NX_env.dat | `${NXCUSTOM_LIB}\ToolBars\` |
| `NXCUSTOM_CUSTOMER_DEFAULTS_DIR` | NX_common.bat | `CustomerDefaults`, or `CustomerDefaults\Tc` in managed (Teamcenter) mode |
| `UGII_USER_PROFILE_DIR` | NX_common.bat | per-user settings, not in this repo |

Use `${NXCUSTOM_LIB}\...` in `.rtb`/`.men`/`.dat` files rather than absolute drive paths so the tree stays relocatable.

## Directory map

- **`NX2306library/Ufunc/`** — the bulk of the custom functionality: ~110 pre-compiled NXOpen .NET DLLs (`add-fasteners.dll`, `gm-seal.dll`, `assembly-export-design-data.dll`, …) plus the shared NXOpen/Snap/Office-interop assemblies they link against. **Source code is not in this repository**; DLLs are built from a separate `tsg-library` repo on the developer's machine (`C:\Users\<dev>\repos\tsg-library`) and copied in. Subfolders (`DetailNumberNote/`, `ExportImportData/`, `DwgTranslator/`, `PdfTranslator/`, `StepTranslator/`, `InfoUnitsIN/`, `InfoUnitsMM/`) each carry their own private copy of the dependency set.
- **`NX2306library/ToolBars/`** — `startup/rbn_cts.rtb` (the main "CTS Custom" ribbon tab, ~82 buttons), `startup/rbn_cts_help.rtb` (a "CTS Help" tab whose buttons have no `ACTION` lines, so they render but do nothing; one bitmap still points at a dead `U:\NX110\...` path), `startup/rbn_merlin.rtb`; `bitmaps/` (128 BMP icons, one per button); `macros/` (recorded `.macro` files); `application/` (per-application toolbar overrides).
- **`NX2306library/Menuscript/`** — `startup/ug_main_cts.men` adds the **CTS Help** cascade to the main menu bar (buttons shell out to Excel/PowerPoint/EXEs on the `U:` and `G:` shares); `startup/NX_title.men` sets the window title. `application/` holds a few older `.dll`/`.dlg` helpers.
- **`NX2306library/CustomerDefaults/`** — `.dpv` preference files (XML) with matching `.xsl` stylesheets. `Site/startup/nx_site.dpv` is the site-wide locked-preference set; `TC/` mirrors it for Teamcenter-managed mode (`NXCUSTOM_MANAGED_CUSTOMER_DEFAULTS=true` requires both sets be kept in sync). Also holds the `drafting_standards/` limit-fits tables.
- **`NX2306library/Grip/`** — 213 `.grx` files. These are **compiled** GRIP binaries, not editable text; the `.grs` sources are not in this repo. Only two are still wired into the ribbon (`part_doctor`, `identify`); the rest are legacy.
- **`NX2306library/AutoLoad/udo/`** — User-Defined Object libraries NX loads automatically so UDOs in existing parts resolve.
- **`NX2306library/Templates/`**, **`Tables/`** — file-new palette (`cts_templates.pax` + seed parts) and drafting table templates (`UGII_TABLE_TEMPLATES`).
- **`NX2306library/concept.cdf`** — the CTS color-definition file, referenced from `nx_site.dpv` as `$NXCUSTOM_LIB\concept.cdf`.
- **`delete_siemens_industry.bat`** — support script that wipes `%LOCALAPPDATA%\Siemens_Industry_Software` to clear a corrupt user cache.

## Ribbon (`.rtb`) file format

```
TITLE  CTS Custom
VERSION 170

BEGIN_GROUP CTS_SIMULATION
    LABEL Simulation

    BUTTON SimulationDataBuilder
        LABEL  Simulation Data Builder
        RIBBON_STYLE MEDIUM_IMAGE
        BITMAP ${NXCUSTOM_LIB}\toolbars\bitmaps\SimulationDataBuilder.bmp
        ACTION ${NXCUSTOM_LIB}\ufunc\simulation-data-builder.dll("simulation-data-builder")
END_GROUP
```

`ACTION` takes two distinct forms depending on how the DLL was authored — copy the form used by a neighboring button of the same vintage rather than guessing:
- `…\name.dll("entry-point-name")`
- `…\name.dll("UFUNC", "EntryPointName")`

`ACTION` may also point at a `.macro`, a `.grx`, a `.cs` journal, or a bare executable/`start` command (see `ug_main_cts.men` for the shell-out style).

Adding a button means three coordinated things: the DLL in `Ufunc/`, a matching BMP in `ToolBars/bitmaps/`, and the `BUTTON` block in the `.rtb`. A missing bitmap or a misspelled DLL name fails silently or with an obscure NX error at startup.

## Conventions

**Rolling DLL backups.** When a new build of a plugin is posted, the previous binary is kept as a numbered sibling: `copy-attributes.dll` is live, `copy-attributes1.dll` … `copy-attributes4.dll` are prior versions in age order. The unnumbered name is the one referenced by the ribbon. To post a new build: copy the current `foo.dll` to the next free `fooN.dll`, overwrite `foo.dll`, and commit both. Never renumber or delete the archive files — they are the rollback path. A `-dts` suffix (`assembly-color-code-dts.dll`) marks a customer/site-specific variant.

**Local-dev hook buttons.** To test an unreleased build, the developer temporarily points a `BUTTON`'s `ACTION` at a local path (`C:\Users\<dev>\repos\tsg-library\bin\...\*.dll`) or the `G:\CTS\junk\merlin\` scratch folder. Because this file is live for every user, **never commit an `ACTION` that references a local drive or scratch path** — before committing an `.rtb`, `grep -n 'ACTION [CG]:' NX2306library/ToolBars/startup/*.rtb` should come back empty (or only list the known-in-progress `rbn_merlin.rtb`). Release means copying the DLL into `Ufunc/` and switching the `ACTION` to `${NXCUSTOM_LIB}\ufunc\...`.

**Commit messages** in this repo follow the pattern "posted \<tool names\>" and describe which plugins were deployed. Keep that style.

**Binary-heavy history.** Roughly 190 DLLs and 128 BMPs are tracked. `git diff` is useless on them; rely on commit messages and file sizes.

## Known-broken ribbon entries in `ToolBars/startup/rbn_cts.rtb`

These are pre-existing defects, worth knowing before debugging a "button does nothing" report:

- Line ~146: `tap-ream-contro.dll` — typo; the file on disk is `tap-ream-control.dll`.
- Line ~384: `ACTION ${NXCUSTOM_LIB}\ufunc\("UFUNC", "UnHighlight").dll("unhighlight")` — the DLL name and argument list were transposed; should be `unhighlight.dll("UFUNC", "UnHighlight")`.
- Two buttons (`part_doctor`, `identify`) still resolve GRIP programs through an absolute **NX1899** path on `P:\CTS_Programs\...` rather than `${NXCUSTOM_LIB}\Grip\`.
- `ToolBars/startup/rbn_merlin.rtb` points every button at `G:\CTS\junk\merlin\*.dll` — a developer scratch directory outside this repo, not `${NXCUSTOM_LIB}`. This tab is in-progress work, not a stable deployment.

## Verifying a change

There is nothing to run in-repo. The only real test is launching `NXstartup\NX2306.bat` and confirming the console banner reports the expected `NXCUSTOM_DIR` / `NXCUSTOM_LIB` / `UGII_SITE_DIR`, then checking that the ribbon tab or menu item appears and its action fires. The console window stays up long enough (`CMD_PAUSE=60`) to read the resolved variables; setting `NXCUSTOM_SUPPRESS_VARIABLES_DISPLAY` hides that banner.
