from utils.dicom.dicom_archive import make_list_items_hashable


def test_make_list_items_hashable_mixed_type():
    test_list = [[0, 1, 2], None, 'spam', 'eggs']
    hashable_list = make_list_items_hashable(test_list)

    assert hashable_list == [(0, 1, 2), None, 'spam', 'eggs']