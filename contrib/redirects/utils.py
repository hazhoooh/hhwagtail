from django.conf import settings

from wagtail.contrib.redirects.base_formats import DEFAULT_FORMATS
from wagtail.contrib.redirects.tmp_storages import CacheStorage, TempFolderStorage


def write_to_file_storage(import_file, input_format):
    FileStorage = get_file_storage()
    file_storage = FileStorage()

    data = bytes()
    for chunk in import_file.chunks():
        data += chunk

    file_storage.save(data, input_format.get_read_mode())
    return file_storage


def get_supported_extensions():
    return ("csv", "tsv", "xls", "xlsx")


def get_format_cls_by_extension(extension):
    formats = get_import_formats()

    available_formats = [x for x in formats if x.__name__ == extension.upper()]

    if not available_formats:
        return None

    return available_formats[0]


def get_import_formats():
    formats = [f for f in DEFAULT_FORMATS if f().can_import()]
    return formats


def get_file_storage():
    file_storage = getattr(
        settings, 'CONSOLE_REDIRECTS_FILE_STORAGE', 'tmp_file'
    )
    if file_storage == 'tmp_file':
        return TempFolderStorage
    if file_storage == 'cache':
        return RedirectsCacheStorage

    raise Exception(
        "Invalid file storage, must be either 'tmp_file' or 'cache'"
    )


class RedirectsCacheStorage(CacheStorage):
    CACHE_PREFIX = 'wagtail-redirects-'
