DICOM
=====

DICOM files, and collections of them. A collection can be referenced either as the
directory that contains it (``DicomDir``) or as the set of files themselves
(``DicomSeries``). ``DicomImage`` derives from ``fileformats.application.Dicom`` in the
main package, so its metadata is read with pydicom by fileformats-extras.


.. autoclass:: fileformats.medimage.DicomImage
.. autoclass:: fileformats.medimage.DicomCollection
.. autoclass:: fileformats.medimage.DicomDir
.. autoclass:: fileformats.medimage.DicomSeries
