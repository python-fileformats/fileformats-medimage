import zipfile
from pathlib import Path
import pytest
from fileformats.core.exceptions import FormatMismatchError
from fileformats.medimage import DicomSeries, DicomZip


def _make_dicom_zip(tmp_path: Path, seed: int = 0) -> DicomZip:
    """Helper: create a DicomZip from a sample DicomSeries."""
    series = DicomSeries.sample(tmp_path / f"src_{seed}", seed=seed)
    zip_path = tmp_path / f"dicoms_{seed}.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for fspath in series.fspaths:
            zf.write(fspath, fspath.name)
    return DicomZip(zip_path)


def test_dicom_zip_identify(tmp_path: Path) -> None:
    dz = _make_dicom_zip(tmp_path)
    assert dz.fspath.suffix == ".zip"


def test_dicom_zip_num_members(tmp_path: Path) -> None:
    series = DicomSeries.sample(tmp_path / "src")
    dz = _make_dicom_zip(tmp_path)
    assert dz.num_members == len(series)


def test_dicom_zip_extract_first(tmp_path: Path) -> None:
    dz = _make_dicom_zip(tmp_path)
    dest = tmp_path / "extracted"
    sample = dz.extract_first(dest)
    assert sample is not None
    assert sample.exists()
    # Verify the extracted file has a valid DICOM preamble
    data = sample.read_bytes()
    assert data[128:132] == b"DICM"


def test_dicom_zip_rejects_empty_zip(tmp_path: Path) -> None:
    zip_path = tmp_path / "empty.zip"
    with zipfile.ZipFile(zip_path, "w"):
        pass
    with pytest.raises(FormatMismatchError):
        DicomZip(zip_path)


def test_dicom_zip_peek_header(tmp_path: Path) -> None:
    dz = _make_dicom_zip(tmp_path)
    header = dz.peek_header()
    assert "Modality" in header
    assert "StudyInstanceUID" in header
    assert "SeriesNumber" in header
    # Sample DICOMs should have non-None values for these
    assert header["Modality"] is not None
    assert header["StudyInstanceUID"] is not None


def test_dicom_zip_peek_header_custom_tags(tmp_path: Path) -> None:
    dz = _make_dicom_zip(tmp_path)
    tags = {"Modality": (0x0008, 0x0060)}
    header = dz.peek_header(tags=tags)
    assert list(header.keys()) == ["Modality"]
    assert header["Modality"] is not None


def test_dicom_zip_peek_header_empty_rejected(tmp_path: Path) -> None:
    """An empty zip is rejected at construction (invalid magic number)."""
    zip_path = tmp_path / "empty.zip"
    with zipfile.ZipFile(zip_path, "w"):
        pass
    with pytest.raises(FormatMismatchError):
        DicomZip(zip_path)
