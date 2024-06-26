from django.conf import settings
from django.contrib import admin

from wagtail.documents.models import Document


if hasattr(settings, 'DOCS_DOCUMENT_MODEL') and settings.DOCS_DOCUMENT_MODEL != 'wagtaildocs.Document':
    # This installation provides its own custom document class;
    # to avoid confusion, we won't expose the unused wagtaildocs.Document class
    # in the admin.
    pass
else:
    admin.site.register(Document)
