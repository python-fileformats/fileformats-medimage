import json
import tempfile
import typing as ty
from pathlib import Path

from fileformats.application import Json
from fileformats.core import converter
from fileformats.core.typing import PathType
from fileformats.generic import Directory, File  # noqa: F401
from fileformats.vendor.mrtrix3.medimage import ImageIn, ImageOut, Tracks  # noqa: F401
from pydra.compose import python, workflow
from pydra.tasks.dcm2niix import Dcm2Niix
from pydra.tasks.mrtrix3.v3_1 import MrConvert

from fileformats.medimage import (
    Analyze,
    MedicalImage,
    Nifti,
    NiftiBvec,
    NiftiGz,
    NiftiGzBvec,
    NiftiGzX,
    NiftiGzXBvec,
    NiftiX,
    NiftiXBvec,
)
from fileformats.medimage.dicom import DicomCollection, DicomDir, DicomSeries


@python.define  # type: ignore
def EnsureDicomDir(dicom: DicomCollection) -> DicomDir:
    if isinstance(dicom, DicomSeries):
        dicom_dir_fspath = tempfile.mkdtemp()
        dicom.copy(dicom_dir_fspath, mode=DicomDir.CopyMode.link)
        dicom = DicomDir(dicom_dir_fspath)
    elif not isinstance(dicom, DicomDir):
        raise TypeError(
            "Unrecognised input to ensure_dicom_dir, should be DicomSeries or DicomDir "
            f"not {dicom}"
        )
    return dicom


@converter(source_format=DicomCollection, target_format=Nifti)  # type: ignore
@converter(source_format=DicomCollection, target_format=NiftiGz, compress="y")  # type: ignore
@converter(source_format=DicomCollection, target_format=NiftiX)  # type: ignore
@converter(source_format=DicomCollection, target_format=NiftiGzX, compress="y")  # type: ignore
@converter(source_format=DicomCollection, target_format=NiftiXBvec)  # type: ignore
@converter(source_format=DicomCollection, target_format=NiftiBvec)  # type: ignore
@converter(source_format=DicomCollection, target_format=NiftiGzBvec, compress="y")  # type: ignore
@converter(source_format=DicomCollection, target_format=NiftiGzXBvec, compress="y")  # type: ignore
@workflow.define(outputs=["out_file"])  # type: ignore
def ExtendedDcm2niix(
    in_file: DicomCollection,
    compress: str = "n",
    file_postfix: ty.Optional[str] = None,
    side_car_jq: ty.Optional[str] = None,
    extract_volume: ty.Optional[int] = None,
    to_4d: bool = False,
) -> Nifti:
    """The Dcm2niix command wrapped in a workflow in order to map the inputs and outputs
    onto "in_file" and "out_file", respectively, and implement optional post-conversion
    manipulations to allow manual override of conversion issues.

    Parameters
    ----------
    name : str
        name of the workflow
    compress : str, optional
        whether to apply compression to the conversion, by default "n"
    file_postfix : str, optional
        select one of the multiple output files by its generated postfix.
        See https://github.com/rordenlab/dcm2niix/blob/master/FILENAMING.md for
        complete list of different postfixes that will be generated, by default None
    side_car_jq : str, optional
        JQ (https://stedolan.github.io/jq/) expression that can be provided to edit
        the resulting JSON side-car. Can be used to fix any conversion issues or add
        required fields manually, by default None
    extract_volume : int, optional
        extract a 3D volume from a 4D dataset by passing the index (0-based) of the
        volume to extract, by default None
    to_4d : bool, optional
        whether to wrap resulting 3D NIfTI volume in a 4D dataset, by default False

    Returns
    -------
    out_file: list[Path]
        the converter workflow

    Raises
    ------
    ValueError
        when mutually exclusive "extract_volume" and "to_4d" options are provided
    """

    if extract_volume is not None and to_4d:
        raise ValueError(
            f"'extract_volume' ({extract_volume}) and 'to_4d' are mutually exclusive"
        )
    # Create workflow to map input field to "in_file" and optionally perform post-conversion
    # steps to manipulate the converted NIfTI files
    ensure_dicom_dir = workflow.add(EnsureDicomDir(dicom=in_file))

    dcm2niix = workflow.add(
        Dcm2Niix(
            in_dir=ensure_dicom_dir.out,
            out_dir=Path("."),
            compress=compress,
            file_postfix=file_postfix,
        )
    )
    out_file = dcm2niix.out_file
    out_json = dcm2niix.out_json
    # Add MRConvert step to either select a single volume of a 4D dataset or the inverse,
    # wrap a single volume in a 4D dataset
    if extract_volume is not None or to_4d:
        if extract_volume:
            coord = (3, extract_volume)
            axes = [0, 1, 2]
        else:  # to_4d
            coord = None
            axes = [0, 1, 2, -1]
        mrconvert = workflow.add(
            MrConvert(
                in_file=out_file,
                out_file="out" + NiftiGzX.ext,
                coord=coord,
                axes=axes,
            )
        )
        out_file = mrconvert.out_file
    # Add JQ edit of side car to allow manual fixing of any conversion issues
    if side_car_jq is not None:
        json_edit = workflow.add(
            EditDcm2niixSideCar(in_file=out_json, jq_expr=side_car_jq), name="json_edit"
        )
        out_json = json_edit.out

    collect_outputs = workflow.add(
        CollectDcm2niixOutputs(
            out_file=out_file,
            out_json=out_json,
            out_bvec=dcm2niix.out_bvec,
            out_bval=dcm2niix.out_bval,
        )
    )
    # Set workflow outputs
    return collect_outputs.out  # type: ignore[no-any-return]


@python.define  # type: ignore
def EditDcm2niixSideCar(
    in_file: ty.Optional[Json], jq_expr: str, out_file: ty.Optional[PathType] = None
) -> ty.Optional[Json]:
    """ "Applies ad-hoc edit of JSON side car with JQ query language"""
    if in_file is None:
        assert jq_expr is not None
        return None
    if out_file is None:
        out_dir = Path(tempfile.mkdtemp())
        out_file = out_dir / "out.json"
    with open(in_file) as f:
        dct = json.load(f)
    try:
        import jq
    except ImportError:
        raise RuntimeError(
            "Cannot edit dcm2niix file with jq expression as `jq` package is not "
            "available in the current environment. Please reinstall "
            "fileformats-medimage-extras with the `jq` extra, i.e. "
            "`pip install 'fileformats-medimage-extras[jq]'`, noting that on Windows "
            "you will first need to install the jq package from https://jqlang.org/download/."
        )
    dct = jq.compile(jq_expr).input(dct).first()
    with open(out_file, "w") as f:
        json.dump(dct, f)
    return Json(out_file)


@python.define  # type: ignore
def CollectDcm2niixOutputs(
    out_file: Path,
    out_json: ty.Optional[Path],
    out_bvec: ty.Optional[Path],
    out_bval: ty.Optional[Path],
) -> Nifti:
    klass = NiftiGz if out_file.suffix == ".gz" else Nifti
    if out_json:
        if klass is NiftiGz:
            klass = NiftiGzX
        else:
            klass = NiftiX
    if any((out_bvec, out_bval)):
        if not all((out_bvec, out_bval)):
            raise RuntimeError(
                "Both bvec and bval files must be present for diffusion NIfTI outputs"
            )
        if klass is NiftiGz:
            klass = NiftiGzBvec
        elif klass is NiftiGzX:
            klass = NiftiGzXBvec
        elif klass is NiftiX:
            klass = NiftiXBvec
        else:
            assert klass is Nifti
            klass = NiftiBvec

    return klass(
        [out_file] + [f for f in (out_json, out_bvec, out_bval) if f is not None]
    )


converter(
    source_format=MedicalImage,
    target_format=Analyze,
    out_file_="out_file" + Analyze.ext,
)(MrConvert)
