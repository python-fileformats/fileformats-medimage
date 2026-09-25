from pathlib import Path
import typing as ty
import nibabel
import typing  # noqa: F401
import numpy.typing  # noqa: F401
from fileformats.core import FileSet, SampleFileGenerator, extra_implementation
from fileformats.medimage import (
    MedicalImage,
    Nifti,
    NiftiGz,
    NiftiGzX,
    NiftiGzXBvec,
    NiftiXBvec,
    NiftiX,
    T1w,
    Fmri,
    Dmri,
    Brain,
)
from fileformats.medimage.base import DataArrayType
import medimages4tests.dummy.nifti
import medimages4tests.mri.neuro.t1w
import medimages4tests.mri.neuro.dwi
import medimages4tests.mri.neuro.bold


@extra_implementation(FileSet.read_metadata)
def nifti_read_metadata(nifti: Nifti, **kwargs: ty.Any) -> ty.Mapping[str, ty.Any]:
    metadata = dict(nibabel.load(nifti.fspath).header)  # type: ignore[call-overload]
    return metadata  # type: ignore[no-any-return]


@extra_implementation(MedicalImage.read_array)
def nifti_data_array(nifti: Nifti) -> DataArrayType:  # noqa
    return nibabel.load(nifti.fspath).get_data()  # type: ignore[attr-defined]


@extra_implementation(MedicalImage.vox_sizes)
def nifti_vox_sizes(nifti: Nifti) -> ty.Tuple[float, float, float]:
    ndims = len(nifti_dims(nifti))
    return tuple(float(d) for d in nifti.metadata["pixdim"][1 : ndims + 1])  # type: ignore[return-value]


@extra_implementation(MedicalImage.dims)
def nifti_dims(nifti: Nifti) -> ty.Tuple[int, int, int]:
    dim_array = [int(d) for d in nifti.metadata["dim"]]
    for i in range(1, len(dim_array)):
        if all(d == 1 for d in dim_array[i:]):
            break  # Stop when the remaining dimensions are singletons
    return tuple(dim_array[1:i])  # type: ignore[return-value]


@extra_implementation(FileSet.generate_sample_data)
def nifti_generate_sample_data(
    nifti: Nifti,
    generator: SampleFileGenerator,
) -> ty.List[Path]:
    return [
        medimages4tests.dummy.nifti.get_image(
            out_file=generator.generate_fspath(file_type=Nifti),
            seed=generator.seed,
        )
    ]


@extra_implementation(FileSet.generate_sample_data)
def nifti_gz_generate_sample_data(
    nifti: NiftiGz,
    generator: SampleFileGenerator,
) -> ty.List[Path]:
    return [
        medimages4tests.dummy.nifti.get_image(
            out_file=generator.generate_fspath(file_type=NiftiGz),
            compressed=True,
            seed=generator.seed,
        )
    ]


@extra_implementation(FileSet.generate_sample_data)
def nifti_gz_x_generate_sample_data(
    nifti: NiftiGzX,
    generator: SampleFileGenerator,
) -> ty.List[Path]:
    return _get_t1w_nifti_gz_x(generator)


@extra_implementation(FileSet.generate_sample_data)
def t1w_nifti_gz_x_generate_sample_data(
    nifti: NiftiGzX[T1w],  # type: ignore[type-arg]
    generator: SampleFileGenerator,
) -> ty.List[Path]:
    return _get_t1w_nifti_gz_x(generator)


@extra_implementation(FileSet.generate_sample_data)
def t1w_nifti_x_generate_sample_data(
    nifti: NiftiX[T1w],  # type: ignore[type-arg]
    generator: SampleFileGenerator,
) -> ty.List[Path]:
    nifti_gz_x = NiftiGzX(_get_t1w_nifti_gz_x(generator))
    return NiftiX.convert(nifti_gz_x)  # type: ignore[return-value]


@extra_implementation(FileSet.generate_sample_data)
def t1w_brain_nifti_gz_x_generate_sample_data(
    nifti: NiftiGzX[T1w, Brain],  # type: ignore[type-arg]
    generator: SampleFileGenerator,
) -> ty.List[Path]:
    return _get_t1w_nifti_gz_x(generator)


@extra_implementation(FileSet.generate_sample_data)
def t1w_brain_nifti_x_generate_sample_data(
    nifti: NiftiX[T1w, Brain],  # type: ignore[type-arg]
    generator: SampleFileGenerator,
) -> ty.List[Path]:
    nifti_gz_x = NiftiGzX(_get_t1w_nifti_gz_x(generator))
    return NiftiX.convert(nifti_gz_x)  # type: ignore[return-value]


@extra_implementation(FileSet.generate_sample_data)
def fmri_brain_nifti_gz_x_generate_sample_data(
    nifti: NiftiGzX[Fmri, Brain],  # type: ignore[type-arg]
    generator: SampleFileGenerator,
) -> ty.List[Path]:
    return _get_fmri_nifti_gz_x(generator)


@extra_implementation(FileSet.generate_sample_data)
def fmri_brain_nifti_x_generate_sample_data(
    nifti: NiftiX[Fmri, Brain],  # type: ignore[type-arg]
    generator: SampleFileGenerator,
) -> ty.List[Path]:
    nifti_gz_x = NiftiGzX(_get_fmri_nifti_gz_x(generator))
    return NiftiX.convert(nifti_gz_x)  # type: ignore[return-value]


@extra_implementation(FileSet.generate_sample_data)
def fmri_nifti_gz_x_generate_sample_data(
    nifti: NiftiGzX[Fmri],  # type: ignore[type-arg]
    generator: SampleFileGenerator,
) -> ty.List[Path]:
    return _get_fmri_nifti_gz_x(generator)


@extra_implementation(FileSet.generate_sample_data)
def fmri_nifti_x_generate_sample_data(
    nifti: NiftiX[Fmri],  # type: ignore[type-arg]
    generator: SampleFileGenerator,
) -> ty.List[Path]:
    nifti_gz_x = NiftiGzX(_get_fmri_nifti_gz_x(generator))
    return NiftiX.convert(nifti_gz_x)  # type: ignore[return-value]


@extra_implementation(FileSet.generate_sample_data)
def dmri_brain_nifti_gz_x_generate_sample_data(
    nifti: NiftiGzXBvec[Dmri, Brain],  # type: ignore[type-arg]
    generator: SampleFileGenerator,
) -> ty.List[Path]:
    return _get_dmri_nifti_gz_x(generator)


@extra_implementation(FileSet.generate_sample_data)
def dmri_brain_nifti_x_generate_sample_data(
    nifti: NiftiXBvec[Dmri, Brain],  # type: ignore[type-arg]
    generator: SampleFileGenerator,
) -> ty.List[Path]:
    nifti_gz_x = NiftiGzX(_get_dmri_nifti_gz_x(generator))
    return NiftiX.convert(nifti_gz_x)  # type: ignore[return-value]


@extra_implementation(FileSet.generate_sample_data)
def dmri_nifti_gz_x_generate_sample_data(
    nifti: NiftiGzXBvec[Dmri],  # type: ignore[type-arg]
    generator: SampleFileGenerator,
) -> ty.List[Path]:
    return _get_dmri_nifti_gz_x(generator)


@extra_implementation(FileSet.generate_sample_data)
def dmri_nifti_x_generate_sample_data(
    nifti: NiftiXBvec[Dmri],  # type: ignore[type-arg]
    generator: SampleFileGenerator,
) -> ty.List[Path]:
    nifti_gz_x = NiftiGzXBvec(_get_dmri_nifti_gz_x(generator))
    return NiftiX.convert(nifti_gz_x)  # type: ignore[return-value]


def _get_t1w_nifti_gz_x(generator: SampleFileGenerator) -> ty.List[Path]:
    sample = generator.seed if generator.seed else "ds002014-01"
    fspaths = medimages4tests.mri.neuro.t1w.get_image(sample=sample)
    return list(NiftiGzX(fspaths).copy(generator.dest_dir, mode=NiftiGzX.CopyMode.link_or_copy, new_stem=generator.fname_stem).fspaths)


def _get_fmri_nifti_gz_x(generator: SampleFileGenerator) -> ty.List[Path]:
    sample = generator.seed if generator.seed else "ds002014-01"
    fspaths = medimages4tests.mri.neuro.bold.get_image(sample=sample)
    return list(NiftiGzX(fspaths).copy(generator.dest_dir, mode=NiftiGzX.CopyMode.link_or_copy, new_stem=generator.fname_stem).fspaths)


def _get_dmri_nifti_gz_x(generator: SampleFileGenerator) -> ty.List[Path]:
    sample = generator.seed if generator.seed else "ds004024-CON031"
    fspaths = medimages4tests.mri.neuro.dwi.get_image(sample=sample)
    return list(NiftiGzX(fspaths).copy(generator.dest_dir, mode=NiftiGzX.CopyMode.link_or_copy, new_stem=generator.fname_stem).fspaths)
