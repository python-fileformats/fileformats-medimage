import json
import os
import subprocess
import sys

import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage


@pytest.fixture
def instances(tmp_path):
    for number in (4, 2, 6, 1, 5, 3):
        path = tmp_path / f"instance-{number}.dcm"
        meta = FileMetaDataset()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        meta.MediaStorageSOPClassUID = MRImageStorage
        meta.MediaStorageSOPInstanceUID = f"1.2.826.0.1.3680043.10.99.{number}"
        dataset = FileDataset(path, {}, file_meta=meta, preamble=b"\0" * 128)
        dataset.SOPClassUID = meta.MediaStorageSOPClassUID
        dataset.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
        dataset.StudyInstanceUID = "1.2.826.0.1.3680043.10.99.100"
        dataset.SeriesInstanceUID = "1.2.826.0.1.3680043.10.99.101"
        dataset.PatientName = dataset.PatientID = "SYNTHETIC"
        dataset.Modality = "MR"
        dataset.InstanceNumber = number
        dataset.ImagePositionPatient = [0, 0, number]
        dataset.Rows = dataset.Columns = dataset.SamplesPerPixel = 1
        dataset.PhotometricInterpretation = "MONOCHROME2"
        dataset.BitsAllocated = dataset.BitsStored = 16
        dataset.HighBit = 15
        dataset.PixelRepresentation = 0
        dataset.PixelData = b"\0\0"
        dataset.save_as(path, write_like_original=False)
    return tmp_path


@pytest.mark.parametrize("collection_name", ["DicomSeries", "DicomDir"])
def test_metadata_order_is_stable_across_hash_seeds(instances, collection_name):
    script = """
import json
from pathlib import Path
import sys
from fileformats.medimage import DicomImage, DicomDir, DicomSeries

directory = Path(sys.argv[1])
collection_type = {"DicomSeries": DicomSeries, "DicomDir": DicomDir}[sys.argv[2]]
paths = list(directory.glob("*.dcm"))
collection = collection_type(paths if collection_type is DicomSeries else directory)

def forbidden_contents(self):
    raise AssertionError("The metadata reader must use the base collection")

collection_type.contents = property(forbidden_contents)
metadata = dict(collection.metadata)
keys = ("SOPInstanceUID", "InstanceNumber", "ImagePositionPatient")
expected_rows = []
for path in paths:
    instance = DicomImage(path)
    expected_rows.append([instance.metadata[key] for key in keys])
expected_rows.sort(key=lambda row: row[0])
print(json.dumps({"metadata": metadata, "expected_rows": expected_rows}, default=str))
"""
    results = []
    for seed in (1, 2, 3):
        result = subprocess.run(
            [sys.executable, "-c", script, str(instances), collection_name],
            env=dict(os.environ, PYTHONHASHSEED=str(seed)),
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        results.append(json.loads(result.stdout))
    assert results[0]["metadata"] == results[1]["metadata"] == results[2]["metadata"]
    metadata = results[0]["metadata"]
    rows = list(
        map(
            list,
            zip(
                metadata["SOPInstanceUID"],
                metadata["InstanceNumber"],
                metadata["ImagePositionPatient"],
            ),
        )
    )
    assert rows == results[0]["expected_rows"]
