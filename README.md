# FileFormats-Medimage

[![CI/CD](https://github.com/python-fileformats/fileformats-medimage/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/python-fileformats/fileformats-medimage/actions/workflows/ci-cd.yml)
[![Codecov](https://codecov.io/gh/python-fileformats/fileformats-medimage/branch/main/graph/badge.svg?token=UIS0OGPST7)](https://codecov.io/gh/python-fileformats/fileformats-medimage)
![Static Badge](https://img.shields.io/badge/type%20checked-mypy-039dfc)
[![Supported Python versions](https://img.shields.io/pypi/pyversions/fileformats-medimage.svg)](https://pypi.python.org/pypi/fileformats-medimage/)
[![Latest Version](https://img.shields.io/pypi/v/fileformats-medimage.svg)](https://pypi.python.org/pypi/fileformats-medimage/)
[![Documentation Status](https://img.shields.io/badge/docs-latest-brightgreen.svg?style=flat)](https://python-fileformats.github.io/fileformats-medimage/)

*FileFormats-Medimage* is an extension of the [FileFormats](https://github.com/python-fileformats/fileformats)
package for the file formats used in medical imaging, particularly medical imaging research.
It provides Python classes for validating, detecting and typing:

* **DICOM**: single files, and series of them, either in a directory (`DicomDir`) or as a
  set of files (`DicomSeries`)
* **NIfTI**: NIfTI-1/2, gzipped, with [BIDS](https://bids.neuroimaging.io) JSON side-cars,
  and with FSL-style diffusion encodings (e.g. `NiftiGzX`, `NiftiGzBvec`)
* **other image formats** from neuroimaging and image analysis tools: Analyze, FreeSurfer MGH,
  NRRD, MetaImage, VTK, GIPL and GIFTI surfaces
* **raw data**: MRI k-space and spectroscopy, and PET list-mode, sinograms, count rates and
  normalisation
* **deidentification recipes** for the [deid](https://pydicom.github.io/deid/) package, with
  declarative side-cars for values that have to be computed

Like the main package, the format classes have no external dependencies. Multi-file
formats, e.g. a NIfTI image with its JSON side-car or a DICOM series, are handled as single
objects that can be validated, copied, moved and hashed together. Classifiers describing
the contents of an image (modality, contrast, anatomy, derivatives) can be attached to
formats to type data more specifically, e.g. `NiftiGz[T1w]`.

Functionality that needs external libraries is implemented in the sister package
[fileformats-medimage-extras](https://pypi.org/project/fileformats-medimage-extras/):
reading image data and headers, generating sample data, converting between formats (e.g.
DICOM to NIfTI with [dcm2niix](https://github.com/rordenlab/dcm2niix)), and deidentifying
DICOMs.

See the [documentation](https://python-fileformats.github.io/fileformats-medimage/) for the full
list of formats and the extras they support.

## Installation

*FileFormats-Medimage* can be installed for Python >= 3.11 from PyPI with

```console
$ python3 -m pip install fileformats-medimage
```

To read image data and metadata, convert between formats and deidentify images, also
install the extras package

```console
$ python3 -m pip install fileformats-medimage-extras
```

The converters wrap command-line tools that need to be installed separately:
[dcm2niix](https://github.com/rordenlab/dcm2niix) for DICOM to NIfTI conversion, and
[MRtrix3](https://www.mrtrix.org) for conversion to Analyze and MRtrix formats. On Ubuntu,
for example

```console
$ sudo apt install libopenjp2-7
$ curl -fLO https://github.com/rordenlab/dcm2niix/releases/latest/download/dcm2niix_lnx.zip
$ unzip dcm2niix_lnx.zip && sudo mv dcm2niix /usr/local/bin
$ conda install -c mrtrix3 mrtrix3
```

(on macOS, use Homebrew in place of `apt`).

## Examples

Instantiating a format class checks that the files are of that format, raising a
`FormatMismatchError` if they aren't

```python
from pathlib import Path
from fileformats.medimage import DicomSeries, NiftiGzX

series = DicomSeries(Path("/path/to/dicoms").iterdir())
nifti = NiftiGzX("/path/to/sub-01_T1w.nii.gz", "/path/to/sub-01_T1w.json")
nifti.json_file  # the BIDS side-car
```

Formats that aren't registered with IANA are identified by "MIME-like" strings in the
`medimage` namespace, and classifiers can be attached to formats with square brackets

```python
from fileformats.core import from_mime, to_mime
from fileformats.medimage import NiftiGz, T1w

from_mime("medimage/dicom-series")  # -> DicomSeries
to_mime(NiftiGz[T1w], official=False)  # -> 'medimage/t1-weighted+nifti-gz'
```

With the extras installed, headers can be read and data converted

```python
series.metadata["SeriesDescription"]  # read with pydicom
nifti = NiftiGzX.convert(series)  # converted with dcm2niix
nifti.dims(), nifti.vox_sizes()
```

## Deidentification

All formats holding medical imaging data have a `deidentify` method, which is implemented
for DICOM in the extras using [deid](https://pydicom.github.io/deid/) recipes. A recipe can
have side-cars: a `.transforms.yaml` file declaring the values of the computed `var:` and
`func:` references in the recipe (e.g. a salted hash of the patient ID), and a `.salt` file
holding the key to salt hashes with

```python
from fileformats.medimage import DeidRecipeX

recipe = DeidRecipeX("/path/to/specs/dicom-series.deid").load()
deidentified = series.deidentify("/path/to/output", recipe=recipe)
```

Each `deidentify` implementation declares the format its recipe is loaded from with a
`Loaded[<recipe format>]` annotation, so other packages can add deidentification for their
own formats, with their own recipe formats. See
[Deidentification](https://python-fileformats.github.io/fileformats-medimage/deidentification.html)
in the docs.

## Contributing

Pull requests adding formats, and implementations of the extras for formats that don't have
them yet, are welcome. See the [FileFormats developer guide](https://python-fileformats.github.io/fileformats/developer/extensions.html)
for how formats and extras are defined.

## License

This work is licensed under a
[Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/)

[![Creative Commons Attribution 4.0 International License](https://i.creativecommons.org/l/by/4.0/88x31.png)](http://creativecommons.org/licenses/by/4.0/)

## Acknowledgements

The authors acknowledge the facilities and scientific and technical assistance of the
National Imaging Facility, a National Collaborative Research Infrastructure Strategy (NCRIS)
capability.
