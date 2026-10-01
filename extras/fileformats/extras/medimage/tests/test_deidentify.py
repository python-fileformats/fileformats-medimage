"""Generic deidentification tests.

Tests verify the deidentification *mechanism* works correctly for any deid recipe
by parsing the recipe programmatically. Adding or changing recipe rules does not
require updating tests.
"""

import hashlib
import typing as ty
from pathlib import Path

import pydicom
import pytest
from deid.config import DeidRecipe
from fileformats.core import LoadedMarker, find_extra_implementation
from fileformats.core.exceptions import FileFormatsExtrasError
from fileformats.extras.medimage.deid_recipe import DeidRecipeWithTransforms
from medimages4tests.dummy.dicom.mri.t1w.siemens.skyra.syngo_d13c import (
    get_image as get_dicom_image,
)

from fileformats.medimage import DeidRecipe as DeidRecipeFile
from fileformats.medimage import (
    DeidRecipeX,
    DicomDir,
    DicomImage,
    DicomSeries,
    MedicalImagingData,
    Nifti1,
)

# ---------------------------------------------------------------------------
# Recipe, with its variable builders defined in the recipe.transforms.py side-car
# ---------------------------------------------------------------------------

DEFAULT_RECIPE_PATH = Path(__file__).parent / "recipe.dicom"
DEFAULT_RECIPE = DeidRecipeX(DEFAULT_RECIPE_PATH).load()

_PATTERN_PREFIXES = ("endswith:", "startswith:", "contains:")


def _is_pattern(field: str) -> bool:
    return any(field.startswith(p) for p in _PATTERN_PREFIXES)


def _parse_actions(recipe_path: Path) -> dict[str, list[dict]]:
    """Parse a deid recipe and group entries by action type."""
    recipe = DeidRecipe(str(recipe_path))
    grouped: dict[str, list[dict]] = {}
    for entry in recipe.deid.get("header", []):
        grouped.setdefault(entry["action"], []).append(entry)
    return grouped


def _explicit_fields(actions: dict, action_type: str) -> list[str]:
    """Non-pattern field names for an action type."""
    return [
        e["field"] for e in actions.get(action_type, []) if not _is_pattern(e["field"])
    ]


def _expand_patterns(actions: dict, action_type: str, all_keys: set[str]) -> set[str]:
    """Expand pattern-based entries against a set of DICOM keywords."""
    matched = set()
    for entry in actions.get(action_type, []):
        field = entry["field"]
        if not _is_pattern(field):
            continue
        prefix, suffix = field.split(":", 1)
        for key in all_keys:
            if prefix == "endswith" and key.endswith(suffix):
                matched.add(key)
            elif prefix == "startswith" and key.startswith(suffix):
                matched.add(key)
            elif prefix == "contains" and suffix in key:
                matched.add(key)
    return matched


def _all_explicit_fields(actions: dict) -> set[str]:
    """All non-pattern field names across all action types."""
    fields = set()
    for entries in actions.values():
        for e in entries:
            if not _is_pattern(e["field"]):
                fields.add(e["field"])
    return fields


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def recipe_actions():
    return _parse_actions(DEFAULT_RECIPE_PATH)


@pytest.fixture(params=["image", "dir", "series"])
def dicom(request):
    dicom_dir = get_dicom_image(first_name="John", last_name="Doe")
    dicom_files = sorted(p for p in dicom_dir.iterdir() if p.suffix == ".dcm")
    if request.param == "image":
        return DicomImage(dicom_files[0])
    elif request.param == "dir":
        return DicomDir(dicom_dir)
    else:
        return DicomSeries(dicom_files)


@pytest.fixture
def single_dicom():
    dicom_dir = get_dicom_image(first_name="John", last_name="Doe")
    dcm_file = next(p for p in dicom_dir.iterdir() if p.suffix == ".dcm")
    return DicomImage(dcm_file)


# ---------------------------------------------------------------------------
# REMOVE — fields should be absent after deidentification
# ---------------------------------------------------------------------------


def test_remove_explicit_fields_are_absent(dicom, tmp_path, recipe_actions):
    """Explicit REMOVE fields that exist in the original should be absent."""
    remove_fields = [
        f for f in _explicit_fields(recipe_actions, "REMOVE") if f in dicom.metadata
    ]
    if not remove_fields:
        pytest.skip("No testable REMOVE fields found in test DICOM")

    deidentified = dicom.deidentify(tmp_path, recipe=DEFAULT_RECIPE)
    for field in remove_fields:
        assert field not in deidentified.metadata, f"{field} should have been removed"


def test_remove_pattern_fields_are_absent(dicom, tmp_path, recipe_actions):
    """Fields matching REMOVE patterns should be absent (unless explicitly overridden)."""
    orig_keys = set(dicom.metadata.keys())
    pattern_matched = _expand_patterns(recipe_actions, "REMOVE", orig_keys)

    # Exclude fields that have an explicit (non-pattern) entry in any action,
    # since deid gives explicit rules priority over patterns
    explicitly_handled = _all_explicit_fields(recipe_actions)
    testable = pattern_matched - explicitly_handled

    if not testable:
        pytest.skip(
            "All pattern-REMOVE matches are also explicitly handled — "
            "nothing to test independently"
        )

    deidentified = dicom.deidentify(tmp_path, recipe=DEFAULT_RECIPE)
    for field in sorted(testable):
        assert (
            field not in deidentified.metadata
        ), f"{field} (matched by REMOVE pattern) should have been removed"


# ---------------------------------------------------------------------------
# KEEP — fields should be unchanged
# ---------------------------------------------------------------------------


def test_keep_fields_are_unchanged(dicom, tmp_path, recipe_actions):
    """Fields marked KEEP should retain their original value."""
    keep_fields = [
        f for f in _explicit_fields(recipe_actions, "KEEP") if f in dicom.metadata
    ]
    assert keep_fields, "No testable KEEP fields found"

    orig_values = {f: dicom.metadata[f] for f in keep_fields}
    deidentified = dicom.deidentify(tmp_path, recipe=DEFAULT_RECIPE)
    for field in keep_fields:
        assert field in deidentified.metadata, f"{field} should still be present"
        deid_val = deidentified.metadata[field]
        orig_val = orig_values[field]
        # For collections (DicomDir/DicomSeries), per-file fields like
        # SOPInstanceUID return a list; compare element-wise via sets
        if isinstance(orig_val, list):
            assert set(deid_val) == set(orig_val), f"{field} should be unchanged"
        else:
            assert deid_val == orig_val, f"{field} should be unchanged"


# ---------------------------------------------------------------------------
# REPLACE — fields should have different values
# ---------------------------------------------------------------------------


def test_replace_fields_are_changed(dicom, tmp_path, recipe_actions):
    """Fields marked REPLACE should have a different value after deidentification."""
    replace_fields = [
        f for f in _explicit_fields(recipe_actions, "REPLACE") if f in dicom.metadata
    ]
    assert replace_fields, "No testable REPLACE fields found"

    orig_values = {f: str(dicom.metadata[f]) for f in replace_fields}
    deidentified = dicom.deidentify(tmp_path, recipe=DEFAULT_RECIPE)
    for field in replace_fields:
        assert field in deidentified.metadata, f"{field} should still be present"
        assert (
            str(deidentified.metadata[field]) != orig_values[field]
        ), f"{field} value should have been replaced"


# ---------------------------------------------------------------------------
# ADD — fields should be present with specified value
# ---------------------------------------------------------------------------


def test_add_fields_are_present(dicom, tmp_path, recipe_actions):
    """Fields marked ADD should be present with the specified literal value."""
    add_entries = [
        e for e in recipe_actions.get("ADD", []) if not _is_pattern(e["field"])
    ]
    assert add_entries, "No ADD entries in recipe"

    deidentified = dicom.deidentify(tmp_path, recipe=DEFAULT_RECIPE)
    for entry in add_entries:
        field = entry["field"]
        expected = entry.get("value", "")
        assert field in deidentified.metadata, f"{field} should be present (ADD)"
        if not expected.startswith("var:"):
            assert (
                str(deidentified.metadata[field]) == expected
            ), f"{field} should be '{expected}'"


# ---------------------------------------------------------------------------
# BLANK — fields should be empty
# ---------------------------------------------------------------------------


def test_blank_fields_are_empty(dicom, tmp_path, recipe_actions):
    """Fields marked BLANK should be empty after deidentification."""
    blank_fields = [
        f for f in _explicit_fields(recipe_actions, "BLANK") if f in dicom.metadata
    ]
    assert blank_fields, "No testable BLANK fields found"

    deidentified = dicom.deidentify(tmp_path, recipe=DEFAULT_RECIPE)
    for field in blank_fields:
        value = deidentified.metadata.get(field)
        assert (
            value is None or str(value) == ""
        ), f"{field} should be blank, got {value!r}"


# ---------------------------------------------------------------------------
# JITTER — date fields should shift by the configured number of days
# ---------------------------------------------------------------------------


def test_jitter_fields_unchanged_with_zero_jitter(dicom, tmp_path, recipe_actions):
    """JITTER fields should be unchanged when date_jitter is 0 (the default)."""
    # Only test explicit JITTER fields that aren't overridden by REPLACE/BLANK
    overridden = set(
        _explicit_fields(recipe_actions, "REPLACE")
        + _explicit_fields(recipe_actions, "BLANK")
    )
    jitter_fields = [
        f
        for f in _explicit_fields(recipe_actions, "JITTER")
        if f in dicom.metadata and f not in overridden
    ]
    if not jitter_fields:
        pytest.skip("No testable JITTER fields found")

    orig_values = {f: dicom.metadata[f] for f in jitter_fields}
    deidentified = dicom.deidentify(tmp_path, recipe=DEFAULT_RECIPE)
    for field in jitter_fields:
        assert field in deidentified.metadata, f"{field} should still be present"
        assert (
            deidentified.metadata[field] == orig_values[field]
        ), f"{field} should be unchanged with zero jitter"


# ---------------------------------------------------------------------------
# Private tags — should be removed (strip_sequences / remove_private)
# ---------------------------------------------------------------------------


# def test_private_tags_are_removed(single_dicom, tmp_path):
#     """Private (odd-group) tags should be removed."""
#     orig_ds = pydicom.dcmread(str(single_dicom.fspath))
#     orig_private_tags = [elem.tag for elem in orig_ds if elem.tag.is_private]
#     assert orig_private_tags, "Test DICOM has no private tags"

#     deidentified = single_dicom.deidentify(
#         tmp_path, recipe=DEFAULT_RECIPE
#     )
#     deid_ds = pydicom.dcmread(str(deidentified.fspath))
#     deid_private_tags = [elem.tag for elem in deid_ds if elem.tag.is_private]
#     assert not deid_private_tags, (
#         f"Private tags should have been removed, found: {deid_private_tags}"
#     )


# ---------------------------------------------------------------------------
# Custom variable builders
# ---------------------------------------------------------------------------


def test_custom_transforms_override_defaults(single_dicom, tmp_path):
    """Caller-supplied transforms should override default builders."""
    recipe = DeidRecipeWithTransforms(
        str(DEFAULT_RECIPE_PATH),
        transforms={
            **DEFAULT_RECIPE.transforms,
            "anon_patient_name": lambda _ds: "CUSTOM_NAME",
        },
    )
    deidentified = single_dicom.deidentify(tmp_path, recipe=recipe)
    assert str(deidentified.metadata["PatientName"]) == "CUSTOM_NAME"


def test_custom_transforms_preserve_other_defaults(single_dicom, tmp_path):
    """Overriding one builder should not affect other default builders."""
    recipe = DeidRecipeWithTransforms(
        str(DEFAULT_RECIPE_PATH),
        transforms={
            **DEFAULT_RECIPE.transforms,
            "anon_patient_name": lambda _ds: "CUSTOM_NAME",
        },
    )
    orig_year = single_dicom.metadata["PatientBirthDate"][:4]
    deidentified = single_dicom.deidentify(tmp_path, recipe=recipe)
    assert deidentified.metadata["PatientBirthDate"] == f"{orig_year}0101"


def test_transforms_side_car_custom_recipe(single_dicom, tmp_path):
    """Transforms are loaded from a side-car named after the recipe"""
    recipe_file = tmp_path / "custom.deid"
    recipe_file.write_text("FORMAT dicom\n\n%header\nREPLACE PatientName var:name\n")
    (tmp_path / "custom.transforms.py").write_text(
        'TRANSFORMS = {"name": lambda ds: "FROM_SIDE_CAR"}\n'
    )
    recipe_x = DeidRecipeX(recipe_file)
    assert recipe_x.transforms_file.fspath == tmp_path / "custom.transforms.py"

    deidentified = single_dicom.deidentify(tmp_path / "output", recipe=recipe_x.load())
    assert str(deidentified.metadata["PatientName"]) == "FROM_SIDE_CAR"


def test_transforms_side_car_without_transforms_dict(tmp_path):
    recipe_file = tmp_path / "custom.deid"
    recipe_file.write_text("FORMAT dicom\n\n%header\nREMOVE PatientName\n")
    (tmp_path / "custom.transforms.py").write_text("NOT_TRANSFORMS = {}\n")
    with pytest.raises(ValueError, match="does not define a TRANSFORMS dict"):
        DeidRecipeX(recipe_file).load()


def test_salt_side_car_passed_to_transforms(single_dicom, tmp_path, caplog):
    """The key in the salt side-car is available to the transforms as SALT"""
    recipe_file = tmp_path / "custom.deid"
    recipe_file.write_text("FORMAT dicom\n\n%header\nREPLACE PatientName var:name\n")
    (tmp_path / "custom.transforms.py").write_text(
        "import hashlib\n"
        "TRANSFORMS = {\n"
        '    "name": lambda ds: hashlib.sha256(SALT + b"x").hexdigest()[:16]\n'
        "}\n"
    )
    salt_file = tmp_path / "custom.salt"
    salt_file.write_bytes(b"secret-key\n")
    salt_file.chmod(0o600)

    recipe_x = DeidRecipeX(recipe_file)
    assert recipe_x.salt_file.fspath == salt_file
    with caplog.at_level("WARNING"):
        recipe = recipe_x.load()
    assert "accessible by other users" not in caplog.text

    deidentified = single_dicom.deidentify(tmp_path / "output", recipe=recipe)
    expected = hashlib.sha256(b"secret-key" + b"x").hexdigest()[:16]
    assert str(deidentified.metadata["PatientName"]) == expected


def test_salt_side_car_optional_and_permissions_warning(tmp_path, caplog):
    recipe_file = tmp_path / "custom.deid"
    recipe_file.write_text("FORMAT dicom\n\n%header\nREMOVE PatientName\n")
    (tmp_path / "custom.transforms.py").write_text(
        "TRANSFORMS = {}\nassert SALT is None\n"
    )
    assert DeidRecipeX(recipe_file).salt_file is None
    DeidRecipeX(recipe_file).load()

    salt_file = tmp_path / "custom.salt"
    salt_file.write_bytes(b"secret-key")
    salt_file.chmod(0o644)
    (tmp_path / "custom.transforms.py").write_text("TRANSFORMS = {}\n")
    with caplog.at_level("WARNING"):
        DeidRecipeX(recipe_file).load()
    assert "accessible by other users" in caplog.text


# ---------------------------------------------------------------------------
# Missing transforms — recipe references var: but transforms not provided
# ---------------------------------------------------------------------------


def test_missing_transforms_raises():
    """Loading a recipe that references var: variables without its transforms
    side-car should raise ValueError."""
    with pytest.raises(ValueError, match="var: variables"):
        DeidRecipeFile(DEFAULT_RECIPE_PATH).load()


def test_partial_transforms_raises():
    """Should raise ValueError when only some of the required transforms are provided."""
    partial = {"anon_patient_id": lambda _ds: "test"}
    with pytest.raises(ValueError, match="var: variables"):
        DeidRecipeWithTransforms(str(DEFAULT_RECIPE_PATH), transforms=partial)


def test_plain_deid_recipe_rejected(single_dicom, tmp_path):
    """A deid recipe that wasn't loaded from a DeidRecipe fileset is rejected"""
    with pytest.raises(TypeError, match="Expected data loaded from DeidRecipe"):
        single_dicom.deidentify(tmp_path, recipe=DeidRecipe(str(DEFAULT_RECIPE_PATH)))


# ---------------------------------------------------------------------------
# Custom recipe
# ---------------------------------------------------------------------------


def test_custom_recipe_path(single_dicom, tmp_path):
    """A custom recipe file should be used instead of the default."""
    recipe_file = tmp_path / "custom.dicom"
    recipe_file.write_text(
        "FORMAT dicom\n\n%header\nREPLACE PatientName CUSTOM_FROM_RECIPE\n"
    )
    out_dir = tmp_path / "output"
    recipe = DeidRecipeFile(recipe_file).load()
    deidentified = single_dicom.deidentify(out_dir, recipe=recipe)
    assert str(deidentified.metadata["PatientName"]) == "CUSTOM_FROM_RECIPE"


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------


def test_deidentify_creates_output_dir(single_dicom, tmp_path):
    """Output directory should be created if it doesn't exist."""
    out_dir = tmp_path / "nested" / "output"
    single_dicom.deidentify(out_dir, recipe=DEFAULT_RECIPE)
    assert out_dir.is_dir()


def test_deidentify_output_is_valid_dicom(single_dicom, tmp_path):
    """Output file should be a valid DICOM that pydicom can read."""
    deidentified = single_dicom.deidentify(tmp_path, recipe=DEFAULT_RECIPE)
    ds = pydicom.dcmread(str(deidentified.fspath))
    assert ds.PatientName is not None


# ---------------------------------------------------------------------------
# Unsupported format
# ---------------------------------------------------------------------------


def test_nifti_deidentify_raises(tmp_path):
    """Calling deidentify on an unsupported format should raise."""
    nifti = Nifti1.sample()
    with pytest.raises(FileFormatsExtrasError):
        nifti.deidentify(tmp_path)


# ---------------------------------------------------------------------------
# Recipe format
# ---------------------------------------------------------------------------


def test_recipe_type_from_implementation(single_dicom):
    """The recipe formats can be found from the deidentify implementation signature"""
    impl = find_extra_implementation(MedicalImagingData.deidentify, type(single_dicom))
    hint = ty.get_type_hints(impl, include_extras=True)["recipe"]
    markers = LoadedMarker.all_from_hint(hint)
    assert [m.format for m in markers] == [DeidRecipeX, DeidRecipeFile]


def test_recipe_wrong_type(single_dicom, tmp_path):
    with pytest.raises(TypeError, match="Expected data loaded from DeidRecipe"):
        single_dicom.deidentify(tmp_path, recipe=str(DEFAULT_RECIPE_PATH))
