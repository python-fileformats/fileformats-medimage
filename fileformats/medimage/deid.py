import re

from fileformats.core import validated_property
from fileformats.core.exceptions import FormatMismatchError
from fileformats.generic import UnicodeFile

FORMAT_LINE_RE = re.compile(r"FORMAT\s+(\S+)")


class DeidRecipe(UnicodeFile):
    """A deidentification recipe for the `deid <https://pydicom.github.io/deid/>`__
    package. Recipes don't have a standard extension (they are typically named
    ``deid.<format>``), so they are identified by the ``FORMAT <format>`` line they
    start with instead"""

    loaded_type = "deid.config.DeidRecipe"

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
