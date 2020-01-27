import os

from pydicom.data import get_testdata_files

from run import split_embedded_localizer


def test_split_embedded_localizer_non_zip():
    test_dicom_path = get_testdata_files('MR_small.dcm')[0]
    split_embedded_localizer(test_dicom_path, os.getcwd())
