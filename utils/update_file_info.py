import copy
import json
import logging
import os

import backoff
import flywheel

WHITELIST_KEYS = ('classification', 'info', 'modality', 'type')

log = logging.getLogger(__name__)


def false_if_exc_is_timeout(exception):
    if exception.status in [504]:
        return False
    return True


@backoff.on_exception(backoff.expo, flywheel.rest.ApiException,
                      max_time=300, giveup=false_if_exc_is_timeout)
def dest_file_dict_request(fw_client, acq_id, file_name):
    file_dict = dict()
    cont_obj = fw_client.get(acq_id)
    file_obj = cont_obj.get_file(file_name)
    if file_obj:
        file_dict = file_obj.to_dict()
    return file_dict


def get_dest_cont_file_dict(input_key):
    """
    Gets the current file info for the file, if the input parent
    :param input_key: the key for the input in the manifest
    :type input_key: str
    :return: a dictionary representing the file object
    """
    with flywheel.GearContext() as gear_context:
        file_name = gear_context.get_input(input_key).get('location', {}).get('name')
        parent_id = gear_context.get_input(input_key).get('hierarchy', {}).get('id')
        parent_type = gear_context.get_input(input_key).get('hierarchy', {}).get('type')
        if parent_id == 'aex':
            parent_id = '5e66bbaa529e160945812d92'
        if not file_name:
            file_dict = dict()
        else:
            fw_client = gear_context.client
            file_dict = dest_file_dict_request(fw_client, parent_id, file_name)
        return file_dict, parent_type


def get_file_update_dict(fw_file_dict):
    """
    Removes info.header from input_dict.info and any non-info keys that aren't in
    WHITELIST_KEYS or evaluate to False
    :param fw_file_dict: a dictionary representing a flywheel file
    :return:
    """
    fw_file_dict = copy.deepcopy(fw_file_dict)
    remove_keys = list()
    for key, value in fw_file_dict.items():
        if key not in WHITELIST_KEYS:
            remove_keys.append(key)
    for key in remove_keys:
        fw_file_dict.pop(key)

    # Remove header info
    if isinstance(fw_file_dict.get('info'), dict):
        if 'header' in fw_file_dict['info'].keys():
            fw_file_dict['info'].pop('header')

    return fw_file_dict


def get_meta_file_dict_and_index(metadata_dict, file_name, parent_type):
    """
    Returns a tuple of the acquisition.files list index for the file named file_name
    if a dictionary for file_name exists within acquisition.files
    """

    file_index = None
    file_dict = dict()
    if isinstance(metadata_dict.get(parent_type), dict):
        if isinstance(metadata_dict[parent_type].get('files'), list):
            for index, file_item in enumerate(metadata_dict[parent_type]['files']):
                if isinstance(file_item, dict):
                    if file_item.get('name') == file_name:
                        file_dict = file_item
                        file_index = index
    return file_index, file_dict


def update_meta_file_dict(meta_file_dict, fw_file_dict):
    """
    updates meta_file_dict with fw_file_dict for keys that fw_file_dict doesn't have
    :param meta_file_dict: dictionary representation of the gear-generated file dict in .metadata.json
    :param fw_file_dict: dictionary representation of the flywheel file object
    :return: meta_file_dict with updated fw_file_dict
    """
    fw_file_dict = copy.deepcopy(fw_file_dict)
    meta_file_dict = copy.deepcopy(meta_file_dict)
    fw_file_dict = get_file_update_dict(fw_file_dict)
    meta_file_dict['info'] = meta_file_dict.get('info', {})

    for key in WHITELIST_KEYS:
        if not meta_file_dict.get(key) and fw_file_dict.get(key):
            meta_file_dict[key] = fw_file_dict[key]
    for key, value in fw_file_dict['info'].items():
        if not meta_file_dict['info'].get(key):
            meta_file_dict['info'] = value

    return meta_file_dict


def replace_metadata_file_dict(metadata_dict, index, meta_file_dict, parent_type):
    """
    Replaces the file dictionary at the index within the parent container's file list
    :param metadata_dict: dictionary representation of .metadata.json
    :param index: index at which to replace the file dictionary within the parent's file list
    :param meta_file_dict: the dictionary to place within the parent's file list
    :param parent_type: the container type of the file's parent (i.e. session, acquisition)
    :return:
    """
    metadata_dict = copy.deepcopy(metadata_dict)
    metadata_dict[parent_type] = metadata_dict.get(parent_type, {})
    metadata_dict[parent_type]['files'] = metadata_dict[parent_type].get('files', list())
    if not index or len(metadata_dict[parent_type]['files']) <= index:
        metadata_dict[parent_type]['files'].append(meta_file_dict)
    else:
        metadata_dict[parent_type]['files'][index] = meta_file_dict
    return metadata_dict


def update_file_metadata(fw_file_dict, metadata_dict, parent_type):
    if fw_file_dict.get('name'):
        file_index, meta_file_dict = get_meta_file_dict_and_index(metadata_dict, fw_file_dict['name'], parent_type)
        updated_file_dict = update_meta_file_dict(meta_file_dict, fw_file_dict)
        updated_metadata_dict = replace_metadata_file_dict(metadata_dict, file_index, updated_file_dict)
        return updated_metadata_dict
    else:
        return metadata_dict


def update_metadata_json(fw_file_dict, metadata_json_path, parent_type):
    if not os.path.exists(metadata_json_path):
        metadata_dict = dict()
    else:
        with open(metadata_json_path) as metadata_data:
            metadata_dict = json.load(metadata_data)
    if isinstance(fw_file_dict, dict):
        updated_metadata_dict = update_file_metadata(fw_file_dict, metadata_dict, parent_type)
        if updated_metadata_dict:
            with open(metadata_json_path, 'w') as metafile:
                json.dump(updated_metadata_dict, metafile, separators=(', ', ': '), sort_keys=True, indent=4)


def get_file_dict_and_update_metadata_json(input_key, metadata_json_path):
    """
    writes 
    :param input_key:
    :param metadata_json_path:
    :return:
    """
    file_dict, parent_type = get_dest_cont_file_dict(input_key)
    update_metadata_json(file_dict, metadata_json_path, parent_type)
