API
===

Base classes
------------

The base classes of the formats in the package, which declare the hooks implemented
in fileformats-medimage-extras (see :ref:`extras:Extras`).

.. autoclass:: fileformats.medimage.MedicalImagingData
    :members: deidentify, contains_phi

.. autoclass:: fileformats.medimage.MedicalImage
    :members: read_array, data_array, dims, vox_sizes

.. autoclass:: fileformats.medimage.DicomCollection
    :no-index:
    :members: series_number, contents

.. autoclass:: fileformats.medimage.DwiEncoding
    :no-index:
    :members: read_encodings, encodings_array, directions, b_values


Deidentification (extras)
-------------------------

The types that deidentification recipes are loaded into, from
fileformats-medimage-extras (see :ref:`deidentification:Deidentification`).

.. autoclass:: fileformats.extras.medimage.deid_recipe.DeidRecipeWithTransforms
    :members: parser, variables, function_names

.. autoclass:: fileformats.extras.medimage.deid_transforms.DeidTransformsSpec

.. autofunction:: fileformats.extras.medimage.deid_transforms.load_transforms

.. autoclass:: fileformats.extras.medimage.deid_transforms.DeidTransformsError
