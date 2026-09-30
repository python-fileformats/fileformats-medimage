import pytest

from fileformats.core.exceptions import FormatMismatchError
from fileformats.medimage import DeidRecipe


def test_deid_recipe(tmp_path):
    fspath = tmp_path / "deid.dicom"
    fspath.write_text("# A comment\n\nFORMAT dicom\n\n%header\nREMOVE PatientID\n")
    assert DeidRecipe(fspath).recipe_format == "dicom"


def test_deid_recipe_no_extension(tmp_path):
    fspath = tmp_path / "deid.dicom.ct"
    fspath.write_text("FORMAT nifti\n")
    assert DeidRecipe(fspath).recipe_format == "nifti"


def test_deid_recipe_missing_format(tmp_path):
    fspath = tmp_path / "deid.dicom"
    fspath.write_text("%header\nREMOVE PatientID\n")
    with pytest.raises(FormatMismatchError, match="FORMAT"):
        DeidRecipe(fspath)
