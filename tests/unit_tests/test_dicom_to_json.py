import os
import tempfile

import pydicom
import copy

from pydicom.data import get_testdata_files

from run import dicom_to_json, validate_timezone, get_seq_data


def test_dicom_to_json_no_patientname():
    test_dicom_path = get_testdata_files('MR_small.dcm')[0]
    dcm = pydicom.read_file(test_dicom_path)
    time_zone = validate_timezone(None)
    setattr(dcm, 'PatientName', None)
    with tempfile.TemporaryDirectory() as tempdir:
        temp_path = os.path.join(tempdir, os.path.basename(test_dicom_path))
        dcm.save_as(temp_path)

        metadata_path = dicom_to_json(zip_file_path=temp_path, outbase=tempdir, timezone=time_zone, json_template={})
        assert os.path.isfile(metadata_path)


def test_get_seq_data():
    test_dicom_path = get_testdata_files('liver.dcm')[0]
    dcm = pydicom.read_file(test_dicom_path)
    dcm.decode()
    res = get_seq_data(dcm.get('DimensionIndexSequence'), [])
    assert isinstance(res, list)
    assert len(res) == 2
    assert 'DimensionOrganizationUID' in res[0]
    assert 'DimensionOrganizationUID' in res[1]

    # testing ignore_key filter
    res = get_seq_data(dcm.get('DimensionIndexSequence'), ['DimensionOrganizationUID'])
    assert 'DimensionOrganizationUID' not in res[0]

    # testing recursivity
    dcm = pydicom.read_file(test_dicom_path)
    dcm.decode()
    sequence = pydicom.Sequence()
    dcm['DimensionIndexSequence'][0].add_new(dcm['DimensionIndexSequence'].tag, 'SQ', copy.deepcopy(dcm.get('DimensionIndexSequence')))
    res = get_seq_data(dcm.get('DimensionIndexSequence'), [])
    assert 'DimensionOrganizationUID' in res[0]['DimensionIndexSequence'][0]

