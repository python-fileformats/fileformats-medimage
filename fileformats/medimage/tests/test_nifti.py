import gzip

import pytest
from medimages4tests.dummy.dicom.mri.t1w.siemens.skyra.syngo_d13c import get_image as get_dicom
from medimages4tests.dummy.nifti import get_image as get_nifti
from fileformats.core.exceptions import FormatMismatchError
from fileformats.medimage import Nifti1, Nifti2, NiftiGz


def test_nifti_identify():
    Nifti1(get_nifti())
    Nifti2(get_nifti(nifti_version_2=True))


def test_nifti_wrong_version():
    with pytest.raises(FormatMismatchError, match='Magic number of file \'"02000000"\' doesn\'t match expected \'"6E 2B 31 00"\''):
        Nifti1(get_nifti(nifti_version_2=True))
    with pytest.raises(FormatMismatchError, match='Magic number of file \'"0000000000000000"\' doesn\'t match expected \'"6E 2B 32 00 0D 0A 1A 0A"\''):
        Nifti2(get_nifti())


def test_nifti_not_identify():
    with pytest.raises(FormatMismatchError, match="No matching files with extensions"):
        Nifti1(get_dicom())


def test_nifti_gz_identify():
    NiftiGz(get_nifti(compressed=True))


def test_non_nifti_gz(tmp_path):
    out_file = tmp_path / "sample.nii.gz"
    with gzip.open(out_file, 'w') as fh_out:
        fh_out.write(b"This is not a valid NIFTI file but a valid gzip.")
    with pytest.raises(FormatMismatchError, match="Magic number of file '.*' doesn't match expected '\"6E 2B 31 00\"'"):
        NiftiGz(out_file)