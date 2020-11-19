import pydicom

from pydicom.data import get_testdata_files

import pytest
from run import assign_type as assign_type1
from utils.dicom.dicom_metadata import assign_type as assign_type2
from utils.dicom.dicom_metadata import format_string


def test_assign_type_uid_is_str():
    test_dicom_path = get_testdata_files("MR_small.dcm")[0]
    dcm = pydicom.dcmread(test_dicom_path)
    setattr(dcm, "StudyInstanceUID", "9876543210123456789012345678")
    return_val = assign_type1(dcm.get("StudyInstanceUID"))
    assert type(return_val) == str


@pytest.mark.parametrize("assign_type", [assign_type1, assign_type2])
def test_assign_type_personname(assign_type):
    test_dicom_path = get_testdata_files("MR_small.dcm")[0]
    dcm = pydicom.dcmread(test_dicom_path)

    dcm.PatientName = "Test^Name"
    ret = assign_type(dcm.get("PatientName"))
    assert type(ret) == str
    assert ret == format_string(dcm.get("PatientName"))
