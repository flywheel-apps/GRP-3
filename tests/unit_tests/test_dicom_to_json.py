import os
import tempfile

import pydicom

from pydicom.data import get_testdata_files

from run import dicom_to_json, validate_timezone


def test_dicom_to_json_no_patientname():
    test_dicom_path = get_testdata_files('MR_small.dcm')[0]
    dcm = pydicom.read_file(test_dicom_path)
    time_zone = validate_timezone(None)
    setattr(dcm, 'PatientName', None)
    with tempfile.TemporaryDirectory() as tempdir:
        temp_path = os.path.join(tempdir, os.path.basename(test_dicom_path))
        dcm.save_as(temp_path)

        metadata_path = dicom_to_json(temp_path, tempdir, time_zone, {})
        assert os.path.isfile(metadata_path)
