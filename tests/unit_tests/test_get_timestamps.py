import pydicom
import tempfile
import pytz
import tzlocal
from pathlib import Path
from pydicom.data import get_testdata_files

from run import get_timestamp, validate_timezone


def test_get_timestamp_logic(timestamp_clean_dcm):

    with tempfile.TemporaryDirectory() as tmpdir:
        # Dicom with no DateTime, Date or Time
        dcm_path = timestamp_clean_dcm(tmpdir)

        # Dicom Date Time format: YYYYMMDDHHMMSS.FFFFFF&ZZXX
        # Dicom Time format: HHMMSS.FFFFFF

        # Only testing a subset of all possible combinations

        # StudyDate, StudyTime and AcquisitionDateTime defined
        dcm = pydicom.read_file(dcm_path)
        dcm.StudyDate = '20200101'
        dcm.StudyTime = '120000.000000'
        dcm.AcquisitionDateTime = '20200101120100.000000'
        timezone = pytz.timezone('UTC')
        session_timestamp, acquisition_timestamp = get_timestamp(dcm, timezone)
        assert session_timestamp == '2020-01-01T12:00:00+00:00'
        assert acquisition_timestamp == '2020-01-01T12:01:00+00:00'

        # StudyDate, StudyTime and AcquisitionDate and AcquisitionTime defined
        dcm = pydicom.read_file(dcm_path)
        dcm.StudyDate = '20200101'
        dcm.StudyTime = '120000.000000'
        dcm.AcquisitionDate = '20200101'
        dcm.AcquisitionTime = '120100.000000'
        timezone = pytz.timezone('UTC')
        session_timestamp, acquisition_timestamp = get_timestamp(dcm, timezone)
        assert session_timestamp == '2020-01-01T12:00:00+00:00'
        assert acquisition_timestamp == '2020-01-01T12:01:00+00:00'

        # StudyDate, StudyTime and SeriesDate and SeriesTime defined
        dcm = pydicom.read_file(dcm_path)
        dcm.StudyDate = '20200101'
        dcm.StudyTime = '120000.000000'
        dcm.SeriesDate = '20200101'
        dcm.SeriesTime = '120100.000000'
        timezone = pytz.timezone('UTC')
        session_timestamp, acquisition_timestamp = get_timestamp(dcm, timezone)
        assert session_timestamp == '2020-01-01T12:00:00+00:00'
        assert acquisition_timestamp == '2020-01-01T12:01:00+00:00'

        # StudyDate, StudyTime
        dcm = pydicom.read_file(dcm_path)
        dcm.StudyDate = '20200101'
        dcm.StudyTime = '120000.000000'
        timezone = pytz.timezone('UTC')
        session_timestamp, acquisition_timestamp = get_timestamp(dcm, timezone)
        assert session_timestamp == '2020-01-01T12:00:00+00:00'
        assert acquisition_timestamp == '2020-01-01T12:00:00+00:00'

        # StudyDate, SeriesDate
        dcm = pydicom.read_file(dcm_path)
        dcm.StudyDate = '20200101'
        dcm.SeriesDate = '20200102'
        timezone = pytz.timezone('UTC')
        session_timestamp, acquisition_timestamp = get_timestamp(dcm, timezone)
        assert session_timestamp == '2020-01-01T12:00:00+00:00'
        assert acquisition_timestamp == '2020-01-02T12:00:00+00:00'

        # StudyDate
        dcm = pydicom.read_file(dcm_path)
        dcm.StudyDate = '20200101'
        timezone = pytz.timezone('UTC')
        session_timestamp, acquisition_timestamp = get_timestamp(dcm, timezone)
        assert session_timestamp == '2020-01-01T12:00:00+00:00'
        assert acquisition_timestamp == '2020-01-01T12:00:00+00:00'