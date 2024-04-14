from django import forms
from django.conf import settings
from django.forms.models import modelform_factory
from django.utils.text import capfirst
from django.utils.translation import gettext as _

from wagtail.admin import widgets
from wagtail.admin.forms.collections import (BaseCollectionMemberForm, CollectionChoiceField, collection_member_permission_formset_factory)
from wagtail.core.models import Collection
from wagtail.images.fields import WagtailImageField
from wagtail.images.formats import get_image_formats
from wagtail.images.models import Image
from wagtail.images.permissions import permission_policy as images_permission_policy


# Callback to allow us to override the default form field for the image file field and collection field.
def formfield_for_dbfield(db_field, **kwargs):
    # Check if this is the file field
    if db_field.name == 'file': return WagtailImageField(label=capfirst(db_field.verbose_name), **kwargs)
    elif db_field.name == 'collection': return CollectionChoiceField(label="Collection", queryset=Collection.objects.all(), empty_label=None, **kwargs)
    # For all other fields, just call its formfield() method.
    return db_field.formfield(**kwargs)

class MultipleFileInput(forms.ClearableFileInput): allow_multiple_selected = True

class MultipleFileField(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)
    # @property
    # def is_hidden(self): return self.widget.is_hidden
    # @property
    # def id_for_label(self): return self.widget.id_for_label
    # @property
    # def auto_id(self): return self.widget.auto_id
    # @property
    # def attrs(self): return self.widget.attrs
    # @property
    # def use_required_attribute(self): return self.widget.use_required_attribute
    # def render(self): return self.widget.render
    # def has_changed(self, initial, data): return self.widget.has_changed(initial, data)
    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)): result = [single_file_clean(d, initial) for d in data]
        else: result = single_file_clean(data, initial)
        return result
    
class BaseImageForm(BaseCollectionMemberForm):
    permission_policy = images_permission_policy
    class Meta:
        widgets = {
            'file': MultipleFileInput(),
            'focal_point_x': forms.HiddenInput(attrs={'class': 'focal_point_x'}),
            'focal_point_y': forms.HiddenInput(attrs={'class': 'focal_point_y'}),
            'focal_point_width': forms.HiddenInput(attrs={'class': 'focal_point_width'}),
            'focal_point_height': forms.HiddenInput(attrs={'class': 'focal_point_height'}),
        }
class EditImageForm(BaseCollectionMemberForm):
    permission_policy = images_permission_policy
    class Meta:
        widgets = {
            'file': forms.FileInput(),
            'focal_point_x': forms.HiddenInput(attrs={'class': 'focal_point_x'}),
            'focal_point_y': forms.HiddenInput(attrs={'class': 'focal_point_y'}),
            'focal_point_width': forms.HiddenInput(attrs={'class': 'focal_point_width'}),
            'focal_point_height': forms.HiddenInput(attrs={'class': 'focal_point_height'}),
        }

def get_image_base_form(): return BaseImageForm

def get_image_form(model, view="add"):
    fields = model.admin_form_fields
    if 'collection' not in fields: fields = list(fields) + ['collection']
    if view == "edit": return modelform_factory(model,form=EditImageForm,fields=fields,formfield_callback=formfield_for_dbfield,)
    return modelform_factory(model,form=get_image_base_form(),fields=fields,formfield_callback=formfield_for_dbfield,)

def get_image_multi_form(model_class):
    # edit form for use within the multiple uploader
    ImageForm = get_image_form(model_class)
    # Make a new form with the file and focal point fields excluded
    class ImageEditForm(ImageForm):
        class Meta(ImageForm.Meta):
            model = model_class
            exclude = ('file','focal_point_x','focal_point_y','focal_point_width','focal_point_height',)
    return ImageEditForm

class ImageInsertionForm(forms.Form):
    """ Form for selecting parameters of the image (e.g. format) prior to insertion into a rich text area """
    format = forms.ChoiceField(label="Format",choices=[(format.name, format.label) for format in get_image_formats()],widget=forms.Select)
    image_is_decorative = forms.BooleanField(required=False, label="Image is decorative")
    alt_text = forms.CharField(required=False, label="Alt text")
    # dynamic_classes = forms.CharField(required=False, label="class names")

    def clean_alt_text(self):
        alt_text = self.cleaned_data['alt_text']
        image_is_decorative = self.cleaned_data['image_is_decorative']

        # Empty the alt text value if the image is set to be decorative
        if image_is_decorative:
            return ''
        else:
            # Alt text is required if image is not decorative.
            if not alt_text:
                msg = "Please add some alt text for your image or mark it as decorative"
                self.add_error('alt_text', msg)
        return alt_text

class URLGeneratorForm(forms.Form):
    filter_method = forms.ChoiceField(
        label="Filter",
        choices=(
            ('original', "Original size"),
            ('width', "Resize to width"),
            ('height', "Resize to height"),
            ('min', "Resize to min"),
            ('max', "Resize to max"),
            ('fill', "Resize to fill"),
        ),
    )
    width = forms.IntegerField(label="Width", min_value=0)
    height = forms.IntegerField(label="Height", min_value=0)
    closeness = forms.IntegerField(label="Closeness", min_value=0, initial=0)


GroupImagePermissionFormSet = collection_member_permission_formset_factory(
    Image,
    [
        ('add_image', "Add", "Add/edit images you own"),
        ('change_image', "Edit", "Edit any image"),
        ('choose_image', "Choose", "Select images in choosers"),
    ],
    'wagtailimages/permissions/includes/image_permissions_formset.html'
)
