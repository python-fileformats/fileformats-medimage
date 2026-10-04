Deidentification
================

All formats that hold medical imaging data derive from ``MedicalImagingData``, which
declares a ``deidentify`` hook. An implementation strips identifying information from
the data and writes the result to a new location. The fileformats-medimage-extras
package implements it for DICOM using the `deid`_ package, and other packages can
implement it for other formats, with recipes in whichever format suits them.

.. code-block:: python

    class MedicalImagingData(FileSet):

        @extra
        def deidentify(
            self,
            out_dir: os.PathLike[str],
            recipe: Loaded[FileSet] | None = None,
            **kwargs: Any,
        ) -> Self:
            ...

``out_dir``
    the directory the deidentified data is written to
``recipe``
    the deidentification recipe, *already loaded* from the recipe format that the
    implementation for the data's format expects (see :ref:`deidentification:Recipes`)
``**kwargs``
    format-specific options, e.g. ``max_workers`` for DICOM collections.
    Implementations ignore options they don't use.

Implementations only need to strip the identifying data. They don't report what
they changed. Callers that need a record of the changes, e.g. for re-identification,
can compare ``metadata`` before and after deidentification, which works the same for
every format.


Deidentifying DICOM
-------------------

DICOM files are deidentified with `deid recipes <https://pydicom.github.io/deid/getting-started/dicom-config/>`__,
which list actions to apply to the header fields, e.g.

.. code-block:: text

    FORMAT dicom

    %header

    ADD PatientIdentityRemoved YES
    REPLACE PatientName ANONYMOUS
    REPLACE PatientID var:anon_patient_id
    BLANK AccessionNumber
    JITTER endswith:Date var:date_jitter
    REMOVE startswith:Referring

The recipe is loaded and passed to ``deidentify``, which can be called on a single
``DicomImage`` or on a whole ``DicomSeries``/``DicomDir``. Collections are deidentified
file by file, in parallel threads (``max_workers`` sets how many, defaulting to that of
``concurrent.futures.ThreadPoolExecutor``)

.. code-block:: python

    >>> from fileformats.medimage import DicomSeries, DeidRecipeX
    >>> recipe = DeidRecipeX("/path/to/specs/dicom-series.deid").load()
    >>> deidentified = series.deidentify("/path/to/output", recipe=recipe, max_workers=4)

The deidentified files keep their names. A ``DicomDir`` is written to a
sub-directory of ``out_dir`` with the same name as the original directory.

A recipe is required for DICOM. Header fields that the recipe doesn't mention are
left as they are, and so are **private tags and sequences** (the recipe is applied
with deid's ``remove_private`` and ``strip_sequences`` turned off), so the recipe needs
to account for every field that may hold identifying information, including private
tags.

Recipe formats
~~~~~~~~~~~~~~

Two formats are defined for deid recipes:

``DeidRecipe`` (``medimage/deid-recipe``)
    a deid recipe file on its own. Recipes don't have a standard extension (they are
    typically named ``deid.dicom`` or ``<name>.deid``), so they are identified by the
    ``FORMAT <format>`` line they start with. The recipe can't use ``var:`` or
    ``func:`` values, since nothing defines them.
``DeidRecipeX`` (``medimage/deid-recipe-x``)
    a deid recipe with side-cars that share its stem:

    * ``<stem>.transforms.yaml`` (``DeidTransforms``, required) declares the values of
      the ``var:`` and ``func:`` references in the recipe, e.g. a pseudonym hashed
      from the patient ID, or a date shift read from an environment variable. They are
      written in a small, declarative language rather than as code, so that recipes
      can be distributed to and run at sites safely (see :ref:`deid_transforms:Deid transforms specification, version 0.1`).
    * ``<stem>.salt`` (``DeidSalt``, optional) holds a secret key that hashes in the
      transforms are salted with. A warning is logged if other users can read it.

    For example, ``dicom-series.deid``, ``dicom-series.transforms.yaml`` and
    ``dicom-series.salt``.

Both are loaded as ``DeidRecipeWithTransforms``, a subclass of
``deid.config.DeidRecipe`` that holds the compiled transforms too. Loading fails if
the recipe references a ``var:`` or ``func:`` that isn't defined, or if the transforms
are invalid.

The DICOM implementation accepts either. Its ``recipe`` argument is annotated with
``Loaded[DeidRecipeX] | Loaded[DeidRecipe] | None``, in order of preference, so a
recipe with side-cars is loaded as ``DeidRecipeX``, and one without them as
``DeidRecipe`` (see :ref:`deidentification:Finding the recipe format for a datatype`).

.. code-block:: python

    >>> from fileformats.medimage import DeidRecipe, DeidRecipeX
    >>> DeidRecipeX.matches("/path/to/specs/dicom-series.deid")  # has side-cars
    True
    >>> DeidRecipe("/path/to/specs/deid.dicom").load()  # no side-cars needed


Recipes
-------

The recipe that ``deidentify`` takes depends on the format being deidentified. DICOM
uses deid recipes, but a recipe for raw scanner data, or for a vendor's proprietary
format, could be completely different. So the hook doesn't fix the recipe type.
Instead, each implementation declares which format(s) its recipe is loaded from, by
annotating the ``recipe`` argument with ``Loaded[<recipe format>]``.

``Loaded`` and ``loaded_type``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Every format has a ``loaded_type`` class attribute, the type of the object its
``load()`` method returns. ``Loaded[<format>]`` is an annotation meaning "data loaded
from ``<format>``". At runtime it evaluates to
``Annotated[<format>.loaded_type, LoadedMarker(<format>)]``, so

* type checkers and most tools see the loaded type itself (static checkers treat it
  as ``Any``),
* code that inspects the signature can recover the *format* the data should be
  loaded from, from the ``LoadedMarker``,
* ``FileSet.load`` checks that implementations return an instance of the
  ``loaded_type``, and implementations can check the data they are passed with
  ``check_loaded(<format>, data)``.

The base ``deidentify`` hook annotates ``recipe`` with ``Loaded[FileSet]``, which
accepts ``Loaded[<any format>]`` in implementations. ``LoadedMarker`` is covariant,
so data loaded from a subclass of the annotated format is accepted too.

``loaded_type`` can be a class, or a dotted-path string that is only imported when
it is needed. Use a string when the class lives in an extras package, so that the
format classes don't depend on it, e.g.

.. code-block:: python

    class DeidRecipe(UnicodeFile):
        loaded_type = "fileformats.extras.medimage.deid_recipe.DeidRecipeWithTransforms"

See `Loaded data <https://python-fileformats.github.io/fileformats/read_write.html#loaded-data>`__
in the *FileFormats* docs for more details.

Finding the recipe format for a datatype
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Callers that deidentify data of many formats, e.g. an ingestion pipeline with a
directory of recipes, don't need to know which recipe format each one uses. They
can read it from the ``recipe`` annotation of the implementation for the datatype

.. code-block:: python

    import typing as ty
    from fileformats.core import LoadedMarker, find_extra_implementation
    from fileformats.medimage import MedicalImagingData


    def load_recipe(datatype: type[MedicalImagingData], recipe_path: Path) -> ty.Any:
        impl = find_extra_implementation(MedicalImagingData.deidentify, datatype)
        hint = ty.get_type_hints(impl, include_extras=True)["recipe"]
        markers = LoadedMarker.all_from_hint(hint)  # in order of preference
        if markers is None:
            raise ValueError(f"The deidentify implementation for {datatype} doesn't take a recipe")
        # Load the recipe from the first of the formats it matches
        recipe_format = next(m.format for m in markers if m.format.matches(recipe_path))
        return recipe_format(recipe_path).load()


    recipe = load_recipe(type(series), Path("/path/to/specs/dicom-series.deid"))
    deidentified = series.deidentify("/path/to/output", recipe=recipe)

``LoadedMarker.all_from_hint`` returns the formats of a ``Loaded[X] | Loaded[Y] | None``
annotation in order, or ``None`` if the implementation doesn't take a recipe (i.e. its
``recipe`` argument is annotated with ``None``). The hints must be retrieved with
``include_extras=True``, otherwise the ``LoadedMarker`` metadata is stripped.
`xnat-ingest <https://github.com/Australian-Imaging-Service/xnat-ingest>`__ uses this to
pick the recipe for each format from a directory of recipes named after their formats
(e.g. ``medimage/dicom-series``).


Custom recipes
--------------

There are two ways to use your own recipe format: use it with the DICOM
implementation, or use it to deidentify a format of your own.

Extending the DICOM recipe
~~~~~~~~~~~~~~~~~~~~~~~~~~

The DICOM implementation can be passed data loaded from a subclass of ``DeidRecipe``
or ``DeidRecipeX``, as long as it loads to a subclass of ``DeidRecipeWithTransforms``.
The implementation checks this with ``check_loaded(DeidRecipe, recipe)``, and calls
the ``parser`` method of the loaded recipe.

For example, a recipe that also records the site it was written for. The format
goes in your extension package, with its ``loaded_type`` given as a dotted path to the
class in your extras package

.. code-block:: python

    # fileformats/myvendor/deid.py
    from fileformats.medimage import DeidRecipeX


    class SiteDeidRecipe(DeidRecipeX):
        """A DeidRecipeX that is specific to the site it is in a directory of"""

        loaded_type = "fileformats.extras.myvendor.deid.SiteRecipe"

The loaded type and the ``load`` implementation go in your extras package. The
implementation constructs the loaded type directly. It doesn't call
``DeidRecipeX.load(recipe)``, which would dispatch back to itself.

.. code-block:: python

    # fileformats/extras/myvendor/deid.py
    import typing as ty
    from fileformats.core import FileSet, Loaded, extra_implementation
    from fileformats.extras.medimage.deid_recipe import DeidRecipeWithTransforms
    from fileformats.myvendor import SiteDeidRecipe


    class SiteRecipe(DeidRecipeWithTransforms):

        def __init__(self, deid: str, site: str, **kwargs: ty.Any) -> None:
            super().__init__(deid, **kwargs)
            self.site = site


    @extra_implementation(FileSet.load)
    def load_site_recipe(recipe: SiteDeidRecipe, **kwargs: ty.Any) -> Loaded[SiteDeidRecipe]:
        salt = recipe.salt_file.load() if recipe.salt_file is not None else None
        return SiteRecipe(
            str(recipe.fspath),
            site=recipe.fspath.parent.name,
            transforms=recipe.transforms_file.load(salt=salt),
        )

The return annotation of a ``load`` implementation has to be ``Loaded[<format>]`` or
the ``loaded_type`` itself, and ``load`` raises a ``TypeError`` if it returns anything
else. The recipe can then be loaded and passed to the DICOM implementation

.. code-block:: python

    >>> recipe = SiteDeidRecipe("/path/to/site-a/dicom-series.deid").load()
    >>> recipe.site
    'site-a'
    >>> deidentified = series.deidentify("/path/to/output", recipe=recipe)

Callers that find the recipe format from the annotation (see
:ref:`deidentification:Finding the recipe format for a datatype`) will still load
``DeidRecipeX``/``DeidRecipe``. To have them use your format, implement ``deidentify``
for the datatype, with ``recipe: Loaded[SiteDeidRecipe]``, as below.

Recipes for other formats
~~~~~~~~~~~~~~~~~~~~~~~~~

To deidentify a format of your own, define a recipe format for it with a
``loaded_type``, implement ``load`` for the recipe format, and implement
``deidentify`` for the data format, annotating ``recipe`` with
``Loaded[<recipe format>]``. For example, for a raw data format whose header is
``key=value`` lines, with a YAML recipe listing the fields to blank

.. code-block:: python

    # fileformats/myvendor/__init__.py (no dependencies)
    from fileformats.generic import BinaryFile, UnicodeFile
    from fileformats.medimage import MedicalImagingData


    class RawDeidRecipe(UnicodeFile):
        """Lists the header fields of MyRawData files to blank"""

        ext = ".raw-deid.yaml"
        loaded_type = "fileformats.extras.myvendor.deid.RawDeidRules"


    class MyRawData(MedicalImagingData, BinaryFile):
        ext = ".myraw"

.. code-block:: python

    # fileformats/extras/myvendor/deid.py
    import os
    import typing as ty
    from dataclasses import dataclass, field
    from pathlib import Path

    import yaml
    from fileformats.core import FileSet, Loaded, check_loaded, extra_implementation
    from fileformats.medimage import MedicalImagingData
    from fileformats.myvendor import MyRawData, RawDeidRecipe


    @dataclass
    class RawDeidRules:
        blank: list[str] = field(default_factory=list)


    @extra_implementation(FileSet.load)
    def load_raw_deid_recipe(recipe: RawDeidRecipe, **kwargs: ty.Any) -> Loaded[RawDeidRecipe]:
        with recipe.open() as f:
            spec = yaml.safe_load(f) or {}
        return RawDeidRules(blank=list(spec.get("blank", [])))


    @extra_implementation(MedicalImagingData.deidentify)
    def my_raw_deidentify(
        data: MyRawData,
        out_dir: os.PathLike[str],
        recipe: Loaded[RawDeidRecipe] | None = None,
        **kwargs: ty.Any,
    ) -> MyRawData:
        if recipe is None:
            raise ValueError("A recipe is required to deidentify MyRawData")
        check_loaded(RawDeidRecipe, recipe)  # e.g. not a recipe for another format
        header = []
        for line in data.fspath.read_text().splitlines():
            key = line.split("=", 1)[0]
            header.append(f"{key}=" if key in recipe.blank else line)
        out = Path(out_dir) / data.fspath.name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(header))
        return MyRawData(out)

Notes on the implementation's signature:

* the first argument is the format it is implemented for, and the return type has
  to match it,
* ``recipe`` can be annotated with a union of formats in order of preference, e.g.
  ``Loaded[RawDeidRecipeV2] | Loaded[RawDeidRecipe] | None``, and with ``None``
  alone (``recipe: None = None``) if the implementation doesn't take a recipe,
* other options are keyword arguments with defaults, and ``**kwargs`` takes the
  options meant for other implementations.

Callers can then use your recipe without knowing about it, e.g. with the
``load_recipe`` function above

.. code-block:: python

    >>> recipe = load_recipe(MyRawData, Path("/path/to/rules.raw-deid.yaml"))
    >>> recipe
    RawDeidRules(blank=['PatientName'])
    >>> MyRawData("/path/to/scan.myraw").deidentify("/path/to/output", recipe=recipe)


.. _deid: https://pydicom.github.io/deid/
