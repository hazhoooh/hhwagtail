import json

from django import forms
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.functional import cached_property

from django.templatetags.static import static

from wagtail.admin.widgets import AdminChooser
from wagtail.core.telepath import register
from wagtail.core.widget_adapters import WidgetAdapter
from wagtail.images import get_image_model
from wagtail.images.shortcuts import get_rendition_or_not_found


class AdminImageChooser(AdminChooser):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.image_model = get_image_model()

    def get_value_data(self, value):
        if value is None: return None
        elif isinstance(value, self.image_model): image = value
        else: image = self.image_model.objects.get(pk=value)
        preview_image = get_rendition_or_not_found(image, 'max-165x165')
        return {
            'id': image.pk,
            'title': image.title,
            'preview': {'url': preview_image.url,'width': preview_image.width,'height': preview_image.height,},
            'edit_url': reverse('wagtailimages:edit', args=[image.id]),
        }

    def render_html(self, name, value_data, attrs):
        value_data = value_data or {}
        original_field_html = super().render_html(name, value_data.get('id'), attrs)

        return render_to_string("wagtailimages/widgets/image_chooser.html", {
            'widget': self,
            'original_field_html': original_field_html,
            'attrs': attrs,
            'value': bool(value_data),  # only used by chooser.html to identify blank values
            'title': value_data.get('title', ''),
            'preview': value_data.get('preview', {}),
            'edit_url': value_data.get('edit_url', ''),
        })

    def render_js_init(self, id_, name, value_data): return "createImageChooser({0});".format(json.dumps(id_))


class ImageChooserAdapter(WidgetAdapter):
    js_constructor = 'wagtail.images.widgets.ImageChooser'
    def js_args(self, widget): return [widget.render_html('__NAME__', None, attrs={'id': '__ID__'}),widget.id_for_label('__ID__'),]
    @cached_property
    def media(self): return forms.Media(js=[static('wimages/js/image-chooser-telepath.js') + "?=99",])

register(ImageChooserAdapter(), AdminImageChooser)
