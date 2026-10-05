.. _home:

FileFormats-Medimage
====================
.. image:: https://github.com/python-fileformats/fileformats-medimage/actions/workflows/ci-cd.yml/badge.svg
   :target: https://github.com/python-fileformats/fileformats-medimage/actions/workflows/ci-cd.yml
.. image:: https://codecov.io/gh/python-fileformats/fileformats-medimage/branch/main/graph/badge.svg?token=UIS0OGPST7
   :target: https://codecov.io/gh/python-fileformats/fileformats-medimage
.. image:: https://img.shields.io/pypi/pyversions/fileformats-medimage.svg
   :target: https://pypi.python.org/pypi/fileformats-medimage/
   :alt: Supported Python versions
.. image:: https://img.shields.io/pypi/v/fileformats-medimage.svg
   :target: https://pypi.python.org/pypi/fileformats-medimage/
   :alt: Latest Version


*FileFormats-Medimage* is an extension of the `FileFormats`_ package for the file
formats used in medical imaging, particularly in medical imaging research. It
adds format classes for:

* **DICOM**: single files, and series of them, either in a directory or as a set of
  files
* **NIfTI**: NIfTI-1/2, gzipped, with `BIDS`_ JSON side-cars, and with FSL-style
  diffusion encodings
* **other image formats** from neuroimaging and image analysis tools: Analyze,
  FreeSurfer MGH, NRRD, MetaImage, VTK, GIPL and GIFTI surfaces
* **raw data**: MRI k-space and spectroscopy, and PET list-mode, sinograms, count
  rates and normalisation
* **deidentification recipes** for the `deid`_ package, with declarative side-cars for
  values that have to be computed (see :ref:`deidentification:Deidentification`)

As in the main package, the format classes have no dependencies. They can be used to
detect and validate files, and as type hints in data workflows. Classifiers describing
the image contents, e.g. the modality (``Mri``, ``Pet``), contrast (``T1w``, ``Flair``)
or anatomy (``Brain``), can be attached to formats with square brackets, e.g.
``NiftiGz[T1w]``.

Functionality that needs external libraries lives in the separate
`fileformats-medimage-extras <https://pypi.org/project/fileformats-medimage-extras/>`__
package. It includes reading image data and headers, generating sample data,
converters between formats (e.g. DICOM to NIfTI with `dcm2niix`_), and the
deidentification of DICOMs. See :ref:`extras:Extras` for the hooks it implements.


Installation
------------

*FileFormats-Medimage* can be installed for Python >= 3.11 using *pip*

.. code-block:: console

    $ python3 -m pip install fileformats-medimage

This installs the format classes, which have no dependencies other than *FileFormats*
itself. To read image data and metadata, convert between formats and deidentify
images, also install the extras package

.. code-block:: console

    $ python3 -m pip install fileformats-medimage-extras

The converters wrap command-line tools, which need to be installed separately.
`dcm2niix`_ converts DICOM to NIfTI, and `MRtrix3`_ converts images to Analyze and
MRtrix formats (see :ref:`extras:Converters`). On Ubuntu, for example, they can be
installed with

.. code-block:: console

    $ sudo apt install libopenjp2-7
    $ curl -fLO https://github.com/rordenlab/dcm2niix/releases/latest/download/dcm2niix_lnx.zip
    $ unzip dcm2niix_lnx.zip && sudo mv dcm2niix /usr/local/bin
    $ conda install -c mrtrix3 mrtrix3

(on macOS, use Homebrew in place of ``apt``).


License
-------

This work is licensed under a
`Creative Commons Attribution 4.0 International License <http://creativecommons.org/licenses/by/4.0/>`_

.. image:: https://i.creativecommons.org/l/by/4.0/88x31.png
  :target: http://creativecommons.org/licenses/by/4.0/
  :alt: Creative Commons Attribution 4.0 International License


Acknowledgements
----------------

The authors acknowledge the facilities and scientific and technical assistance of the
National Imaging Facility, a National Collaborative Research Infrastructure Strategy
(NCRIS) capability.


.. toctree::
    :maxdepth: 2
    :hidden:

    quick_start
    extras
    deidentification
    deid_transforms
    api

.. toctree::
   :maxdepth: 2
   :caption: Available Types
   :hidden:

   reference/dicom
   reference/nifti
   reference/diffusion
   reference/other_images
   reference/raw
   reference/deid
   reference/classifiers


.. _FileFormats: https://python-fileformats.github.io/fileformats/
.. _BIDS: https://bids.neuroimaging.io
.. _deid: https://pydicom.github.io/deid/
.. _dcm2niix: https://github.com/rordenlab/dcm2niix
.. _MRtrix3: https://www.mrtrix.org
