from fileformats.core.exceptions import FormatMismatchError
from fileformats.generic import BinaryFile
from fileformats.core import validated_property
from fileformats.core.mixin import WithSideCars, WithMagicNumber, WithAdjacentFiles
from fileformats.core.decorators import mtime_cached_property
from fileformats.application import Json
from fileformats.application.archive import BaseGzip
from .base import MedicalImage

class Nifti(WithMagicNumber, MedicalImage, BinaryFile):
    iana_mime = "application/x-nifti"
    ext: str = ".nii"
    contains_phi = False

    # Depending on Nifti1 or Nifti2, the offset and magic number changes
    # n+1 followed by null
    magic_number_n1 = "6E 2B 31 00"
    # n+2 followed by null, a carriage return, newline, EOF character, and newline
    magic_number_n2 = '6E 2B 32 00 0D 0A 1A 0A'
    magic_number_offset_n1 = 344
    magic_number_offset_n2 = 4

    @mtime_cached_property
    def nifti_version_1(self) -> bool:
        header_bytes = self.read_contents(4)

        size_le = int.from_bytes(header_bytes, byteorder='little')
        size_be = int.from_bytes(header_bytes, byteorder='big')

        if size_le == 348 or size_be == 348:
            return True
        elif size_le == 540 or size_be == 540:
            return False
        else:
            raise FormatMismatchError("Not a valid Nifti header, the size indication does not match either 348 or 540 bytes!")

    @property
    def magic_number_offset(self) -> int:
        return self.magic_number_offset_n1 if self.nifti_version_1 else self.magic_number_offset_n2

    @property
    def magic_number(self) -> str:
        return self.magic_number_n1 if self.nifti_version_1 else self.magic_number_n2


class WithBids(WithSideCars):
    primary_type = Nifti
    side_car_types = (Json,)

    @validated_property
    def json_file(self) -> Json:
        return Json(self.select_by_ext(Json))  # type: ignore[attr-defined]


class NiftiGz(Nifti, BaseGzip):
    ext = ".nii.gz"
    iana_mime = "application/x-nifti+gzip"
    archived_type = Nifti


class NiftiX(WithBids, Nifti):
    iana_mime = "application/x-nifti+json"


class NiftiGzX(WithBids, NiftiGz):
    iana_mime = "application/x-nifti+gzip.bids"


class NiftiDataFile(MedicalImage):
    ext = ".img"


class NiftiWithDataFile(WithAdjacentFiles, Nifti):
    """Nifti file with separate data file"""

    # ni1 followed by null
    magic_number_n1 = "6E 69 31 00"
    # ni2 followed by null, a carriage return, newline, EOF character, and newline
    magic_number_n2 = '6E 69 32 00 0D 0A 1A 0A'

    alternate_exts = (".hdr",)

    @validated_property
    def data_file(self) -> NiftiDataFile:
        return NiftiDataFile(self.select_by_ext(NiftiDataFile))
