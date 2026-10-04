import re
import typing as ty
from pathlib import Path

from fileformats.core import validated_property
from fileformats.core.exceptions import FormatMismatchError
from fileformats.core.mixin import WithAdjacentFiles
from fileformats.generic import BinaryFile, UnicodeFile

FORMAT_LINE_RE = re.compile(r"FORMAT\s+(\S+)")


class DeidRecipe(UnicodeFile):
    """A deidentification recipe for the `deid <https://pydicom.github.io/deid/>`__
    package. Recipes don't have a standard extension (they are typically named
    ``deid.<format>``), so they are identified by the ``FORMAT <format>`` line they
    start with instead"""

    # Loaded into a subclass of `deid.config.DeidRecipe` that also holds the transforms
    # for any "var:"/"func:" references in the recipe (see DeidRecipeX). Given as a
    # dotted path so the class is only imported if the extras are installed
    loaded_type = "fileformats.extras.medimage.deid_recipe.DeidRecipeWithTransforms"

    @validated_property
    def recipe_format(self) -> str:
        """The format the recipe applies to, as given by its ``FORMAT`` line. Only
        the lines up to the first one that isn't blank or a comment are read, so this
        is a cheap check (the recipe itself is only parsed when it is loaded)"""
        with self.open() as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                match = FORMAT_LINE_RE.fullmatch(line)
                if match:
                    return match.group(1)
                break
        raise FormatMismatchError(
            f"{self.fspath} does not start with a 'FORMAT <format>' line"
        )


class DeidTransforms(UnicodeFile):
    """A YAML file declaring the values of the variables and functions referenced by
    ``var:`` and ``func:`` values in a `DeidRecipe`, using a small expression language
    rather than code, so that it can be safely distributed to and run at sites (see
    the "Deid transforms specification" in the docs).

    Expressions can read DICOM tags and environment variables, combine them with
    templates, and transform them, e.g. truncating them or hashing them with the key
    from the `DeidSalt` side-car of the recipe"""

    ext = ".transforms.yaml"
    # Given as a dotted path so the class is only imported if the extras are installed
    loaded_type = "fileformats.extras.medimage.deid_transforms.DeidTransformsSpec"


class DeidSalt(BinaryFile):
    """A secret key used to salt values that are hashed by the transforms of a
    `DeidRecipeX` (see `DeidTransforms`). Surrounding whitespace is stripped when it is
    loaded. It should only be readable by the user running the deidentification"""

    ext = ".salt"
    loaded_type = bytes


class DeidRecipeX(WithAdjacentFiles, DeidRecipe):
    """A `DeidRecipe` with a `DeidTransforms` side-car, which defines the values of the
    variables and functions referenced by ``var:`` and ``func:`` values in the recipe,
    and optionally a `DeidSalt` side-car with a key for the transforms to salt hashed
    values with. The side-cars are named after the recipe with its extension (if any)
    replaced by ``.transforms.yaml`` and ``.salt``, e.g. ``dicom-series.deid``,
    ``dicom-series.transforms.yaml`` and ``dicom-series.salt``"""

    @validated_property
    def fspath(self) -> Path:
        side_car_exts = (DeidTransforms.ext, DeidSalt.ext)
        recipes = [p for p in self.fspaths if not p.name.endswith(side_car_exts)]
        if len(recipes) != 1:
            raise FormatMismatchError(
                f"Expected exactly one recipe file (i.e. not a side-car) in "
                f"{type(self).__name__}, found {recipes}"
            )
        return recipes[0]

    @property
    def stem(self) -> str:
        # Recipes don't have a defined extension, so strip whatever extension it has
        return self.fspath.stem

    @validated_property
    def transforms_file(self) -> DeidTransforms:
        return DeidTransforms(self.select_by_ext(DeidTransforms))

    @validated_property
    def salt_file(self) -> DeidSalt | None:
        salt_fspaths = [p for p in self.fspaths if p.name.endswith(DeidSalt.ext)]
        return DeidSalt(salt_fspaths[0]) if salt_fspaths else None

    def get_adjacent_files(self) -> ty.Set[Path]:
        side_cars = (
            self.fspath.parent / (self.stem + ext)
            for ext in (DeidTransforms.ext, DeidSalt.ext)
        )
        return {p for p in side_cars if p.exists()}
