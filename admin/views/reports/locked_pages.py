import datetime

import django_filters

from django.core.exceptions import PermissionDenied


from wagtail.admin.filters import WagtailFilterSet
from wagtail.core.models import Page, UserPagePermissionsProxy

from .base import PageReportView


class LockedPagesReportFilterSet(WagtailFilterSet):
    locked_at = django_filters.DateTimeFromToRangeFilter()
    class Meta:
        model = Page
        fields = ['locked_by', 'locked_at', 'live']


class LockedPagesView(PageReportView):
    template_name = "cms/reports/locked_pages.html"
    title = "Locked pages"
    header_icon = "🔏"
    list_export = PageReportView.list_export + ["locked_at","locked_by",]
    filterset_class = LockedPagesReportFilterSet

    def get_filename(self): return "locked-pages-report-{}".format(datetime.datetime.today().strftime("%Y-%m-%d"))

    def get_queryset(self):
        pages = (UserPagePermissionsProxy(self.request.user).editable_pages() | Page.objects.filter(locked_by=self.request.user)).filter(locked=True).specific(defer=True)
        self.queryset = pages
        return super().get_queryset()

    def dispatch(self, request, *args, **kwargs):
        if not UserPagePermissionsProxy(request.user).can_remove_locks(): raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
