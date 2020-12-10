import os
import pathlib
import tempfile
import zipfile
from unittest.mock import MagicMock

import numpy as np
import pytest
from pydicom.data import get_testdata_files

from utils.dicom.dicom_archive import DicomArchive


def test_dicom_archive_class_validate():

    test_dicom_path = get_testdata_files("MR_small.dcm")[0]
    with tempfile.TemporaryDirectory() as temp_dir:
        # Test valid DICOM
        dicom_archive = DicomArchive(
            zip_path=test_dicom_path, extract_dir=temp_dir, validate=True
        )
        assert dicom_archive.dataset

        # Test file doesn't exist
        with pytest.raises(FileNotFoundError) as err:
            assert DicomArchive(
                zip_path=os.path.join(temp_dir, "DoesntExist"),
                extract_dir=temp_dir,
                validate=True,
            )

        # Test empty archive
        with pytest.raises(RuntimeError) as err:
            zip_path = os.path.join(temp_dir, "empty_zip.zip")

            with zipfile.ZipFile(zip_path, "w") as zip_obj:
                pass
            assert DicomArchive(zip_path, extract_dir=temp_dir, validate=True)

        # Test non-dicom
        not_dicom_path = pathlib.Path(temp_dir) / "empty_file.txt"
        not_dicom_path.touch()
        not_dicom_path.write_text("SPAM")
        with pytest.raises(RuntimeError) as err:
            assert DicomArchive(not_dicom_path, extract_dir=temp_dir, validate=True)
        assert "failed to parse DICOMs" in str(err.value)


im_arr = [
    [0.9989550114, 0.04570378363, 0, 0, 0, -1],
    [0.9989550114, 0.04570382088, 0, 0, 0, -1],
    [0.9989550114, 0.04570381716, 0, 0, 0, -1],
    [0.9989550114, 0.04570382088, 0, 0, 0, -1],
    [1, 0, 0, 0, 1, 0],
]
out = [
    [-0.0, 0.009, 0.0, 0.0, -0.2, -0.2],
    [-0.0, 0.009, 0.0, 0.0, -0.2, -0.2],
    [-0.0, 0.009, 0.0, 0.0, -0.2, -0.2],
    [-0.0, 0.009, 0.0, 0.0, -0.2, -0.2],
    [0.001, -0.037, 0.0, 0.0, 0.8, 0.8],
]


def test_contains_localizer_round():

    assert DicomArchive._round_iop(im_arr).tolist() == out


def test_dicom_tag_value_dict(mocker):
    zip_mock = mocker.patch("utils.dicom.dicom_archive.zipfile")
    mocker.patch("utils.dicom.dicom_archive.DicomArchive._validate")
    mocker.patch("utils.dicom.dicom_archive.DicomArchive.initialize_dataset")
    archive = DicomArchive("test", "test2")

    tag_vals = mocker.patch.object(archive, "dicom_tag_value_list")
    tag_vals.return_value = im_arr
    ims = []
    for im in im_arr:
        im_patch = MagicMock()
        im_patch.header_dict.get.return_value = im
        ims.append(im_patch)
    archive.dataset_list = ims

    rounded = archive.dicom_tag_value_dict("ImageOrientationPatient")
    assert list(rounded.keys()) == [
        tuple(o) for o in np.unique(np.array(out), axis=0).tolist()
    ]
