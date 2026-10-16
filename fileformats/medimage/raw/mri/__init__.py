from fileformats.generic import BinaryFile


class Kspace(BinaryFile):

    binary = True
    # iana_mime = None
    pass


class Rda(BinaryFile):
    """MRS format"""

    ext = ".rda"
    binary = True


class Ismrmrd(Kspace):
    ext = ".ismrmd"