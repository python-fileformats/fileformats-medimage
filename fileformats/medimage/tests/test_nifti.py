import gzip

import pytest
from medimages4tests.dummy.dicom.mri.t1w.siemens.skyra.syngo_d13c import get_image as get_dicom
from medimages4tests.dummy.nifti import get_image as get_nifti
from fileformats.core.exceptions import FormatMismatchError
from fileformats.medimage import Nifti, NiftiGz


def test_nifti1_identify():
    Nifti(get_nifti())


def test_nifti2_identify():
    Nifti(get_nifti(nifti_version_2=True))


def test_nifti_not_identify():
    with pytest.raises(FormatMismatchError, match="No matching files with extensions"):
        Nifti(get_dicom())


def test_nifti1_gz_identify():
    NiftiGz(get_nifti(compressed=True))


def test_nifti2_gz_identify():
    NiftiGz(get_nifti(compressed=True, nifti_version_2=True))


def test_non_nifti_gz(tmp_path):
    out_file = tmp_path / "sample.nii.gz"
    with gzip.open(out_file, 'w') as fh_out:
        fh_out.write(b"This is not a valid NIFTI file but a valid gzip.")
    with pytest.raises(FormatMismatchError, match="Not a valid Nifti header, the size indication does not match either 348 or 540 bytes!"):
        NiftiGz(out_file)