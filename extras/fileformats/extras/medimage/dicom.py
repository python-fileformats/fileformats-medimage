import logging
import os
import typing as ty
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import deid.config
import fileformats.extras.application.medical  # noqa: F401
import medimages4tests.dummy.dicom.mri.t1w.siemens.skyra.syngo_d13c
import numpy
import pydicom
from deid.dicom.parser import DicomParser
from fileformats.core import (
    FileSet,
    Loaded,
    SampleFileGenerator,
    check_loaded,
    extra_implementation,
)

from fileformats.medimage import (
    DeidRecipe,
    DicomCollection,
    DicomDir,
    DicomImage,
    DicomSeries,
    MedicalImage,
    MedicalImagingData,
)
from fileformats.medimage.base import DataArrayType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Variable builders for deid recipe var: references
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


@extra_implementation(FileSet.load)
def deid_recipe_load(recipe: DeidRecipe, **kwargs: ty.Any) -> "deid.config.DeidRecipe":
    return deid.config.DeidRecipe(str(recipe.fspath), **kwargs)


def _recipe_vars(recipe: "deid.config.DeidRecipe") -> set[str]:
    """Names of the variables referenced by 'var:' values anywhere in the recipe"""
    recipe_vars: set[str] = set()

    def walk(node: ty.Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            recipe_vars.update(t[4:] for t in node.split() if t.startswith("var:"))

    walk(recipe.deid)
    return recipe_vars


@extra_implementation(MedicalImagingData.deidentify)
def dicom_deidentify(
    dicom: DicomImage,
    out_dir: os.PathLike[str],
    recipe: Loaded[DeidRecipe] | None = None,
    **kwargs: ty.Any,
) -> DicomImage:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    outfile = out_dir / dicom.fspath.name
    transforms: dict[str, VariableBuilder] | None = kwargs.get("transforms", None)

    if recipe is None:
        raise ValueError(
            "A deidentification recipe must be provided for DICOM deidentification"
        )
    # DicomParser silently accepts a path too, so check it was loaded from DeidRecipe
    check_loaded(DeidRecipe, recipe)

    # Check transforms are provided for all var: references in the recipe
    if transforms is None:
        transforms = {}

    missing = _recipe_vars(recipe) - set(transforms)
    if missing:
        raise ValueError(
            f"Recipe references var: variables {missing} but no matching "
            f"transforms were provided. Supply these via the 'transforms' argument."
        )

    parser = DicomParser(str(dicom.fspath), recipe=recipe)

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
    recipe: Loaded[DeidRecipe] | None = None,
    max_workers: int | None = None,
    **kwargs: ty.Any,
) -> DicomCollection:
    out_dir = Path(out_dir)
    if isinstance(collection, DicomDir):
        out_dir /= collection.name
    out_dir.mkdir(parents=True, exist_ok=True)
    transforms: dict[str, VariableBuilder] | None = kwargs.get("transforms", None)

    def _deidentify_one(dicom: DicomImage) -> Path:
        return dicom.deidentify(out_dir, recipe=recipe, transforms=transforms).fspath

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        deid_fspaths = list(executor.map(_deidentify_one, collection.contents))
    type_ = type(collection)
    if isinstance(collection, DicomDir):
        deidentified = type_(Path(out_dir))
    else:
        deidentified = type_(deid_fspaths)
    return deidentified
