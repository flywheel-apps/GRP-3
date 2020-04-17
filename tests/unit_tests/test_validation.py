import os
import logging
from tempfile import NamedTemporaryFile

import jsonschema

from utils.validation import get_validation_error_dict, validate_against_template, validate_against_rules, \
    check_0_byte_files, check_instance_number_uniqueness, check_missing_slices, check_pydicom_exception, \
    check_file_is_not_empty, dump_validation_error_file


def test_check_0_byte_file():
    dcm_dict_list = [{'size': 0, 'path': 'path0'}, {'size': 1, 'path': 'path1'}]

    error_list = check_0_byte_files(dcm_dict_list)

    assert len(error_list) == 1
    expected_error = {
        'error_message': 'Dicom file is empty: path0',
        'revalidate': False
    }
    assert error_list == [expected_error]

    error_list = check_0_byte_files(dcm_dict_list[1:])
    assert not error_list


def test_check_corrupted_dicom():
    dcm_dict_list = [{'path': 'path0', 'pydicom_exception': False, 'force': False}]
    error_list = check_pydicom_exception(dcm_dict_list)
    assert len(error_list) == 0

    dcm_dict_list = [{'path': 'path0', 'pydicom_exception': False, 'force': True}]
    error_list = check_pydicom_exception(dcm_dict_list)
    assert len(error_list) == 0

    dcm_dict_list = [{'path': 'path0', 'pydicom_exception': True, 'force': True}]
    error_list = check_pydicom_exception(dcm_dict_list)
    assert len(error_list) == 1
    expected_error = {
        'error_message': 'Pydicom raised an exception with force=True for file: path0',
        'revalidate': False
    }
    assert error_list == [expected_error]

    dcm_dict_list = [{'path': 'path0', 'pydicom_exception': True, 'force': False}]
    error_list = check_pydicom_exception(dcm_dict_list)
    assert len(error_list) == 1
    expected_error = {
        'error_message': 'Dicom signature not found in: path0. Try running gear with force=True',
        'revalidate': False
    }
    assert error_list == [expected_error]


def test_check_file_is_not_empty():
    with NamedTemporaryFile() as tempfile:
        with open(tempfile.name, 'w') as fp:
            pass
        error_list = check_file_is_not_empty(tempfile.name)
        assert len(error_list) == 1
        expected_error = {
            'error_message': f'File is empty: {tempfile.name}',
            'revalidate': False
        }
        assert error_list == [expected_error]


def test_dump_validation_error():
    validation_error = ['Test']
    with NamedTemporaryFile() as tmpfile:
        dump_validation_error_file(tmpfile.name, validation_error)
        assert os.path.getatime(tmpfile.name) > 0


def test_check_instance_number_uniqueness():
    dcm_dict_list = [{'path': 'path0', 'header': {'InstanceNumber': 1}},
                     {'path': 'path1', 'header': {'InstanceNumber': 1}}]

    error_list = check_instance_number_uniqueness(dcm_dict_list)

    expected_error = {
        "error_message": "InstanceNumber is duplicated for values:[1]",
        "revalidate": False
    }
    assert error_list == [expected_error]

    error_list = check_instance_number_uniqueness(dcm_dict_list[:1])
    assert not error_list


def test_check_missing_slices_log_warning_if_not_enough_slices(caplog):
    dcm_dict_list = [{'path': 'path0', 'header': {'SliceLocation': 1}},
                     {'path': 'path1', 'header': {'SliceLocation': 2}}]
    with caplog.at_level(logging.INFO):
        _ = check_missing_slices(dcm_dict_list)
        assert caplog.records[0].levelname == 'WARNING'
        assert 'Small number of images in sequence.' in caplog.records[0].message


def test_check_mising_slices_from_slice_location():
    dcm_dict_list = []
    for s in range(20):
        dcm_dict_list.append({'path': f'path{s}',
                              'header': {'SliceLocation': s,
                                         'SequenceName': 'S1',
                                         'ImageType': ['Whatever']}
                              })

    error_list = check_missing_slices(dcm_dict_list)
    assert not error_list

    # Popping one slice raises an error
    _ = dcm_dict_list.pop(10)
    error_list = check_missing_slices(dcm_dict_list)
    assert error_list


def test_check_mising_slices_from_ImagePositionPatient():
    dcm_dict_list = []
    for s in range(20):
        dcm_dict_list.append({'path': f'path{s}',
                              'header': {'SequenceName': 'S1',
                                         'ImageType': ['Whatever'],
                                         'ImageOrientationPatient': '[0, 1, 0, 1, 0, 1]',
                                         'ImagePositionPatient': f'[0, 0, {s}]'}
                              })

    error_list = check_missing_slices(dcm_dict_list)
    assert not error_list

    # Popping one slice raises an error
    _ = dcm_dict_list.pop(10)
    error_list = check_missing_slices(dcm_dict_list)
    assert error_list


def test_get_validation_error_dict_enum():
    test_dict = {
        'Modality': 'NM',
        'ImageType': 'SCREEN SAVE',
        'Units': 'MLML'
    }

    # Test enum
    template = {
        "properties": {
            "Modality": {
                "description": "Modality must match 'MR' or 'CT' or 'PT'",
                "enum": ["CT", "PT", "MR"],
                "type": "string"
            }
        }
    }
    test_validator = jsonschema.Draft7Validator(template)
    test_error = next(test_validator.iter_errors(test_dict))
    expected_dict = {
        'error_message': "'NM' is not one of ['CT', 'PT', 'MR']",
         'error_type': 'enum',
         'error_value': 'NM',
         'item': 'info.header.dicom.Modality',
         'revalidate': True,
         'schema': {'description': "Modality must match 'MR' or 'CT' or 'PT'",
                    'enum': ['CT', 'PT', 'MR'],
                    'type': 'string'}
    }
    error_dict = get_validation_error_dict(test_error)
    assert error_dict == expected_dict


def test_get_validation_error_dict_anyof():
    test_dict = {
        'Modality': 'NM',
        'ImageType': 'SCREEN SAVE',
        'Units': 'MLML'
    }

    # Test enum
    template = {
        "anyOf": [
            {"required": ["AcquisitionDate"]},
            {"required": ["SeriesDate"]},
            {"required": ["StudyDate"]}
        ]
    }
    test_validator = jsonschema.Draft7Validator(template)
    test_error = next(test_validator.iter_errors(test_dict))
    expected_dict = {
        'error_type': 'anyOf',
        'error_value': None,
        'item': 'info.header.dicom',
        'revalidate': True,
        'schema': {'anyOf': [{'required': ['AcquisitionDate']},
                             {'required': ['SeriesDate']},
                             {'required': ['StudyDate']}]}
    }
    error_dict = get_validation_error_dict(test_error)
    for key in expected_dict.keys():
        assert error_dict[key] == expected_dict[key]


def test_validate_against_template():
    template = {
        "properties": {
            "ImageType": {
                "description": "ImageType cannot be 'SCREEN SAVE'",
                "type": "array",
                "items": {
                    "not": {
                        "enum": [
                            "SCREEN SAVE"
                        ]
                    }
                }
            },
            "Modality": {
                "description": "Modality must match 'MR' or 'CT' or 'PT'",
                "enum": ["CT", "PT", "MR"],
                "type": "string"
            }
        },
        "type": "object",
        "anyOf": [
            {
                "required": [
                    "AcquisitionDate"
                ]
            },
            {
                "required": [
                    "SeriesDate"
                ]
            },
            {
                "required": [
                    "StudyDate"
                ]
            }
        ],
        "dependencies": {
            "Units": ["PatientWeight"]
        }
    }

    test_dict = {
        'Modality': 'NM',
        'ImageType': ['SCREEN SAVE'],
        'Units': 'MLML'
    }
    error_list = validate_against_template(test_dict, template)
    assert len(error_list) == 4


