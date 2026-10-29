"""
Python port of the NX work in the SimulationDataBuilder form (src\\UFuncs\\SimulationDataBuilder.cs). The C# now
lives in src\\Static\\SimulationDataBuilder.cs as static members of TSG_Library.Static.

Ported from:
  - Static.SimulationDataBuilderBuildFilesExportIges -> SimulationDataBuilder.build_files_export_iges
  - Static.SimulationDataBuilderStep                 -> SimulationDataBuilder.step
  - Static.SimulationDataBuilderIges                 -> SimulationDataBuilder.iges
  - Static.SimulationDataBuilderAddNewSurface        -> SimulationDataBuilder.add_new_surface
  - Static.SimulationDataBuilderCheckName            -> SimulationDataBuilder.check_name
  - Static.SimulationDataBuilderExportPart           -> SimulationDataBuilder.export_part
  - the OK branch of Static.SimulationDataBuilderSimDataDeletion, with SimulationDataBuilderDeleteFiles and
    SimulationDataBuilderCloseAndDelete -> SimulationDataBuilder.delete_sim_data
  - GFolder.create_or_null(Part) / DirJob / dir_surfaces -> _GFolder (only the members this module reads)

Not ported:
  - Static.SimulationDataBuilderSelectObjects: the UF_UI_select_with_class_dialog pick. Selection stays C#.
  - Static.SimulationDataBuilderNameBuilder and the SimulationDataBuilderCombo*Items lists: string building and
    combo-box contents, no NX work. The caller passes the built name.
  - The rest of Static.SimulationDataBuilderSimDataDeletion - the component pick, the file search and the
    SimDataDeleteConfirm WinForms list. The search's only consumer is that dialog, and Session.Execute cannot hand
    the found list back to C#, so only what runs after the user presses OK is ported.
  - The form's event handlers (ButtonSelect_Click's "Replace file?" MessageBox and close-and-delete of the existing
    component, ResetForm, the operation combo's version guess, ...).

WIRED (2026-10-21), in src\\Static\\SimulationDataBuilder.cs:
  - Static.SimulationDataBuilderSelectAndExport (the Select button's body) calls check_name (its bool comes back as
    a UInt32 and goes through Convert.ToBoolean; a null operation is sent as "") and, through
    SimulationDataBuilderBuildFilesExportIgesPython, build_files_export_iges with the picked tags as TaggedObjects
    (Session.Execute cannot pass a Tag[]).
  - Static.SimulationDataBuilderSimDataDeletion's OK branch calls
        delete_sim_data(filesToDelete.ToArray(), selComponents.Cast<TaggedObject>().ToArray()).
The C# these replaced (BuildFilesExportIges, Step, Iges, AddNewSurface, CheckName, ExportPart, DeleteFiles,
CloseAndDelete) is commented out there. The pick, the "Replace file?" MessageBox and the close-and-delete of the
existing component in SelectAndExport stay C#.

This module has NEVER BEEN RUN IN NX.

Differences from the C# / unconfirmed bindings:
  - The WinForms boxes are NX Question boxes: build_files_export_iges's "Part ... already exists" (YesNo) and
    check_name's "Replace file ...?" (OKCancel). Yes = 1 (as in CleanJobDirectory.py) is taken as Yes / OK; any
    other answer is No / Cancel.
  - The C# throws ArgumentException(message, paramName), whose Message carries a second
    "Parameter name: ..." line; here it is a plain Exception with the first line only.
  - File.Delete is a no-op on a missing file; _file_delete keeps that.
  - NXOpen.UF.Part.ExportOptions (NewPart / ExpressionMode / ParamsMode) and ExportExpMode.COPY_EXP_DEEPLY /
    ExportParamsMode.REMOVE_PARAMS are read off the NXOpen_UF.pyd strings; that the struct is built with no
    arguments and ExportWithOptions takes it by value (the C# passes it by ref) is assumed, as in
    BlankDataBuilder.py (src\\UFuncs).
  - The StepCreator / IgesCreator property names (ExportFrom, ObjectTypes, FileSaveFlag, LayerMask, MapTabCylToBSurf,
    BcurveTol, IdenticalPointResolution, MaxThreeDMdlSpace, MaxLineThickness, SysDef*, DrawingList, ViewList) and
    ExportFromOption.ExistingPart are confirmed only as strings in NXOpen.pyd.
  - File.Copy -> shutil.copy2.
"""

from __future__ import annotations

import ntpath
import os
import re
import shutil
import sys
from typing import List, Optional, Sequence

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402

# Extensions.__SimActive (Globals.cs _simActive); also Static.SimulationDataBuilderSimActive.
_SimActive = "P:\\CTS_SIM\\Active"

# NXMessageBox.Show's return value for Yes on a Question dialog (CleanJobDirectory.py).
_MessageBoxYes = 1


class SimulationDataBuilder(object):

    @staticmethod
    def build_files_export_iges(part_file: str, tag_objects: Sequence[NXOpen.TaggedObject], name_builder: str,
                                operation: str, selected_operation: str, data_level: str, is_prt: bool,
                                is_iges: bool, is_stp: bool) -> None:
        """Static.SimulationDataBuilderBuildFilesExportIges - exports the picked objects to part_file and to
        {job}\\Simulation\\surfaces\\{name}.prt, builds the sim folder under P:\\CTS_SIM\\Active, adds the surface
        part to the display part, then copies the .prt / writes the .igs and/or writes the .stp into
        data\\{operation}. selected_operation is $"{cmbOperation.SelectedItem}", operation cmbOperation.Text."""
        if os.path.isfile(part_file):
            result = nx.message_box(
                "Question?",
                NXOpen.NXMessageBox.DialogType.Question,
                "Part {} already exists. Do you want to save over it?".format(part_file))

            if result == _MessageBoxYes:
                _file_delete(part_file)
            else:
                return

        folder = _GFolder.create_or_null(nx.work_part().FullPath)

        if folder is None:
            # C#: InvalidOperationException
            raise Exception("The current work part does not reside within a GFolder.")

        SimulationDataBuilder.export_part(part_file, tag_objects)
        # get path to sim location, check directory structure
        comp_surface_directory = folder.dir_surfaces()

        # export part to simulation\surfaces directory
        if not os.path.isdir(comp_surface_directory):
            os.makedirs(comp_surface_directory, exist_ok=True)

        comp_surface_directory += "\\{}.prt".format(name_builder)
        SimulationDataBuilder.export_part(comp_surface_directory, tag_objects)
        sim_dir = "{}-{}".format(_file_name_without_extension(folder.DirJob), data_level)
        sim_path_sim_dir = "{}\\{}".format(_SimActive, sim_dir)

        if not os.path.isdir(sim_path_sim_dir):
            os.makedirs(sim_path_sim_dir, exist_ok=True)

        if not os.path.isdir("{}\\data".format(sim_path_sim_dir)):
            os.makedirs("{}\\data".format(sim_path_sim_dir), exist_ok=True)

        if not os.path.isdir("{}\\reports".format(sim_path_sim_dir)):
            os.makedirs("{}\\reports".format(sim_path_sim_dir), exist_ok=True)

        if not os.path.isdir("{}\\data\\fShapes".format(sim_path_sim_dir)):
            os.makedirs("{}\\data\\fShapes".format(sim_path_sim_dir), exist_ok=True)

        SimulationDataBuilder.add_new_surface(comp_surface_directory, operation, name_builder)
        # export blank iges data
        # Removed code below for exporting iges files according to CTS-CIT Item# 2014-0011 Simulation Data Builder
        # Change - 2014-03 Duane VW
        sim_path_dir_data = "{}\\data".format(sim_path_sim_dir)
        operation_dir = "{}\\{}".format(sim_path_dir_data, selected_operation)

        if is_prt:
            if not os.path.isdir(operation_dir):
                os.makedirs(operation_dir, exist_ok=True)

            prt_copy = "{}\\{}.prt".format(operation_dir, name_builder)

            if os.path.isfile(prt_copy):
                os.remove(prt_copy)

            shutil.copy2(comp_surface_directory, prt_copy)

            nx.print_("Copied to : {}".format(prt_copy))
        elif is_iges:
            iges_directory = operation_dir

            if not os.path.isdir(iges_directory):
                os.makedirs(iges_directory, exist_ok=True)

            SimulationDataBuilder.iges(comp_surface_directory, "{}\\{}.igs".format(iges_directory, name_builder))

            nx.print_("Created: {}\\{}.igs".format(iges_directory, name_builder))
        elif not is_stp:
            return

        if not os.path.isdir(operation_dir):
            os.makedirs(operation_dir, exist_ok=True)

        stp_path = "{}\\{}.stp".format(operation_dir, name_builder)

        if os.path.isfile(stp_path):
            os.remove(stp_path)

        SimulationDataBuilder.step(comp_surface_directory, stp_path)
        nx.print_("Created: {}".format(stp_path))

    @staticmethod
    def step(part_path: str, dwg_path: str) -> None:
        """Static.SimulationDataBuilderStep - AP214 STEP of an existing part file. The creator is not destroyed,
        like the C#."""
        try:
            if not os.path.isfile(part_path):
                raise Exception("Path to part does not exist.")

            if os.path.isfile(dwg_path):
                raise Exception("Path for Step file already exists.")

            if os.path.isfile(dwg_path):
                raise Exception("Path for Step file already exists.")

            step_creator1 = nx.session_.DexManager.CreateStepCreator()
            step_creator1.ExportAs = NXOpen.StepCreator.ExportAsOption.Ap214
            step_creator1.ExportFrom = NXOpen.StepCreator.ExportFromOption.ExistingPart
            step_creator1.ObjectTypes.Solids = True
            step_creator1.InputFile = part_path
            step_creator1.OutputFile = dwg_path
            step_creator1.ObjectTypes.Curves = True
            step_creator1.ObjectTypes.Surfaces = True
            step_creator1.ObjectTypes.Solids = True
            step_creator1.FileSaveFlag = False
            step_creator1.ProcessHoldFlag = True
            step_creator1.LayerMask = "1-256"
            step_creator1.Commit()
        except Exception as ex:
            nx.print_exception(ex, "Error when creating Step file for " + part_path)

    @staticmethod
    def iges(new_part_file: str, iges_path: str) -> None:
        """Static.SimulationDataBuilderIges - IGES of an existing part file with the NX 11 igesexport.def settings.
        Like the C#, the creator is destroyed only when Commit succeeds."""
        try:
            iges_creator = nx.session_.DexManager.CreateIgesCreator()
            iges_creator.ExportModelData = True
            iges_creator.ExportDrawings = True
            iges_creator.MapTabCylToBSurf = True
            iges_creator.BcurveTol = 0.050799999999999998
            iges_creator.IdenticalPointResolution = 0.001
            iges_creator.MaxThreeDMdlSpace = 10000.0
            iges_creator.ObjectTypes.Curves = True
            iges_creator.ObjectTypes.Surfaces = True
            iges_creator.ObjectTypes.Annotations = True
            iges_creator.ObjectTypes.Structures = True
            iges_creator.ObjectTypes.Solids = True
            iges_creator.ExportFrom = NXOpen.IgesCreator.ExportFromOption.ExistingPart
            iges_creator.SettingsFile = "C:\\Program Files\\Siemens\\NX 11.0\\iges\\igesexport.def"
            iges_creator.MaxLineThickness = 2.0
            iges_creator.SysDefmaxThreeDMdlSpace = True
            iges_creator.SysDefidenticalPointResolution = True
            iges_creator.InputFile = new_part_file
            iges_creator.OutputFile = iges_path
            iges_creator.FileSaveFlag = False
            iges_creator.LayerMask = "1-256"
            iges_creator.DrawingList = ""
            iges_creator.ViewList = "Top,Front,Right,Back,Bottom,Left,Isometric,Trimetric,User Defined"
            iges_creator.ProcessHoldFlag = False
            iges_creator.Commit()
            iges_creator.Destroy()
        except Exception as ex:
            nx.print_exception(ex, "Error when creating Iges file for " + iges_path)

    @staticmethod
    def add_new_surface(comp_surface_path: str, combo_box_text: str, name_builder: str) -> None:
        """Static.SimulationDataBuilderAddNewSurface - adds the surface part to the display part on a layer picked
        from the operation (dN -> N*10+1, tN -> N*10+101, b -> 101, Unfold 199, MidSurfCurve/RefData 201), then saves
        the display part with its components."""
        base_part1 = nx.find_or_open(comp_surface_path)
        layer = 1

        if combo_box_text.startswith("d"):
            for i in range(1, 10):
                if str(i) in combo_box_text:
                    layer = i * 10 + 1
        elif combo_box_text.startswith("t"):
            for i in range(1, 10):
                if str(i) in combo_box_text:
                    layer = i * 10 + 101
        elif combo_box_text.startswith("b"):
            layer = 101
        elif combo_box_text == "Unfold":
            layer = 199
        elif combo_box_text == "MidSurfCurve" or combo_box_text == "RefData":
            layer = 201
        else:
            layer = 1

        nx.add_component(nx.display_part(), base_part1, component_name=name_builder, layer=layer)
        nx.print_("Added Component: {}".format(name_builder))
        # __Save(true): save components, don't close.
        nx.display_part().Save(NXOpen.BasePart.SaveComponents.TrueValue, NXOpen.BasePart.CloseAfterSave.FalseValue)

    @staticmethod
    def check_name(part_name: str, engineering: str, operation: str, sim_path: str, name_builder: str,
                   tsg_num: str) -> bool:
        """Static.SimulationDataBuilderCheckName - False when there is no operation or the user declines; when a
        child of the display part already has part_name, closes and deletes its part file and the component, and
        deletes the matching files in {sim}\\data\\{operation}. The bool reaches C# as a UInt32 (Convert.ToBoolean);
        an empty operation ("" for C# null) counts as none."""
        if not operation:
            return False

        root = nx.root_component(nx.display_part())

        if root is None:
            return True

        children_comps = [component for component in root.GetChildren() if component.DisplayName == part_name]

        if len(children_comps) == 0:
            return True

        # If the program gets here then there must already be a child with that name.
        result = nx.message_box(
            "File Exist",
            NXOpen.NXMessageBox.DialogType.Question,
            "Replace file {}?".format(name_builder))

        if result != _MessageBoxYes:
            return False
        part = nx.find_or_open(children_comps[0].DisplayName)
        part_file_path = part.FullPath
        # __Close(true, true)
        part.Close(NXOpen.BasePart.CloseWholeTree.TrueValue, NXOpen.BasePart.CloseModified.CloseModified, None)
        _file_delete(part_file_path)
        _delete_objects(children_comps)

        folder = _GFolder.create_or_null(nx.work_part().FullPath)

        if folder is None:
            # C#: InvalidOperationException
            raise Exception("The current work part does not reside within a GFolder.")

        # Unused, as in the C#.
        _eng = "" if not engineering else " {}".format(engineering)
        sim_folder = "{}\\{}-{}".format(sim_path, _file_name_without_extension(folder.DirJob), tsg_num)
        temp = "{}\\data\\{}".format(sim_folder, operation)

        # Revision 3.1
        files = [path for path in _directory_get_files(temp)
                 if _file_name_without_extension(path).lower() == part_name.lower()]

        for file in files:
            _file_delete(file)
        return True

    @staticmethod
    def export_part(part_file: str, tag_objects: Sequence[NXOpen.TaggedObject]) -> None:
        """Static.SimulationDataBuilderExportPart - UF_PART_export_with_options into a new part, expressions copied
        deeply, parameters removed. Deletes {part_file}.prt first (not part_file itself), like the C#."""
        if os.path.isfile("{}.prt".format(part_file)):
            os.remove("{}.prt".format(part_file))

        tags = [obj.Tag for obj in tag_objects]

        # Binding read off the pyd, not confirmed in NX - see the module docstring.
        export_options = NXOpen.UF.Part.ExportOptions()
        export_options.NewPart = True
        export_options.ExpressionMode = NXOpen.UF.Part.ExportExpMode.COPY_EXP_DEEPLY
        export_options.ParamsMode = NXOpen.UF.Part.ExportParamsMode.REMOVE_PARAMS

        nx.ufsession_.Part.ExportWithOptions(part_file, len(tags), tags, export_options)
        nx.print_("Created: {}".format(part_file))

    @staticmethod
    def delete_sim_data(files_to_delete: Sequence[str],
                        sel_components: Sequence[NXOpen.Assemblies.Component]) -> None:
        """The OK branch of Static.SimulationDataBuilderSimDataDeletion: SimulationDataBuilderDeleteFiles, then
        SimulationDataBuilderCloseAndDelete, then saves the display part (__Save(): components too)."""
        # SimulationDataBuilderDeleteFiles
        for file in files_to_delete:
            _file_delete(file)

        # SimulationDataBuilderCloseAndDelete
        for comp in sel_components:
            proto = comp.Prototype

            if isinstance(proto, NXOpen.Part):
                proto.Close(NXOpen.BasePart.CloseWholeTree.FalseValue, NXOpen.BasePart.CloseModified.CloseModified,
                            None)

            _delete_objects([comp])

        nx.display_part().Save(NXOpen.BasePart.SaveComponents.TrueValue, NXOpen.BasePart.CloseAfterSave.FalseValue)


def _delete_objects(objects: Sequence[NXOpen.TaggedObject]) -> None:
    """Session.__DeleteObjects / TaggedObject.__Delete - adds the objects to the delete list inside a DoUpdate.

    Private copy: tsg_nx.delete_objects is defined twice with different signatures."""
    with nx.do_update():
        nx.session_.UpdateManager.AddObjectsToDeleteList(list(objects))


def _file_delete(path: str) -> None:
    """File.Delete - a missing file is not an error."""
    if os.path.isfile(path):
        os.remove(path)


def _directory_get_files(path: str) -> List[str]:
    """Directory.GetFiles(path) - the full paths of the files directly in path; raises when it does not exist."""
    return [ntpath.join(path, name) for name in os.listdir(path) if os.path.isfile(ntpath.join(path, name))]


def _file_name_without_extension(path: str) -> str:
    """Path.GetFileNameWithoutExtension"""
    return ntpath.splitext(ntpath.basename(path))[0]


class _GFolder(object):
    """GFolder (src\\Utilities\\GFolder.cs) - only the members SimulationDataBuilder reads."""

    def __init__(self, dir_job: str, customer_number: str) -> None:
        self.DirJob = dir_job
        self.CustomerNumber = customer_number

    @property
    def DirSimulation(self) -> str:
        """GFolder.DirSimulation"""
        return "{}\\Simulation".format(self.DirJob)

    def dir_surfaces(self) -> str:
        """GFolder.dir_surfaces"""
        return "{}\\surfaces".format(self.DirSimulation)

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
