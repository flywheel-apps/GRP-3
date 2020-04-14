import json

import jsonschema

from utils.validation import get_validation_error_dict, validate_against_template


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
