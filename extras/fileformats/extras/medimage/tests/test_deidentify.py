"""Generic deidentification tests.

Tests verify the deidentification *mechanism* works correctly for any deid recipe
by parsing the recipe programmatically. Adding or changing recipe rules does not
require updating tests.
"""

import os
import zipfile
import pytest
import pydicom
from pathlib import Path
from deid.config import DeidRecipe
from fileformats.core.exceptions import FileFormatsExtrasError
from medimages4tests.dummy.dicom.mri.t1w.siemens.skyra.syngo_d13c import (
    get_image as get_dicom_image,
)

from fileformats.medimage import DicomDir, DicomImage, DicomSeries, DicomZip, Nifti1

# ---------------------------------------------------------------------------
# Recipe and variable builders (mirrors what the consumer must supply)
# ---------------------------------------------------------------------------

DEFAULT_RECIPE = Path(__file__).parent / "recipe.dicom"

DEFAULT_VARIABLE_BUILDERS = {
    "anon_birth_date": lambda ds: str(ds.get("PatientBirthDate", ""))[:4] + "0101",
    "anon_patient_name": lambda ds: str(ds.get("PatientID", "")),
    "anon_patient_id": lambda ds: (
        f"{ds.get('PatientID', '')}-{ds.get('AcquisitionTime', '')}"
    ),
    "patient_comments": lambda ds: (
        f"Project={ds.get('ReferringPhysicianName', '')};"
        f"Subject={ds.get('PatientID', '')};"
        f"Session={ds.get('PatientID', '')}-{ds.get('AcquisitionTime', '')}"
    ),
    "date_jitter": lambda _ds: int(os.environ.get("DEID_DATE_JITTER", "0")),
}

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
    return _parse_actions(DEFAULT_RECIPE)


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

    deidentified = dicom.deidentify(
        tmp_path, spec=DEFAULT_RECIPE, transforms=DEFAULT_VARIABLE_BUILDERS
    )
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

    deidentified = dicom.deidentify(
        tmp_path, spec=DEFAULT_RECIPE, transforms=DEFAULT_VARIABLE_BUILDERS
    )
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
    deidentified = dicom.deidentify(
        tmp_path, spec=DEFAULT_RECIPE, transforms=DEFAULT_VARIABLE_BUILDERS
    )
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
    deidentified = dicom.deidentify(
        tmp_path, spec=DEFAULT_RECIPE, transforms=DEFAULT_VARIABLE_BUILDERS
    )
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

    deidentified = dicom.deidentify(
        tmp_path, spec=DEFAULT_RECIPE, transforms=DEFAULT_VARIABLE_BUILDERS
    )
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

    deidentified = dicom.deidentify(
        tmp_path, spec=DEFAULT_RECIPE, transforms=DEFAULT_VARIABLE_BUILDERS
    )
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
    deidentified = dicom.deidentify(
        tmp_path, spec=DEFAULT_RECIPE, transforms=DEFAULT_VARIABLE_BUILDERS
    )
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
#         tmp_path, spec=DEFAULT_RECIPE, transforms=DEFAULT_VARIABLE_BUILDERS
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
    custom_builders = {
        **DEFAULT_VARIABLE_BUILDERS,
        "anon_patient_name": lambda _ds: "CUSTOM_NAME",
    }
    deidentified = single_dicom.deidentify(
        tmp_path, spec=DEFAULT_RECIPE, transforms=custom_builders
    )
    assert str(deidentified.metadata["PatientName"]) == "CUSTOM_NAME"


def test_custom_transforms_preserve_other_defaults(single_dicom, tmp_path):
    """Overriding one builder should not affect other default builders."""
    custom_builders = {
        **DEFAULT_VARIABLE_BUILDERS,
        "anon_patient_name": lambda _ds: "CUSTOM_NAME",
    }
    orig_year = single_dicom.metadata["PatientBirthDate"][:4]
    deidentified = single_dicom.deidentify(
        tmp_path, spec=DEFAULT_RECIPE, transforms=custom_builders
    )
    assert deidentified.metadata["PatientBirthDate"] == f"{orig_year}0101"


# ---------------------------------------------------------------------------
# Missing transforms — recipe references var: but transforms not provided
# ---------------------------------------------------------------------------


def test_missing_transforms_raises(single_dicom, tmp_path):
    """Should raise ValueError when recipe has var: references but transforms are missing."""
    with pytest.raises(ValueError, match="var: variables"):
        single_dicom.deidentify(tmp_path, spec=DEFAULT_RECIPE)


def test_partial_transforms_raises(single_dicom, tmp_path):
    """Should raise ValueError when only some of the required transforms are provided."""
    partial = {"anon_patient_id": lambda _ds: "test"}
    with pytest.raises(ValueError, match="var: variables"):
        single_dicom.deidentify(tmp_path, spec=DEFAULT_RECIPE, transforms=partial)


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
    deidentified = single_dicom.deidentify(out_dir, spec=str(recipe_file))
    assert str(deidentified.metadata["PatientName"]) == "CUSTOM_FROM_RECIPE"


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------


def test_deidentify_creates_output_dir(single_dicom, tmp_path):
    """Output directory should be created if it doesn't exist."""
    out_dir = tmp_path / "nested" / "output"
    single_dicom.deidentify(
        out_dir, spec=DEFAULT_RECIPE, transforms=DEFAULT_VARIABLE_BUILDERS
    )
    assert out_dir.is_dir()


def test_deidentify_output_is_valid_dicom(single_dicom, tmp_path):
    """Output file should be a valid DICOM that pydicom can read."""
    deidentified = single_dicom.deidentify(
        tmp_path, spec=DEFAULT_RECIPE, transforms=DEFAULT_VARIABLE_BUILDERS
    )
    ds = pydicom.dcmread(str(deidentified.fspath))
    assert ds.PatientName is not None


# ---------------------------------------------------------------------------
# DicomZip format
# ---------------------------------------------------------------------------


def _make_dicom_zip(tmp_path: Path, seed: int = 0) -> DicomZip:
    """Helper: create a DicomZip from a sample DicomSeries."""
    series = DicomSeries.sample(tmp_path / f"src_{seed}", seed=seed)
    zip_path = tmp_path / f"dicoms_{seed}.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for fspath in series.fspaths:
            zf.write(fspath, fspath.name)
    return DicomZip(zip_path)


def test_dicom_zip_deidentify(tmp_path: Path) -> None:
    """Deidentifying a DicomZip produces a new DicomZip with replaced fields."""
    dz = _make_dicom_zip(tmp_path)
    out_dir = tmp_path / "deid_out"
    deid_dz = dz.deidentify(
        out_dir, spec=DEFAULT_RECIPE, transforms=DEFAULT_VARIABLE_BUILDERS
    )
    assert isinstance(deid_dz, DicomZip)
    assert deid_dz.fspath != dz.fspath
    assert deid_dz.num_members == dz.num_members


def test_dicom_zip_deidentify_replaces_patient_name(tmp_path: Path) -> None:
    """PatientName should be replaced after deidentification."""
    dz = _make_dicom_zip(tmp_path)

    # Read original PatientName from the zip
    with zipfile.ZipFile(dz.fspath) as zf:
        first = sorted(
            n for n in zf.namelist() if n.endswith(".dcm") or not n.endswith("/")
        )[0]
        orig_ds = pydicom.dcmread(
            pydicom.filebase.DicomBytesIO(zf.read(first)),
            stop_before_pixels=True,
            force=True,
        )
    orig_name = str(orig_ds.get("PatientName", ""))

    out_dir = tmp_path / "deid_out"
    deid_dz = dz.deidentify(
        out_dir, spec=DEFAULT_RECIPE, transforms=DEFAULT_VARIABLE_BUILDERS
    )

    # Read deidentified PatientName
    with zipfile.ZipFile(deid_dz.fspath) as zf:
        first = sorted(
            n for n in zf.namelist() if n.endswith(".dcm") or not n.endswith("/")
        )[0]
        deid_ds = pydicom.dcmread(
            pydicom.filebase.DicomBytesIO(zf.read(first)),
            stop_before_pixels=True,
            force=True,
        )
    deid_name = str(deid_ds.get("PatientName", ""))
    assert deid_name != orig_name, "PatientName should have been replaced"


def test_dicom_zip_deidentify_all_members_valid(tmp_path: Path) -> None:
    """Every file in the deidentified zip should be a valid DICOM."""
    dz = _make_dicom_zip(tmp_path)
    out_dir = tmp_path / "deid_out"
    deid_dz = dz.deidentify(
        out_dir, spec=DEFAULT_RECIPE, transforms=DEFAULT_VARIABLE_BUILDERS
    )
    with zipfile.ZipFile(deid_dz.fspath, "r") as zf:
        for name in zf.namelist():
            data = zf.read(name)
            assert data[128:132] == b"DICM"


# ---------------------------------------------------------------------------
# Unsupported format
# ---------------------------------------------------------------------------


def test_nifti_deidentify_raises(tmp_path):
    """Calling deidentify on an unsupported format should raise."""
    nifti = Nifti1.sample()
    with pytest.raises(FileFormatsExtrasError):
        nifti.deidentify(tmp_path)
