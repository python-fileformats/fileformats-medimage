Quick start
===========

The format classes in *FileFormats-Medimage* work like those in the main `FileFormats`_
package (see its `quick start <https://python-fileformats.github.io/fileformats/quick_start.html>`__),
so this page focuses on what is specific to medical imaging data.

Validating files
----------------

Instantiating a format class with the path(s) to the files checks that they are of
that format, raising a ``FormatMismatchError`` if they aren't

.. code-block:: python

    >>> from fileformats.medimage import NiftiGz, DicomSeries, DicomDir
    >>> nifti = NiftiGz("/path/to/image.nii.gz")

DICOM data is normally a *collection* of files, one per slice or volume. It can be
referenced either as the directory that contains them (``DicomDir``) or as the set of
files themselves (``DicomSeries``), and their contents are presented as ``DicomImage``
objects, sorted by ``SOPInstanceUID``

.. code-block:: python

    >>> from pathlib import Path
    >>> series = DicomSeries(Path("/path/to/dicoms").iterdir())
    >>> len(series)
    192
    >>> type(series.contents[0])
    <class 'fileformats.medimage.dicom.DicomImage'>
    >>> dicom_dir = DicomDir("/path/to/dicoms")

Multi-file formats are handled as single objects, e.g. a NIfTI file with its `BIDS`_
JSON side-car (``NiftiGzX``), or with FSL-style diffusion encoding files
(``NiftiGzBvec``), and can be copied, moved and hashed together

.. code-block:: python

    >>> from fileformats.medimage import NiftiGzX
    >>> nifti = NiftiGzX("/path/to/sub-01_T1w.nii.gz", "/path/to/sub-01_T1w.json")
    >>> nifti.json_file.fspath.name
    'sub-01_T1w.json'
    >>> copied = nifti.copy("/path/to/dest")

As with all formats, ``matches`` checks whether paths are of a format without raising
an exception, and ``find_matching`` returns all the formats that do

.. code-block:: python

    >>> NiftiGz.matches("/path/to/image.nii.gz")
    True

Format names
------------

Formats that aren't registered with IANA are identified by "MIME-like" strings in the
``medimage`` namespace, which can be used to refer to them from configuration files or
command-line arguments

.. code-block:: python

    >>> from fileformats.core import from_mime, to_mime
    >>> to_mime(NiftiGzX, official=False)
    'medimage/nifti-gz-x'
    >>> from_mime("medimage/dicom-series")
    <class 'fileformats.medimage.dicom.DicomSeries'>

Describing image contents
-------------------------

Classifiers describing the contents of an image can be attached to a format with
square brackets, to type data more specifically, e.g. a T1-weighted MRI in gzipped
NIfTI format. They are grouped into modalities (e.g. ``Mri``, ``Ct``, ``Pet``),
contrasts and other properties of the imaging procedure (e.g. ``T1w``, ``Flair``,
``Dwi``), anatomy (e.g. ``Brain``) and derivatives (e.g. ``Mask``). See
:ref:`reference/classifiers:Classifiers` for the full list

.. code-block:: python

    >>> from fileformats.medimage import NiftiGz, T1w
    >>> NiftiGz[T1w]
    <class 'fileformats.medimage.nifti.NiftiGz[T1Weighted]'>
    >>> to_mime(NiftiGz[T1w], official=False)
    'medimage/t1-weighted+nifti-gz'

Reading metadata and data
-------------------------

With `fileformats-medimage-extras <https://pypi.org/project/fileformats-medimage-extras/>`__
installed, the header metadata of images can be read with the ``metadata`` attribute
(using `pydicom`_ for DICOM and `nibabel`_ for NIfTI), along with their dimensions and
voxel sizes (see :ref:`extras:Extras` for all the methods available)

.. code-block:: python

    >>> series.metadata["SeriesDescription"]
    't1_mprage_sag_p2_iso_1'
    >>> nifti.dims()
    (192, 240, 256)
    >>> nifti.vox_sizes()
    (1.0, 1.0, 1.0)

Converting between formats
--------------------------

The extras also register converters, e.g. from DICOM to NIfTI with `dcm2niix`_, which
can be run with the ``convert`` method of the format to convert to

.. code-block:: python

    >>> nifti = NiftiGzX.convert(series)
    >>> nifti.json_file.load()["SeriesDescription"]
    't1_mprage_sag_p2_iso_1'

or added to a `Pydra`_ workflow as a task, with ``get_converter``.

Sample data
-----------

Sample data for testing can be generated for many of the formats (requires the
extras)

.. code-block:: python

    >>> sample = NiftiGz.sample()


.. _FileFormats: https://python-fileformats.github.io/fileformats/
.. _BIDS: https://bids.neuroimaging.io
.. _pydicom: https://pydicom.github.io/pydicom/
.. _nibabel: https://nipy.org/nibabel/
.. _dcm2niix: https://github.com/rordenlab/dcm2niix
.. _Pydra: https://pydra.readthedocs.io
