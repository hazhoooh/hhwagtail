import json

from django import forms
from django.conf import settings
from django.forms import widgets
from django.utils.formats import get_format

from wagtail.admin.datetimepicker import to_datetimepicker_format
from wagtail.admin.staticfiles import versioned_static
from wagtail.core.telepath import register
from wagtail.core.widget_adapters import WidgetAdapter


DEFAULT_DATE_FORMAT = '%Y-%m-%d'
DEFAULT_DATETIME_FORMAT = '%Y-%m-%d %H:%M'
DEFAULT_TIME_FORMAT = '%H:%M' 


class AdminDateInput(widgets.DateInput):
    template_name = 'cms/widgets/date_input.html'
    def __init__(self, attrs=None, format=None):
        default_attrs = {'autocomplete': 'off'}
        fmt = format
        if attrs: default_attrs.update(attrs)
        if fmt is None: fmt = getattr(settings, 'CONSOLE_DATE_FORMAT', DEFAULT_DATE_FORMAT)
        self.js_format = to_datetimepicker_format(fmt)
        super().__init__(attrs=default_attrs, format=fmt)

    def get_config(self): return {'dayOfWeekStart': get_format('FIRST_DAY_OF_WEEK'),'format': self.js_format,}

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context['widget']['config_json'] = json.dumps(self.get_config())
        return context

    # @property
    # def media(self): return forms.Media(js=[versioned_static('aw/js/date-time-chooser.js'),])

class AdminDateInputAdapter(WidgetAdapter):
    js_constructor = 'wagtail.widgets.AdminDateInput'
    def js_args(self, widget): return [widget.get_config(),]

register(AdminDateInputAdapter(), AdminDateInput)
