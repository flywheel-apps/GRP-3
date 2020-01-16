import contextlib
import logging
import os
import re
import shutil
import tempfile
import zipfile

from .dicom.dicom_archive import DicomArchive
log = logging.getLogger(__name__)


@contextlib.contextmanager
def make_temp_directory():
    temp_dir = tempfile.mkdtemp()
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir)


def create_zip_from_file_list(root_dir, file_list, output_path, comment=None):
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for fp in file_list:
            zipf.write(fp, os.path.relpath(fp, root_dir))
    return output_path


def contains_embedded_localizer(dicom_archive):
    """
    :param dicom_archive: a DicomArchive object representing a dicom_archive
    :type dicom_archive: DicomArchive
    :return: embedded_localizer
    :rtype bool
    """
    embedded_localizer = False
    iop_value_list = dicom_archive.dicom_tag_value_list('ImageOrientationPatient')
    # Convert to list of tuples so it's hashable for set
    iop_tuple_list = [tuple(iop_val) for iop_val in iop_value_list]
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


def split_archive_on_unique_tag(dicom_archive, dicom_tag, output_dir, append_str, all_unique=True):
    tag_dict = dicom_archive.dicom_tag_value_dict(dicom_tag)
    top_value = max(tag_dict, key=lambda x: len(tag_dict[x]))

    index = 1
    for tag_value, image_paths in tag_dict.items():
        if tag_value == top_value:
            out_path = os.path.join(output_dir, os.path.basename(dicom_archive.path))
            create_zip_from_file_list(dicom_archive.extract_dir, image_paths, out_path)
            if not all_unique:
                out_path = append_str_to_dcm_zip_path(out_path, append_str)
                other_image_paths = [dcm.path for dcm in dicom_archive.dataset_list if dcm.path not in image_paths]
                create_zip_from_file_list(dicom_archive.extract_dir, other_image_paths, out_path)
        elif len(tag_dict.keys()) > 2 and all_unique:

            tmp_append_str = append_str + str(index)
            index += 1
            basename = append_str_to_dcm_zip_path(os.path.basename(dicom_archive.path), tmp_append_str)
            out_path = os.path.join(output_dir, basename)
            create_zip_from_file_list(dicom_archive.extract_dir, image_paths, out_path)
        else:
            continue

