import pytest
import os
import shutil
from pathlib import Path

import pydicom
from pydicom.data import get_testdata_files
import tempfile

DATA_ROOT = os.path.join(os.path.dirname(__file__), '..', 'data')
DICOM_ROOT = os.path.join(DATA_ROOT, 'DICOM')


@pytest.fixture(scope='function')
def dicom_file():
    def get_dicom_file(folder, filename):
        # copying file to temp folder to allow for overwriting while preserving the
        # original file
        fd, path = tempfile.mkstemp(suffix='.dcm')
        os.close(fd)

        src_path = os.path.join(DICOM_ROOT, folder, filename)
        shutil.copy(src_path, path)

        return path

    return get_dicom_file


@pytest.fixture(scope='function')
def timestamp_clean_dcm():
        def get_timestamp_clean_dcm(folder):
            path = get_testdata_files()[0]
            dcm = pydicom.dcmread(path)
            if hasattr(dcm, 'StudyDate'):
                delattr(dcm, 'StudyDate')
            if hasattr(dcm, 'StudyTime'):
                delattr(dcm, 'StudyTime')
            if hasattr(dcm, 'StudyDateTime'):
                delattr(dcm, 'StudyDateTime')
            if hasattr(dcm, 'SeriesDate'):
                delattr(dcm, 'SeriesDate')
            if hasattr(dcm, 'SeriesTime'):
                delattr(dcm, 'SeriesTime')
            if hasattr(dcm, 'SeriesDateTime'):
                delattr(dcm, 'SeriesDateTime')
            if hasattr(dcm, 'AcquisitionDate'):
                delattr(dcm, 'AcquisitionDate')
            if hasattr(dcm, 'ContentDate'):
                delattr(dcm, 'ContentDate')
            if hasattr(dcm, 'AcquisitionTime'):
                delattr(dcm, 'AcquisitionTime')
            if hasattr(dcm, 'AcquisitionDateTime'):
                delattr(dcm, 'AcquisitionDateTime')
            clean_dmc_path = str(Path(folder) / 'clean.dcm')
            dcm.save_as(clean_dmc_path)

            return clean_dmc_path

        return get_timestamp_clean_dcm
