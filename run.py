#!/usr/bin/env python3

import os
import re
import json
import pytz
import pydicom
from pydicom.errors import InvalidDicomError
import string
import tzlocal
import logging
import zipfile
import datetime
import nibabel
import tempfile

from utils.dicom import dicom_archive
from utils.update_file_info import get_file_dict_and_update_metadata_json
from utils.validation import validate_against_rules, validate_against_template

logging.basicConfig()
log = logging.getLogger('grp-3')
log.setLevel('INFO')


def validate_dicom(path):
    with tempfile.TemporaryDirectory() as temp_dir:
        dicom_archive.DicomArchive(zip_path=path, extract_dir=temp_dir)


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
    Parse Study Date and Time, return acquisition and session timestamps.

    For study date/time Dicom tag used by order of priority goes like a:
        - StudyDate/StudyTime
        - SeriesDate/SeriesTime
        - AcquisitionDate/AcquisitionTime
        - AcquisitionDateTime
        - StudyDate and Time defaults to 00:00
        - SeriesDates and Time defaults to 00:00
        - AcquisitionDate and Time defaults to 00:00

    For acquisition date/time Dicom tag used by order of priority goes like a:
        - SeriesDate/SeriesTime
        - AcquisitionDate/AcquisitionTime
        - AcquisitionDateTime
        - ContentDate/ContentTime
        - StudyDate/StudyTime
        - SeriesDate and Time defaults to 00:00
        - AcquisitionDate and Time defaults to 00:00
        - StudyDate and Time defaults to 00:00
    """
    # Study Date and Time, with precedence as below
    if getattr(dcm, 'StudyDate', None) and getattr(dcm, 'StudyTime', None):
        study_date = dcm.StudyDate
        study_time = dcm.StudyTime
    elif getattr(dcm, 'SeriesDate', None) and getattr(dcm, 'SeriesTime', None):
        study_date = dcm.SeriesDate
        study_time = dcm.SeriesTime
    elif getattr(dcm, 'AcquisitionDate', None) and getattr(dcm, 'AcquisitionTime', None):
        study_date = dcm.AcquisitionDate
        study_time = dcm.AcquisitionTime
    elif getattr(dcm, 'AcquisitionDateTime', None):
        study_date = dcm.AcquisitionDateTime[0:8]
        study_time = dcm.AcquisitionDateTime[8:]
    # If only Dates are available setting time to 00:00
    elif getattr(dcm, 'StudyDate', None):
        study_date = dcm.StudyDate
        study_time = '000000.00'
    elif getattr(dcm, 'SeriesDate', None):
        study_date = dcm.SeriesDate
        study_time = '000000.00'
    elif getattr(dcm, 'AcquisitionDate', None):
        study_date = dcm.AcquisitionDate
        study_time = '000000.00'
    else:
        study_date = None
        study_time = None

    # Acquisition Date and Time, with precedence as below
    if getattr(dcm, 'SeriesDate', None) and getattr(dcm, 'SeriesTime', None):
        acquisition_date = dcm.SeriesDate
        acquisition_time = dcm.SeriesTime
    elif getattr(dcm, 'AcquisitionDate', None) and getattr(dcm, 'AcquisitionTime', None):
        acquisition_date = dcm.AcquisitionDate
        acquisition_time = dcm.AcquisitionTime
    elif getattr(dcm, 'AcquisitionDateTime', None):
        acquisition_date = dcm.AcquisitionDateTime[0:8]
        acquisition_time = dcm.AcquisitionDateTime[8:]
    # The following allows the timestamps to be set for ScreenSaves
    elif getattr(dcm, 'ContentDate', None) and getattr(dcm, 'ContentTime', None):
        acquisition_date = dcm.ContentDate
        acquisition_time = dcm.ContentTime
    # Looking deeper if nothing found so far
    elif getattr(dcm, 'StudyDate', None) and getattr(dcm, 'StudyTime', None):
        acquisition_date = dcm.StudyDate
        acquisition_time = dcm.StudyTime
    # If only Dates are available setting time to 00:00
    elif getattr(dcm, 'SeriesDate', None):
        acquisition_date = dcm.SeriesDate
        acquisition_time = '000000.00'
    elif getattr(dcm, 'AcquisitionDate', None):
        acquisition_date = dcm.AcquisitionDate
        acquisition_time = '000000.00'
    elif getattr(dcm, 'StudyDate', None):
        acquisition_date = dcm.StudyDate
        acquisition_time = '000000.00'

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
    """Return list of nested dictionaries matching sequence

    Args:
        sequence (pydicom.Sequence): A pydicom sequence
        ignore_keys (list): List of keys to ignore

    Returns:
        (list): list of nested dictionary matching sequence
    """
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


def walk_dicom(dcm):
    taglist = sorted(dcm._dict.keys())
    errors = []
    for tag in taglist:
        try:
            data_element = dcm[tag]
            if tag in dcm and data_element.VR == "SQ":
                sequence = data_element.value
                for dataset in sequence:
                    walk_dicom(dataset)
        except Exception as ex:
            msg = f'With tag {tag} got exception: {str(ex)}'
            errors.append(msg)
    return errors


def get_pydicom_header(dcm):
    # Extract the header values
    errors = walk_dicom(dcm)   # used to load all dcm tags in memory
    if errors:
        result = ''
        for error in errors:
            result += '\n  {}'.format(error)
        log.warning(f'Errors found in walking dicom: {result}')
    header = {}
    exclude_tags = ['[Unknown]',
                    'PixelData',
                    'Pixel Data',
                    '[User defined data]',
                    '[Protocol Data Block (compressed)]',
                    '[Histogram tables]',
                    '[Unique image iden]',
                    'ContourData',
                    'EncryptedAttributesSequence'
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


def get_dcm_data_dict(dcm_path, force=False):
    file_size = os.path.getsize(dcm_path)
    res = {
        'path': dcm_path,
        'size': file_size
    }
    if file_size > 0:
        try:
            dcm = pydicom.dcmread(dcm_path, force=force, stop_before_pixels=True)
            res['header'] = get_pydicom_header(dcm)
        except Exception:
            log.warning('Failed to parse %s. Skipping.', os.path.basename(dcm_path))
    else:
        log.warning('%s is empty. Skipping.', os.path.basename(dcm_path))
    return res


def dicom_to_json(file_path, outbase, timezone, json_template, force=False):

    # Build list of dcm files
    if zipfile.is_zipfile(file_path):
        log.info('Extracting %s ' % os.path.basename(file_path))
        zip = zipfile.ZipFile(file_path)
        tmp_dir = tempfile.TemporaryDirectory().name
        zip.extractall(path=tmp_dir)
        dcm_path_list = [os.path.join(tmp_dir, p) for p in zip.namelist()]
    else:
        log.info('Not a zip. Attempting to read %s directly' % os.path.basename(file_path))
        dcm_path_list = [file_path]

    # Get list of Dicom data dict (with keys path, size, header)
    dcm_dict_list = []
    for dcm_path in dcm_path_list:
        dcm_dict_list.append(get_dcm_data_dict(dcm_path, force=force))

    # Load a representative dcm file
    # Currently: not 0-byte file and SOPClassUID not Raw Data Storage unless that the only file
    dcm = None
    for i, it in enumerate(dcm_dict_list):
        if it['size'] > 0 and it.get('header'):
            # Here we check for the Raw Data Storage SOP Class, if there
            # are other pydicom files in the zip then we read the next one,
            # if this is the only class of pydicom in the file, we accept
            # our fate and move on.
            if it['header'].get('SOPClassUID') == 'Raw Data Storage' and i < len(dcm_dict_list) - 1:
                log.warning('SOPClassUID=Raw Data Storage for %s. Skipping', it['path'])
                continue
            else:
                dcm = pydicom.dcmread(it['path'], force=force)
    if not dcm:
        log.warning('No dcm file found to be parsed!!!')
        os.sys.exit(1)
    else:
        log.info('%s will be used for metadata extraction', os.path.basename(it['path']))

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
        patient_weight = assign_type(dcm.get('PatientWeight'))
        if isinstance(patient_weight, (int, float)):  # PatientWeight VR is DS (decimal string)
            # assign_type manages to cast it to numeric
            metadata['session']['weight'] = patient_weight
        else:
            log.warning('PatientWeight not a numeric (%s). Will not be stored in session metadata.', patient_weight)

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
    pydicom_file['name'] = os.path.basename(file_path)
    pydicom_file['modality'] = format_string(dcm.get('Modality', 'MR'))
    pydicom_file['info'] = {
                                "header": {
                                    "dicom": {}
                                }
                            }

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
    error_file_name = os.path.basename(file_path) + '.error.log.json'
    error_filepath = os.path.join(outbase, error_file_name)
    validation_errors = validate_against_template(pydicom_file['info']['header']['dicom'], json_template)

    # Validate DICOM header df against file rules
    rule_errors = validate_against_rules(dcm_dict_list)

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
    print_string = json.dumps(metadata, separators=(', ', ': '), sort_keys=True, indent=4)
    log.info('DICOM .metadata.json: \n%s\n', print_string)
    with open(metafile_outname, 'w') as metafile:
        json.dump(metadata, metafile, separators=(', ', ': '), sort_keys=True, indent=4)

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
            get_file_dict_and_update_metadata_json('dicom', output_filepath)
            os.sys.exit(0)


def split_seriesinstanceUID(dcm_archive_path, output_dir, force=False):
    with dicom_archive.make_temp_directory() as tmp_dir:
        dcm_archive_obj = dicom_archive.DicomArchive(dcm_archive_path, tmp_dir, dataset_list=True, force=force)
        if dcm_archive_obj.contains_different_seriesinstanceUID():
            log.info('Splitting embedded Series...')
            dcm_archive_obj.split_archive_on_unique_tag(
                'SeriesInstanceUID',
                output_dir,
                '',
                all_unique=True
            )
            # Exit - gear rule should pick up new files and extract+Validate
            log.info(
                'SeriesInstanceUID split! Please run this gear on the output dicom archives if a gear rule is not set!'
            )
            get_file_dict_and_update_metadata_json('dicom', output_filepath)
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
    split_on_seriesuid = config['config']['split_on_SeriesUID']
    force_dicom_read = config['config']['force_dicom_read']
    # Set dicom path and name from config file
    dicom_filepath = config['inputs']['dicom']['location']['path']
    dicom_name = config['inputs']['dicom']['location']['name']

    # Check that input is DICOM
    validate_dicom(dicom_filepath)
    # Set template json filepath (if provided)
    if config['inputs'].get('json_template'):
        template_filepath = config['inputs']['json_template']['location']['path']
    else:
        template_filepath = None

    # Determine the level from which the gear was invoked
    hierarchy_level = config['inputs']['dicom']['hierarchy']['type']

    # Split seriesinstanceUID
    if split_on_seriesuid:
        try:
            split_seriesinstanceUID(dicom_filepath, output_folder, force_dicom_read)

        except Exception as err:
            log.error('split_seriesinstanceUID failed! err={}'.format(err), exc_info=True)

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

    metadatafile = dicom_to_json(dicom_filepath, output_folder, timezone, json_template, force=force_dicom_read)

    get_file_dict_and_update_metadata_json('dicom', metadatafile)

    if os.path.isfile(metadatafile):
        os.sys.exit(0)
