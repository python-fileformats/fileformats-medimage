Extras
======

The format classes in *FileFormats-Medimage* declare "extra" methods (hooks) for
functionality that needs external libraries. The hooks are implemented in the sister
package `fileformats-medimage-extras <https://pypi.org/project/fileformats-medimage-extras/>`__,
which is imported automatically the first time one of them is called. For how hooks
and their implementations work in general, see
`Extras <https://python-fileformats.github.io/fileformats/developer/extras.html>`__ in
the *FileFormats* docs.

.. code-block:: console

    $ python3 -m pip install fileformats-medimage-extras

Calling a hook that has no implementation for the format it is called on raises a
``NotImplementedError``. Other packages can implement the hooks for formats that aren't
covered here (see :ref:`extras:Implementing hooks for other formats`).


Hooks
-----

Image data and headers
~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
    :header-rows: 1
    :widths: 30 40 30

    * - Hook
      - Returns
      - Implemented for
    * - ``MedicalImage.read_array()`` (cached as the ``data_array`` property)
      - the voxel data as a numpy array
      - ``Nifti`` (nibabel), ``DicomCollection`` (pydicom, slices stacked in
        ``SOPInstanceUID`` order)
    * - ``MedicalImage.dims()``
      - the image dimensions
      - ``Nifti``, ``DicomCollection``
    * - ``MedicalImage.vox_sizes()``
      - the voxel sizes along each dimension
      - ``Nifti``, ``DicomCollection``
    * - ``DicomCollection.series_number()``
      - the ``SeriesNumber`` of the series
      - ``DicomCollection``
    * - ``FileSet.read_metadata()`` (via the ``metadata`` attribute)
      - the header fields
      - ``Nifti`` (nibabel header). DICOM metadata is read with pydicom by the
        implementation for ``fileformats.application.Dicom`` in
        `fileformats-extras <https://pypi.org/project/fileformats-extras/>`__,
        which ``DicomImage`` and ``DicomCollection`` derive from
    * - ``FileSet.load()``
      - the loaded data (see ``loaded_type``)
      - ``DicomImage`` (``pydicom.FileDataset``, from fileformats-extras), and the
        deidentification formats ``DeidRecipe``, ``DeidRecipeX``, ``DeidTransforms``
        and ``DeidSalt`` (see :ref:`deidentification:Deidentification`)

Diffusion encodings
~~~~~~~~~~~~~~~~~~~

.. list-table::
    :header-rows: 1
    :widths: 30 40 30

    * - Hook
      - Returns
      - Implemented for
    * - ``DwiEncoding.read_encodings()`` (cached as ``encodings_array``, and split
        into the ``directions`` and ``b_values`` properties)
      - the gradient directions and b-values as an N x 4 array
      - ``Bvec`` (with its ``Bval`` pair), and the NIfTI formats that include them,
        e.g. ``NiftiGzBvec``
    * - ``Bval.read_array()``
      - the b-values
      - ``Bval``

Deidentification
~~~~~~~~~~~~~~~~

.. list-table::
    :header-rows: 1
    :widths: 30 40 30

    * - Hook
      - Returns
      - Implemented for
    * - ``MedicalImagingData.deidentify(out_dir, recipe=None, **kwargs)``
      - a deidentified copy of the data, written to ``out_dir``
      - ``DicomImage`` and ``DicomCollection``, using `deid`_ recipes

See :ref:`deidentification:Deidentification` for how recipes are loaded and passed to it,
and how to use your own recipe formats.

Sample data
~~~~~~~~~~~

``FileSet.generate_sample_data``, which is used by ``FileSet.sample()``, is implemented
for

* ``Nifti1``, ``NiftiGz`` and ``NiftiGzX``
* ``NiftiGzX`` with classifiers describing the image contents, generated from realistic
  images in `medimages4tests`_: ``NiftiGzX[T1w]``, ``NiftiGzX[T1w, Brain]``,
  ``NiftiGzX[Fmri]`` and ``NiftiGzX[Fmri, Brain]``
* ``DicomDir`` and ``DicomSeries`` (a T1-weighted MRI series, with a random series
  number)
* ``Bval`` and ``Bvec``

.. code-block:: python

    >>> from fileformats.medimage import NiftiGzX, T1w, Brain
    >>> t1w = NiftiGzX[T1w, Brain].sample()


Converters
----------

The extras register converters (as `Pydra`_ tasks) that can be run with the
``convert`` method of the format to convert to, or added to Pydra workflows with
``get_converter``. Keyword arguments to ``convert``/``get_converter`` are passed on to
the converter.

.. list-table::
    :header-rows: 1
    :widths: 30 30 40

    * - From
      - To
      - Tool
    * - ``DicomCollection`` (``DicomDir`` or ``DicomSeries``)
      - ``Nifti``, ``NiftiGz``, ``NiftiX``, ``NiftiGzX``, ``NiftiBvec``,
        ``NiftiGzBvec``, ``NiftiXBvec``, ``NiftiGzXBvec``
      - `dcm2niix`_
    * - any ``MedicalImage``
      - ``Analyze``
      - `MRtrix3`_ ``mrconvert``
    * - any ``MedicalImage``
      - the MRtrix image formats (``.mif``, ``.mif.gz``, ``.mih``), from
        `fileformats-vendor-mrtrix3-extras <https://pypi.org/project/fileformats-vendor-mrtrix3-extras/>`__
      - `MRtrix3`_ ``mrconvert``

The DICOM to NIfTI converter takes the following optional arguments, to work around
conversion issues

``file_postfix``
    selects one of several output files of the conversion by the postfix dcm2niix gives
    it (see `dcm2niix's file naming <https://github.com/rordenlab/dcm2niix/blob/master/FILENAMING.md>`__),
    e.g. ``"e2"`` for the second echo
``side_car_jq``
    a `jq <https://jqlang.github.io/jq/>`__ expression to edit the JSON side-car
    with, e.g. to fix or add fields
``extract_volume``
    the (0-based) index of a volume to extract from a 4D image
``to_4d``
    wraps a 3D image in a 4D one (can't be combined with ``extract_volume``)

.. code-block:: python

    >>> from fileformats.medimage import DicomSeries, NiftiGzX
    >>> nifti = NiftiGzX.convert(series, file_postfix="e2", side_car_jq=".EchoNumber = 2")

dcm2niix and MRtrix3 need to be installed separately and be on the ``PATH`` (see
:ref:`index:Installation`).


Implementing hooks for other formats
------------------------------------

The hooks above can be implemented for other formats by any package, with the
``@extra_implementation`` decorator. The first argument of the implementation is the
format it is implemented for, and the rest of its signature has to match the hook's.
For example, to read the voxel data of MetaImage files

.. code-block:: python

    import SimpleITK as sitk
    from fileformats.core import extra_implementation
    from fileformats.medimage import MedicalImage, MetaImage
    from fileformats.medimage.base import DataArrayType


    @extra_implementation(MedicalImage.read_array)
    def metaimage_read_array(image: MetaImage) -> DataArrayType:
        return sitk.GetArrayFromImage(sitk.ReadImage(str(image.fspath)))

The implementations for the formats in this package belong in
fileformats-medimage-extras, so contributions of them are welcome. For formats in
other namespaces, implement them in the extras package of that namespace (see the
`extension template <https://github.com/python-fileformats/fileformats-extension-template>`__).


.. _deid: https://pydicom.github.io/deid/
.. _dcm2niix: https://github.com/rordenlab/dcm2niix
.. _MRtrix3: https://www.mrtrix.org
.. _Pydra: https://pydra.readthedocs.io
.. _medimages4tests: https://github.com/australian-imaging-service/medimages4tests
