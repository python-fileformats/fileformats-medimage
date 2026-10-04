"""Loads the declarative (YAML) transforms that define the values of the ``var:`` and
``func:`` references in a deid recipe (see ``docs/source/deid_transforms.rst``).

The transforms are a small, closed expression language rather than Python code, so
that recipes and their transforms can be distributed to and run at sites (e.g. on edge
devices) without them being able to execute arbitrary code. Each expression is
compiled into a callable when the transforms are loaded, so errors in them are reported
up-front rather than when the first DICOM file is deidentified.

The sources and operations an expression can be built from are held in the `SOURCES`
and `OPERATIONS` registries, which future versions of the spec extend.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import typing as ty
from dataclasses import dataclass, field

import pydicom
from pydicom.datadict import tag_for_keyword

logger = logging.getLogger(__name__)

#: The versions of the spec that can be loaded. Minor versions are backwards
#: compatible, i.e. a 0.2 loader will also load 0.1 transforms, but not vice versa
SUPPORTED_VERSIONS = ("0.1",)

#: Keys starting with this prefix are ignored wherever they appear in a mapping, so
#: that tools can attach their own metadata without breaking validation
EXTENSION_PREFIX = "x-"

HASH_ALGORITHMS = ("sha256", "sha512", "blake2b")


class DeidTransformsError(ValueError):
    """Raised when the transforms aren't valid, with the location of the problem"""


@dataclass
class Context:
    """What an expression is evaluated against

    Attributes
    ----------
    dataset : pydicom.Dataset
        the DICOM dataset being deidentified
    salt : bytes, optional
        the key loaded from the salt side-car of the recipe, if there is one
    field_name : str, optional
        the keyword of the field a function is being applied to (functions only)
    field_value : Any, optional
        the current value of the field a function is being applied to (functions only)
    """

    dataset: pydicom.Dataset
    salt: bytes | None = None
    field_name: str | None = None
    field_value: ty.Any = None


Expression = ty.Callable[[Context], ty.Any]
VariableBuilder = ty.Callable[[pydicom.Dataset], ty.Any]
DeidFunction = ty.Callable[..., ty.Any]


@dataclass
class DeidTransformsSpec:
    """The loaded transforms

    Attributes
    ----------
    variables : dict[str, VariableBuilder]
        builders for the values of ``var:`` references, keyed by variable name, which
        take the dataset being deidentified
    functions : dict[str, DeidFunction]
        callables for ``func:`` references, keyed by function name, with the signature
        deid calls them with, i.e. ``(item, value, field, dicom)``
    version : str
        the version of the spec the transforms were written against
    description : str
        the description given in the transforms, if any
    """

    variables: dict[str, VariableBuilder] = field(default_factory=dict)
    functions: dict[str, DeidFunction] = field(default_factory=dict)
    version: str = SUPPORTED_VERSIONS[-1]
    description: str = ""


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_transforms(spec: ty.Any, salt: bytes | None = None) -> DeidTransformsSpec:
    """Compiles parsed YAML transforms into callables

    Parameters
    ----------
    spec : Any
        the parsed YAML document
    salt : bytes, optional
        the key from the salt side-car of the recipe, used by salted hashes

    Returns
    -------
    DeidTransformsSpec
        the compiled variables and functions

    Raises
    ------
    DeidTransformsError
        if the transforms aren't valid, or they use a salted hash but there is no salt
    """
    if spec is None:
        spec = {}
    _check_mapping(spec, "<root>")
    _check_keys(
        spec, "<root>", allowed={"version", "description", "variables", "functions"}
    )
    version = spec.get("version")
    if version is None:
        raise DeidTransformsError(
            "<root>: 'version' is required, e.g. version: \"0.1\""
        )
    version = str(version)
    if version not in SUPPORTED_VERSIONS:
        raise DeidTransformsError(
            f"<root>: transforms are version {version!r}, but only versions "
            f"{', '.join(SUPPORTED_VERSIONS)} are supported by this version of "
            "fileformats-medimage-extras"
        )
    compiler = _Compiler(salt=salt)
    variables = {}
    for name, node in _named_entries(spec, "variables"):
        expression = compiler.compile(node, f"variables.{name}", in_function=False)
        variables[name] = _variable_builder(expression, salt)
    functions = {}
    for name, node in _named_entries(spec, "functions"):
        expression = compiler.compile(node, f"functions.{name}", in_function=True)
        functions[name] = _deid_function(expression, salt)
    return DeidTransformsSpec(
        variables=variables,
        functions=functions,
        version=version,
        description=str(spec.get("description", "")),
    )


def _named_entries(
    spec: dict[str, ty.Any], section: str
) -> ty.Iterator[tuple[str, ty.Any]]:
    entries = spec.get(section) or {}
    _check_mapping(entries, section)
    for name, node in entries.items():
        if not isinstance(name, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*", name
        ):
            raise DeidTransformsError(
                f"{section}: {name!r} isn't a valid name, names can contain letters, "
                "digits and underscores and can't start with a digit"
            )
        if not isinstance(node, dict):
            # Constants are written in the recipe itself, e.g. "REPLACE PatientName
            # ANONYMOUS", "BLANK PatientName" or "KEEP PatientName", so that there is
            # only one way to write them
            raise DeidTransformsError(
                f"{section}.{name}: expected an expression computing the value, e.g. "
                "from a tag. Constant values (including null) should be written in the "
                "recipe directly, e.g. 'REPLACE <field> <value>', 'BLANK <field>' or "
                "'KEEP <field>'"
            )
        yield name, node


def _variable_builder(expression: Expression, salt: bytes | None) -> VariableBuilder:
    def build(dataset: pydicom.Dataset) -> ty.Any:
        return expression(Context(dataset=dataset, salt=salt))

    return build


def _deid_function(expression: Expression, salt: bytes | None) -> DeidFunction:
    def apply(
        item: ty.Any = None,
        value: ty.Any = None,
        field: ty.Any = None,
        dicom: pydicom.Dataset | None = None,
        **kwargs: ty.Any,
    ) -> ty.Any:
        # NB: deid passes the value from the recipe (e.g. "func:name") as `value`, the
        # current value of the field is held by its element. For ADD actions `field`
        # is just the name of the tag being added
        element = getattr(field, "element", None)
        if element is not None:
            field_name = element.keyword or str(element.tag)
            field_value = element.value
        else:
            field_name = str(field) if field is not None else None
            field_value = None
            if dicom is not None and field_name and field_name in dicom:
                field_value = dicom[field_name].value
        return expression(
            Context(
                dataset=dicom if dicom is not None else pydicom.Dataset(),
                salt=salt,
                field_name=field_name,
                field_value=field_value,
            )
        )

    return apply


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------


class _Compiler:
    def __init__(self, salt: bytes | None) -> None:
        self.salt = salt

    def compile(self, node: ty.Any, path: str, in_function: bool) -> Expression:
        """Compiles an expression, which is a mapping with exactly one source key, plus
        optional 'default' and 'apply' keys. Where an expression is an argument (e.g.
        of 'default', 'suffix' or a template value) it can also be a literal (a
        scalar)"""
        if node is None or isinstance(node, (str, int, float, bool)):
            return _literal(node)
        _check_mapping(node, path)
        reserved = {"default", "apply"}
        source_keys = [
            k
            for k in node
            if k not in reserved and not str(k).startswith(EXTENSION_PREFIX)
        ]
        if len(source_keys) != 1:
            raise DeidTransformsError(
                f"{path}: an expression needs exactly one of "
                f"{', '.join(sorted(SOURCES))} (found {source_keys or 'none'})"
            )
        source_key = source_keys[0]
        try:
            source_factory = SOURCES[source_key]
        except KeyError:
            raise DeidTransformsError(
                f"{path}: unknown source {source_key!r}, expected one of "
                f"{', '.join(sorted(SOURCES))}"
            ) from None
        if source_key == "field" and not in_function:
            raise DeidTransformsError(
                f"{path}: 'field' can only be used in functions, which are applied to "
                "a field, not in variables"
            )
        expression = source_factory(
            self, node[source_key], f"{path}.{source_key}", in_function
        )
        if "default" in node:
            default = self.compile(node["default"], f"{path}.default", in_function)
            expression = _with_default(expression, default)
        steps = node.get("apply", [])
        if not isinstance(steps, list):
            raise DeidTransformsError(f"{path}.apply: expected a list of operations")
        for i, step in enumerate(steps):
            expression = self._compile_step(
                step, f"{path}.apply[{i}]", expression, in_function
            )
        return expression

    def _compile_step(
        self, step: ty.Any, path: str, expression: Expression, in_function: bool
    ) -> Expression:
        if isinstance(step, str):
            name, args = step, None
        elif isinstance(step, dict) and len(step) == 1:
            ((name, args),) = step.items()
        else:
            raise DeidTransformsError(
                f"{path}: an operation is either its name, e.g. 'upper', or a mapping "
                "from its name to its arguments, e.g. {truncate: 4}"
            )
        try:
            operation_factory = OPERATIONS[name]
        except KeyError:
            raise DeidTransformsError(
                f"{path}: unknown operation {name!r}, expected one of "
                f"{', '.join(sorted(OPERATIONS))}"
            ) from None
        operation = operation_factory(self, args, f"{path}.{name}", in_function)
        return lambda context: operation(expression(context), context)


# ---------------------------------------------------------------------------
# Sources, i.e. where the value of an expression comes from
# ---------------------------------------------------------------------------

SourceFactory = ty.Callable[[_Compiler, ty.Any, str, bool], Expression]
SOURCES: dict[str, SourceFactory] = {}


def _source(name: str) -> ty.Callable[[SourceFactory], SourceFactory]:
    def register(factory: SourceFactory) -> SourceFactory:
        SOURCES[name] = factory
        return factory

    return register


def _literal(value: ty.Any) -> Expression:
    return lambda _context: value


TAG_RE = re.compile(r"\(?([0-9A-Fa-f]{4}),?\s*([0-9A-Fa-f]{4})\)?")


def _parse_tag(arg: ty.Any, path: str) -> int:
    if not isinstance(arg, str):
        raise DeidTransformsError(f"{path}: expected a DICOM keyword or tag")
    match = TAG_RE.fullmatch(arg.strip())
    if match:
        return int(match.group(1) + match.group(2), 16)
    tag = tag_for_keyword(arg)
    if tag is None:
        raise DeidTransformsError(
            f"{path}: {arg!r} isn't a known DICOM keyword or a tag, e.g. (0010,0020)"
        )
    return int(tag)


def _element_str(value: ty.Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple, pydicom.multival.MultiValue)):
        return "\\".join(str(v) for v in value)  # DICOM's multi-value delimiter
    return str(value)


@_source("tag")
def _tag_source(
    compiler: _Compiler, arg: ty.Any, path: str, in_function: bool
) -> Expression:
    tag = _parse_tag(arg, path)

    def read(context: Context) -> str | None:
        element = context.dataset.get(tag)
        return None if element is None else _element_str(element.value)

    return read


@_source("env")
def _env_source(
    compiler: _Compiler, arg: ty.Any, path: str, in_function: bool
) -> Expression:
    if not isinstance(arg, str) or not arg:
        raise DeidTransformsError(
            f"{path}: expected the name of an environment variable"
        )
    return lambda _context: os.environ.get(arg)


@_source("field")
def _field_source(
    compiler: _Compiler, arg: ty.Any, path: str, in_function: bool
) -> Expression:
    if arg == "value":
        return lambda context: _element_str(context.field_value)
    if arg == "name":
        return lambda context: context.field_name
    raise DeidTransformsError(f"{path}: expected 'value' or 'name'")


PLACEHOLDER_RE = re.compile(r"\{\{|\}\}|\{([A-Za-z_][A-Za-z0-9_]*)\}|\{|\}")


@_source("template")
def _template_source(
    compiler: _Compiler, arg: ty.Any, path: str, in_function: bool
) -> Expression:
    _check_mapping(arg, path)
    _check_keys(arg, path, allowed={"format", "values"}, required={"format"})
    fmt = arg["format"]
    if not isinstance(fmt, str):
        raise DeidTransformsError(f"{path}.format: expected a string")
    values_node = arg.get("values") or {}
    _check_mapping(values_node, f"{path}.values")
    values = {
        name: compiler.compile(node, f"{path}.values.{name}", in_function)
        for name, node in values_node.items()
        if not str(name).startswith(EXTENSION_PREFIX)
    }
    # Parsed up-front rather than using str.format, which would allow attribute and
    # item access within placeholders
    parts: list[str | Expression] = []
    position = 0
    for match in PLACEHOLDER_RE.finditer(fmt):
        parts.append(fmt[position : match.start()])
        token = match.group(0)
        if token in ("{{", "}}"):
            parts.append(token[0])
        elif match.group(1) is None:
            raise DeidTransformsError(
                f"{path}.format: unmatched {token!r} at position {match.start()}, use "
                f"'{token * 2}' for a literal brace"
            )
        else:
            name = match.group(1)
            if name not in values:
                raise DeidTransformsError(
                    f"{path}.format: '{{{name}}}' isn't defined in 'values'"
                )
            parts.append(values[name])
        position = match.end()
    parts.append(fmt[position:])

    def render(context: Context) -> str:
        rendered = []
        for part in parts:
            if isinstance(part, str):
                rendered.append(part)
            else:
                value = part(context)
                rendered.append("" if value is None else str(value))
        return "".join(rendered)

    return render


# ---------------------------------------------------------------------------
# Operations, i.e. how the value of an expression is transformed. Each receives the
# value so far, which may be None if the source has no value (e.g. a missing tag)
# ---------------------------------------------------------------------------

Operation = ty.Callable[[ty.Any, Context], ty.Any]
OperationFactory = ty.Callable[[_Compiler, ty.Any, str, bool], Operation]
OPERATIONS: dict[str, OperationFactory] = {}


def _operation(name: str) -> ty.Callable[[OperationFactory], OperationFactory]:
    def register(factory: OperationFactory) -> OperationFactory:
        OPERATIONS[name] = factory
        return factory

    return register


def _no_args(name: str, arg: ty.Any, path: str) -> None:
    if arg is not None:
        raise DeidTransformsError(f"{path}: '{name}' doesn't take any arguments")


def _str_op(func: ty.Callable[[str], ty.Any]) -> Operation:
    return lambda value, _context: None if value is None else func(str(value))


@_operation("truncate")
def _truncate(
    compiler: _Compiler, arg: ty.Any, path: str, in_function: bool
) -> Operation:
    if not isinstance(arg, int) or isinstance(arg, bool) or arg < 0:
        raise DeidTransformsError(f"{path}: expected a non-negative integer")
    return _str_op(lambda s: s[:arg])


@_operation("slice")
def _slice(compiler: _Compiler, arg: ty.Any, path: str, in_function: bool) -> Operation:
    _check_mapping(arg, path)
    _check_keys(arg, path, allowed={"start", "stop"})
    start, stop = arg.get("start"), arg.get("stop")
    for name, bound in (("start", start), ("stop", stop)):
        if bound is not None and (
            not isinstance(bound, int) or isinstance(bound, bool)
        ):
            raise DeidTransformsError(f"{path}.{name}: expected an integer")
    return _str_op(lambda s: s[start:stop])


@_operation("prefix")
def _prefix(
    compiler: _Compiler, arg: ty.Any, path: str, in_function: bool
) -> Operation:
    addition = compiler.compile(arg, path, in_function)
    return lambda value, context: (
        None if value is None else _to_str(addition(context)) + str(value)
    )


@_operation("suffix")
def _suffix(
    compiler: _Compiler, arg: ty.Any, path: str, in_function: bool
) -> Operation:
    addition = compiler.compile(arg, path, in_function)
    return lambda value, context: (
        None if value is None else str(value) + _to_str(addition(context))
    )


@_operation("upper")
def _upper(compiler: _Compiler, arg: ty.Any, path: str, in_function: bool) -> Operation:
    _no_args("upper", arg, path)
    return _str_op(str.upper)


@_operation("lower")
def _lower(compiler: _Compiler, arg: ty.Any, path: str, in_function: bool) -> Operation:
    _no_args("lower", arg, path)
    return _str_op(str.lower)


@_operation("strip")
def _strip(compiler: _Compiler, arg: ty.Any, path: str, in_function: bool) -> Operation:
    _no_args("strip", arg, path)
    return _str_op(str.strip)


@_operation("replace")
def _replace(
    compiler: _Compiler, arg: ty.Any, path: str, in_function: bool
) -> Operation:
    _check_mapping(arg, path)
    _check_keys(arg, path, allowed={"old", "new"}, required={"old", "new"})
    old, new = arg["old"], arg["new"]
    if not isinstance(old, str) or not isinstance(new, str) or not old:
        raise DeidTransformsError(
            f"{path}: 'old' and 'new' must be strings, 'old' non-empty"
        )
    return _str_op(lambda s: s.replace(old, new))


@_operation("default")
def _default_op(
    compiler: _Compiler, arg: ty.Any, path: str, in_function: bool
) -> Operation:
    default = compiler.compile(arg, path, in_function)
    return lambda value, context: default(context) if value in (None, "") else value


@_operation("blank_if_empty")
def _blank_if_empty(
    compiler: _Compiler, arg: ty.Any, path: str, in_function: bool
) -> Operation:
    _no_args("blank_if_empty", arg, path)
    return lambda value, _context: None if value in (None, "") else value


@_operation("to_int")
def _to_int(
    compiler: _Compiler, arg: ty.Any, path: str, in_function: bool
) -> Operation:
    _no_args("to_int", arg, path)

    def convert(value: ty.Any, _context: Context) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(str(value).strip())
        except ValueError:
            raise ValueError(
                f"{value!r} can't be converted to an integer ({path})"
            ) from None

    return convert


@_operation("to_str")
def _to_str_op(
    compiler: _Compiler, arg: ty.Any, path: str, in_function: bool
) -> Operation:
    _no_args("to_str", arg, path)
    return lambda value, _context: None if value is None else str(value)


@_operation("hash")
def _hash(compiler: _Compiler, arg: ty.Any, path: str, in_function: bool) -> Operation:
    """Hashes the value with ``salt + namespace + value`` as the input, returning the
    hex digest (truncated to `length` if given). Salting is on by default, as an
    unsalted hash of an identifier can be reversed by hashing candidate identifiers"""
    arg = {} if arg is None else arg
    _check_mapping(arg, path)
    _check_keys(arg, path, allowed={"algorithm", "length", "salt", "namespace"})
    algorithm = arg.get("algorithm", "sha256")
    if algorithm not in HASH_ALGORITHMS:
        raise DeidTransformsError(
            f"{path}.algorithm: {algorithm!r} isn't supported, expected one of "
            f"{', '.join(HASH_ALGORITHMS)}"
        )
    length = arg.get("length")
    if length is not None and (
        not isinstance(length, int) or isinstance(length, bool) or length < 1
    ):
        raise DeidTransformsError(f"{path}.length: expected a positive integer")
    salted = arg.get("salt", True)
    if not isinstance(salted, bool):
        raise DeidTransformsError(f"{path}.salt: expected true or false")
    if salted and compiler.salt is None:
        raise DeidTransformsError(
            f"{path}: the hash is salted (the default), but the recipe doesn't have a "
            "salt side-car. Provide one, or set 'salt: false' if an unsalted hash is "
            "acceptable"
        )
    namespace = (
        compiler.compile(arg["namespace"], f"{path}.namespace", in_function)
        if "namespace" in arg
        else None
    )

    def digest(value: ty.Any, context: Context) -> str | None:
        if value is None:
            return None
        data = b""
        if salted:
            assert context.salt is not None
            data += context.salt
        if namespace is not None:
            data += _to_str(namespace(context)).encode("utf-8")
        data += str(value).encode("utf-8")
        hex_digest = hashlib.new(algorithm, data).hexdigest()
        return hex_digest[:length] if length else hex_digest

    return digest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _with_default(expression: Expression, default: Expression) -> Expression:
    def evaluate(context: Context) -> ty.Any:
        value = expression(context)
        return default(context) if value in (None, "") else value

    return evaluate


def _to_str(value: ty.Any) -> str:
    return "" if value is None else str(value)


def _check_mapping(node: ty.Any, path: str) -> None:
    if not isinstance(node, dict):
        raise DeidTransformsError(
            f"{path}: expected a mapping, got {type(node).__name__}"
        )


def _check_keys(
    node: dict[str, ty.Any],
    path: str,
    allowed: set[str],
    required: set[str] = frozenset(),  # type: ignore[assignment]
) -> None:
    unknown = {
        k for k in node if k not in allowed and not str(k).startswith(EXTENSION_PREFIX)
    }
    if unknown:
        raise DeidTransformsError(
            f"{path}: unknown key(s) {', '.join(sorted(map(str, unknown)))}, expected "
            f"{', '.join(sorted(allowed))}"
        )
    missing = required - set(node)
    if missing:
        raise DeidTransformsError(f"{path}: missing {', '.join(sorted(missing))}")
