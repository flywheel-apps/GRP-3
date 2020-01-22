import collections
import contextlib
import logging
import os
import re
import shutil
import tempfile
import zipfile

import pydicom
from pydicom.multival import MultiValue

from .dicom_metadata import get_pydicom_header

log = logging.getLogger(__name__)


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
        try:
            self.dataset = pydicom.dcmread(file_path, force=force)
            self.header_dict = get_pydicom_header(self.dataset)
        except Exception as e:
            filename = os.path.basename(file_path)
            log.error(f'Exception occurred when reading {filename}: {e}')


class DicomArchive:
    def __init__(self, zip_path, extract_dir, dataset_list=False, force=False):
        self.path = zip_path
        self.dataset = None
        self.dataset_list = None
        self.extract_dir = extract_dir
        self.force = force

        with zipfile.ZipFile(self.path) as zipf:
            file_list = zipf.namelist()
            # Get full paths and remove directories from list
            self.file_list = [fp for fp in file_list if not fp.endswith(os.path.sep)]
        try:
            self.initialize_dataset(dataset_list=dataset_list)
        except Exception as e:
            log.error(f'An exception occurred while parsing {zip_path}: {e}')

    def initialize_dataset(self, dataset_list=False):
        if dataset_list:
            self.dataset_list = list()
        for fp in self.file_list:
            with zipfile.ZipFile(self.path) as zipf:
                extract_path = zipf.extract(fp, self.extract_dir)
                if os.path.isfile(extract_path):
                    dicom_file = DicomFile(extract_path, self.extract_dir, self.force)
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
        for dicom_file in self.dataset_list:
            tag_value = dicom_file.header_dict.get(dicom_tag)
            if tag_value:
                if type(tag_value) == list:
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
                if not all_unique:
                    out_path = append_str_to_dcm_zip_path(out_path, append_str)
                    other_image_paths = [dcm.path for dcm in self.dataset_list if dcm.path not in image_paths]
                    create_zip_from_file_list(self.extract_dir, other_image_paths, out_path)
            elif len(tag_dict.keys()) > 2 and all_unique:

                tmp_append_str = append_str + str(index)
                index += 1
                basename = append_str_to_dcm_zip_path(os.path.basename(self.path), tmp_append_str)
                out_path = os.path.join(output_dir, basename)
                create_zip_from_file_list(self.extract_dir, image_paths, out_path)
            else:
                continue

    def contains_embedded_localizer(self):
        embedded_localizer = False
        iop_value_list = self.dicom_tag_value_list('ImageOrientationPatient')
        # Convert to list of tuples so it's hashable for set
        iop_tuple_list = make_list_items_hashable(iop_value_list)
        image_count = len(iop_tuple_list)
        iop_tuple_set = set(iop_tuple_list)
        nunique_iop = len(iop_tuple_set)
        # If there's more than one unique IOP, it's a localizer
        if nunique_iop > 1:
            # Only a scan series with embedded localizer if the number of unique IOP
            # values/ total images is less than 0.20
            if (nunique_iop / image_count) < 0.20:
                embedded_localizer = True
        return embedded_localizer

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
