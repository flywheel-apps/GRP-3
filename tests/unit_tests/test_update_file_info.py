import copy

from utils.update_file_info import get_meta_file_dict_and_index, update_meta_file_dict, get_file_update_dict, \
    replace_metadata_file_dict


METADATA_DICT = {
    'acquisition': {
        'files': [
            {
                'name': 'test.dicom.zip',
                'modality': 'MR',
                'info': {}
            }
        ]
    }
}

FW_FILE_DICT = {
    'name': 'test.dicom.zip',
    'spam': 'eggs',
    'modality': 'CT',
    'type': 'dicom',
    'info': {
        'header': {'dicom': {}},
        'export': {
            'origin_id': 'test_id'
        }
    }
}


def test_get_file_update_dict():
    expected_dict = {
        'modality': 'CT',
        'type': 'dicom',
        'info': {
            'export': {
                'origin_id': 'test_id'
            }
        }
    }
    assert get_file_update_dict(FW_FILE_DICT) == expected_dict


def test_get_meta_file_dict_and_index():
    idx, f_dict = get_meta_file_dict_and_index(METADATA_DICT, 'test.dicom.zip', 'acquisition')
    assert idx == 0
    assert f_dict == METADATA_DICT['acquisition']['files'][0]


def test_update_meta_file_dict():
    idx, meta_file_dict = get_meta_file_dict_and_index(METADATA_DICT, FW_FILE_DICT.get('name'),
                                                       'acquisition')
    print(meta_file_dict)
    updated_dict = update_meta_file_dict(meta_file_dict, FW_FILE_DICT)
    expected_dict = {
        'name': 'test.dicom.zip',
        'modality': 'MR',
        'type': 'dicom',
        'info': {
            'export': {
                'origin_id': 'test_id'
            }
        }
    }
    assert updated_dict == expected_dict


def test_replace_metadata_file_dict():
    index = 0
    meta_file_dict = {
        'name': 'test.dicom.zip',
        'modality': 'MR',
        'type': 'dicom',
        'info': {
            'export': {
                'origin_id': 'test_id'
            }
        }
    }
    parent_type = 'acquisition'
    expected = {
        'acquisition': {
            'files': [
                {
                    'name': 'test.dicom.zip',
                    'modality': 'MR',
                    'info': {
                        'export': {
                            'origin_id': 'test_id'
                        }
                    }
                }
            ]
        }
    }
    result = replace_metadata_file_dict(METADATA_DICT, index, meta_file_dict, parent_type)
    assert sorted(result) == sorted(expected)