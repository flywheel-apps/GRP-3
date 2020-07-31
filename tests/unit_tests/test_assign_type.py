import pydicom

from pydicom.data import get_testdata_files

from run import assign_type


def test_assign_type_uid_is_str():
    test_dicom_path = get_testdata_files('MR_small.dcm')[0]
    dcm = pydicom.dcmread(test_dicom_path)
    setattr(dcm, 'StudyInstanceUID', '9876543210123456789012345678')
    return_val = assign_type(dcm.get('StudyInstanceUID'))
    assert type(return_val) == str
