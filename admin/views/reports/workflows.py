import datetime

import django_filters

from django.contrib.auth import get_user_model


from wagtail.admin.filters import FilteredModelChoiceFilter, WagtailFilterSet
from wagtail.core.models import Task, TaskState, UserPagePermissionsProxy, Workflow, WorkflowState

from .base import ReportView


def get_requested_by_queryset(request):
    User = get_user_model()
    return User.objects.filter(
        pk__in=set(WorkflowState.objects.values_list('requested_by__pk', flat=True))
    ).order_by(User.USERNAME_FIELD)


class WorkflowReportFilterSet(WagtailFilterSet):
    created_at = django_filters.DateTimeFromToRangeFilter(label="Started at")
    reviewable = django_filters.ChoiceFilter(
        label="Show",
        method='filter_reviewable',
        choices=(('true', "Awaiting my review"),),
        empty_label="All",
        # widget=ButtonSelect
    )
    requested_by = django_filters.ModelChoiceFilter(
        field_name='requested_by', queryset=get_requested_by_queryset
    )

    def filter_reviewable(self, queryset, name, value):
        if value and self.request and self.request.user:
            queryset = queryset.filter(current_task_state__in=TaskState.objects.reviewable_by(self.request.user))
        return queryset

    class Meta:
        model = WorkflowState
        fields = ['reviewable', 'workflow', 'status', 'requested_by', 'created_at']


class WorkflowTasksReportFilterSet(WagtailFilterSet):
    started_at = django_filters.DateTimeFromToRangeFilter(label="Started at")
    finished_at = django_filters.DateTimeFromToRangeFilter(label="Completed at")
    workflow = django_filters.ModelChoiceFilter(
        field_name='workflow_state__workflow', queryset=Workflow.objects.all(), label="Workflow"
    )

    # When a workflow is chosen in the 'id_workflow' selector, filter this list of tasks
    # to just the ones whose workflows attribute includes the selected workflow.
    task = FilteredModelChoiceFilter(
        queryset=Task.objects.all(), filter_field='id_workflow', filter_accessor='workflows'
    )

    reviewable = django_filters.ChoiceFilter(
        label="Show",
        method='filter_reviewable',
        choices=(('true', "Awaiting my review"),),
        empty_label="All",
        # widget=ButtonSelect
    )

    def filter_reviewable(self, queryset, name, value):
        if value and self.request and self.request.user:
            queryset = queryset.filter(id__in=TaskState.objects.reviewable_by(self.request.user).values_list('id', flat=True))
        return queryset

    class Meta:
        model = TaskState
        fields = ['reviewable', 'workflow', 'task', 'status', 'started_at', 'finished_at']


class WorkflowView(ReportView):
    template_name = 'cms/reports/workflow.html'
    title = "Workflows"
    header_icon = '✅'
    filterset_class = WorkflowReportFilterSet

    export_headings = {
        "page.id": "Page ID",
        "page.content_type.model_class._meta.verbose_name.title": "Page Type",
        "page.title": "Page Title",
        "get_status_display": "Status",
        "created_at": "Started at"
    }
    list_export = [
        "workflow",
        "page.id",
        "page.content_type.model_class._meta.verbose_name.title",
        "page.title",
        "get_status_display",
        "requested_by",
        "created_at",
    ]

    def get_filename(self):
        return "workflow-report-{}".format(
            datetime.datetime.today().strftime("%Y-%m-%d")
        )

    def get_queryset(self):
        pages = UserPagePermissionsProxy(self.request.user).editable_pages()
        return WorkflowState.objects.filter(page__in=pages).order_by('-created_at')


class WorkflowTasksView(ReportView):
    template_name = 'cms/reports/workflow_tasks.html'
    title = "Workflow tasks"
    header_icon = '📌'
    filterset_class = WorkflowTasksReportFilterSet
    export_headings = {
        "workflow_state.page.id": "Page ID",
        "workflow_state.page.content_type.model_class._meta.verbose_name.title": "Page Type",
        "workflow_state.page.title": "Page Title",
        "get_status_display": "Status",
        "workflow_state.requested_by": "Requested By"
    }
    list_export = [
        "task",
        "workflow_state.page.id",
        "workflow_state.page.content_type.model_class._meta.verbose_name.title",
        "workflow_state.page.title",
        "get_status_display",
        "workflow_state.requested_by",
        "started_at",
        "finished_at",
        "finished_by",
    ]
    def get_filename(self): return "workflow-tasks-{}".format(datetime.datetime.today().strftime("%Y-%m-%d"))
    def get_queryset(self): return TaskState.objects.filter(workflow_state__page__in=UserPagePermissionsProxy(self.request.user).editable_pages()).order_by('-started_at')
