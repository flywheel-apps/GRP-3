#!/usr/bin/env python3

import os
import re
import json
import jsonschema
import pytz
import pydicom
import string
import tzlocal
import logging
import zipfile
import datetime
import argparse
import nibabel
import pandas as pd
import numpy as np
from fnmatch import fnmatch
from pprint import pprint

from utils.dicom import dicom_archive

logging.basicConfig()
log = logging.getLogger('grp-3')
log.setLevel('INFO')


def get_session_label(dcm):
    """
    Switch on manufacturer and either pull out the StudyID or the StudyInstanceUID
    """
    session_label = ''
    if ( dcm.get('Manufacturer') and (dcm.get('Manufacturer').find('GE') != -1 or dcm.get('Manufacturer').find('Philips') != -1 ) and dcm.get('StudyID')):
        session_label = dcm.get('StudyID')
    else:
        session_label = dcm.get('StudyInstanceUID')

    return session_label


def validate_timezone(zone):
    # pylint: disable=missing-docstring
    if zone is None:
        zone = tzlocal.get_localzone()
    else:
        try:
            zone = pytz.timezone(zone.zone)
        except pytz.UnknownTimeZoneError:
            zone = None
    return zone


def parse_patient_age(age):
    """
    Parse patient age from string.
    convert from 70d, 10w, 2m, 1y to datetime.timedelta object.
    Returns age as duration in seconds.
    """
    if age == 'None' or not age:
        return None

    conversion = {  # conversion to days
        'Y': 365.25,
        'M': 30,
        'W': 7,
        'D': 1,
    }
    scale = age[-1:]
    value = age[:-1]
    if scale not in conversion.keys():
        # Assume years
        scale = 'Y'
        value = age

    age_in_seconds = datetime.timedelta(int(value) * conversion.get(scale)).total_seconds()

    # Make sure that the age is reasonable
    if not age_in_seconds or age_in_seconds <= 0:
        age_in_seconds = None

    return age_in_seconds


def timestamp(date, time, timezone):
    """
    Return datetime formatted string
    """
    if date and time and timezone:
        try:
            return timezone.localize(datetime.datetime.strptime(date + time[:6], '%Y%m%d%H%M%S'), timezone)
        except:
            log.warning('Failed to create timestamp!')
            log.info(date)
            log.info(time)
            log.info(timezone)
            return None
    return None


def get_timestamp(dcm, timezone):
    """
    Parse Study Date and Time, return acquisition and session timestamps
    """
    if hasattr(dcm, 'StudyDate') and hasattr(dcm, 'StudyTime') and \
       getattr(dcm, 'StudyDate') and getattr(dcm, 'StudyTime'):
        study_date = dcm.StudyDate
        study_time = dcm.StudyTime
    elif hasattr(dcm, 'StudyDateTime') and \
         getattr(dcm, 'StudyDateTime'):
        study_date = dcm.StudyDateTime[0:8]
        study_time = dcm.StudyDateTime[8:]
    elif hasattr(dcm, 'SeriesDate') and hasattr(dcm, 'SeriesTime') and \
         getattr(dcm, 'SeriesDate') and getattr(dcm, 'SeriesTime'):
        study_date = dcm.SeriesDate
        study_time = dcm.SeriesTime
    else:
        study_date = None
        study_time = None

    if hasattr(dcm, 'AcquisitionDate') and hasattr(dcm, 'AcquisitionTime') and \
       getattr(dcm, 'AcquisitionDate') and getattr(dcm, 'AcquisitionTime'):
        acquisition_date = dcm.AcquisitionDate
        acquisition_time = dcm.AcquisitionTime
    elif hasattr(dcm, 'AcquisitionDateTime') and  \
         getattr(dcm, 'AcquisitionDateTime'):
        acquisition_date = dcm.AcquisitionDateTime[0:8]
        acquisition_time = dcm.AcquisitionDateTime[8:]
    # The following allows the timestamps to be set for ScreenSaves
    elif hasattr(dcm, 'ContentDate') and hasattr(dcm, 'ContentTime') and \
         getattr(dcm, 'ContentDate') and getattr(dcm, 'ContentTime'):
        acquisition_date = dcm.ContentDate
        acquisition_time = dcm.ContentTime
    # These will ensure that acquisition_date and acquisition_time are set
    elif hasattr(dcm, 'StudyDate') and hasattr(dcm, 'StudyTime') and \
         getattr(dcm, 'StudyDate') and getattr(dcm, 'StudyTime'):
        acquisition_date = dcm.StudyDate
        acquisition_time = dcm.StudyTime
    elif hasattr(dcm, 'StudyDateTime') and \
         getattr(dcm, 'StudyDateTime'):
        acquisition_date = dcm.StudyDateTime[0:8]
        acquisition_time = dcm.StudyDateTime[8:]
    else:
        acquisition_date = None
        acquisition_time = None

    session_timestamp = timestamp(study_date, study_time, timezone)
    acquisition_timestamp = timestamp(acquisition_date, acquisition_time, timezone)

    if session_timestamp:
        if session_timestamp.tzinfo is None:
            log.info('no tzinfo found, using UTC...')
            session_timestamp = pytz.timezone('UTC').localize(session_timestamp)
        session_timestamp = session_timestamp.isoformat()
    else:
        session_timestamp = ''
    if acquisition_timestamp:
        if acquisition_timestamp.tzinfo is None:
            log.info('no tzinfo found, using UTC')
            acquisition_timestamp = pytz.timezone('UTC').localize(acquisition_timestamp)
        acquisition_timestamp = acquisition_timestamp.isoformat()
    else:
        acquisition_timestamp = ''
    return session_timestamp, acquisition_timestamp


def get_sex_string(sex_str):
    """
    Return male or female string.
    """
    if sex_str == 'M':
        sex = 'male'
    elif sex_str == 'F':
        sex = 'female'
    else:
        sex = ''
    return sex


def assign_type(s):
    """
    Sets the type of a given input.
    """
    if type(s) == pydicom.valuerep.PersonName or type(s) == pydicom.valuerep.PersonName3 or type(s) == pydicom.valuerep.PersonNameBase:
        return format_string(s)
    if type(s) == list or type(s) == pydicom.multival.MultiValue:
        try:
            return [ float(x) for x in s ]
        except ValueError:
            try:
                return [ int(x) for x in s ]
            except ValueError:
                return [ format_string(x) for x in s if len(x) > 0 ]
    elif type(s) == float or type(s) == int:
        return s
    else:
        s = str(s)
        try:
            return int(s)
        except ValueError:
            try:
                return float(s)
            except ValueError:
                return format_string(s)


def format_string(in_string):
    formatted = re.sub(r'[^\x00-\x7f]',r'', str(in_string)) # Remove non-ascii characters
    formatted = ''.join(filter(lambda x: x in string.printable, formatted))
    if len(formatted) == 1 and formatted == '?':
        formatted = None
    return formatted#.encode('utf-8').strip()


def get_seq_data(sequence, ignore_keys):
    res = []
    for seq in sequence:
        seq_dict = {}
        for k, v in seq.items():
            if not hasattr(v, 'keyword') or \
                    (hasattr(v, 'keyword') and v.keyword in ignore_keys) or \
                    (hasattr(v, 'keyword') and not v.keyword):  # keyword of type "" for unknown tags
                continue
            kw = v.keyword
            if isinstance(v.value, pydicom.sequence.Sequence):
                seq_dict[kw] = get_seq_data(v, ignore_keys)
            elif isinstance(v.value, str):
                seq_dict[kw] = format_string(v.value)
            else:
                seq_dict[kw] = assign_type(v.value)
        res.append(seq_dict)
    return res


def get_pydicom_header(dcm):
    # Extract the header values
    dcm.decode()
    header = {}
    exclude_tags = ['[Unknown]',
                    'PixelData',
                    'Pixel Data',
                    '[User defined data]',
                    '[Protocol Data Block (compressed)]',
                    '[Histogram tables]',
                    '[Unique image iden]',
                    'ContourData',
                    ]
    tags = dcm.dir()
    for tag in tags:
        try:
            if (tag not in exclude_tags) and ( type(dcm.get(tag)) != pydicom.sequence.Sequence ):
                value = dcm.get(tag)
                if value or value == 0: # Some values are zero
                    # Put the value in the header
                    if type(value) == str and len(value) < 10240: # Max pydicom field length
                        header[tag] = format_string(value)
                    else:
                        header[tag] = assign_type(value)
                else:
                    log.debug('No value found for tag: ' + tag)

            if (tag not in exclude_tags) and type(dcm.get(tag)) == pydicom.sequence.Sequence:
                seq_data = get_seq_data(dcm.get(tag), exclude_tags)
                # Check that the sequence is not empty
                if seq_data:
                    header[tag] = seq_data
        except:
            log.debug('Failed to get ' + tag)
            pass
    return header


def get_csa_header(dcm):
    exclude_tags = ['PhoenixZIP', 'SrMsgBuffer']
    header = {}
    try:
        raw_csa_header = nibabel.nicom.dicomwrappers.SiemensWrapper(dcm).csa_header
        tags = raw_csa_header['tags']
    except:
        log.warning('Failed to parse csa header!')
        return header

    for tag in tags:
        if not raw_csa_header['tags'][tag]['items'] or tag in exclude_tags:
            log.debug('Skipping : %s' % tag)
            pass
        else:
            value = raw_csa_header['tags'][tag]['items']
            if len(value) == 1:
                value = value[0]
                if type(value) == str and ( len(value) > 0 and len(value) < 1024 ):
                    header[format_string(tag)] = format_string(value)
                else:
                    header[format_string(tag)] = assign_type(value)
            else:
                header[format_string(tag)] = assign_type(value)

    return header


def validate_against_template(input_dict, template):
    """
    This is a function for validating a dictionary against a template. Given
    an input_dict and a template object, it will create a JSON schema validator
    and construct an object that is a list of error dictionaries. It will write a
    JSON file to the specified error_log_path and return the validation_errors object as
    well as log each error.message to log.errors

    :param input_dict: a dictionary of DICOM header data to be validated
    :param template: a template dictionary to validate against
    :param error_log_path: the path to which to write error log JSON
    :return: validation_errors, an object containing information on validation errors
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
        # Create a temporary dictionary for the individual error
        tmp_dict = {}
        # Get error type
        tmp_dict['error_type'] = error.validator
        # Get error message and log it
        tmp_dict['error_message'] = error.message
        log.error(error.message)
        # Required field errors are a little special and need to be handled
        # separately to get the field. We don't get the schema because it
        # will print the entire template schema
        if error.validator == "required":
            # Get the item failing validation from the error message
            tmp_dict['item'] = 'info.' + error.message.split("'")[1]
        # Get additional information for pattern and type errors
        elif error.validator in ("pattern", "type"):
            # Get the value of the field that failed validation
            tmp_dict['error_value'] = error.instance
            # Get the field that failed validation
            tmp_dict['item'] = 'info.header.dicom.' + str(error.path.pop())
            # Get the schema object used to validate in failed validation
            tmp_dict['schema'] = error.schema
        elif error.validator == "anyOf":
            tmp_dict['schema'] = {"anyOf": error.schema['anyOf']}
        else:
            pass
        # revalidate key so that validation errors can be revalidated in the future
        tmp_dict['revalidate'] = True
        # Append individual error object to the return validation_errors object
        validation_errors.append(tmp_dict)

    return validation_errors


def most_frequent_interval(intervals):
    size = len(intervals)
    for i in [3,2,1]:
        list = [round(x,i) for x in intervals]
        dict = {}
        count, itm = 0, ''
        for item in reversed(list):
            dict[item] = dict.get(item, 0) + 1
            if dict[item] >= count :
                count, itm = dict[item], item
        if count > size/2:
            return(itm)
    return None


def check_missing_slices(df, this_sequence):
    # holds any error messages related to missing slices
    slice_error_list = []

    # sequence_message is added to slice error message if we are dealing with multiple sequences
    sequence_message = ""
    if this_sequence != None and this_sequence != '':
        sequence_message = ' (SequenceName is {}, in case there are multiple.)'.format(this_sequence)

    # Holds all locations of slices
    locations = []

    ## First we check if acquisition is long enough to warrant slice interval checking (i.e. not localizers)
    threshold = 10
    if len(df) < threshold:
        log.warning("Small number of images in sequence; slice interval checking will not be performed.{}".format(sequence_message))
        return slice_error_list

    ## Attempt to find locations via SliceLocation header
    if (('SliceLocation' in df) and ('ImageType' in df)) and True:
        df = df.dropna(subset=['SliceLocation', 'ImageType'])
        # This line iterates through all SliceLocations in rows where LOCALIZER not in ImageType
        for location in (df.loc[~df['ImageType'].str.contains('LOCALIZER')])['SliceLocation']:
            locations.append(location)

    ## Attempt to find locations by ImageOrientationPatient and ImagePositionPatient headers
    elif 'ImageOrientationPatient' and 'ImagePositionPatient' and 'ImageType' in df.columns:
        # DICOM headers annoyingly hold arrays as strings with puncuation
        # This function is needed to turn that string into a real data structure
        def string_to_array(input_str, expected_length):
            s = input_str.replace('[', '')
            s = s.replace(']','')
            s = s.replace(',','')
            s = s.replace('(','')
            s = s.replace(')','')
            arr = s.split()
            return_arr = [float(x) for x in arr]
            # If new array is not expected length, something's gone wrong
            if(len(return_arr) == expected_length):
                return return_arr
            else:
                return False

        # Find normal vector of patient's orientation
        # This line below finds the first ImageOrientationPatient where LOCALIZER not in ImageType

        arr_str = (df.loc[~df['ImageType'].str.contains('LOCALIZER')])['ImageOrientationPatient'][0]
        arr = string_to_array(arr_str, expected_length=6)
        v1 = v2 = normal = []
        if(arr):
            v1 = [arr[0], arr[1], arr[2]]
            v2 = [arr[3], arr[4], arr[5]]
            normal = np.cross(v2, v1)

            # Slice locations are the position vectors times the normal vector from above
            # This line iterates through all ImagePositionPatients in rows where LOCALIZER not in ImageType
            for pos in (df.loc[~df['ImageType'].str.contains('LOCALIZER')])['ImageOrientationPatient']:
                position = string_to_array(pos, expected_length=3)
                if(position):
                    location = np.dot(normal, position)
                    locations.append(location)
                else:
                    locations = []
                    log.warning("'ImagePositionPatient' string format error, cannot check for missing slices!")
                    break

        else:
            log.warning("'ImageOrientationPatient' string format error, cannot check for missing slices!")

    ## Unable to find locations
    else:
        log.warning("'SliceLocation' or 'ImageOrientationPatient' and 'ImagePositionPatient' missing, cannot check for missing slices!")


    ## If locations is not empty (i.e. if nothing's gone wrong), sort it to get accurate intervals
    ## Also if there's only one location found, we don't need to check intervals
    if len(locations) > 1:
        locations.sort()

    ## Now we use the locations to measure intervals
        intervals = []
        for i, loc in enumerate(locations[1:]):
            intervals.append(locations[i+1] - locations[i])

        ## We want to ignore (i.e. remove) all intervals near 0 because they most likely come from duplicate images
        intervals = [ elem for elem in intervals if elem > 0.001 ]

        ## Get the most frequent interval in intervals
        # If most_frequent_interval returns None, end function early
        mode = most_frequent_interval(intervals)
        if not mode:
            error_dict = {
                "error_message": "Inconsistent slice intervals; no common interval found!",
                "revalidate": False
            }
            slice_error_list.append(error_dict)
            return slice_error_list

        tolerance = 0.2 * mode
        abnormal_intervals = []

        for i, val in enumerate(intervals):
            if abs(mode-val) > tolerance:
                rounded_val = round(val,3)
                if rounded_val not in abnormal_intervals:
                    abnormal_intervals.append(rounded_val)

        if len(abnormal_intervals) > 0:
            abnormal_intervals_str = str(abnormal_intervals).strip('[]')
            error_dict = {
                "error_message": "Inconsistent slice intervals. Majority are ~{}mm but intervals include {}.{}"\
                    .format(mode, abnormal_intervals_str, sequence_message),
                "revalidate": False
            }
            slice_error_list.append(error_dict)

    return slice_error_list


def validate_against_rules(df):
    error_list = []
    # Holds all unique sequence names in df (It's possible SequenceName is not a valid field in df)
    sequences = []
    # Holds the new frames after we separate df by SequenceName (i.e. this is a LIST of FRAMES)
    new_frames = []

    # Split df into multiple frames by SequenceName tag
    if 'SequenceName' in df:
        # Populate sequences list and then use it to populate new_frames
        for sequence in df['SequenceName']:
            if sequence not in sequences:
                sequences.append(sequence)
        for sequence in sequences:
            new_frames.append((df.loc[df['SequenceName'] == sequence]))

        # If there's only one sequence, we don't bother alerting the user and pass an empty string to check_missing_slices()
        if len(sequences) == 1:
            sequences = ['']
        else:
            log.warning("Multiple image sequences found in acquisition ({}), will check each individually".format(sequences))

    # If SequenceName tag is not in the header, don't bother trying to split up df
    else:
        sequences = ['']
        new_frames = [df]

    # For every frame in new_frame, add any missing slice errors to error_list
    for i, frame in enumerate(new_frames):
        error_list.extend(check_missing_slices(frame, this_sequence=sequences[i]))


    # Determine if InstanceNumber is unique (not duplicated)
    if 'InstanceNumber' in df:
        if df['InstanceNumber'].is_unique:
            pass
        else:
            duplicated_values = df.loc[df['InstanceNumber'].duplicated(),'InstanceNumber'].values
            error_dict = {
                "error_message": "InstanceNumber is duplicated for values:{}".format(duplicated_values),
                "revalidate": False
            }
            error_list.append(error_dict)
    return error_list


def dicom_date_handler(dcm):
    if dcm.get('AcquisitionDate'):
        pass
    elif dcm.get('SeriesDate'):
        dcm.AcquisitionDate = dcm.get('SeriesDate')
    elif dcm.get('StudyDate'):
        dcm.AcquisitionDate = dcm.get('StudyDate')
    else:
        log.warning('No date found for DICOM file')
    return dcm


def dicom_to_json(zip_file_path, outbase, timezone, json_template, force=False):

    # Extract the last file in the zip to /tmp/ and read it
    if zipfile.is_zipfile(zip_file_path):
        dcm_list = []
        zip = zipfile.ZipFile(zip_file_path)
        num_files = len(zip.namelist())
        for n in range((num_files - 1), -1, -1):
            dcm_path = zip.extract(zip.namelist()[n], '/tmp')
            dcm_tmp = None
            if os.path.isfile(dcm_path):
                try:
                    log.info('reading %s' % dcm_path)
                    dcm_tmp = pydicom.read_file(dcm_path, force=force)
                    # Here we check for the Raw Data Storage SOP Class, if there
                    # are other pydicom files in the zip then we read the next one,
                    # if this is the only class of pydicom in the file, we accept
                    # our fate and move on.
                    if dcm_tmp.get('SOPClassUID') == 'Raw Data Storage' and n != range((num_files - 1), -1, -1)[-1]:
                        continue
                    else:
                        dcm_list.append(dcm_tmp)
                except:
                    pass
            else:
                log.warning('%s does not exist!' % dcm_path)
        dcm = dcm_list[-1]
    else:
        log.info('Not a zip. Attempting to read %s directly' % os.path.basename(zip_file_path))
        dcm = pydicom.read_file(zip_file_path, force=force)
        dcm_list = [dcm]
    if not dcm:
        log.warning('dcm is empty!!!')
        os.sys.exit(1)

    # Handle date on dcm
    dcm = dicom_date_handler(dcm)

    # Create pandas object for comparing headers
    df_list = []
    for header in dcm_list:
        tmp_dict = get_pydicom_header(header)
        for key in tmp_dict:
            if type(tmp_dict[key]) == list:
                tmp_dict[key] = str(tmp_dict[key])
            else:
                tmp_dict[key] = [tmp_dict[key]]
        df_tmp = pd.DataFrame.from_dict(tmp_dict)
        df_list.append(df_tmp)
    df = pd.concat(df_list, ignore_index=True, sort=True)

    # Build metadata
    metadata = {}

    # Session metadata
    metadata['session'] = {}
    session_timestamp, acquisition_timestamp = get_timestamp(dcm, timezone)
    if session_timestamp:
        metadata['session']['timestamp'] = session_timestamp
    if hasattr(dcm, 'OperatorsName') and dcm.get('OperatorsName'):
        metadata['session']['operator'] = format_string(dcm.get('OperatorsName'))
    session_label = get_session_label(dcm)
    if session_label:
        metadata['session']['label'] = session_label
    if hasattr(dcm, 'PatientWeight') and dcm.get('PatientWeight'):
        metadata['session']['weight'] = assign_type(dcm.get('PatientWeight'))

    # Subject Metadata
    metadata['session']['subject'] = {}
    if hasattr(dcm, 'PatientSex') and get_sex_string(dcm.get('PatientSex')):
        metadata['session']['subject']['sex'] = get_sex_string(dcm.get('PatientSex'))
    if hasattr(dcm, 'PatientAge') and dcm.get('PatientAge'):
        try:
            age = parse_patient_age(dcm.get('PatientAge'))
            if age:
                metadata['session']['subject']['age'] = int(age)
        except:
            pass
    if hasattr(dcm, 'PatientName'):
        if hasattr(dcm.get('PatientName'), 'given_name') and hasattr(dcm.get('PatientName'), 'family_name'):
            # If the first name or last name field has a space-separated string, and one or the other field is not
            # present, then we assume that the operator put both first and last names in that one field. We then
            # parse that field to populate first and last name.
            if dcm.get('PatientName').given_name:
                metadata['session']['subject']['firstname'] = str(format_string(dcm.get('PatientName').given_name))
                if not dcm.get('PatientName').family_name:
                    name = format_string(dcm.get('PatientName').given_name.split(' '))
                    if len(name) == 2:
                        first = name[0]
                        last = name[1]
                        metadata['session']['subject']['lastname'] = str(last)
                        metadata['session']['subject']['firstname'] = str(first)
            if dcm.get('PatientName').family_name:
                metadata['session']['subject']['lastname'] = str(format_string(dcm.get('PatientName').family_name))
                if not dcm.get('PatientName').given_name:
                    name = format_string(dcm.get('PatientName').family_name.split(' '))
                    if len(name) == 2:
                        first = name[0]
                        last = name[1]
                        metadata['session']['subject']['lastname'] = str(last)
                        metadata['session']['subject']['firstname'] = str(first)

    # File metadata
    pydicom_file = {}
    pydicom_file['name'] = os.path.basename(zip_file_path)
    pydicom_file['modality'] = format_string(dcm.get('Modality', 'MR'))
    pydicom_file['info'] = {
                                "header": {
                                    "dicom": {}
                                }
                            }
    # Determine how many DICOM files are in directory
    slice_number = len(df)

    # Determine whether ImageOrientationPatient is constant
    if hasattr(df, 'ImageOrientationPatient'):
        uniqueiop = df.ImageOrientationPatient.is_unique
    else:
        uniqueiop = []


    # Acquisition metadata
    metadata['acquisition'] = {}
    if hasattr(dcm, 'Modality') and dcm.get('Modality'):
        metadata['acquisition']['instrument'] = format_string(dcm.get('Modality'))

    series_desc = format_string(dcm.get('SeriesDescription', ''))
    if series_desc:
        metadata['acquisition']['label'] = series_desc

    if acquisition_timestamp:
        metadata['acquisition']['timestamp'] = acquisition_timestamp

    # File metadata from pydicom header
    pydicom_file['info']['header']['dicom'] = get_pydicom_header(dcm)

    # Add CSAHeader to DICOM
    if dcm.get('Manufacturer') == 'SIEMENS':
        csa_header = get_csa_header(dcm)
        if csa_header:
            pydicom_file['info']['header']['dicom']['CSAHeader'] = csa_header

    # Validate header data against json schema template
    error_file_name = os.path.basename(zip_file_path) + '.error.log.json'
    error_filepath = os.path.join(outbase, error_file_name)
    validation_errors = validate_against_template(pydicom_file['info']['header']['dicom'], json_template)

    # Validate DICOM header df against file rules
    rule_errors = validate_against_rules(df)

    # Add error lists together
    validation_errors = validation_errors + rule_errors

    # Write error file
    if validation_errors:
        with open(error_filepath, 'w') as outfile:
            json.dump(validation_errors, outfile, separators=(', ', ': '), sort_keys=True, indent=4)
    if validation_errors:
        metadata['acquisition']['tags'] = ['error']

    # Append the pydicom_file to the files array
    metadata['acquisition']['files'] = [pydicom_file]

    # Write out the metadata to file (.metadata.json)
    metafile_outname = os.path.join(os.path.dirname(outbase), '.metadata.json')
    with open(metafile_outname, 'w') as metafile:
        json.dump(metadata, metafile, separators=(', ', ': '), sort_keys=True, indent=4)

    # Show the metadata
    pprint(metadata)

    return metafile_outname


def split_embedded_localizer(dcm_archive_path, output_dir, force=False):
    with dicom_archive.make_temp_directory() as tmp_dir:
        dcm_archive_obj = dicom_archive.DicomArchive(dcm_archive_path, tmp_dir, dataset_list=True, force=force)
        if dcm_archive_obj.contains_embedded_localizer():
            log.info('Splitting embedded localizer...')
            dcm_archive_obj.split_archive_on_unique_tag(
                'ImageOrientationPatient',
                output_dir,
                '_Localizer',
                all_unique=False
            )
            # Exit - gear rule should pick up new files and extract+Validate
            log.info(
                'Embedded localizer split! Please run this gear on the output dicom archives if a gear rule is not set!'
            )
            os.sys.exit(0)


if __name__ == '__main__':
    # Set paths
    input_folder = '/flywheel/v0/input/file/'
    output_folder = '/flywheel/v0/output/'
    config_file_path = '/flywheel/v0/config.json'
    output_filepath = os.path.join(output_folder, '.metadata.json')

    # Load config file
    with open(config_file_path) as config_data:
        config = json.load(config_data)

    # Get config values
    split_localizer = config['config']['split_localizer']
    force_dicom_read = config['config']['force_dicom_read']
    # Set dicom path and name from config file
    dicom_filepath = config['inputs']['dicom']['location']['path']
    dicom_name = config['inputs']['dicom']['location']['name']

    # Set template json filepath (if provided)
    if config['inputs'].get('json_template'):
        template_filepath = config['inputs']['json_template']['location']['path']
    else:
        template_filepath = None

    # Determine the level from which the gear was invoked
    hierarchy_level = config['inputs']['dicom']['hierarchy']['type']

    # Split embedded localizers if configured to do so and if the
    # Dicom archive is a series that contains an embedded localizer
    if split_localizer:
        try:
            split_embedded_localizer(dicom_filepath, output_folder, force_dicom_read)
        except Exception as err:
            log.error('split_embedded_localizer failed! err={}'.format(err), exc_info=True)

    # Configure timezone
    timezone = validate_timezone(tzlocal.get_localzone())

    # Set default validation template
    template = {}

    # Import JSON template (if provided)
    if template_filepath:
        with open(template_filepath) as template_data:
            import_template = json.load(template_data)
        template.update(import_template)
    json_template = template.copy()

    metadatafile = dicom_to_json(dicom_filepath, output_folder, timezone, json_template, force_dicom_read)
    if os.path.isfile(metadatafile):
        os.sys.exit(0)
