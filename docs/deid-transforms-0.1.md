# Deid transforms specification, version 0.1

A *transforms* file declares how the values of the `var:` and `func:` references
in a [deid](https://pydicom.github.io/deid/) recipe are computed. It is a YAML
side-car to the recipe (see `DeidRecipeX` in `fileformats.medimage`).

They are written in a small, closed expression language instead of Python. Recipes and their transforms
can be distributed to sites and run there, for example on edge devices, so they must
not be able to execute arbitrary code. A transforms file can only:

- read the DICOM dataset being deidentified,
- read environment variables,
- read the salt side-car, but only as the key of a salted hash, never as a value,
- combine and transform those values with the operations listed below.

It can't import modules, access the file system or network, or call arbitrary
functions.

Status: **0.1, initial draft.**, it
is designed to be extended (see [Versioning and extensibility](#versioning-and-extensibility)).

## Files

A recipe and its side-cars share a stem:

| File | Format | Required |
|---|---|---|
| `<stem>.deid` (or any other name, e.g. `deid.dicom`) | deid recipe, starting with `FORMAT <format>` | yes |
| `<stem>.transforms.yaml` | transforms, this spec | yes for `DeidRecipeX` |
| `<stem>.salt` | secret key for salted hashes; surrounding whitespace is stripped; should be readable only by the user running the deidentification | only if a salted hash is used |

For example: `dicom-series.deid`, `dicom-series.transforms.yaml`, `dicom-series.salt`.

## Document structure

```yaml
version: "0.1"            # required, quote it so YAML doesn't read it as a number
description: free text    # optional
variables:                # optional, the values of var:<name> references
  <name>: <expression>
functions:                # optional, the values of func:<name> references
  <name>: <expression>
```

- Names match `[A-Za-z_][A-Za-z0-9_]*`.
- Every `var:` and `func:` reference in the recipe must be defined here, or the
  recipe fails to load. `deid_func:` references are deid's built-ins (e.g.
  `deid_func:dicom_uuid`, `deid_func:jitter`) and aren't defined here.
- Unknown keys are errors, except keys starting with `x-`, which are ignored
  wherever they appear (see [Versioning and extensibility](#versioning-and-extensibility)).

### Variables and functions

A **variable** is evaluated once per DICOM file, before deid applies the recipe,
and its value is substituted wherever `var:<name>` appears. Use variables for
values derived from the dataset as a whole, e.g. `REPLACE PatientID var:anon_patient_id`.

A **function** is evaluated by deid each time a `func:<name>` reference is
applied to a field, e.g. `REPLACE endswith:ID func:hash_value`. It can also read
the field it is applied to (see the [`field`](#field-functions-only) source).
Evaluating to `null` (e.g. via `blank_if_empty`) blanks the field.

Transforms are only for values that have to be **computed**. Constants are written
in the recipe itself, e.g. `REPLACE PatientName ANONYMOUS`, `JITTER StudyDate 10`,
`BLANK PatientName` or `KEEP PatientID`, so a variable or function that is just a
constant (including `null`) is an error.

## Expressions

Each variable and function is defined by an expression: a mapping with exactly one
*source* key, which says where the value comes from, plus optionally:

- `default:` an argument used if the source's value is missing (`null`) or empty (`""`),
- `apply:` a list of *operations* applied to the value in order.

```yaml
anon_birth_date:
  tag: PatientBirthDate      # source
  default: ""                # if the tag is absent or empty
  apply:                     # then, in order
    - truncate: 4
    - suffix: "0101"
```

How an expression is evaluated:

1. The source produces a value. It may be `null`, e.g. a missing tag or unset
   environment variable.
2. If `default` is given and the value is `null` or `""`, the default expression's
   value is used instead.
3. Each operation in `apply` is applied in turn. Unless stated otherwise, an
   operation passes `null` through unchanged, so a missing value stays missing
   and isn't, for example, hashed.

An operation is written as its name if it takes no arguments (`- upper`), or as a
single-key mapping from its name to its arguments (`- truncate: 4`,
`- hash: {length: 16}`).

Wherever an argument is described as an *expression* below (including `default:`
and template values), it can be either a literal (a YAML scalar: string, number,
boolean or `null`) or a nested expression mapping.

### Sources

| Source | Argument | Value |
|---|---|---|
| `tag` | DICOM keyword (`PatientID`) or tag (`(0010,0020)`, `0010,0020`, `00100020`) | the element's value as a string, or `null` if absent. Multi-valued elements are joined with `\`. Person names are in DICOM form, e.g. `Doe^Jane`. Unknown keywords are an error when the transforms are loaded |
| `env` | environment variable name | its value, or `null` if unset |
| `template` | `{format: <string>, values: {<name>: <expression>}}` | `format` with each `{name}` placeholder replaced by the value of that expression (`null` → `""`). `{{` and `}}` are literal braces. Placeholders are plain names only (no attribute or index access), and every placeholder must be defined in `values` |
| `field` | `value` or `name` | **functions only**: the current value of the field the function is applied to (as a string, as for `tag`), or its keyword |

#### `field` (functions only)

deid calls a function as `func(item, value, field, dicom)`. Note that `value` is the
text from the recipe (e.g. `"func:hash_value"`), *not* the field's current value.
The `field` source gives the field's actual current value and its keyword. For
`ADD` actions, where the field doesn't exist yet, `field: name` is the tag being
added and `field: value` is `null`.

### Operations

| Operation | Arguments | Result |
|---|---|---|
| `truncate` | non-negative integer *n* | the first *n* characters |
| `slice` | `{start: int, stop: int}` (both optional, may be negative) | the characters `start` to `stop`, with Python slice semantics |
| `prefix` | expression | its value prepended (`null` → `""`) |
| `suffix` | expression | its value appended (`null` → `""`) |
| `upper`, `lower`, `strip` | — | upper-cased, lower-cased, surrounding whitespace removed |
| `replace` | `{old: string, new: string}` | every occurrence of `old` replaced by `new` (literal, not a regex) |
| `default` | expression | its value if the value so far is `null` or `""`, i.e. like the `default:` key, but at any point in the pipeline |
| `blank_if_empty` | — | `null` if the value is `""` (in a function, `null` blanks the field) |
| `to_int` | — | the value as an integer, e.g. for `JITTER ... var:date_jitter`. `""` → `null`; other non-integers are an error |
| `to_str` | — | the value as a string |
| `hash` | `{algorithm, length, salt, namespace}`, all optional | the hex digest of `salt + namespace + value` (see below) |

#### `hash`

| Argument | Default | Meaning |
|---|---|---|
| `algorithm` | `sha256` | one of `sha256`, `sha512`, `blake2b` |
| `length` | full digest | truncate the hex digest to this many characters. Mind the VR of the target field, e.g. `SH` fields such as `AccessionNumber` are limited to 16 characters, `LO` fields such as `PatientID` to 64 |
| `salt` | `true` | prefix the input with the key from the `.salt` side-car. If `true` and the recipe has no salt side-car, the transforms **fail to load** |
| `namespace` | none | an expression whose value is put between the salt and the value. Use it to hash the same identifier differently in different fields so they can't be linked, e.g. `namespace: AccessionNumber`, or in a function `namespace: {field: name}` |

The input is the UTF-8 encoding of `namespace + value`, prefixed by the raw salt
bytes. Salting is on by default because an unsalted hash of an identifier can be
reversed by hashing candidate identifiers. Turning it off (`salt: false`) should be
a deliberate choice.

## Errors

Transforms are validated and compiled when the recipe is loaded, i.e. before any
file is deidentified. Errors give their location, e.g.
`variables.v.template.values.a.apply[0].truncate: expected a non-negative integer`.
Loading fails when:

- `version` is missing or not supported,
- a variable or function is a constant rather than an expression,
- there are unknown keys, sources or operations, or invalid arguments,
- a tag keyword is unknown,
- a template placeholder isn't defined,
- a salted hash is used without a salt side-car,
- the recipe references a `var:`/`func:` that isn't defined.

Errors raised while evaluating a **variable** for a particular file (e.g.
`to_int` of a non-integer) are logged as warnings, and that variable isn't defined
for that file. deid then skips the actions that reference it.

## Versioning and extensibility

- `version` is `"<major>.<minor>"`. A loader supports a specific set of versions
  and **rejects** any others. Transforms that use features a site doesn't support
  fail loudly instead of being partially applied.
- **Minor versions only add things**: new sources, operations, arguments with
  defaults that keep the old behaviour, or new top-level sections. A loader that
  supports 0.*n* also loads 0.*m* for all *m* ≤ *n*.
- **Major versions** may change or remove things.
- Unknown keys are always errors, so a typo can't silently change how data is
  deidentified. Keys starting with `x-` are reserved for tools and annotations
  (e.g. `x-owner`, `x-reviewed-by`) and are ignored by loaders.
- In the reference implementation (`fileformats.extras.medimage.deid_transforms`),
  sources and operations live in the `SOURCES` and `OPERATIONS` registries.
  Adding one is a matter of registering a factory that validates its arguments when
  the transforms are loaded and returns the callable used at evaluation time.

### Candidates for future versions

These are not part of 0.1, and are listed to guide extensions:

- **Date/time operations**: parse a DA/DT/TM value and reformat it, shift it by an
  expression's number of days, or keep only some of it (e.g. year). Today a
  birth date reduced to a year is done with `truncate` + `suffix`.
- **Regular-expression `replace`/`match`**, with a bounded engine to avoid
  catastrophic backtracking on hostile input.
- **Conditionals**, e.g. `if: {tag: X, equals: Y}, then: ..., else: ...`, and
  first-non-empty selection.
- **Lookup tables** from a side-car (e.g. CSV mapping site IDs to pseudonyms), for
  re-identification workflows such as `ais_deid.dicom.header_reid`.
- **Deterministic UID generation** from a hash, e.g. `to_uid: {root: 1.2.826...}`,
  as a stable alternative to deid's random `deid_func:dicom_uuid`.
- **Sequence/nested element access** in `tag`, e.g.
  `(0008,1110)[0].(0008,1155)`.
- A **JSON Schema** for the document, for editor validation.

## Examples

### xnat-ingest default (`dicom-series.transforms.yaml`)

```yaml
version: "0.1"
variables:
  # Year of birth only, e.g. 19830514 -> 19830101
  anon_birth_date:
    tag: PatientBirthDate
    default: ""
    apply: [{truncate: 4}, {suffix: "0101"}]
  anon_patient_name: {tag: PatientID, default: ""}
  anon_patient_id:
    template:
      format: "{patient_id}-{acquisition_time}"
      values:
        patient_id: {tag: PatientID}
        acquisition_time: {tag: AcquisitionTime}
  date_jitter: {env: DEID_DATE_JITTER, default: 10, apply: [to_int]}
  patient_comments:
    template:
      format: "Project={project};Subject={subject};Session={subject}-{acquisition_time}"
      values:
        project: {tag: ReferringPhysicianName}
        subject: {tag: PatientID}
        acquisition_time: {tag: AcquisitionTime}
```

### `ais_deid` (`ais_deid.dicom.transforms` and the engine's variable builders)

```yaml
version: "0.1"
variables:
  anon_patient_id:
    tag: PatientID
    apply: [blank_if_empty, {hash: {length: 24}}]
  anon_accession_number:            # SH, max 16 characters
    tag: AccessionNumber
    apply: [blank_if_empty, {hash: {length: 16, namespace: AccessionNumber}}]
  anon_study_id:
    tag: StudyID
    apply: [blank_if_empty, {hash: {length: 16, namespace: StudyID}}]
  date_jitter: {env: DEID_DATE_JITTER, default: 0, apply: [to_int]}
functions:
  hash_patient_id:
    field: value
    apply: [blank_if_empty, {hash: {length: 24}}]
  hash_accession_number:
    field: value
    apply: [blank_if_empty, {hash: {length: 16, namespace: {field: name}}}]
```

Its constant `anon_patient_name` builder (`"ANONYMOUS"`) and its `passthrough` and
`blank_if_present` functions aren't transforms. In the recipe they are
`REPLACE PatientName ANONYMOUS`, `KEEP <field>` and `BLANK <field>`.

`ais_deid` currently has salting disabled. Its exact current behaviour is
`hash: {salt: false, ...}`, but with a `.salt` side-car the default (salted) is
what its comments describe as the intended configuration.

### deid examples

deid's bundled recipes reference `var:entity_id`, `var:item_id`,
`var:entity_timestamp` and `var:item_timestamp`. For example:

```yaml
version: "0.1"
variables:
  entity_id: {tag: PatientID, apply: [{hash: {length: 16, namespace: entity}}]}
  item_id: {tag: SOPInstanceUID, apply: [{hash: {length: 16, namespace: item}}]}
  entity_timestamp: {tag: StudyDate}
  item_timestamp:
    template:
      format: "{date}{time}"
      values: {date: {tag: AcquisitionDate}, time: {tag: AcquisitionTime}}
```

deid's `func:` examples that generate random values (e.g. a UUID suffix) are
already available without code as `deid_func:suffix_uuid`, `deid_func:dicom_uuid`
and `deid_func:pydicom_uuid`, and date shifting as `JITTER` / `deid_func:jitter`.
