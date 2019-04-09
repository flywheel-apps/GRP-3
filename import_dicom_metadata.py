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
from fnmatch import fnmatch
from pprint import pprint

logging.basicConfig()
log = logging.getLogger('grp-3')


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
        'Y': 365,
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
        # return datetime.datetime.strptime(date + time[:6], '%Y%m%d%H%M%S')
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
    if hasattr(dcm, 'StudyDate') and hasattr(dcm, 'StudyTime'):
        study_date = dcm.StudyDate
        study_time = dcm.StudyTime
    elif hasattr(dcm, 'StudyDateTime'):
        study_date = dcm.StudyDateTime[0:8]
        study_time = dcm.StudyDateTime[8:]
    else:
        study_date = None
        study_time = None

    if hasattr(dcm, 'AcquisitionDate') and hasattr(dcm, 'AcquisitionTime'):
        acquitision_date = dcm.AcquisitionDate
        acquisition_time = dcm.AcquisitionTime
    elif hasattr(dcm, 'AcquisitionDateTime'):
        acquitision_date = dcm.AcquisitionDateTime[0:8]
        acquisition_time = dcm.AcquisitionDateTime[8:]
    # The following allows the timestamps to be set for ScreenSaves
    elif hasattr(dcm, 'ContentDate') and hasattr(dcm, 'ContentTime'):
        acquitision_date = dcm.ContentDate
        acquisition_time = dcm.ContentTime
    else:
        acquitision_date = None
        acquisition_time = None

    session_timestamp = timestamp(dcm.StudyDate, dcm.StudyTime, timezone)
    acquisition_timestamp = timestamp(acquitision_date, acquisition_time, timezone)

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
            return [ int(x) for x in s ]
        except ValueError:
            try:
                return [ float(x) for x in s ]
            except ValueError:
                return [ format_string(x) for x in s if len(x) > 0 ]
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
    seq_dict = {}
    for seq in sequence:
        for s_key in seq.dir():
            s_val = getattr(seq, s_key, '')
            if type(s_val) is pydicom.UID.UID or s_key in ignore_keys:
                continue

            if type(s_val) == pydicom.sequence.Sequence:
                _seq = get_seq_data(s_val, ignore_keys)
                seq_dict[s_key] = _seq
                continue

            if type(s_val) == str:
                s_val = format_string(s_val)
            else:
                s_val = assign_type(s_val)

            if s_val:
                seq_dict[s_key] = s_val

    return seq_dict


def get_pydicom_header(dcm):
    # Extract the header values
    header = {}
    exclude_tags = ['[Unknown]', 'PixelData', 'Pixel Data',  '[User defined data]', '[Protocol Data Block (compressed)]', '[Histogram tables]', '[Unique image iden]']
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

            if type(dcm.get(tag)) == pydicom.sequence.Sequence:
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


def get_classification_from_string(value):
    result = {}

    parts = re.split(r'\s*,\s*', value)
    last_key = None
    for part in parts:
        key_value = re.split(r'\s*:\s*', part)

        if len(key_value) == 2:
            last_key = key = key_value[0]
            value = key_value[1]
        else:
            if last_key:
                key = last_key
            else:
                log.warning('Unknown classification format: {0}'.format(part))
                key = 'Custom'
            value = part

        if key not in result:
            result[key] = []

        result[key].append(value)

    return result


def validate_against_template(input_dict, template, error_log_path):
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
        else:
            # Get the value of the field that failed validation
            tmp_dict['error_value'] = error.instance
            # Get the field that failed validation
            tmp_dict['item'] = 'info.' + str(error.path.pop())
            # Get the schema object used to validate in failed validation
            tmp_dict['schema'] = error.schema
        # Append individual error object to the return validation_errors object
        validation_errors.append(tmp_dict)

    with open(error_log_path, 'w') as outfile:
        json.dump(validation_errors, outfile, separators=(', ', ': '), sort_keys=True, indent=4)
    return validation_errors


def dicom_to_json(zip_file_path, outbase, timezone):
    # Check for input file path
    if not os.path.exists(zip_file_path):
        log.debug('could not find %s' % zip_file_path)
        log.debug('checking input directory ...')
        if os.path.exists(os.path.join('/input', zip_file_path)):
            zip_file_path = os.path.join('/input', zip_file_path)
            log.debug('found %s' % zip_file_path)

    if not outbase:
        outbase = '/flywheel/v0/output'
        log.info('setting outbase to %s' % outbase)

    # Extract the last file in the zip to /tmp/ and read it
    dcm = []
    if zipfile.is_zipfile(zip_file_path):
        zip = zipfile.ZipFile(zip_file_path)
        num_files = len(zip.namelist())
        for n in range((num_files - 1), -1, -1):
            dcm_path = zip.extract(zip.namelist()[n], '/tmp')
            if os.path.isfile(dcm_path):
                try:
                    log.info('reading %s' % dcm_path)
                    dcm = pydicom.read_file(dcm_path)
                    # Here we check for the Raw Data Storage SOP Class, if there
                    # are other pydicom files in the zip then we read the next one,
                    # if this is the only class of pydicom in the file, we accept
                    # our fate and move on.
                    if dcm.get('SOPClassUID') == 'Raw Data Storage' and n != range((num_files - 1), -1, -1)[-1]:
                        continue
                    else:
                        break
                except:
                    pass
            else:
                log.warning('%s does not exist!' % dcm_path)
    else:
        log.info('Not a zip. Attempting to read %s directly' % os.path.basename(zip_file_path))
        dcm = pydicom.read_file(zip_file_path)

    if not dcm:
        log.warning('dcm is empty!!!')
        os.sys.exit(1)

    # Build metadata
    metadata = {}

    # Session metadata
    metadata['session'] = {}
    session_timestamp, acquisition_timestamp = get_timestamp(dcm, timezone);
    if session_timestamp:
        metadata['session']['timestamp'] = session_timestamp
    if hasattr(dcm, 'OperatorsName') and dcm.get('OperatorsName'):
        metadata['session']['operator'] = format_string(dcm.get('OperatorsName'))
    session_label = get_session_label(dcm)
    if session_label:
        metadata['session']['label'] = session_label

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
    if hasattr(dcm, 'PatientName') and dcm.get('PatientName').given_name:
        # If the first name or last name field has a space-separated string, and one or the other field is not
        # present, then we assume that the operator put both first and last names in that one field. We then
        # parse that field to populate first and last name.
        metadata['session']['subject']['firstname'] = str(format_string(dcm.get('PatientName').given_name))
        if not dcm.get('PatientName').family_name:
            name = format_string(dcm.get('PatientName').given_name.split(' '))
            if len(name) == 2:
                first = name[0]
                last = name[1]
                metadata['session']['subject']['lastname'] = str(last)
                metadata['session']['subject']['firstname'] = str(first)
    if hasattr(dcm, 'PatientName') and dcm.get('PatientName').family_name:
        metadata['session']['subject']['lastname'] = str(format_string(dcm.get('PatientName').family_name))
        if not dcm.get('PatientName').given_name:
            name = format_string(dcm.get('PatientName').family_name.split(' '))
            if len(name) == 2:
                first = name[0]
                last = name[1]
                metadata['session']['subject']['lastname'] = str(last)
                metadata['session']['subject']['firstname'] = str(first)

    # File classification
    pydicom_file = {}
    pydicom_file['name'] = os.path.basename(zip_file_path)
    pydicom_file['modality'] = format_string(dcm.get('Modality', 'MR'))

    # Acquisition metadata
    metadata['acquisition'] = {}
    if hasattr(dcm, 'Modality') and dcm.get('Modality'):
        metadata['acquisition']['instrument'] = format_string(dcm.get('Modality'))

    series_desc = format_string(dcm.get('SeriesDescription', ''))
    if series_desc:
        metadata['acquisition']['label'] = series_desc

    if acquisition_timestamp:
        metadata['acquisition']['timestamp'] = acquisition_timestamp

    # Acquisition metadata from pydicom header
    pydicom_file['info'] = get_pydicom_header(dcm)

    # Validate header data
    error_filepath = os.path.join(output_folder, 'log.error.json')
    validate_against_template(pydicom_file['info'], json_template, error_filepath)

    # Append the pydicom_file to the files array
    metadata['acquisition']['files'] = [pydicom_file]

    # Acquisition metadata from pydicom header
    metadata['acquisition']['metadata'] = get_pydicom_header(dcm)
    if dcm.get('Manufacturer') == 'SIEMENS':
        csa_header = get_csa_header(dcm)
        if csa_header:
            metadata['acquisition']['metadata']['CSAHeader'] = csa_header

    # Write out the metadata to file (.metadata.json)
    metafile_outname = os.path.join(os.path.dirname(outbase), '.metadata.json')
    with open(metafile_outname, 'w') as metafile:
        json.dump(metadata, metafile, separators=(', ', ': '), sort_keys=True, indent=4)

    # Show the metadata
    pprint(metadata)

    return metafile_outname


# Gear basics
input_folder = '/flywheel/v0/input/file/'
output_folder = '/flywheel/v0/output/'

# Declare config file path
config_file_path = '/flywheel/v0/config.json'

# Load config file
with open(config_file_path) as config_data:
    config = json.load(config_data)

# Determine dicom zip path and name
dicom_filepath = config['inputs']['dicom']['location']['path']
dicom_name = config['inputs']['dicom']['location']['name']

# Determine template json filepath
template_filepath = config['inputs']['json_template']['location']['path']

# Declare the output path
output_filepath = os.path.join(output_folder, '.metadata.json')

# Determine the level from which the gear was invoked
hierarchy_level = config['inputs']['dicom']['hierarchy']['type']

# Configure timezone
timezone = validate_timezone(tzlocal.get_localzone())

# Import JSON template
with open(template_filepath) as template_data:
    json_template = json.load(template_data)


metadatafile = dicom_to_json(dicom_filepath, output_filepath, timezone)