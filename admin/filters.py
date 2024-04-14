import django_filters

from django.db import models

from django_filters.widgets import SuffixedMultiWidget

from wagtail.admin.widgets import FilteredSelect
from wagtail.core.utils import get_content_type_label


class FilteredModelChoiceIterator(django_filters.fields.ModelChoiceIterator):
    """
    A variant of Django's ModelChoiceIterator that, instead of yielding (value, label) tuples,
    returns (value, label, filter_value) so that FilteredSelect can drop filter_value into
    the data-filter-value attribute.
    """
    def choice(self, obj): return (self.field.prepare_value(obj),self.field.label_from_instance(obj),self.field.get_filter_value(obj))

class FilteredModelChoiceField(django_filters.fields.ModelChoiceField):
    """
    A ModelChoiceField that uses FilteredSelect to dynamically show/hide options based on another
    ModelChoiceField of related objects; an option will be shown whenever the selected related
    object is present in the result of filter_accessor for that option.

    filter_field - the HTML `id` of the related ModelChoiceField
    filter_accessor - either the name of a relation, property or method on the model instance which
        returns a queryset of related objects, or a function which accepts the model instance and
        returns such a queryset.
    """
    widget = FilteredSelect
    iterator = FilteredModelChoiceIterator
    def __init__(self, *args, **kwargs):
        self.filter_accessor = kwargs.pop('filter_accessor')
        filter_field = kwargs.pop('filter_field')
        super().__init__(*args, **kwargs)
        self.widget.filter_field = filter_field
    def get_filter_value(self, obj):
        if callable(self.filter_accessor):
            queryset = self.filter_accessor(obj)
        else:
            queryset = getattr(obj, self.filter_accessor)
            if isinstance(queryset, models.Manager):
                queryset = queryset.all()
            elif callable(queryset):
                queryset = queryset()
        return queryset.values_list('pk', flat=True)

class FilteredModelChoiceFilter(django_filters.ModelChoiceFilter):
    field_class = FilteredModelChoiceField

class WagtailFilterSet(django_filters.FilterSet): pass

class ContentTypeModelChoiceField(django_filters.fields.ModelChoiceField):
    """
    Custom ModelChoiceField for ContentType, to show the model verbose name as the label rather
    than the default 'wagtailcore | page' representation of a ContentType
    """
    def label_from_instance(self, obj):
        return get_content_type_label(obj)

class ContentTypeFilter(django_filters.ModelChoiceFilter):
    field_class = ContentTypeModelChoiceField
