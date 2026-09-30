import logging
import os
import sys
import typing as ty

from fileformats.core import FileSet, Loaded, extra, mtime_cached_property
from fileformats.core.mixin import WithClassifiers

from .contents import ContentsClassifier
from .contents.anatomical_entity import AnatomicalEntity
from .contents.imaging.derivatives import Derivative
from .contents.imaging.modality import ImagingModality

logger = logging.getLogger("fileformats")

if sys.version_info >= (3, 9):
    from typing import TypeAlias
else:
    from typing_extensions import TypeAlias
if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

if ty.TYPE_CHECKING:
    import numpy.typing  # noqa: F401


# =====================================================================
# Custom loader functions for different image types
# =====================================================================

DataArrayType: TypeAlias = (
    ty.Any
)  # In Py<3.9 this is problematic "numpy.typing.NDArray[typing.Union[numpy.floating[typing.Any], numpy.integer[typing.Any]]]"


class MedicalImagingData(FileSet):
    """Base class for all medical imaging data including pre-image raw data and
    associated data"""

    contains_phi: bool = True

    @extra
    def deidentify(
        self,
        out_dir: os.PathLike[str],
        recipe: Loaded[FileSet] | None = None,
        **kwargs: ty.Any,
    ) -> Self:
        """
        Deidentifies the image by stripping any subject-identifying information from the
        image header. The exact implementation of this method will depend on the
        specific image format and the type of identifying information that is present. The
        output files should be named with a new file path(s) that is derived from the metadata,
        such that it doesn't contain any subject-identifying information within it.

        Implementations only need to strip the identifying data -- they don't need to
        track/report what was changed. Callers that need that (e.g. for re-identification
        audit trails) can diff `metadata` before and after calling this method instead,
        since that works uniformly across formats without extra bookkeeping in each
        implementation.

        Parameters
        ----------
        out_dir: PathLike[str]
            The directory where the deidentified image should be saved
        recipe: Loaded[FileSet], optional
            A recipe for the deidentification process, loaded from a format that depends
            on the implementation (e.g. `DeidRecipe` for DICOM), which may include
            details on which fields to remove or how to handle certain types of data.
            Implementations annotate it with ``Loaded[<recipe format>]``, so callers can
            find the format to load the recipe from with
            ``LoadedMarker.from_hint(get_type_hints(find_extra_implementation(
            MedicalImagingData.deidentify, type(image)), include_extras=True)["recipe"])``
        **kwargs: Any
            Additional format-specific keyword arguments (e.g. concurrency options),
            which implementations that don't use them should accept and ignore

        Returns
        -------
        Self
            A new instance of the image with any subject-identifying information stripped from
            the image header.
        """
        raise NotImplementedError


class MedicalImage(WithClassifiers, MedicalImagingData):

    INCLUDE_HDR_KEYS: ty.Optional[ty.Tuple[str, ...]] = None
    IGNORE_HDR_KEYS: ty.Optional[ty.Tuple[str, ...]] = None
    binary = True
    classifiers_attr_name = "image_contents"
    image_contents = ()
    allowed_classifiers = (ContentsClassifier,)
    exclusive_classifiers = (ImagingModality, AnatomicalEntity, Derivative)

    @extra
    def read_array(self) -> DataArrayType:
        """
        Returns the binary data of the image in a numpy array
        """

    @mtime_cached_property
    def data_array(self) -> DataArrayType:
        return self.read_array()

    @extra
    def vox_sizes(self) -> ty.Tuple[float, float, float]:
        """The length of the voxels along each dimension"""
        raise NotImplementedError

    @extra
    def dims(self) -> ty.Tuple[int, int, int]:
        """The dimensions of the image"""
        raise NotImplementedError
