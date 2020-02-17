import tempfile
import os
import pathlib
import zipfile

import pytest
from pydicom.data import get_testdata_files

from utils.dicom.dicom_archive import DicomArchive


def test_dicom_archive_class_validate():

    test_dicom_path = get_testdata_files('MR_small.dcm')[0]
    with tempfile.TemporaryDirectory() as temp_dir:
        # Test valid DICOM
        dicom_archive = DicomArchive(zip_path=test_dicom_path, extract_dir=temp_dir, validate=True)
        assert dicom_archive.dataset

        # Test file doesn't exist
        with pytest.raises(FileNotFoundError) as err:
            assert DicomArchive(zip_path=os.path.join(temp_dir, 'DoesntExist'), extract_dir=temp_dir, validate=True)

        # Test empty archive
        with pytest.raises(RuntimeError) as err:
            zip_path = os.path.join(temp_dir, 'empty_zip.zip')

            with zipfile.ZipFile(zip_path, 'w') as zip_obj:
                pass
            assert DicomArchive(zip_path, extract_dir=temp_dir, validate=True)

        # Test non-dicom
        not_dicom_path = pathlib.Path(temp_dir)/'empty_file.txt'
        not_dicom_path.touch()
        not_dicom_path.write_text('SPAM')
        with pytest.raises(RuntimeError) as err:
            assert DicomArchive(not_dicom_path, extract_dir=temp_dir, validate=True)
        assert 'failed to parse DICOMs' in str(err.value)