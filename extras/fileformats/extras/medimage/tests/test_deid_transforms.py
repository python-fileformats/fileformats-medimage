"""Tests of the declarative (YAML) deid transforms, version 0.1"""

import hashlib
import re
import typing as ty
from pathlib import Path

import pydicom
import pytest
import yaml
from deid.dicom.fields import DicomField

from fileformats.extras.medimage.deid_transforms import (
    DeidTransformsError,
    load_transforms,
)

SALT = b"secret-key"


@pytest.fixture
def dataset() -> pydicom.Dataset:
    ds = pydicom.Dataset()
    ds.PatientID = "P001"
    ds.PatientName = "Doe^Jane"
    ds.PatientBirthDate = "19830514"
    ds.AcquisitionTime = "101500"
    ds.ReferringPhysicianName = "MYPROJECT"
    ds.AccessionNumber = "ACC123"
    ds.StudyID = "S42"
    ds.ImageType = ["ORIGINAL", "PRIMARY"]
    ds.StudyDescription = " MiXed "
    ds.PatientComments = ""
    return ds


def variables(yaml_text: str, salt: bytes | None = None) -> dict[str, ty.Any]:
    return load_transforms(yaml.safe_load(yaml_text), salt=salt).variables


def evaluate(
    expression_yaml: str, dataset: pydicom.Dataset, salt: bytes | None = None
) -> ty.Any:
    spec = {"version": "0.1", "variables": {"v": yaml.safe_load(expression_yaml)}}
    return load_transforms(spec, salt=salt).variables["v"](dataset)


def apply_function(
    expression_yaml: str,
    dataset: pydicom.Dataset,
    keyword: str,
    salt: bytes | None = None,
) -> ty.Any:
    """Calls a compiled function the way deid does for a field of the dataset"""
    spec = {"version": "0.1", "functions": {"f": yaml.safe_load(expression_yaml)}}
    func = load_transforms(spec, salt=salt).functions["f"]
    element = dataset[keyword]
    field = DicomField(element, keyword, keyword)
    return func(item={}, value="func:f", field=field, dicom=dataset)


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("section", ["variables", "functions"])
@pytest.mark.parametrize("constant", ["ANONYMOUS", 10, None])
def test_constant_definitions_rejected(section, constant):
    """Constants are written in the recipe directly, e.g. 'REPLACE PatientName
    ANONYMOUS' or 'BLANK PatientName', so that there is only one way to write them"""
    with pytest.raises(DeidTransformsError, match="written in the recipe directly"):
        load_transforms({"version": "0.1", section: {"v": constant}})


def test_literals_as_arguments(dataset):
    """Literals can be used wherever an expression is an argument"""
    assert evaluate("{tag: PatientSex, default: ANONYMOUS}", dataset) == "ANONYMOUS"
    assert evaluate("{tag: PatientSex, default: 10}", dataset) == 10
    assert evaluate("{tag: PatientID, apply: [{suffix: 10}]}", dataset) == "P00110"


@pytest.mark.parametrize("tag", ["PatientID", "(0010,0020)", "0010,0020", "00100020"])
def test_tag(dataset, tag):
    assert evaluate(f'{{tag: "{tag}"}}', dataset) == "P001"


def test_tag_missing_and_default(dataset):
    assert evaluate("{tag: PatientSex}", dataset) is None
    assert evaluate("{tag: PatientSex, default: O}", dataset) == "O"


def test_tag_multi_valued(dataset):
    assert evaluate("{tag: ImageType}", dataset) == "ORIGINAL\\PRIMARY"


def test_tag_person_name(dataset):
    assert evaluate("{tag: PatientName}", dataset) == "Doe^Jane"


def test_env(dataset, monkeypatch):
    monkeypatch.setenv("DEID_DATE_JITTER", "-7")
    assert evaluate("{env: DEID_DATE_JITTER, apply: [to_int]}", dataset) == -7
    monkeypatch.delenv("DEID_DATE_JITTER")
    assert (
        evaluate("{env: DEID_DATE_JITTER, default: 0, apply: [to_int]}", dataset) == 0
    )


def test_template(dataset):
    expression = """
    template:
      format: "Project={project};Subject={subject};Session={subject}-{time} {{x}}"
      values:
        project: {tag: ReferringPhysicianName}
        subject: {tag: PatientID}
        time: {tag: AcquisitionTime}
    """
    assert (
        evaluate(expression, dataset)
        == "Project=MYPROJECT;Subject=P001;Session=P001-101500 {x}"
    )


def test_template_missing_value_is_empty(dataset):
    expression = '{template: {format: "{a}-{b}", values: {a: {tag: PatientID}, b: {tag: PatientSex}}}}'
    assert evaluate(expression, dataset) == "P001-"


def test_template_doesnt_allow_attribute_access(dataset):
    with pytest.raises(DeidTransformsError, match="unmatched"):
        evaluate(
            '{template: {format: "{a.__class__}", values: {a: {tag: PatientID}}}}',
            dataset,
        )


def test_template_undefined_placeholder(dataset):
    with pytest.raises(DeidTransformsError, match="'{b}' isn't defined"):
        evaluate(
            '{template: {format: "{a}{b}", values: {a: {tag: PatientID}}}}', dataset
        )


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "apply,expected",
    [
        ("[{truncate: 4}, {suffix: '0101'}]", "19830101"),
        ("[{slice: {start: 4, stop: 6}}]", "05"),
        ("[{slice: {start: -2}}]", "14"),
        ("[{prefix: 'DOB-'}]", "DOB-19830514"),
        ("[{replace: {old: '1983', new: 'XXXX'}}]", "XXXX0514"),
        ("[to_int]", 19830514),
        ("[to_int, to_str]", "19830514"),
    ],
)
def test_operations(dataset, apply, expected):
    assert evaluate(f"{{tag: PatientBirthDate, apply: {apply}}}", dataset) == expected


def test_case_and_strip(dataset):
    assert (
        evaluate("{tag: StudyDescription, apply: [strip, upper]}", dataset) == "MIXED"
    )
    assert (
        evaluate("{tag: StudyDescription, apply: [strip, lower]}", dataset) == "mixed"
    )


def test_operations_pass_through_missing_values(dataset):
    assert (
        evaluate(
            "{tag: PatientSex, apply: [{truncate: 1}, upper, {suffix: x}]}", dataset
        )
        is None
    )


def test_default_operation_and_blank_if_empty(dataset):
    assert evaluate("{tag: PatientComments, apply: [{default: N/A}]}", dataset) == "N/A"
    assert evaluate("{tag: PatientComments, apply: [blank_if_empty]}", dataset) is None
    assert evaluate("{tag: PatientID, apply: [blank_if_empty]}", dataset) == "P001"


def test_to_int_invalid(dataset):
    spec = {
        "version": "0.1",
        "variables": {"v": {"tag": "PatientID", "apply": ["to_int"]}},
    }
    builder = load_transforms(spec).variables["v"]
    with pytest.raises(ValueError, match="can't be converted to an integer"):
        builder(dataset)


def test_hash_salted(dataset):
    result = evaluate(
        "{tag: PatientID, apply: [{hash: {length: 24}}]}", dataset, salt=SALT
    )
    assert result == hashlib.sha256(SALT + b"P001").hexdigest()[:24]


def test_hash_unsalted_with_namespace_and_algorithm(dataset):
    result = evaluate(
        "{tag: AccessionNumber, apply: [{hash: {salt: false, namespace: AccessionNumber, algorithm: sha512, length: 16}}]}",
        dataset,
    )
    assert result == hashlib.sha512(b"AccessionNumberACC123").hexdigest()[:16]


def test_hash_full_length(dataset):
    result = evaluate("{tag: PatientID, apply: [{hash: {salt: false}}]}", dataset)
    assert result == hashlib.sha256(b"P001").hexdigest()


def test_hash_salted_requires_salt(dataset):
    with pytest.raises(DeidTransformsError, match="salt side-car"):
        evaluate("{tag: PatientID, apply: [hash]}", dataset)


def test_hash_invalid_algorithm(dataset):
    with pytest.raises(DeidTransformsError, match="isn't supported"):
        evaluate(
            "{tag: PatientID, apply: [{hash: {algorithm: md5, salt: false}}]}", dataset
        )


# ---------------------------------------------------------------------------
# Functions (func:), which are applied to the field they are referenced by
# ---------------------------------------------------------------------------


def test_function_field_value_and_name(dataset):
    assert apply_function("{field: value}", dataset, "PatientID") == "P001"
    assert (
        apply_function("{field: name}", dataset, "AccessionNumber") == "AccessionNumber"
    )


def test_function_for_added_field(dataset):
    """For ADD actions deid passes the name of the tag rather than its element"""
    spec = {"version": "0.1", "functions": {"f": {"field": "name"}}}
    func = load_transforms(spec).functions["f"]
    assert func(
        item={}, value="func:f", field="PatientIdentityRemoved", dicom=dataset
    ) == ("PatientIdentityRemoved")


def test_field_not_allowed_in_variables(dataset):
    with pytest.raises(DeidTransformsError, match="only be used in functions"):
        evaluate("{field: value}", dataset)


# The ais_deid transforms (ais_deid.dicom.transforms), as YAML
AIS_DEID_TRANSFORMS = """
version: "0.1"
description: Equivalent of the ais_deid transforms, with salting disabled as it is there
variables:
  anon_patient_id:
    tag: PatientID
    apply: [blank_if_empty, {hash: {salt: false, length: 24}}]
  anon_accession_number:
    tag: AccessionNumber
    apply: [blank_if_empty, {hash: {salt: false, length: 16, namespace: AccessionNumber}}]
  anon_study_id:
    tag: StudyID
    apply: [blank_if_empty, {hash: {salt: false, length: 16, namespace: StudyID}}]
  date_jitter: {env: DEID_DATE_JITTER, default: 0, apply: [to_int]}
functions:
  hash_patient_id:
    field: value
    apply: [blank_if_empty, {hash: {salt: false, length: 24}}]
  hash_accession_number:
    field: value
    apply: [blank_if_empty, {hash: {salt: false, length: 16, namespace: {field: name}}}]
"""


def test_ais_deid_equivalents(dataset, monkeypatch):
    monkeypatch.delenv("DEID_DATE_JITTER", raising=False)
    loaded = load_transforms(yaml.safe_load(AIS_DEID_TRANSFORMS))

    def sha(data: str, length: int) -> str:
        return hashlib.sha256(data.encode()).hexdigest()[:length]

    v = {name: builder(dataset) for name, builder in loaded.variables.items()}
    assert v == {
        "anon_patient_id": sha("P001", 24),
        "anon_accession_number": sha("AccessionNumberACC123", 16),
        "anon_study_id": sha("StudyIDS42", 16),
        "date_jitter": 0,
    }

    field = DicomField(dataset["AccessionNumber"], "AccessionNumber", "AccessionNumber")
    call = dict(item={}, value="func:x", field=field, dicom=dataset)
    assert loaded.functions["hash_accession_number"](**call) == sha(
        "AccessionNumberACC123", 16
    )

    dataset.PatientID = ""
    pid_field = DicomField(dataset["PatientID"], "PatientID", "PatientID")
    assert (
        loaded.functions["hash_patient_id"](
            item={}, value="func:x", field=pid_field, dicom=dataset
        )
        is None
    )


# ---------------------------------------------------------------------------
# Validation and versioning
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spec,match",
    [
        ({}, "'version' is required"),
        ({"version": "0.2"}, "only versions 0.1 are supported"),
        ({"version": "0.1", "unknown": 1}, "unknown key"),
        ({"version": "0.1", "variables": {"1bad": "x"}}, "isn't a valid name"),
        (
            {"version": "0.1", "variables": {"v": {"tag": "NotAKeyword"}}},
            "known DICOM keyword",
        ),
        (
            {"version": "0.1", "variables": {"v": {"tag": "PatientID", "env": "X"}}},
            "exactly one",
        ),
        ({"version": "0.1", "variables": {"v": {"python": "1+1"}}}, "unknown source"),
        ({"version": "0.1", "variables": {"v": {"value": "x"}}}, "unknown source"),
        (
            {
                "version": "0.1",
                "variables": {"v": {"tag": "PatientID", "apply": ["eval"]}},
            },
            "unknown operation",
        ),
        (
            {
                "version": "0.1",
                "variables": {"v": {"tag": "PatientID", "apply": "upper"}},
            },
            "list of operations",
        ),
        (
            {
                "version": "0.1",
                "variables": {"v": {"tag": "PatientID", "apply": [{"truncate": -1}]}},
            },
            "non-negative",
        ),
        (
            {
                "version": "0.1",
                "variables": {"v": {"tag": "PatientID", "apply": [{"upper": 1}]}},
            },
            "doesn't take",
        ),
    ],
)
def test_invalid_specs(spec, match):
    with pytest.raises(DeidTransformsError, match=match):
        load_transforms(spec)


def test_errors_report_their_location():
    spec = {
        "version": "0.1",
        "variables": {
            "v": {
                "template": {
                    "format": "{a}",
                    "values": {"a": {"tag": "PatientID", "apply": [{"truncate": "4"}]}},
                }
            }
        },
    }
    with pytest.raises(
        DeidTransformsError,
        match=r"variables\.v\.template\.values\.a\.apply\[0\]\.truncate",
    ):
        load_transforms(spec)


def test_version_can_be_a_number():
    """`version: 0.1` (unquoted) is parsed by YAML as a float"""
    assert load_transforms(yaml.safe_load("version: 0.1")).version == "0.1"


def test_extension_keys_are_ignored(dataset):
    spec = yaml.safe_load("""
        version: "0.1"
        x-owner: ais
        variables:
          v:
            tag: PatientID
            x-note: anything
            apply: [upper]
        """)
    assert load_transforms(spec).variables["v"](dataset) == "P001"


SPEC_DOC = Path(__file__).parents[5] / "docs" / "deid-transforms-0.1.md"


@pytest.mark.skipif(not SPEC_DOC.exists(), reason="spec document isn't available")
def test_spec_examples_are_valid(dataset):
    """The complete examples in the spec document load and evaluate"""
    blocks = re.findall(r"```yaml\n(.*?)```", SPEC_DOC.read_text(), re.DOTALL)
    # the outline of the document structure has "<placeholders>" rather than values
    examples = [yaml.safe_load(b) for b in blocks if "<" not in b]
    examples = [e for e in examples if isinstance(e, dict) and "version" in e]
    assert len(examples) >= 3
    for example in examples:
        loaded = load_transforms(example, salt=SALT)
        for builder in loaded.variables.values():
            builder(dataset)
