"""Validation module"""
from collections import Counter
import itertools
import logging
import os
import json


import jsonschema
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


DEFAULT_RULE_LIST = [
    'check_instance_number_uniqueness',
    'check_missing_slices',
    'check_0_byte_files',
    'check_pydicom_exception'
]

MIN_NUM_SLICES_TO_CHECK_MISSING_SLICES = 10


def dump_validation_error_file(error_filepath, validation_errors):
    with open(error_filepath, 'w') as outfile:
        json.dump(validation_errors, outfile, separators=(', ', ': '), sort_keys=True, indent=4)


def get_rule_function(func_name):
    """Return function in current module by name"""
    return globals()[func_name]


def get_most_frequent(array, rounding=None):
    """Get the most frequent element in array that is at least found len(array)/2 of times.

    The implementation support a certain tolerance for rounding of the float. Will

    Args:
        array (list): An array of float.
        rounding (list): List of ndigits precision to applied to floats in array (default=[3, 2, 1])

    Returns:
        The most frequent element or None
    """

    if not array:
        return None

    if not isinstance(array, list):
        raise TypeError('array must be of type list')

    if not rounding:
        rounding = [3, 2, 1]

    size = len(array)
    for r in rounding:
        counter = Counter([round(x, r) for x in array])
        most_com = counter.most_common()[0]  # most common first in list: (item, count)
        if most_com[1] > size/2:
            return most_com[0]
    return None


def check_file_is_not_empty(file_path):
    validation_errors = []
    if not os.path.getsize(file_path) > 1:
        error_dict = {
            "error_message": "File is empty: {}".format(file_path),
            "revalidate": False
        }
        validation_errors.append(error_dict)
    return validation_errors


def check_missing_slices(dcm_dict_list):
    """Check for missing slices based on some geometric heuristic

    Check is performed for each individual sequence (SequenceName) in the dicom header

    Args:
        dcm_dict_list (list): List of dict containing dicom data with keys: 'path', 'size', 'header'.

    Returns:
        list: List of errors.
    """

    def _check_missing_slices(ddl, seq_mes):
        error_list = []
        locations = []
        data = []
        for el in ddl:
            data.append({
                'path': el['path'],
                'SliceLocation': el['header'].get('SliceLocation'),
                'ImageType': el['header'].get('ImageType'),
                'ImageOrientationPatient': el['header'].get('ImageOrientationPatient'),
                'ImagePositionPatient': el['header'].get('ImagePositionPatient'),
            })
        df = pd.DataFrame(data)

        # Attempt to find locations via SliceLocation header
        if all(elem in df.columns for elem in ['SliceLocation', 'ImageType']) and \
                len(df.dropna(subset=['SliceLocation', 'ImageType'])) > 1:
            df.dropna(subset=['SliceLocation', 'ImageType'], inplace=True)
            # This line iterates through all SliceLocations in rows where LOCALIZER not in ImageType
            for location in (df.loc[~df['ImageType'].str.join('').str.contains('LOCALIZER')])['SliceLocation']:
                locations.append(location)

        # Attempt to find locations by ImageOrientationPatient and ImagePositionPatient headers
        elif all(elem in df.columns for elem in ['ImageOrientationPatient', 'ImagePositionPatient', 'ImageType']) and \
            len(df.dropna(subset=['ImageOrientationPatient', 'ImagePositionPatient', 'ImageType'])) > 1:
            df.dropna(subset=['ImageOrientationPatient', 'ImageType', 'ImagePositionPatient'], inplace=True)
            # DICOM headers annoyingly hold arrays as strings with puncuation
            # This function is needed to turn that string into a real data structure
            def string_to_array(input_str, expected_length):
                s = input_str.replace('[', '')
                s = s.replace(']', '')
                s = s.replace(',', '')
                s = s.replace('(', '')
                s = s.replace(')', '')
                array = s.split()
                return_arr = [float(x) for x in array]
                # If new array is not expected length, something's gone wrong
                if len(return_arr) == expected_length:
                    return return_arr
                else:
                    return False

            # Find normal vector of patient's orientation
            # This line below finds the first ImageOrientationPatient where LOCALIZER not in ImageType
            arr = (df.loc[~df['ImageType'].str.join('').str.contains('LOCALIZER')])['ImageOrientationPatient'].values[0]
            if arr:
                v1 = [arr[0], arr[1], arr[2]]
                v2 = [arr[3], arr[4], arr[5]]
                normal = np.cross(v2, v1)

                # Slice locations are the position vectors times the normal vector from above
                # This line iterates through all ImagePositionPatient in rows where LOCALIZER not in ImageType
                for pos in (df.loc[~df['ImageType'].str.join('').str.contains('LOCALIZER')])['ImagePositionPatient']:
                    if pos:
                        location = np.dot(normal, pos)
                        locations.append(location)
                    else:
                        locations = []
                        log.warning("'ImagePositionPatients' string format error, cannot check for missing slices!")
                        break

            else:
                log.warning("'ImageOrientationPatient' string format error, cannot check for missing slices!")

        # Unable to find locations
        else:
            log.warning(
                "'SliceLocation' or 'ImageOrientationPatient' and 'ImagePositionPatient' missing, "
                "cannot check for missing slices!")

        # If locations is not empty (i.e. if nothing's gone wrong), sort it to get accurate intervals
        # Also if there's only one location found, we don't need to check intervals
        if len(locations) > 1:
            locations.sort()

            # Now we use the locations to measure intervals
            intervals = []
            for i, loc in enumerate(locations[1:]):
                intervals.append(locations[i + 1] - locations[i])

            # We want to ignore (i.e. remove) all intervals near 0 because they most likely come from duplicate images
            intervals = [elem for elem in intervals if elem > 0.001]

            # Get the most frequent interval in intervals
            # If most_frequent_interval returns None, end function early
            mode = get_most_frequent(intervals)
            if not mode:
                error_dict = {
                    "error_message": "Inconsistent slice intervals; no common interval found!",
                    "revalidate": False
                }
                error_list.append(error_dict)
                return error_list

            tolerance = 0.2 * mode
            abnormal_intervals = []

            for i, val in enumerate(intervals):
                if abs(mode - val) > tolerance:
                    rounded_val = round(val, 3)
                    if rounded_val not in abnormal_intervals:
                        abnormal_intervals.append(rounded_val)

            if len(abnormal_intervals) > 0:
                abnormal_intervals_str = str(abnormal_intervals).strip('[]')
                error_dict = {
                    "error_message": "Inconsistent slice intervals. Majority are ~{}mm but intervals include {}.{}"
                                     .format(mode, abnormal_intervals_str, seq_mes),
                    "revalidate": False
                }
                error_list.append(error_dict)

        return error_list

    def _is_enough_slice_to_check_missing_slice(dcm_dict_list):
        """Returns True if enough number of slices in sequence to check missing slices, False otherwise"""
        if len(dcm_dict_list) < MIN_NUM_SLICES_TO_CHECK_MISSING_SLICES:
            return False
        return True

    # Groups dcm_dict_list by SequenceName
    dcm_dict_list = [el for el in dcm_dict_list if el.get('header')]
    dcm_dict_list_grouped = itertools.groupby(dcm_dict_list, key=lambda x: x['header'].get('SequenceName'))
    sequences_group = [(el[0], list(el[1])) for el in dcm_dict_list_grouped]
    sequences = list(zip(sequences_group))[0]

    # If there's only one sequence, we don't bother logging
    if len(sequences_group) > 1:
        log.warning('Multiple image sequences found in acquisition (%s), will check each individually', sequences)

    # For every frame in new_frame, add any missing slice errors to error_list
    error_list = []
    for seq, dcm_dict_list_sub in sequences_group:

        dcm_dict_list_sub_l = list(dcm_dict_list_sub)
        if not _is_enough_slice_to_check_missing_slice(dcm_dict_list_sub_l):
            log.warning('Small number of images in sequence. '
                        'Slice interval checking will not be performed for SequenceName=%s'.format(seq))
            continue

        log.info('Checking missing slices for SequenceName=%s', seq)

        # sequence_message is added to slice error message if we are dealing with multiple sequences
        sequence_message = ' (SequenceName is {}, in case there are multiple.)'.format(seq)

        error_list += _check_missing_slices(dcm_dict_list_sub_l, sequence_message)

    return error_list


def check_instance_number_uniqueness(dcm_dict_list):
    """Check if InstanceNumber is unique (not duplicated)

    Args:
        dcm_dict_list (list): List of dict containing dicom data with keys: 'path', 'size', 'header'.

    Returns:
        list: List of errors.
    """
    data = []
    for el in dcm_dict_list:
        if el.get('header'):
            data.append({'path': el['path'], 'InstanceNumber': el['header'].get('InstanceNumber')})
    df = pd.DataFrame(data)
    error_list = []
    if 'InstanceNumber' in df:
        if df['InstanceNumber'].is_unique:
            pass
        else:
            duplicated_values = df.loc[df['InstanceNumber'].duplicated(), 'InstanceNumber'].values
            error_dict = {
                "error_message": "InstanceNumber is duplicated for values:{}".format(duplicated_values),
                "revalidate": False
            }
            error_list.append(error_dict)
    return error_list


def check_0_byte_files(dcm_dict_list):
    """Check if dcm file is 0-byte size

    Args:
        dcm_dict_list (list): List of dict containing dicom data with keys: 'path', 'size', 'header'.

    Returns:
        list: List of errors.
    """
    error_list = []
    for el in dcm_dict_list:
        if el['size'] == 0:
            error_dict = {
                "error_message": "Dicom file is empty: {}".format(os.path.basename(el['path'])),
                "revalidate": False
            }
            error_list.append(error_dict)
    return error_list


def check_pydicom_exception(dcm_dict_list):
    """Check if pydicom raised exception

    Args:
        dcm_dict_list (list): List of dict containing dicom data with keys: 'path', 'size', 'header'.

    Returns:
        list: List of errors.
    """
    error_list = []
    for el in dcm_dict_list:
        if el['pydicom_exception']:
            if el['force']:
                error_dict = {
                    "error_message": "Pydicom raised an exception with force=True for file: {}".format(os.path.basename(el['path'])),
                    "revalidate": False
                }
            else:
                error_dict = {
                    "error_message": "Dicom signature not found in: {}. Try running gear with force=True".format(os.path.basename(el['path'])),
                    "revalidate": False
                }
            error_list.append(error_dict)
    return error_list


def validate_against_rules(dcm_dict_list, rules=None):
    """Validate all dicoms in `dcm_dict_list` against rules

    Args:
        dcm_dict_list (list): List of dict containing dicom data with keys: 'path', 'size', 'header'.
        rules (list): List of function name to validate `dcm_dict_list` against.

    Returns:
        list: List of errors found.
    """
    if not rules:
        rules = DEFAULT_RULE_LIST

    error_list = []
    for rule in rules:
        error_list += get_rule_function(rule)(dcm_dict_list)

    return error_list


def get_validation_error_dict(validation_error, file_dict_key='info.header.dicom'):
    """Generates a validation error dictionary to be appended to error list.

    Error list is consumed by GRP-2

    Args:
    file_dict_key (str): Period-delimited string denoting where the field that failed validation
        is located on the flywheel file object. default = info.header.dicom

    validation_error (jsonschema.exceptions.ValidationError): error generated when validating dictionary
        against template

    Returns:
        list: List of errors
    """
    error_dict = {
        'error_type': validation_error.validator,
        'error_message': validation_error.message,
        'schema': validation_error.schema,
        'item': None,
        'error_value': None,
        'revalidate': True
    }
    if validation_error.absolute_path:
        # validation_error.absolute_path is a deque that represents the path to the field within the dict
        item_deque = validation_error.absolute_path.copy()
        item_deque.appendleft(file_dict_key)
        # item is a period - delimited path to the field violating the template on the file object
        error_dict['item'] = '.'.join([str(item) for item in item_deque])
        error_dict['error_value'] = validation_error.instance
    else:
        error_dict['item'] = file_dict_key

    return error_dict


def validate_against_template(input_dict, template):
    """This is a function for validating a dictionary against a template.

    Given an input_dict and a template object, it will create a JSON schema validator
    and construct an object that is a list of error dictionaries. It will write a
    JSON file to the specified error_log_path and return the validation_errors object as
    well as log each error.message to log.errors

    Args:
    input_dict (dict): A dictionary of DICOM header data to be validated.
    template (dict): A template dictionary to validate against.

    Returns:
        list: List of validation_errors.
    """
    try:
        jsonschema.Draft7Validator.check_schema(template)
    except Exception as e:
        log.fatal(
            'The json_template is invalid. Please make the correction and try again.'
        )
        log.exception(e)
        os.sys.exit(1)

    # Initialize json schema validator
    validator = jsonschema.Draft7Validator(template)
    # Initialize list object for storing validation errors
    validation_errors = []
    for error in sorted(validator.iter_errors(input_dict), key=str):
        error_dict = get_validation_error_dict(error)
        # Append individual error object to the return validation_errors object
        validation_errors.append(error_dict)

    return validation_errors