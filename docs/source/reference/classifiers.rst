Classifiers
===========

Classifiers describe the contents of an image, and are attached to formats with square
brackets, e.g. ``NiftiGz[T1w]`` or ``DicomSeries[Mri, Brain]``. Formats can be given one
classifier from each of the modality, anatomy and derivative groups. Abbreviations
(e.g. ``T1w``, ``Mri``) are aliases of the classes listed here.


Imaging modalities
------------------

.. autoclass:: fileformats.medimage.ImagingModality
.. autoclass:: fileformats.medimage.CombinedModalities
.. autoclass:: fileformats.medimage.DualEnergyXrayAbsorptiometry
.. autoclass:: fileformats.medimage.Fluoroscopy
.. autoclass:: fileformats.medimage.MrFluoroscopy
.. autoclass:: fileformats.medimage.RadioFluoroscopy
.. autoclass:: fileformats.medimage.MagneticResonanceImaging
.. autoclass:: fileformats.medimage.Dmri
.. autoclass:: fileformats.medimage.DiffusionTensorImaging
.. autoclass:: fileformats.medimage.DynamicContrast
.. autoclass:: fileformats.medimage.EnhancedMagneticResonanceImaging
.. autoclass:: fileformats.medimage.Fmri
.. autoclass:: fileformats.medimage.MagneticResonanceAngiography
.. autoclass:: fileformats.medimage.MagneticResonanceSpectroscopy
.. autoclass:: fileformats.medimage.Nm
.. autoclass:: fileformats.medimage.Pet
.. autoclass:: fileformats.medimage.PanographicRadiograph
.. autoclass:: fileformats.medimage.ProjectionRadiography
.. autoclass:: fileformats.medimage.ComputedRadiography
.. autoclass:: fileformats.medimage.DigitalRadiography
.. autoclass:: fileformats.medimage.DualEnergySubtractionRadiograpgy
.. autoclass:: fileformats.medimage.Mammography
.. autoclass:: fileformats.medimage.Rg
.. autoclass:: fileformats.medimage.Stereoscopy
.. autoclass:: fileformats.medimage.StereotacticRadiography
.. autoclass:: fileformats.medimage.Spectroscopy
.. autoclass:: fileformats.medimage.Tomography
.. autoclass:: fileformats.medimage.ComputedTomography
.. autoclass:: fileformats.medimage.Ultrasound

Imaging procedure properties
----------------------------

.. autoclass:: fileformats.medimage.T1w
.. autoclass:: fileformats.medimage.T2w
.. autoclass:: fileformats.medimage.T2StarWeighted
.. autoclass:: fileformats.medimage.T1T2w
.. autoclass:: fileformats.medimage.DiffusionWeighted
.. autoclass:: fileformats.medimage.Flair
.. autoclass:: fileformats.medimage.IntermediateWeighted

Anatomy
-------

.. autoclass:: fileformats.medimage.Brain
.. autoclass:: fileformats.medimage.SpinalCord

Derivatives
-----------

.. autoclass:: fileformats.medimage.Derivative
.. autoclass:: fileformats.medimage.Mask
