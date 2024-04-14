import django_filters
from django.utils.translation import gettext as _
from wagtail.admin.filters import WagtailFilterSet
from wagtail.core.models import Site

class RedirectsReportFilterSet(WagtailFilterSet):
    is_permanent = django_filters.ChoiceFilter(label="Type",method="filter_type",choices=((True, "Permanent"), (False, "Temporary"),),empty_label="All",)
    site = django_filters.ModelChoiceFilter(field_name="site", queryset=Site.objects.all())
    def filter_type(self, queryset, name, value):
        if value and self.request and self.request.user: queryset = queryset.filter(is_permanent=value)
        return queryset
