import pytest

from fileformats.core.exceptions import FormatMismatchError
from fileformats.medimage import DeidRecipe, DeidRecipeX


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


def test_deid_recipe_x_side_cars(tmp_path):
    recipe = tmp_path / "dicom-series.deid"
    recipe.write_text("FORMAT dicom\n")
    transforms = tmp_path / "dicom-series.transforms.yaml"
    transforms.write_text('version: "0.1"\n')
    (tmp_path / "dicom-series.other").write_text("not a side-car")

    recipe_x = DeidRecipeX(recipe)
    assert recipe_x.fspath == recipe
    assert recipe_x.transforms_file.fspath == transforms
    assert recipe_x.salt_file is None
    assert recipe_x.fspaths == {recipe, transforms}

    salt = tmp_path / "dicom-series.salt"
    salt.write_bytes(b"key")
    assert DeidRecipeX(recipe).salt_file.fspath == salt
    assert DeidRecipeX(recipe).fspaths == {recipe, transforms, salt}


def test_deid_recipe_x_requires_transforms(tmp_path):
    recipe = tmp_path / "deid.dicom"
    recipe.write_text("FORMAT dicom\n")
    assert not DeidRecipeX.matches([recipe])
    assert DeidRecipe.matches([recipe])
