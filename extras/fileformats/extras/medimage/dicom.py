import logging
import os
import tempfile
import typing as ty
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fileformats.extras.application.medical  # noqa: F401
import medimages4tests.dummy.dicom.mri.t1w.siemens.skyra.syngo_d13c
import numpy
import pydicom
from deid.config import DeidRecipe
from deid.dicom.parser import DicomParser
from fileformats.core import FileSet, SampleFileGenerator, extra_implementation

from fileformats.medimage import (
    DicomCollection,
    DicomDir,
    DicomImage,
    DicomSeries,
    DicomZip,
    MedicalImage,
    MedicalImagingData,
)
from fileformats.medimage.base import DataArrayType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Variable builders for deid spec var: references
# ---------------------------------------------------------------------------
# Each callable receives the pydicom Dataset and returns the substitution
# value. Sites can override any entry by passing transforms={...}
# to dicom_deidentify.
# ---------------------------------------------------------------------------

VariableBuilder = ty.Callable[[pydicom.Dataset], str | int]


@extra_implementation(MedicalImage.read_array)
def dicom_read_array(
    collection: DicomCollection,
) -> DataArrayType:
    image_stack = []
    for dcm_file in collection.contents:
        image_stack.append(pydicom.dcmread(dcm_file).pixel_array)
    return numpy.asarray(image_stack)


@extra_implementation(MedicalImage.vox_sizes)
def dicom_vox_sizes(collection: DicomCollection) -> tuple[float, float, float]:
    return tuple(
        collection.metadata["PixelSpacing"] + [collection.metadata["SliceThickness"]]
    )


@extra_implementation(MedicalImage.dims)
def dicom_dims(collection: DicomCollection) -> tuple[int, int, int]:
    return (
        collection.metadata["Rows"],
        collection.metadata["DataColumns"],
        len(list(collection.contents)),
    )


@extra_implementation(DicomCollection.series_number)
def dicom_series_number(collection: DicomCollection) -> str:
    return str(collection.metadata["SeriesNumber"])


@extra_implementation(FileSet.generate_sample_data)
def dicom_dir_generate_sample_data(
    dcmdir: DicomDir,
    generator: SampleFileGenerator,
) -> list[Path]:
    dcm_dir = medimages4tests.dummy.dicom.mri.t1w.siemens.skyra.syngo_d13c.get_image()
    series_number = generator.rng.randint(1, SERIES_NUMBER_RANGE)
    dest = generator.generate_fspath(DicomDir)
    dest.mkdir()
    for dcm_file in dcm_dir.iterdir():
        dcm = pydicom.dcmread(dcm_file)
        dcm.SeriesNumber = series_number
        pydicom.dcmwrite(dest / dcm_file.name, dcm)
    return [dest]


@extra_implementation(FileSet.generate_sample_data)
def dicom_series_generate_sample_data(
    dcm_series: DicomSeries,
    generator: SampleFileGenerator,
) -> list[Path]:
    dicom_dir: Path = dicom_dir_generate_sample_data(dcm_series, generator=generator)[0]  # type: ignore[arg-type]
    stem = generator.generate_fspath().stem
    fspaths = []
    for i, dicom_file in enumerate(dicom_dir.iterdir(), start=1):
        fspaths.append(dicom_file.rename(generator.dest_dir / f"{stem}-{i}.dcm"))
    dicom_dir.rmdir()
    return fspaths


SERIES_NUMBER_TAG = ("0020", "0011")
SERIES_NUMBER_RANGE = int(1e8)


@extra_implementation(MedicalImagingData.deidentify)
def dicom_deidentify(
    dicom: DicomImage,
    out_dir: os.PathLike[str],
    spec: str | Path | None = None,
    **kwargs: ty.Any,
) -> DicomImage:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    outfile = out_dir / dicom.fspath.name
    transforms: dict[str, VariableBuilder] | None = kwargs.get("transforms", None)

    if spec is None:
        raise ValueError(
            "A deidentification spec must be provided for DICOM deidentification"
        )
    deid_spec = DeidRecipe(str(spec))

    # Parse recipe to find all var: references and check transforms are provided
    if transforms is None:
        transforms = {}

    recipe_vars = set()
    spec_path = Path(spec)
    if spec_path.is_file():
        with open(spec_path) as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("#") or not stripped:
                    continue
                # Strip inline comments
                if " #" in stripped:
                    stripped = stripped[: stripped.index(" #")]
                for token in stripped.split():
                    if token.startswith("var:"):
                        recipe_vars.add(token[4:])

    missing = recipe_vars - set(transforms)
    if missing:
        raise ValueError(
            f"Recipe references var: variables {missing} but no matching "
            f"transforms were provided. Supply these via the 'transforms' argument."
        )

    parser = DicomParser(str(dicom.fspath), recipe=deid_spec)

    ds = parser.dicom
    for var_name, builder in transforms.items():
        try:
            value = builder(ds)
            parser.define(var_name, value)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Variable builder for '%s' raised %s: %s — skipping",
                var_name,
                type(exc).__name__,
                exc,
            )

    parser.parse(strip_sequences=False, remove_private=False)
    parser.save(str(outfile))

    return type(dicom)(outfile)


@extra_implementation(MedicalImagingData.deidentify)
def dicom_collection_deidentify(
    collection: DicomCollection,
    out_dir: os.PathLike[str],
    spec: str | Path | None = None,
    max_workers: int | None = None,
    **kwargs: ty.Any,
) -> DicomCollection:
    out_dir = Path(out_dir)
    if isinstance(collection, DicomDir):
        out_dir /= collection.name
    out_dir.mkdir(parents=True, exist_ok=True)
    transforms: dict[str, VariableBuilder] | None = kwargs.get("transforms", None)

    def _deidentify_one(dicom: DicomImage) -> Path:
        return dicom.deidentify(out_dir, spec=spec, transforms=transforms).fspath

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        deid_fspaths = list(executor.map(_deidentify_one, collection.contents))
    type_ = type(collection)
    if isinstance(collection, DicomDir):
        deidentified = type_(Path(out_dir))
    else:
        deidentified = type_(deid_fspaths)
    return deidentified


@extra_implementation(MedicalImagingData.deidentify)
def dicom_zip_deidentify(
    dz: DicomZip,
    out_dir: os.PathLike[str],
    spec: str | Path | None = None,
    max_workers: int | None = None,
    **kwargs: ty.Any,
) -> DicomZip:
    """Deidentify a DicomZip: extract all DICOMs, deidentify each, re-zip."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    transforms: dict[str, VariableBuilder] | None = kwargs.get("transforms", None)

    # Extract all DICOMs from the zip
    extract_dir = Path(tempfile.mkdtemp())
    with zipfile.ZipFile(dz.fspath) as zf:
        zf.extractall(extract_dir)

    # Deidentify each extracted DICOM file
    deid_dir = Path(tempfile.mkdtemp())
    extracted = sorted(p for p in extract_dir.rglob("*") if p.is_file())

    def _deidentify_one(fspath: Path) -> Path:
        dicom = DicomImage(fspath)
        return dicom.deidentify(deid_dir, spec=spec, transforms=transforms).fspath

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        deid_fspaths = list(executor.map(_deidentify_one, extracted))

    # Re-zip the deidentified DICOMs
    zip_path = out_dir / Path(dz.fspath).name
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fspath in deid_fspaths:
            zf.write(fspath, fspath.name)

    return DicomZip(zip_path)
