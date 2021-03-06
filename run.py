#!/usr/bin/env python3

import os
import re
import sys
import json
import pytz
import pydicom
from pydicom.datadict import DicomDictionary, tag_for_keyword, get_entry
import string
import tzlocal
import logging
import zipfile
import datetime
import nibabel
import tempfile
from pathlib import Path


from utils.dicom import dicom_archive
from utils.update_file_info import get_file_dict_and_update_metadata_json
from utils.validation import (
    validate_against_rules,
    validate_against_template,
    dump_validation_error_file,
    check_file_is_not_empty,
)

logging.basicConfig()
log = logging.getLogger("grp-3")

DEFAULT_TME = "120000.00"


def fix_VM1_callback(dataset, data_element):
    r"""Update the data element fixing VM based on public tag definition

    This addresses the following none conformance for element with string VR having
    a `\` in the their value which gets interpret as array by pydicom.
    This function re-join string and is aimed to be used as callback.

    From the DICOM Standard, Part 5, Section 6.2, for elements with a VR of LO, such as
    Series Description: A character string that may be padded with leading and/or
    spaces. The character code 5CH (the BACKSLASH "\" in ISO-IR 6) shall not be
    present, as it is used as the delimiter between values in multi-valued data
    elements. The string shall not have Control Characters except for ESC.

    Args:
        dataset (pydicom.DataSet): A pydicom DataSet
        data_element (pydicom.DataElement): A pydicom DataElement from the DataSet

    Returns:
        pydicom.DataElement: An updated pydicom DataElement
    """
    try:
        vr, vm, _, _, _ = get_entry(data_element.tag)
        # Check if it is a VR string
        if (
            vr
            not in [
                "UT",
                "ST",
                "LT",
                "FL",
                "FD",
                "AT",
                "OB",
                "OW",
                "OF",
                "SL",
                "SQ",
                "SS",
                "UL",
                "OB/OW",
                "OW/OB",
                "OB or OW",
                "OW or OB",
                "UN",
            ]
            and "US" not in vr
        ):
            if vm == "1" and hasattr(data_element, "VM") and data_element.VM > 1:
                data_element._value = "\\".join(data_element.value)
    except KeyError:
        # we are only fixing VM for tag supported by get_entry (i.e. DicomDictionary or
        # RepeatersDictionary)
        pass


def validate_dicom(path):
    with tempfile.TemporaryDirectory() as temp_dir:
        dicom_archive.DicomArchive(zip_path=path, extract_dir=temp_dir)


def get_session_label(dcm):
    """
    Switch on manufacturer and either pull out the StudyID or the StudyInstanceUID
    """
    session_label = ""
    if (
        dcm.get("Manufacturer")
        and (
            dcm.get("Manufacturer").find("GE") != -1
            or dcm.get("Manufacturer").find("Philips") != -1
        )
        and dcm.get("StudyID")
    ):
        session_label = dcm.get("StudyID")
    else:
        session_label = dcm.get("StudyInstanceUID")

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
    if age == "None" or not age:
        return None

    conversion = {  # conversion to days
        "Y": 365.25,
        "M": 30,
        "W": 7,
        "D": 1,
    }
    scale = age[-1:]
    value = age[:-1]
    if scale not in conversion.keys():
        # Assume years
        scale = "Y"
        value = age

    age_in_seconds = datetime.timedelta(
        int(value) * conversion.get(scale)
    ).total_seconds()

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
            return timezone.localize(
                datetime.datetime.strptime(date + time[:6], "%Y%m%d%H%M%S"), timezone
            )
        except:
            log.warning("Failed to create timestamp!")
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
        - StudyDate and Time defaults to DEFAULT_TME
        - SeriesDates and Time defaults to DEFAULT_TME
        - AcquisitionDate and Time defaults to DEFAULT_TME

    For acquisition date/time Dicom tag used by order of priority goes like a:
        - SeriesDate/SeriesTime
        - AcquisitionDate/AcquisitionTime
        - AcquisitionDateTime
        - ContentDate/ContentTime
        - StudyDate/StudyTime
        - SeriesDate and Time defaults to DEFAULT_TME
        - AcquisitionDate and Time defaults to DEFAULT_TME
        - StudyDate and Time defaults to DEFAULT_TME
    """
    # Study Date and Time, with precedence as below
    if getattr(dcm, "StudyDate", None) and getattr(dcm, "StudyTime", None):
        study_date = dcm.StudyDate
        study_time = dcm.StudyTime
    elif getattr(dcm, "SeriesDate", None) and getattr(dcm, "SeriesTime", None):
        study_date = dcm.SeriesDate
        study_time = dcm.SeriesTime
    elif getattr(dcm, "AcquisitionDate", None) and getattr(
        dcm, "AcquisitionTime", None
    ):
        study_date = dcm.AcquisitionDate
        study_time = dcm.AcquisitionTime
    elif getattr(dcm, "AcquisitionDateTime", None):
        study_date = dcm.AcquisitionDateTime[0:8]
        study_time = dcm.AcquisitionDateTime[8:]
    # If only Dates are available setting time to 00:00
    elif getattr(dcm, "StudyDate", None):
        study_date = dcm.StudyDate
        study_time = DEFAULT_TME
    elif getattr(dcm, "SeriesDate", None):
        study_date = dcm.SeriesDate
        study_time = DEFAULT_TME
    elif getattr(dcm, "AcquisitionDate", None):
        study_date = dcm.AcquisitionDate
        study_time = DEFAULT_TME
    else:
        study_date = None
        study_time = None

    # Acquisition Date and Time, with precedence as below
    if getattr(dcm, "SeriesDate", None) and getattr(dcm, "SeriesTime", None):
        acquisition_date = dcm.SeriesDate
        acquisition_time = dcm.SeriesTime
    elif getattr(dcm, "AcquisitionDate", None) and getattr(
        dcm, "AcquisitionTime", None
    ):
        acquisition_date = dcm.AcquisitionDate
        acquisition_time = dcm.AcquisitionTime
    elif getattr(dcm, "AcquisitionDateTime", None):
        acquisition_date = dcm.AcquisitionDateTime[0:8]
        acquisition_time = dcm.AcquisitionDateTime[8:]
    # The following allows the timestamps to be set for ScreenSaves
    elif getattr(dcm, "ContentDate", None) and getattr(dcm, "ContentTime", None):
        acquisition_date = dcm.ContentDate
        acquisition_time = dcm.ContentTime
    # Looking deeper if nothing found so far
    elif getattr(dcm, "StudyDate", None) and getattr(dcm, "StudyTime", None):
        acquisition_date = dcm.StudyDate
        acquisition_time = dcm.StudyTime
    # If only Dates are available setting time to 00:00
    elif getattr(dcm, "SeriesDate", None):
        acquisition_date = dcm.SeriesDate
        acquisition_time = DEFAULT_TME
    elif getattr(dcm, "AcquisitionDate", None):
        acquisition_date = dcm.AcquisitionDate
        acquisition_time = DEFAULT_TME
    elif getattr(dcm, "StudyDate", None):
        acquisition_date = dcm.StudyDate
        acquisition_time = DEFAULT_TME

    else:
        acquisition_date = None
        acquisition_time = None

    session_timestamp = timestamp(study_date, study_time, timezone)
    acquisition_timestamp = timestamp(acquisition_date, acquisition_time, timezone)

    if session_timestamp:
        if session_timestamp.tzinfo is None:
            log.info("no tzinfo found, using UTC...")
            session_timestamp = pytz.timezone("UTC").localize(session_timestamp)
        session_timestamp = session_timestamp.isoformat()
    else:
        session_timestamp = ""
    if acquisition_timestamp:
        if acquisition_timestamp.tzinfo is None:
            log.info("no tzinfo found, using UTC")
            acquisition_timestamp = pytz.timezone("UTC").localize(acquisition_timestamp)
        acquisition_timestamp = acquisition_timestamp.isoformat()
    else:
        acquisition_timestamp = ""
    return session_timestamp, acquisition_timestamp


def get_sex_string(sex_str):
    """
    Return male or female string.
    """
    if sex_str == "M":
        sex = "male"
    elif sex_str == "F":
        sex = "female"
    else:
        sex = ""
    return sex


def assign_type(s):
    """
    Sets the type of a given input.
    """
    if type(s) == pydicom.valuerep.PersonName:
        return format_string(s)
    if type(s) == list or type(s) == pydicom.multival.MultiValue:
        try:
            return [float(x) for x in s]
        except ValueError:
            try:
                return [int(x) for x in s]
            except ValueError:
                return [format_string(x) for x in s if len(x) > 0]
    elif type(s) == float or type(s) == int:
        return s
    elif type(s) == pydicom.uid.UID:
        s = str(s)
        return format_string(s)
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
    formatted = re.sub(
        r"[^\x00-\x7f]", r"", str(in_string)
    )  # Remove non-ascii characters
    formatted = "".join(filter(lambda x: x in string.printable, formatted))
    if len(formatted) == 1 and formatted == "?":
        formatted = None
    return formatted  # .encode('utf-8').strip()


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
            if (
                not hasattr(v, "keyword")
                or (hasattr(v, "keyword") and v.keyword in ignore_keys)
                or (hasattr(v, "keyword") and not v.keyword)
            ):  # keyword of type "" for unknown tags
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


def walk_dicom(dcm, callbacks=None, recursive=True):
    """Same as pydicom.DataSet.walk but with logging the exception instead of raising.

    Args:
        dcm (pydicom.DataSet): A pydicom.DataSet.
        callbacks (list): A list of function to apply on each DataElement of the
            DataSet (default = None).
        recursive (bool): It True, walk the dicom recursively when encountering a SQ.

    Returns:
        list: List of errors
    """
    taglist = sorted(dcm._dict.keys())
    errors = []
    for tag in taglist:
        try:
            data_element = dcm[tag]
            if callbacks:
                for cb in callbacks:
                    cb(dcm, data_element)
            if recursive and tag in dcm and data_element.VR == "SQ":
                sequence = data_element.value
                for dataset in sequence:
                    walk_dicom(dataset, callbacks, recursive=recursive)
        except Exception as ex:
            msg = f"With tag {tag} got exception: {str(ex)}"
            errors.append(msg)
    return errors


def fix_type_based_on_dicom_vm(header):
    exc_keys = []
    for key, val in header.items():
        try:
            vr, vm, _, _, _ = DicomDictionary.get(tag_for_keyword(key))
        except (ValueError, TypeError):
            exc_keys.append(key)
            continue

        if vr != "SQ":
            if vm != "1" and not isinstance(val, list):  # anything else is a list
                header[key] = [val]
        elif not isinstance(val, list):
            # To deal with DataElement that pydicom did not read as sequence
            # (e.g. stored as OB and pydicom parsing them as binary string)
            exc_keys.append(key)
        else:
            for dataset in val:
                fix_type_based_on_dicom_vm(dataset)
    if len(exc_keys) > 0:
        log.warning(
            "%s Dicom data elements were not type fixed based on VM", len(exc_keys)
        )


def get_pydicom_header(dcm):
    # Extract the header values
    # Load all dcm tags in memory and fix an issue found a LO VR with `\` in it (fix_VM1)
    errors = walk_dicom(dcm, callbacks=[fix_VM1_callback], recursive=True)
    # dcm.walk(fix_VM1, recursive=True)
    if errors:
        result = ""
        for error in errors:
            result += "\n  {}".format(error)
        log.warning(f"Errors found in walking dicom: {result}")
    header = {}
    exclude_tags = [
        "[Unknown]",
        "PixelData",
        "Pixel Data",
        "[User defined data]",
        "[Protocol Data Block (compressed)]",
        "[Histogram tables]",
        "[Unique image iden]",
        "ContourData",
        "EncryptedAttributesSequence",
    ]
    tags = dcm.dir()
    for tag in tags:
        try:
            if (tag not in exclude_tags) and (
                type(dcm.get(tag)) != pydicom.sequence.Sequence
            ):
                value = dcm.get(tag)
                if value or value == 0:  # Some values are zero
                    # Put the value in the header
                    if (
                        type(value) == str and len(value) < 10240
                    ):  # Max pydicom field length
                        header[tag] = format_string(value)
                    else:
                        header[tag] = assign_type(value)

                else:
                    log.debug("No value found for tag: " + tag)

            if (tag not in exclude_tags) and type(
                dcm.get(tag)
            ) == pydicom.sequence.Sequence:
                seq_data = get_seq_data(dcm.get(tag), exclude_tags)
                # Check that the sequence is not empty
                if seq_data:
                    header[tag] = seq_data
        except:
            log.debug("Failed to get " + tag)
            pass

    fix_type_based_on_dicom_vm(header)

    return header


def get_csa_header(dcm):
    exclude_tags = ["PhoenixZIP", "SrMsgBuffer"]
    header = {}
    try:
        raw_csa_header = nibabel.nicom.dicomwrappers.SiemensWrapper(dcm).csa_header
        tags = raw_csa_header["tags"]
    except:
        log.warning("Failed to parse csa header!")
        return header

    for tag in tags:
        if not raw_csa_header["tags"][tag]["items"] or tag in exclude_tags:
            log.debug("Skipping : %s" % tag)
            pass
        else:
            value = raw_csa_header["tags"][tag]["items"]
            if len(value) == 1:
                value = value[0]
                if type(value) == str and (len(value) > 0 and len(value) < 1024):
                    header[format_string(tag)] = format_string(value)
                else:
                    header[format_string(tag)] = assign_type(value)
            else:
                header[format_string(tag)] = assign_type(value)

    return header


def dicom_date_handler(dcm):
    if dcm.get("AcquisitionDate"):
        pass
    elif dcm.get("SeriesDate"):
        dcm.AcquisitionDate = dcm.get("SeriesDate")
    elif dcm.get("StudyDate"):
        dcm.AcquisitionDate = dcm.get("StudyDate")
    else:
        log.warning("No date found for DICOM file")
    return dcm


def get_dcm_data_dict(dcm_path, force=False):
    file_size = os.path.getsize(dcm_path)
    res = {
        "path": dcm_path,
        "size": file_size,
        "force": force,
        "pydicom_exception": False,
        "header": {},
    }
    if file_size > 0:
        try:
            dcm = pydicom.dcmread(dcm_path, force=force, stop_before_pixels=True)
            res["header"] = get_pydicom_header(dcm)
        except Exception:
            log.exception(
                "Pydicom raised exception reading dicom file %s",
                os.path.basename(dcm_path),
            )
            res["pydicom_exception"] = True
    return res


def dicom_to_json(file_path, outbase, timezone, json_template, force=False):

    error_file_name = os.path.basename(file_path) + ".error.log.json"
    error_filepath = os.path.join(outbase, error_file_name)
    validation_errors = list()

    # check that input file is not empty
    validation_errors += check_file_is_not_empty(file_path)
    if validation_errors:
        log.warning(
            "File %s is empty which warrants further processing. Logging to error.json and Exiting.",
            file_path,
        )
        dump_validation_error_file(error_filepath, validation_errors)
        sys.exit(1)

    # Build list of dcm files
    if zipfile.is_zipfile(file_path):
        try:
            log.info("Extracting %s " % os.path.basename(file_path))
            zip = zipfile.ZipFile(file_path)
            tmp_dir = tempfile.TemporaryDirectory().name
            zip.extractall(path=tmp_dir)
            dcm_path_list = sorted(Path(tmp_dir).rglob("*"))
            # keep only files
            dcm_path_list = [
                str(path) for path in dcm_path_list if os.path.isfile(path)
            ]
        except Exception:
            log.warning(
                "Zip file %s is corrupted. Logging to error.json and Exiting.",
                file_path,
            )
            error_dict = {"error_message": "Zip corrupted", "revalidate": False}
            dump_validation_error_file(error_filepath, [error_dict])
            sys.exit(1)
    else:
        log.info(
            "Not a zip. Attempting to read %s directly" % os.path.basename(file_path)
        )
        dcm_path_list = [file_path]

    # Get list of Dicom data dict (with keys path, size, header)
    dcm_dict_list = []
    for dcm_path in dcm_path_list:
        dcm_dict_list.append(get_dcm_data_dict(dcm_path, force=force))

    # Load a representative dcm file
    # Currently: not 0-byte file and SOPClassUID not Raw Data Storage unless that the only file
    dcm = None
    log.info("Selecting a valid Dicom file for parsing")
    for idx, dcm_dict_el in enumerate(dcm_dict_list):
        if (
            dcm_dict_el["size"] > 0
            and dcm_dict_el["header"]
            and not dcm_dict_el["pydicom_exception"]
        ):
            # Here we check for the Raw Data Storage SOP Class, if there
            # are other pydicom files in the zip then we read the next one,
            # if this is the only class of pydicom in the file, we accept
            # our fate and move on.
            if (
                dcm_dict_el["header"].get("SOPClassUID") == "Raw Data Storage"
                and idx < len(dcm_dict_list) - 1
            ):
                log.warning(
                    "SOPClassUID=Raw Data Storage for %s. Skipping", dcm_dict_el["path"]
                )
                continue
            else:
                # Note: no need to try/except, all files have already been open when calling get_dcm_data_dict
                dcm_path = dcm_dict_el["path"]
                dcm = pydicom.dcmread(dcm_path, force=force)
                break
        elif dcm_dict_el["size"] < 1:
            log.warning("%s is empty. Skipping.", os.path.basename(dcm_dict_el["path"]))
        elif dcm_dict_el["pydicom_exception"]:
            log.warning(
                "Pydicom raised on reading %s. Skipping.",
                os.path.basename(dcm_dict_el["path"]),
            )
    if not dcm:
        log.warning("No Dicom file found to be parsed!!!")
        error_dict = {
            "error_message": "No Dicom file found to be parsed",
            "revalidate": False,
        }
        dump_validation_error_file(error_filepath, [error_dict])
        sys.exit(1)
    else:
        log.info("%s will be used for metadata extraction", os.path.basename(dcm_path))

    # Build metadata
    metadata = {}

    # Session metadata
    metadata["session"] = {}
    session_timestamp, acquisition_timestamp = get_timestamp(dcm, timezone)
    if session_timestamp:
        metadata["session"]["timestamp"] = session_timestamp
    if hasattr(dcm, "OperatorsName") and dcm.get("OperatorsName"):
        metadata["session"]["operator"] = format_string(dcm.get("OperatorsName"))
    session_label = get_session_label(dcm)
    if session_label:
        metadata["session"]["label"] = session_label
    if hasattr(dcm, "PatientWeight") and dcm.get("PatientWeight"):
        patient_weight = assign_type(dcm.get("PatientWeight"))
        if isinstance(
            patient_weight, (int, float)
        ):  # PatientWeight VR is DS (decimal string)
            # assign_type manages to cast it to numeric
            metadata["session"]["weight"] = patient_weight
        else:
            log.warning(
                "PatientWeight not a numeric (%s). Will not be stored in session metadata.",
                patient_weight,
            )

    # Subject Metadata
    metadata["session"]["subject"] = {}
    if hasattr(dcm, "PatientSex") and get_sex_string(dcm.get("PatientSex")):
        metadata["session"]["subject"]["sex"] = get_sex_string(dcm.get("PatientSex"))
    if hasattr(dcm, "PatientAge") and dcm.get("PatientAge"):
        try:
            age = parse_patient_age(dcm.get("PatientAge"))
            if age:
                metadata["session"]["subject"]["age"] = int(age)
        except:
            pass
    if hasattr(dcm, "PatientName"):
        if hasattr(dcm.get("PatientName"), "given_name") and hasattr(
            dcm.get("PatientName"), "family_name"
        ):
            # If the first name or last name field has a space-separated string, and one or the other field is not
            # present, then we assume that the operator put both first and last names in that one field. We then
            # parse that field to populate first and last name.
            if dcm.get("PatientName").given_name:
                metadata["session"]["subject"]["firstname"] = str(
                    format_string(dcm.get("PatientName").given_name)
                )
                if not dcm.get("PatientName").family_name:
                    name = format_string(dcm.get("PatientName").given_name.split(" "))
                    if len(name) == 2:
                        first = name[0]
                        last = name[1]
                        metadata["session"]["subject"]["lastname"] = str(last)
                        metadata["session"]["subject"]["firstname"] = str(first)
            if dcm.get("PatientName").family_name:
                metadata["session"]["subject"]["lastname"] = str(
                    format_string(dcm.get("PatientName").family_name)
                )
                if not dcm.get("PatientName").given_name:
                    name = format_string(dcm.get("PatientName").family_name.split(" "))
                    if len(name) == 2:
                        first = name[0]
                        last = name[1]
                        metadata["session"]["subject"]["lastname"] = str(last)
                        metadata["session"]["subject"]["firstname"] = str(first)

    # File metadata
    pydicom_file = {}
    pydicom_file["name"] = os.path.basename(file_path)
    if dcm.get('Modality'):
        pydicom_file["modality"] = format_string(dcm.get("Modality"))
    else:
        log.warning('No modality found.')
        pydicom_file["modality"] = None

    pydicom_file["info"] = {"header": {"dicom": {}}}

    # Acquisition metadata
    metadata["acquisition"] = {}
    if hasattr(dcm, "Modality") and dcm.get("Modality"):
        metadata["acquisition"]["instrument"] = format_string(dcm.get("Modality"))

    series_desc = format_string(dcm.get("SeriesDescription", ""))
    if series_desc:
        metadata["acquisition"]["label"] = series_desc

    if acquisition_timestamp:
        metadata["acquisition"]["timestamp"] = acquisition_timestamp

    # File metadata from pydicom header
    pydicom_file["info"]["header"]["dicom"] = get_pydicom_header(dcm)

    # Add CSAHeader to DICOM
    if dcm.get("Manufacturer") == "SIEMENS":
        csa_header = get_csa_header(dcm)
        if csa_header:
            pydicom_file["info"]["header"]["dicom"]["CSAHeader"] = csa_header

    # Validate header data against json schema template
    validation_errors += validate_against_template(
        pydicom_file["info"]["header"]["dicom"], json_template
    )

    # Validate DICOM header df against file rules
    rule_errors = validate_against_rules(dcm_dict_list)

    # Add error lists together
    validation_errors = validation_errors + rule_errors

    # Write error file
    if validation_errors:
        dump_validation_error_file(error_filepath, validation_errors)
    if validation_errors:
        metadata["acquisition"]["tags"] = ["error"]

    # Append the pydicom_file to the files array
    metadata["acquisition"]["files"] = [pydicom_file]

    # Write out the metadata to file (.metadata.json)
    metafile_outname = os.path.join(os.path.dirname(outbase), ".metadata.json")
    print_string = json.dumps(
        metadata, separators=(", ", ": "), sort_keys=True, indent=4
    )
    log.info("DICOM .metadata.json: \n%s\n", print_string)
    with open(metafile_outname, "w") as metafile:
        json.dump(metadata, metafile, separators=(", ", ": "), sort_keys=True, indent=4)

    return metafile_outname


def split_embedded_localizer(dcm_archive_path, output_dir, force=False):
    with dicom_archive.make_temp_directory() as tmp_dir:
        dcm_archive_obj = dicom_archive.DicomArchive(
            dcm_archive_path, tmp_dir, dataset_list=True, force=force
        )
        if dcm_archive_obj.contains_embedded_localizer():
            log.info("Splitting embedded localizer...")
            dcm_archive_obj.split_archive_on_unique_tag(
                "ImageOrientationPatient", output_dir, "_Localizer", all_unique=False
            )
            # Exit - gear rule should pick up new files and extract+Validate
            log.info(
                "Embedded localizer split! Please run this gear on the output dicom archives if a gear rule is not set!"
            )
            get_file_dict_and_update_metadata_json("dicom", output_filepath)
            os.sys.exit(0)


def split_seriesinstanceUID(dcm_archive_path, output_dir, force=False):
    with dicom_archive.make_temp_directory() as tmp_dir:
        dcm_archive_obj = dicom_archive.DicomArchive(
            dcm_archive_path, tmp_dir, dataset_list=True, force=force
        )
        if dcm_archive_obj.contains_different_seriesinstanceUID():
            log.info("Splitting embedded Series...")
            dcm_archive_obj.split_archive_on_unique_tag(
                "SeriesInstanceUID", output_dir, "", all_unique=True
            )
            # Exit - gear rule should pick up new files and extract+Validate
            log.info(
                "SeriesInstanceUID split! Please run this gear on the output dicom archives if a gear rule is not set!"
            )
            get_file_dict_and_update_metadata_json("dicom", output_filepath)
            os.sys.exit(0)


if __name__ == "__main__":
    # Set paths
    input_folder = "/flywheel/v0/input/file/"
    output_folder = "/flywheel/v0/output/"
    config_file_path = "/flywheel/v0/config.json"
    output_filepath = os.path.join(output_folder, ".metadata.json")

    # Load config file
    with open(config_file_path) as config_data:
        config = json.load(config_data)

    debug = config.get("config").get("debug")
    root_logger = logging.getLogger()
    if debug:
        root_logger.setLevel(logging.DEBUG)
    else:
        root_logger.setLevel(logging.INFO)

    # Get config values
    split_localizer = config["config"]["split_localizer"]
    split_on_seriesuid = config["config"]["split_on_SeriesUID"]
    force_dicom_read = config["config"]["force_dicom_read"]
    # Set dicom path and name from config file
    dicom_filepath = config["inputs"]["dicom"]["location"]["path"]
    dicom_name = config["inputs"]["dicom"]["location"]["name"]

    # Check that input is DICOM
    validate_dicom(dicom_filepath)
    # Set template json filepath (if provided)
    if config["inputs"].get("json_template"):
        template_filepath = config["inputs"]["json_template"]["location"]["path"]
    else:
        template_filepath = None

    # Determine the level from which the gear was invoked
    hierarchy_level = config["inputs"]["dicom"]["hierarchy"]["type"]

    # Split seriesinstanceUID
    if split_on_seriesuid:
        try:
            split_seriesinstanceUID(dicom_filepath, output_folder, force_dicom_read)

        except Exception as err:
            log.error(
                "split_seriesinstanceUID failed! err={}".format(err), exc_info=True
            )

    # Split embedded localizers if configured to do so and if the
    # Dicom archive is a series that contains an embedded localizer
    if split_localizer:
        try:
            split_embedded_localizer(dicom_filepath, output_folder, force_dicom_read)

        except Exception as err:
            log.error(
                "split_embedded_localizer failed! err={}".format(err), exc_info=True
            )

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

    metadatafile = dicom_to_json(
        dicom_filepath, output_folder, timezone, json_template, force=force_dicom_read
    )

    get_file_dict_and_update_metadata_json("dicom", metadatafile)

    if os.path.isfile(metadatafile):
        os.sys.exit(0)
