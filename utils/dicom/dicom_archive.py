import collections
import contextlib
import logging
import os
import numpy as np
import re
import shutil
import tempfile
import zipfile

import pydicom
from pydicom.multival import MultiValue

from .dicom_metadata import get_pydicom_header

log = logging.getLogger(__name__)

TOLERANCE_ON_ImageOrientationPatient = 3
SERIES_DESCRIPTION_SANITIZER = r'[^A-Za-z0-9\+]+'


@contextlib.contextmanager
def make_temp_directory():
    temp_dir = tempfile.mkdtemp()
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir)


def make_list_items_hashable(input_list):
    output_list = list()
    for item in input_list:
        if not isinstance(item, collections.abc.Hashable):
            item = tuple(item)
        output_list.append(item)
    return output_list


def create_zip_from_file_list(root_dir, file_list, output_path, comment=None):
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for fp in file_list:
            zipf.write(fp, os.path.relpath(fp, root_dir))
    return output_path


def append_str_to_dcm_zip_path(dcm_zip_path, append_str):
    if re.match(r'(.*)((\.dicom\.zip)|(\.dcm\.zip))', dcm_zip_path):
        out_path = re.sub(r'(.*)((\.dicom\.zip)|(\.dcm\.zip))', f'\\1{append_str}\\2', dcm_zip_path)
    elif re.match(r'(.*)(\.zip)', dcm_zip_path):
        out_path = re.sub(r'(.*)(\.zip)', f'\\1{append_str}\\2', dcm_zip_path)
    else:
        out_path = dcm_zip_path + append_str
        log.warning(
            'Did not recognize a standard extension for DICOM '
            f'archive for {os.path.basename(dcm_zip_path)}. '
            f'using {out_path}'
        )
    return out_path


def extract_files(zip_path, output_directory):
    """
    extracts the files in a zip to an output directory
    :param zip_path: path to the zip to extract
    :param output_directory: directory to which to extract the files
    :return: file_list, a list to the paths of the extracted files and comment, the archive comment
    """
    with zipfile.ZipFile(zip_path, 'r') as zipf:
        zipf.extractall(output_directory)
        file_list = zipf.namelist()
        # Get full paths and remove directories from list
        file_list = [os.path.join(output_directory, fp) for fp in file_list if not fp.endswith(os.path.sep)]

    return file_list


class DicomFile:
    def __init__(self, file_path, root_path, force=False):
        self.path = file_path
        self.relpath = os.path.relpath(file_path, root_path)
        filename = os.path.basename(file_path)
        try:
            self.dataset = pydicom.dcmread(file_path, force=force)

        except Exception as e:
            log.error(f'Exception occurred when reading {filename}: {e}')
            self.dataset = None
        try:
            self.header_dict = get_pydicom_header(self.dataset)
        except Exception as e:
            log.error(f'Exception occurred when parsing header for  {filename}: {e}')
            self.header_dict = None


class DicomArchive:
    def __init__(self, zip_path, extract_dir, dataset_list=False, force=False, validate=True):
        self.path = zip_path
        self.dataset = None
        self.dataset_list = None
        self.extract_dir = extract_dir
        self.force = force
        if zipfile.is_zipfile(self.path):
            with zipfile.ZipFile(self.path) as zipf:
                file_list = zipf.namelist()
                # Get full paths and remove directories from list
                self.file_list = [fp for fp in file_list if not fp.endswith(os.path.sep)]
        else:
            log.info(f'{self.path} is not a zip')
            self.file_list = [self.path]
        try:
            self.initialize_dataset(dataset_list=dataset_list)
        except Exception as e:
            log.error(f'An exception occurred while parsing {zip_path}: {e}')
        if validate:
            self._validate()

    def _validate(self):
        basename = os.path.basename(self.path)
        if not os.path.exists(self.path):
            error_detail = f'File {basename} does not exist! Exiting...'
            raise FileNotFoundError(error_detail)
        elif not self.file_list:
            error_detail = f'No files were found within archive {basename}! Exiting...'
            raise RuntimeError(error_detail)
        elif not self.dataset:
            error_detail = f'failed to parse DICOMs at {basename}. File list: {self.file_list}. Exiting...'
            raise RuntimeError(error_detail)
        return None

    def initialize_dataset(self, dataset_list=False):
        if dataset_list:
            self.dataset_list = list()
        if zipfile.is_zipfile(self.path):
            for fp in self.file_list:
                with zipfile.ZipFile(self.path) as zipf:
                    extract_path = zipf.extract(fp, self.extract_dir)
                    if os.path.isfile(extract_path):
                        dicom_file = DicomFile(extract_path, self.extract_dir, force=self.force)
                        file_dataset = dicom_file.dataset
                        if file_dataset:
                            # Here we check for the Raw Data Storage SOP Class, if there
                            # are other pydicom files in the zip then we read the next one,
                            # if this is the only class of pydicom in the file, we accept
                            # our fate and move on.
                            if file_dataset.get('SOPClassUID') == 'Raw Data Storage' and not self.dataset:
                                log.info(f'{os.path.basename(fp)} is Raw Data Storage. Skipping...')
                                continue
                            if dataset_list:
                                self.dataset_list.append(dicom_file)
                                if not self.dataset:
                                    self.dataset = file_dataset
                            else:
                                self.dataset = file_dataset
                                break
        elif os.path.isfile(self.path):
            dicom_file = DicomFile(self.path, os.path.dirname(self.path), self.force)
            file_dataset = dicom_file.dataset
            if file_dataset:
                self.dataset = file_dataset
                if dataset_list:
                    self.dataset_list.append(dicom_file)

    def dicom_tag_value_list(self, dicom_tag):

        if not self.dataset_list:
            self.initialize_dataset(dataset_list=True)

        if not self.dataset.get(dicom_tag):
            log.warning(f'{dicom_tag} is missing from {os.path.basename(self.path)}')
        value_list = [dicom_file.dataset.get(dicom_tag) for dicom_file in self.dataset_list]

        return value_list

    def dicom_tag_value_dict(self, dicom_tag):
        if not self.dataset_list:
            self.initialize_dataset(self.extract_dir)

        value_dict = dict()

        if dicom_tag == 'ImageOrientationPatient':
            # Store means of IOP across archive
            iop_means = DicomArchive._iop_means(self.dicom_tag_value_list('ImageOrientationPatient'))

        for dicom_file in self.dataset_list:
            tag_value = dicom_file.header_dict.get(dicom_tag)
            if tag_value:
                if type(tag_value) == list:
                    if dicom_tag == 'ImageOrientationPatient':  # rounding a little to avoid dropping images
                        # Subtract mean in order to prevent rounding errors close to the rounding cutoff.
                        # around uses a cutoff of the decimal .5, so If we use a three decimal rounding, the 
                        # cutoff is .0005, i.e. .0005 rounds down to 0.000, but .000501 rounds up to .001
                        # Removing the mean before rounding reduces the likelihood that this could happen since
                        # The mean should be very close to 0, and the localizer should be the only one that isn't at 0.
                        tag_value_key = tuple(
                            np.around(np.array(tag_value) - iop_means,
                            decimals=TOLERANCE_ON_ImageOrientationPatient).tolist())
                    else:
                        tag_value_key = tuple(tag_value)
                else:
                    tag_value_key = tag_value
            else:
                tag_value_key = 'NA'
            if not value_dict.get(tag_value_key):
                value_dict[tag_value_key] = list()
            value_dict[tag_value_key].append(dicom_file.path)

        return value_dict

    def split_archive_on_unique_tag(self, dicom_tag, output_dir, append_str, all_unique=True):

        if not self.dataset.get(dicom_tag):
            log.warning(f'{dicom_tag} is missing from {os.path.basename(self.path)}')

        tag_dict = self.dicom_tag_value_dict(dicom_tag)
        top_value = max(tag_dict, key=lambda x: len(tag_dict[x]))

        index = 1
        for tag_value, image_paths in tag_dict.items():
            if tag_value == top_value:
                out_path = os.path.join(output_dir, os.path.basename(self.path))
                create_zip_from_file_list(self.extract_dir, image_paths, out_path)
                if len(tag_dict.keys()) == 2 and not all_unique:
                    other_image_paths = [dcm.path for dcm in self.dataset_list if dcm.path not in image_paths]
                    if not append_str:
                        dcm = pydicom.dcmread(other_image_paths[0])
                        sd_safe = re.sub(SERIES_DESCRIPTION_SANITIZER, '_', dcm.SeriesDescription)
                        app_str = f'_{dcm.Modality}-{dcm.SeriesNumber}-{sd_safe}'
                    else:
                        app_str = append_str
                    out_path = append_str_to_dcm_zip_path(out_path, app_str)
                    log.info('Creating {out_path}...')
                    create_zip_from_file_list(self.extract_dir, other_image_paths, out_path)
            elif len(tag_dict.keys()) >= 2 and all_unique:
                if not append_str:
                    dcm = pydicom.dcmread(image_paths[0])
                    sd_safe = re.sub(SERIES_DESCRIPTION_SANITIZER, '_', dcm.SeriesDescription)
                    tmp_append_str = f'_{dcm.Modality}-{dcm.SeriesNumber}-{sd_safe}'
                else:
                    app_str = append_str
                    tmp_append_str = app_str + str(index)
                    index += 1
                basename = append_str_to_dcm_zip_path(os.path.basename(self.path), tmp_append_str)
                out_path = os.path.join(output_dir, basename)
                log.info('Creating {out_path}...')
                create_zip_from_file_list(self.extract_dir, image_paths, out_path)
            else:
                continue

    @staticmethod
    def _iop_means(iop_val_list):
        # Return means of image orientation patient across the archive
        return np.mean(np.array(iop_val_list),axis=0)

    @staticmethod
    def _round_iop(iop_val_list):
        # Apply some rounding
        # NOTE: It has been observed that, in some series, ImageOrientationPatient might be
        # slightly varying between slices even though the patient orientation remains the same (uncertain root cause).
        # If strictly splitting on ImageOrientationPatient "uniqueness" it leads in wrongly creating multiple series.

        # This method subtracts the mean across the archive from each coordinate of ImageOrientationPatient
        # Then rounds to the number of decimal points specified in TOLERANCE_ON_ImageOrientationPatient
        iop_arr = np.array(iop_val_list)
        iop_arr = iop_arr - np.mean(iop_arr,axis=0)
        iop_arr_rounded = np.around(iop_arr, decimals=TOLERANCE_ON_ImageOrientationPatient)
        return iop_arr_rounded

    def contains_embedded_localizer(self):
        embedded_localizer = False
        iop_value_list = self.dicom_tag_value_list('ImageOrientationPatient')
        # Convert to list of tuples so it's hashable for set
        iop_tuple_list = make_list_items_hashable(iop_value_list)
        iop_tuple_list = [x for x in iop_tuple_list if x]   # removing None
        if not iop_tuple_list:
            log.warning('Dicom ImageOrientationPatient tag missing, skipping localizer splitting')
            return embedded_localizer

        rounded_iops = DicomArchive._round_iop(iop_tuple_list)
        unique_iops = np.unique(rounded_iops,axis=0)

        image_count = rounded_iops.shape[0]
        nunique_iop = unique_iops.shape[0]
        # If there's more than one unique IOP, it's a localizer
        if nunique_iop > 1:
            # Only a scan series with embedded localizer if the number of unique IOP
            # values/ total images is less than 0.20
            if (nunique_iop / image_count) < 0.20:
                embedded_localizer = True
        return embedded_localizer

    def contains_different_seriesinstanceUID(self):
        different_siuid = False
        siuid_value_list = self.dicom_tag_value_list('SeriesInstanceUID')
        # Convert to list of tuples so it's hashable for set
        siuid_tuple_list = make_list_items_hashable(siuid_value_list)
        m_tuple_set = set(siuid_tuple_list)
        nunique_iop = len(m_tuple_set)
        if nunique_iop > 1:
            different_siuid = True
            log.warning('Multiple () SeriesInstanceUID found in archive')
        return different_siuid

    def select_files_by_tag_value(self, dicom_tag, value):
        if not self.dataset_list:
            self.initialize_dataset(self.extract_dir)

        if not self.dataset.get(dicom_tag):
            log.error(f'{dicom_tag} is missing from {os.path.basename(self.path)}')

        else:
            match_list = list()
            not_match_list = list()
            for dicom_file in self.dataset_list:
                if dicom_file.header_dict.get(dicom_tag) == value:

                    match_list.append(dicom_file)
                else:
                    not_match_list.append(dicom_file)
            return match_list, not_match_list
