import os

import willow

from django.conf import settings
from django.core.exceptions import ValidationError
from django.forms.fields import FileField
from django.template.defaultfilters import filesizeformat



ALLOWED_EXTENSIONS = ["docm","docx","doc","txt","pdf","ppt","pptx","pptm","xls","xlsm","xlsx","csv","odt","odf","ods","odg","md","ps","oxps","xps","txt","zip","7z","tar","tar.gz"]

class WagtailDocumentField(FileField):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Get max upload size from settings
        self.max_upload_size = getattr(settings, 'CONSOLE_DOC_MAX_UPLOAD_SIZE', 10 * 1024 * 1024)
        max_upload_size_text = filesizeformat(self.max_upload_size)

        # Help text
        if self.max_upload_size is not None:
            self.help_text = "Supported formats: %(supported_formats)s. Maximum filesize: %(max_upload_size)s." % {'supported_formats': ALLOWED_EXTENSIONS,'max_upload_size': max_upload_size_text,}
        else:
            self.help_text = "Supported formats: %(supported_formats)s." % {'supported_formats': ALLOWED_EXTENSIONS,}

        self.error_messages['invalid_document_extension'] = "Not a supported document format. Supported formats: %s." % ALLOWED_EXTENSIONS
        self.error_messages['invalid_document_known_format'] = "Not a valid %s document."
        self.error_messages['file_too_large'] = "This file is too big (%%s). Maximum filesize %s." % max_upload_size_text
        # self.error_messages['file_too_many_pixels'] = "This file has too many pixels (%%s). Maximum pixels %s." % self.max_document_pixels
        self.error_messages['file_too_large_unknown_size'] = "This file is too big. Maximum filesize %s." % max_upload_size_text

    def check_doc_file_format(self, f):
        # Check file extension
        extension = os.path.splitext(f.name)[1].lower()[1:]

        if extension not in ALLOWED_EXTENSIONS:
            raise ValidationError(self.error_messages['invalid_document_extension'], code='invalid_document_extension')

        document_format = extension.upper()
        print(f)
        try: internal_document_format = f.document.format.upper()
        except Exception as e:
            print(e)
            internal_document_format = document_format

        # Check that the internal format matches the extension
        # It is possible to upload PSD files if their extension is set to jpg, png or gif. This should catch them out
        if internal_document_format != document_format:
            raise ValidationError(self.error_messages['invalid_document_known_format'] % (document_format,), code='invalid_document_known_format')

    def check_doc_file_size(self, f):
        # Upload size checking can be disabled by setting max upload size to None
        if self.max_upload_size is None:
            return

        # Check the filesize
        if f.size > self.max_upload_size:
            raise ValidationError(self.error_messages['file_too_large'] % (
                filesizeformat(f.size),
            ), code='file_too_large')

    def to_python(self, data):
        f = super().to_python(data)

        if f is not None:
            self.check_doc_file_size(f)
            self.check_doc_file_format(f)
        return f
