import logging
import os
import stat
import typing as ty

import deid.config
import yaml
from deid.dicom.parser import DicomParser
from fileformats.core import FileSet, extra_implementation

from fileformats.medimage import DeidRecipe, DeidRecipeX, DeidSalt, DeidTransforms

from .deid_transforms import (
    DeidFunction,
    DeidTransformsError,
    DeidTransformsSpec,
    VariableBuilder,
    load_transforms,
)

logger = logging.getLogger(__name__)


class DeidRecipeWithTransforms(deid.config.DeidRecipe):  # type: ignore[misc]
    """A `deid.config.DeidRecipe` together with the transforms that define the values
    of the "var:" and "func:" references in the recipe

    Parameters
    ----------
    deid : str, optional
        path to the deid recipe file
    transforms : DeidTransformsSpec or Mapping[str, VariableBuilder], optional
        the loaded transforms, or just the variable builders, keyed by the names of the
        variables they define
    **kwargs
        passed through to `deid.config.DeidRecipe`

    Raises
    ------
    ValueError
        if the recipe references variables or functions that aren't defined
    """

    transforms: dict[str, VariableBuilder]
    functions: dict[str, DeidFunction]

    def __init__(
        self,
        deid: str | None = None,
        transforms: DeidTransformsSpec | ty.Mapping[str, VariableBuilder] | None = None,
        **kwargs: ty.Any,
    ) -> None:
        super().__init__(deid, **kwargs)
        if isinstance(transforms, DeidTransformsSpec):
            self.transforms = dict(transforms.variables)
            self.functions = dict(transforms.functions)
        else:
            self.transforms = dict(transforms) if transforms else {}
            self.functions = {}
        for kind, referenced, defined in (
            ("var:", self.variables, self.transforms),
            ("func:", self.function_names, self.functions),
        ):
            missing = referenced - set(defined)
            if missing:
                raise ValueError(
                    f"Recipe references {kind} {sorted(missing)} but they aren't "
                    f"defined. Define them in a '{DeidTransforms.ext}' side-car to "
                    "the recipe"
                )

    def _references(self, prefix: str) -> set[str]:
        """Names referenced by values starting with `prefix` anywhere in the recipe"""
        names: set[str] = set()

        def walk(node: ty.Any) -> None:
            if isinstance(node, dict):
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
            elif isinstance(node, str):
                names.update(
                    t[len(prefix) :] for t in node.split() if t.startswith(prefix)
                )

        walk(self.deid)
        return names

    @property
    def variables(self) -> set[str]:
        """Names of the variables referenced by 'var:' values anywhere in the recipe"""
        return self._references("var:")

    @property
    def function_names(self) -> set[str]:
        """Names of the functions referenced by 'func:' values anywhere in the recipe
        (NB: not 'deid_func:', which are provided by deid)"""
        return self._references("func:")

    def parser(self, dicom_file: os.PathLike[str] | str) -> DicomParser:
        """Creates a parser to deidentify the given DICOM file with the recipe, with
        the variables defined by the transforms evaluated against the file

        Parameters
        ----------
        dicom_file : PathLike
            the DICOM file to deidentify

        Returns
        -------
        DicomParser
            the parser, ready to `parse()` and `save()`
        """
        parser = DicomParser(str(dicom_file), recipe=self)
        for func_name, func in self.functions.items():
            parser.define(func_name, func)
        for var_name, builder in self.transforms.items():
            try:
                value = builder(parser.dicom)
                parser.define(var_name, value)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Variable builder for '%s' raised %s: %s — skipping",
                    var_name,
                    type(exc).__name__,
                    exc,
                )
        return parser


@extra_implementation(FileSet.load)
def deid_salt_load(salt: DeidSalt, **kwargs: ty.Any) -> bytes:
    mode = salt.fspath.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        logger.warning(
            "Deidentification salt file '%s' is accessible by other users (mode %s), "
            "it should only be readable by the user running the deidentification",
            salt.fspath,
            oct(stat.S_IMODE(mode)),
        )
    return salt.fspath.read_bytes().strip()


@extra_implementation(FileSet.load)
def deid_transforms_load(
    transforms: DeidTransforms, salt: bytes | None = None, **kwargs: ty.Any
) -> DeidTransformsSpec:
    """Loads the transforms, compiling their expressions so that any errors in them
    are reported now. `salt` is the key from the salt side-car of the recipe, used by
    salted hashes"""
    with transforms.open() as f:
        try:
            spec = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise DeidTransformsError(
                f"Could not parse transforms file '{transforms.fspath}': {e}"
            ) from e
    try:
        return load_transforms(spec, salt=salt)
    except DeidTransformsError as e:
        raise DeidTransformsError(f"In '{transforms.fspath}': {e}") from e


@extra_implementation(FileSet.load)
def deid_recipe_load(recipe: DeidRecipe, **kwargs: ty.Any) -> DeidRecipeWithTransforms:
    return DeidRecipeWithTransforms(str(recipe.fspath), **kwargs)


@extra_implementation(FileSet.load)
def deid_recipe_x_load(
    recipe: DeidRecipeX, **kwargs: ty.Any
) -> DeidRecipeWithTransforms:
    salt = recipe.salt_file.load() if recipe.salt_file is not None else None
    return DeidRecipeWithTransforms(
        str(recipe.fspath), transforms=recipe.transforms_file.load(salt=salt), **kwargs
    )
