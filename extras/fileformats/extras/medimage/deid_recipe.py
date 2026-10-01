import importlib.util
import logging
import os
import stat
import typing as ty

import deid.config
import pydicom
from deid.dicom.parser import DicomParser
from fileformats.core import FileSet, extra_implementation

from fileformats.medimage import DeidRecipe, DeidRecipeX, DeidSalt, DeidTransforms

logger = logging.getLogger(__name__)

# Each callable receives the pydicom Dataset being deidentified and returns the
# value to substitute for the "var:" reference of the same name in the recipe
VariableBuilder = ty.Callable[[pydicom.Dataset], str | int]


class DeidRecipeWithTransforms(deid.config.DeidRecipe):  # type: ignore[misc]
    """A `deid.config.DeidRecipe` together with the variable builders ("transforms")
    for the "var:" references in the recipe

    Parameters
    ----------
    deid : str, optional
        path to the deid recipe file
    transforms : Mapping[str, VariableBuilder], optional
        the variable builders, keyed by the names of the variables they define
    **kwargs
        passed through to `deid.config.DeidRecipe`

    Raises
    ------
    ValueError
        if the recipe references variables that there aren't transforms for
    """

    transforms: dict[str, VariableBuilder]

    def __init__(
        self,
        deid: str | None = None,
        transforms: ty.Mapping[str, VariableBuilder] | None = None,
        **kwargs: ty.Any,
    ) -> None:
        super().__init__(deid, **kwargs)
        self.transforms = dict(transforms) if transforms else {}
        missing = self.variables - set(self.transforms)
        if missing:
            raise ValueError(
                f"Recipe references var: variables {missing} but no matching "
                "transforms were provided. Define them in a "
                f"'{DeidTransforms.ext}' side-car to the recipe"
            )

    @property
    def variables(self) -> set[str]:
        """Names of the variables referenced by 'var:' values anywhere in the recipe"""
        recipe_vars: set[str] = set()

        def walk(node: ty.Any) -> None:
            if isinstance(node, dict):
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
            elif isinstance(node, str):
                recipe_vars.update(t[4:] for t in node.split() if t.startswith("var:"))

        walk(self.deid)
        return recipe_vars

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
) -> dict[str, VariableBuilder]:
    """Imports the transforms module, setting its ``SALT`` global to `salt` before it
    is executed"""
    spec = importlib.util.spec_from_file_location(
        f"fileformats.extras.medimage._deid_transforms.{transforms.stem}",
        transforms.fspath,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not import transforms from '{transforms.fspath}'")
    module = importlib.util.module_from_spec(spec)
    module.SALT = salt  # type: ignore[attr-defined]
    spec.loader.exec_module(module)
    loaded = getattr(module, "TRANSFORMS", None)
    if not isinstance(loaded, dict):
        raise ValueError(
            f"Transforms file '{transforms.fspath}' does not define a TRANSFORMS dict"
        )
    return loaded


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
