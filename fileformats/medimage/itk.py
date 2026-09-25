import typing as ty
from fileformats.core.mixin import WithMagicNumber
from fileformats.image import (
    RasterImage,
    VectorImage,
    Bitmap,
    Jpeg,
    Tiff,
)
from fileformats.application import Gzip
from .nifti import Nifti, NiftiGz
from .dicom import DicomImage


class GDCM(DicomImage):
    # iana_mime = None
    pass


class GIPL(RasterImage):
    ext = ".gipl"


class VTK(VectorImage):
    ext = ".vtk"


class PGM(RasterImage):
    ext = ".pgm"


class MetaImage(RasterImage):
    ext = ".mhd"


class Nrrd(WithMagicNumber, RasterImage):

    ext = ".nrrd"
    alternate_exts = (".nhdr",)
    magic_number = b"NRRD"


class NrrdGz(Gzip[Nrrd]):  # type: ignore[type-arg]

    ext = ".nrrd.gz"
    alternate_exts = (".nhdr.gz",)


ItkImage = ty.Union[
    Nifti, NiftiGz, DicomImage, Bitmap, Tiff, Jpeg, GIPL, MetaImage, Nrrd, NrrdGz, PGM
]

ItkAll = ty.Union[
    Nifti,
    NiftiGz,
    DicomImage,
    Bitmap,
    Tiff,
    Jpeg,
    GIPL,
    MetaImage,
    Nrrd,
    NrrdGz,
    PGM,
    VTK,
]

__all__ = [
    "GDCM",
    "GIPL",
    "VTK",
    "PGM",
    "MetaImage",
    "Nrrd",
    "NrrdGz",
    "ItkImage",
    "ItkAll",
]
