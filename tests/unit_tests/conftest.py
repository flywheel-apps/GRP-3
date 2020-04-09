import pytest
from pathlib import Path

import pydicom
from pydicom.data import get_testdata_files


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
