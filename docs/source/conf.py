#
# Configuration file for the Sphinx documentation builder, matching that of the main
# fileformats package (https://python-fileformats.github.io/fileformats/)
#
import datetime
import tomllib
import typing as ty
from pathlib import Path

from fileformats.medimage import __version__

REPO_ROOT = Path(__file__).parent.parent.parent

with open(REPO_ROOT / "pyproject.toml", "rb") as f:
    authors = [a["name"] for a in tomllib.load(f)["project"]["authors"]]

# -- General configuration ------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.doctest",
    "sphinx.ext.intersphinx",
    "sphinx.ext.todo",
    "sphinx.ext.coverage",
    "sphinx.ext.viewcode",
    "sphinx.ext.napoleon",
    "sphinx.ext.autosectionlabel",
]

# Make section labels unique across pages, e.g. :ref:`extras:Converters`
autosectionlabel_prefix_document = True

templates_path = ["_templates"]
source_suffix = ".rst"
master_doc = "index"

project = "FileFormats-Medimage"
author = ", ".join(authors)
copyright = "{}, {}".format(datetime.datetime.now().year, author)

version = ".".join(__version__.split(".")[:2])
release = __version__

exclude_patterns: ty.List[str] = []

pygments_style = "lovelace"
pygments_dark_style = "fruity"

todo_include_todos = True

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "fileformats": ("https://python-fileformats.github.io/fileformats/", None),
    "pydicom": ("https://pydicom.github.io/pydicom/stable/", None),
}

# -- Options for HTML output ----------------------------------------------

html_theme = "furo"
html_theme_options = {
    "light_css_variables": {
        "color-brand-primary": "#0e691b",
        "color-brand-content": "#0e691b",
    },
    "dark_css_variables": {
        "color-brand-primary": "#5db754",
        "color-brand-content": "#5db754",
    },
}
html_title = "FileFormats-Medimage v{}".format(__version__)
html_logo = "_static/images/logo_small.png"
html_favicon = "_static/images/favicon.png"
html_static_path = ["_static"]

htmlhelp_basename = "FileFormats-Medimage"

# -- Options for autodoc --------------------------------------------------

autodoc_default_options = {
    "undoc-members": True,
    "show-inheritance": True,
}
napoleon_numpy_docstring = True
napoleon_google_docstring = False
