import datetime
import logging
import re
import string

import nibabel
import pytz
import tzlocal
import pydicom

log = logging.getLogger(__name__)


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
    # Remove non-ascii characters
    formatted = re.sub(r'[^\x00-\x7f]', r'', str(in_string))
    formatted = ''.join(filter(lambda x: x in string.printable, formatted))
    if len(formatted) == 1 and formatted == '?':
        formatted = None
    return formatted


def get_seq_data(sequence, ignore_keys):
    seq_dict = {}
    for seq in sequence:
        for s_key in seq.dir():
            s_val = getattr(seq, s_key, '')
            if type(s_val) is pydicom.uid.UID or s_key in ignore_keys:
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


def validate_timezone(zone):
    # pylint: disable=missing-docstring
    if zone is None:
        zone = tzlocal.get_localzone()
        if not zone:
            zone = pytz.timezone('UTC')
    else:
        try:
            zone = pytz.timezone(zone.zone)
        except pytz.UnknownTimeZoneError:
            zone = None
    return zone


def format_timestamp(date, time, timezone):
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


def dicom_acquisition_date_handler(dicom_ds):
    if dicom_ds.get('AcquisitionDate'):
        pass
    elif dicom_ds.get('SeriesDate'):
        dicom_ds.AcquisitionDate = dicom_ds.get('SeriesDate')
    elif dicom_ds.get('StudyDate'):
        dicom_ds.AcquisitionDate = dicom_ds.get('StudyDate')
    else:
        log.warning('No date found for DICOM file')
    return dicom_ds


def parse_file_dicom_metadata(dicom_ds):
    # Extract the header values
    header = {}
    exclude_tags = ['[Unknown]', 'PixelData', 'Pixel Data',  '[User defined data]', '[Protocol Data Block (compressed)]', '[Histogram tables]', '[Unique image iden]']
    tags = dicom_ds.dir()
    for tag in tags:
        try:
            if (tag not in exclude_tags) and (type(dicom_ds.get(tag)) != pydicom.sequence.Sequence):
                value = dicom_ds.get(tag)
                if value or value == 0: # Some values are zero
                    # Put the value in the header
                    if type(value) == str and len(value) < 10240: # Max pydicom field length
                        header[tag] = format_string(value)
                    else:
                        header[tag] = assign_type(value)
                else:
                    log.debug('No value found for tag: ' + tag)

            if type(dicom_ds.get(tag)) == pydicom.sequence.Sequence:
                seq_data = get_seq_data(dicom_ds.get(tag), exclude_tags)
                # Check that the sequence is not empty
                if seq_data:
                    header[tag] = seq_data
        except:
            log.debug('Failed to get ' + tag)
            pass
    return header


def parse_subject_metadata(dcm):
    subject_dict = dict()
    if hasattr(dcm, 'PatientSex') and get_sex_string(dcm.get('PatientSex')):
        subject_dict['sex'] = get_sex_string(dcm.get('PatientSex'))
    if hasattr(dcm, 'PatientAge') and dcm.get('PatientAge'):
        try:
            age = parse_patient_age(dcm.get('PatientAge'))
            if age:
                subject_dict['age'] = int(age)
        except:
            pass
    if hasattr(dcm, 'PatientName') and dcm.get('PatientName').given_name:
        # If the first name or last name field has a space-separated string, and one or the other field is not
        # present, then we assume that the operator put both first and last names in that one field. We then
        # parse that field to populate first and last name.
        subject_dict['firstname'] = str(format_string(dcm.get('PatientName').given_name))
        if not dcm.get('PatientName').family_name:
            name = format_string(dcm.get('PatientName').given_name.split(' '))
            if len(name) == 2:
                first = name[0]
                last = name[1]
                subject_dict['lastname'] = str(last)
                subject_dict['firstname'] = str(first)
    if hasattr(dcm, 'PatientName') and dcm.get('PatientName').family_name:
        subject_dict['lastname'] = str(format_string(dcm.get('PatientName').family_name))
        if not dcm.get('PatientName').given_name:
            name = format_string(dcm.get('PatientName').family_name.split(' '))
            if len(name) == 2:
                first = name[0]
                last = name[1]
                subject_dict['lastname'] = str(last)
                subject_dict['firstname'] = str(first)
    return subject_dict


def parse_session_dicom_metadata(dicom_ds, timezone):
    session_dict = dict()
    session_timestamp = get_session_timestamp(dicom_ds, timezone)
    session_label = get_session_label(dicom_ds)
    if session_timestamp:
        session_dict['timestamp'] = session_timestamp
    if session_label:
        session_dict['label'] = session_label
    if hasattr(dicom_ds, 'OperatorsName'):
        session_dict['operator'] = format_string(dicom_ds.get('OperatorsName'))
    if hasattr(dicom_ds, 'PatientWeight') and dicom_ds.get('PatientWeight'):
        session_dict['weight'] = assign_type(dicom_ds.get('PatientWeight'))
    session_dict['subject'] = parse_subject_metadata(dicom_ds)
    return session_dict


def parse_acquisition_dicom_metadata(dicom_header_metadata):
    acquisition_dict = dict()
    if dicom_header_metadata.get('Modality'):
        acquisition_dict['instrument'] = dicom_header_metadata.get('Modality')


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