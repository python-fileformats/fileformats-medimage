import io
import sys
import os
import typing as ty
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from fileformats.core.decorators import mtime_cached_property
from fileformats.core import extra, FileSet, extra_implementation
from fileformats.core.utils import collate_metadata_series
from fileformats.core.collection import TypedCollection
from fileformats.generic import TypedDirectory, TypedSet
from fileformats.application import Dicom
from fileformats.application.archive import BaseZip
from .base import MedicalImage

if sys.version_info >= (3, 9):
    from typing import TypeAlias
else:
    from typing_extensions import TypeAlias
if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

if ty.TYPE_CHECKING:
    import pydicom.tag

    TagListType: TypeAlias = ty.Union[
        ty.List[int],
        ty.List[str],
        ty.List[ty.Tuple[int, int]],
        ty.List[pydicom.tag.BaseTag],
    ]
# =====================================================================
# Custom loader functions for different image types
# =====================================================================


class DicomImage(MedicalImage, Dicom):
    """A DICOM file that contains image data. Derives from the generic Dicom class in
    the `application` namespace as well as medical image base class"""


def dicom_sort_key(dicom: Dicom) -> str:
    """Sorts DICOM objects by SOPInstanceUID"""
    assert isinstance(dicom.metadata, ty.Mapping)
    return dicom.metadata["SOPInstanceUID"]  # type: ignore[no-any-return]


class DicomCollection(MedicalImage, TypedCollection):
    """Base class for collections of DICOM files, which can either be stored within a
    directory (DicomDir) or presented as a flat list (DicomSeries)
    """

    content_types = (DicomImage,)

    def __len__(self) -> int:
        return len(self.contents)

    @extra
    def series_number(self) -> str:
        raise NotImplementedError


class DicomDir(TypedDirectory, DicomCollection):
    content_types = (DicomImage,)

    @mtime_cached_property
    def contents(self) -> ty.List[DicomImage]:
        return sorted(TypedDirectory.contents.__get__(self), key=dicom_sort_key)


class DicomSeries(TypedSet, DicomCollection):
    content_types = (DicomImage,)

    @classmethod
    def from_paths(
        cls,
        fspaths: ty.Iterable[Path],
        common_ok: bool = False,
        max_workers: ty.Optional[int] = None,
        full_metadata: bool = True,
        **kwargs: ty.Any,
    ) -> ty.Tuple[ty.Set[Self], ty.Set[Path]]:
        """Separates a list of DICOM files into separate series from the file-system
        paths

        Parameters
        ----------
        fspaths : ty.Iterable[Path]
            the fspaths pointing to the DICOM files
        common_ok : bool, optional
            included to match the signature of the overridden method, but ignored as each
            dicom should belong to only one series.
        max_workers : int, optional
            the number of threads to use to read the identifying metadata from the
            DICOM files concurrently. If None, defaults to
            `concurrent.futures.ThreadPoolExecutor`'s default (based on the number of
            processors on the machine)
        full_metadata : bool, optional
            whether to read the full (default) set of metadata tags from each DICOM
            file while grouping them into series. The already-read `DicomImage`
            objects (with their `metadata` cached) are then reused as the `contents`
            of the returned `DicomSeries` objects, so subsequent access of `metadata`
            or `contents` doesn't trigger a second file read. If False, only the tags
            in `ID_KEYS` are read, which involves less parsing per file, at the cost
            of `contents`/`metadata` re-reading each file from scratch the first time
            they are accessed. Turning this off is best reserved for large series
            and/or files with heavy headers (e.g. enhanced multi-frame DICOM) where
            the full metadata won't be needed afterwards.
        specific_tags : ty.Optional[TagListType], optional
            the DICOM tags to read from the files. If None, the default tags will be
            read
        **kwargs : ty.Any
            additional keyword arguments to passed through to the DicomImage constructor

        Returns
        -------
        tuple[set[DicomSeries], set[Path]]
            the found dicom series objects and any unrecognised file paths
        """
        dicoms_set, remaining = DicomImage.from_paths(
            fspaths, common_ok=common_ok, **kwargs
        )
        dicoms = list(dicoms_set)

        def id_key(dicom: DicomImage) -> ty.Tuple[ty.Any, ...]:
            metadata = (
                dicom.metadata
                if full_metadata
                else dicom.read_metadata(metadata_keys=cls.ID_KEYS)
            )
            return tuple(metadata[k] for k in cls.ID_KEYS)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            id_keys = executor.map(id_key, dicoms)
        series_dict = defaultdict(list)
        for dicom, key in zip(dicoms, id_keys):
            series_dict[key].append(dicom)
        all_series = set()
        for members in series_dict.values():
            series = cls(d.fspath for d in members)
            if full_metadata:
                # Reuse the already-read DicomImage objects (with `metadata` cached)
                # as the series' `contents`, instead of letting `contents` rebuild
                # them from scratch (and re-read every file) on first access. Relies
                # on the private cache key used by `mtime_cached_property`.
                series.__dict__["_contents_mtime_cache"] = (
                    series.mtimes,
                    sorted(members, key=dicom_sort_key),
                )
            all_series.add(series)
        return all_series, remaining

    @mtime_cached_property
    def contents(self) -> ty.List[DicomImage]:
        return sorted(TypedSet.contents.__get__(self), key=dicom_sort_key)

    ID_KEYS = ("StudyInstanceUID", "SeriesNumber")


class DicomZip(MedicalImage, BaseZip):
    """A zip archive containing DICOM files"""

    iana_mime = "application/x-dicom+zip"

    # DICOM tags used by peek_header
    DICOM_TAGS: ty.ClassVar[ty.Dict[str, ty.Tuple[int, int]]] = {
        "Modality": (0x0008, 0x0060),
        "SOPClassUID": (0x0008, 0x0016),
        "SeriesDescription": (0x0008, 0x103E),
        "StudyInstanceUID": (0x0020, 0x000D),
        "SeriesNumber": (0x0020, 0x0011),
        "PatientID": (0x0010, 0x0020),
        "AccessionNumber": (0x0008, 0x0050),
        "StudyComments": (0x0032, 0x4000),
    }

    @mtime_cached_property
    def _first_member_name(self) -> ty.Optional[str]:
        """Name of the first non-directory entry in the zip."""
        with zipfile.ZipFile(self.fspath) as zf:
            members = sorted(n for n in zf.namelist() if not n.endswith("/"))
        return members[0] if members else None

    @mtime_cached_property
    def num_members(self) -> int:
        """Number of file entries in the zip archive."""
        with zipfile.ZipFile(self.fspath) as zf:
            return sum(1 for n in zf.namelist() if not n.endswith("/"))

    def extract_first(self, dest_dir: Path) -> ty.Optional[Path]:
        """Extract the first DICOM file from the zip to *dest_dir*.

        Returns the path to the extracted file, or ``None`` if the zip is empty.
        """
        name = self._first_member_name
        if name is None:
            return None
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = dest_dir / (Path(self.fspath).stem + "-sample")
        with zipfile.ZipFile(self.fspath) as zf:
            out.write_bytes(zf.read(name))
        return out

    def peek_header(
        self,
        tags: ty.Optional[ty.Dict[str, ty.Tuple[int, int]]] = None,
    ) -> ty.Dict[str, ty.Optional[ty.Union[str, bytes]]]:
        """Read selected DICOM tags from the first file in the zip.

        This avoids extracting the full archive or loading pixel data — only the
        first member's header bytes are read. Uses the lightweight
        ``get_dicom_tag`` parser so pydicom is not required.

        Parameters
        ----------
        tags : dict, optional
            Mapping of ``{name: (group, element)}`` for the tags to read.
            Defaults to ``DicomZip.DICOM_TAGS``.

        Returns
        -------
        dict
            ``{name: value}`` for each requested tag, with ``None`` for any tag
            not found. An empty dict is returned if the zip contains no files.
        """
        if tags is None:
            tags = self.DICOM_TAGS
        name = self._first_member_name
        if name is None:
            return {}
        with zipfile.ZipFile(self.fspath) as zf:
            blob = zf.read(name)
        result: ty.Dict[str, ty.Optional[ty.Union[str, bytes]]] = {}
        for tag_name, tag_tuple in tags.items():
            result[tag_name] = get_dicom_tag(io.BytesIO(blob), tag_tuple)
        return result


@extra_implementation(FileSet.read_metadata)
def dicom_zip_read_metadata(dz: DicomZip, **kwargs: ty.Any) -> ty.Mapping[str, ty.Any]:
    return dz.peek_header()


@extra_implementation(FileSet.read_metadata)
def dicom_collection_read_metadata(
    collection: DicomCollection, **kwargs: ty.Any
) -> ty.Mapping[str, ty.Any]:
    # We use the "contents" property implementation in TypeSet instead of the overload
    # in DicomCollection because we don't want the metadata to be read ahead of the
    # the `select_metadata` call below
    base_class: ty.Union[ty.Type[TypedSet], ty.Type[TypedDirectory]] = (
        TypedSet if isinstance(collection, DicomSeries) else TypedDirectory
    )
    return collate_metadata_series(
        [d.metadata for d in base_class.contents.__get__(collection)]
    )


def get_dicom_tag(
    file: ty.Union[str, os.PathLike[ty.Any], ty.BinaryIO],
    target_tag: ty.Tuple[int, int],
) -> ty.Union[str, bytes, None]:
    """A basic function to read a DICOM file and extract the value of a specific tag.
    This is a low-level function that does not use any external libraries.
    It is not a replacement for pydicom, but can be used to extract specific tags
    without loading the entire DICOM file into memory.

    Parameters
    ----------
    filepath : str or os.PathLike
        The path to the DICOM file.
    target_tag : tuple[int, int]
        The DICOM tag to extract, specified as a tuple of (group, element).
        For example, (0x0010, 0x0010) for PatientName.

    Returns
    -------
    str or bytes or None
        The value of the specified DICOM tag, decoded as a string if possible.
        If the tag is not found or cannot be decoded, returns None.
    """
    if isinstance(file, (str, os.PathLike)):
        filepath = file
        file_stream = open(filepath, "rb")
        close_stream = True
    elif hasattr(file, "read"):
        file_stream = file  # type: ignore[assignment]
        close_stream = False
    else:
        raise TypeError("file must be a path-like object or a binary stream")

    try:
        file_stream.seek(132)  # Skip preamble and 'DICM' if at file start

        while True:
            tag_bytes = file_stream.read(4)
            if len(tag_bytes) < 4:
                break

            group = int.from_bytes(tag_bytes[:2], "little")
            element = int.from_bytes(tag_bytes[2:], "little")
            tag = (group, element)

            vr_bytes = file_stream.read(2)
            # If the VR bytes are not purely alphabetic, assume implicit VR.
            if vr_bytes.decode(errors="ignore").strip().isalpha():
                vr = vr_bytes.decode()
                if vr in {"OB", "OW", "OF", "SQ", "UT", "UN"}:
                    file_stream.read(2)  # reserved
                    length = int.from_bytes(file_stream.read(4), "little")
                else:
                    length = int.from_bytes(file_stream.read(2), "little")
            else:
                # Implicit VR: rewind the 2 bytes and read a 4-byte length
                file_stream.seek(-2, 1)
                length = int.from_bytes(file_stream.read(4), "little")
            value = file_stream.read(length)

            if tag == target_tag:
                try:
                    return value.decode().strip()
                except UnicodeDecodeError:
                    return value
    finally:
        if close_stream:
            file_stream.close()

    return None  # Not found


# class Vnd_Siemens_Vision(DicomImage):
#     ext = ".ima"


# class Vnd_Siemens_VisionDir(DicomDir):
#     content_types = (Vnd_Siemens_Vision,)
