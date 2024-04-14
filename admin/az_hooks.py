from django.conf import settings
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils.http import urlencode
from django.utils.translation import gettext
from wagtail import __version__
from wagtail.admin.admin_url_finder import ModelAdminURLFinder, register_admin_url_finder
from wagtail.admin.auth import user_has_any_page_permission
from wagtail.admin.forms.collections import GroupCollectionManagementPermissionFormSet
from wagtail.admin.menu import MenuItem, SubmenuMenuItem, reports_menu, settings_menu
from wagtail.admin.navigation import get_explorable_root_page
from wagtail.admin.search import SearchArea
from wagtail.admin.site_summary import SummaryItem
from wagtail.admin.ui.components import SubMenuItem
from wagtail.admin.views.pages.bulk_actions import DeleteBulkAction, MoveBulkAction, PublishBulkAction, UnpublishBulkAction
from wagtail.admin.viewsets import viewsets
from wagtail.admin.widgets import Button, ButtonWithDropdownFromHook, PageListingButton
from wagtail.core import hooks
from wagtail.core.models import Collection, Page, Task, UserPagePermissionsProxy, Workflow
from wagtail.core.permissions import collection_permission_policy, task_permission_policy, workflow_permission_policy
from wagtail.core.whitelist import allow_without_attributes, attribute_rule, check_url

class SettingsMenuItem(SubmenuMenuItem):
    template = 'cms/shared/menu_settings_menu_item.html'
    def render_component(self, request):
        return SubMenuItem(self.name,self.label,self.menu.render_component(request),icon_name=self.icon_name,classnames=self.classnames,footer_text="Wagtail v." + __version__)

@hooks.register('register_console_menu_item')
def register_settings_menu():return SettingsMenuItem('⚙️ Settings',settings_menu,icon_name='',order=10000)

@hooks.register('register_permissions')
def register_permissions():return Permission.objects.filter(content_type__app_label='wagtailadmin', codename='access_admin')
class PageSearchArea(SearchArea):
    def __init__(self): super().__init__('Pages', reverse('wagtailadmin_pages:search'),name='pages',icon_name='folder-open-inverse',order=100)
    def is_shown(self, request): return user_has_any_page_permission(request.user)

@hooks.register('register_admin_search_area')
def register_pages_search_area(): return PageSearchArea()

@hooks.register('register_group_permission_panel')
def register_collection_permissions_panel(): return GroupCollectionManagementPermissionFormSet

class WorkflowsMenuItem(MenuItem):
    def is_shown(self, request):
        # if not getattr(settings, 'CONSOLE_WORKFLOW_ENABLED', True): return False
        return workflow_permission_policy.user_has_any_permission(request.user, ['add', 'change', 'delete'])
class WorkflowTasksMenuItem(MenuItem):
    def is_shown(self, request):
        return task_permission_policy.user_has_any_permission(request.user, ['add', 'change', 'delete'])

@hooks.register('register_console_menu_item')
def register_workflows_menu_item(): return WorkflowsMenuItem('Workflows', reverse('wagtailadmin_workflows:index'), icon_name='tasks', order=1000)

@hooks.register('register_console_menu_item')
def register_workflow_tasks_menu_item(): return WorkflowTasksMenuItem('Workflow tasks', reverse('wagtailadmin_workflows:task_index'), icon_name='thumbtack', order=1100)

@hooks.register('register_page_listing_buttons')
def page_listing_buttons(page, page_perms, is_parent=False, next_url=None):
    if page_perms.can_edit(): yield PageListingButton('Edit',reverse('wagtailadmin_pages:edit', args=[page.id]),attrs={'title': "Edit this page",},priority=20)
    if page.has_unpublished_changes and page.is_previewable(): yield PageListingButton('View draft',reverse('wagtailadmin_pages:view_draft', args=[page.id]),attrs={'title': "Preview draft version of this page",'rel': 'noopener noreferrer'},priority=30)
    if page.live and page.url: yield PageListingButton('View live',page.url,attrs={'rel': 'noopener noreferrer','title': "View live version of this page",'target': 'blank'},priority=30)
    if page_perms.can_copy():
        url = reverse('wagtailadmin_pages:copy', args=[page.id])
        if next_url:url += '?' + urlencode({'next': next_url})
        yield Button('Copy',url,attrs={'title': "Copy this page",'class': 'btn'},priority=20)
    if page_perms.can_delete():
        url = reverse('wagtailadmin_pages:delete', args=[page.id])
        if next_url == reverse('wagtailadmin_pages:explore', args=[page.id]): next_url = None
        if next_url: url += '?' + urlencode({'next': next_url})
        yield Button('Delete',url,attrs={'title': "Delete this page",'class': 'btn'},priority=30)
    if page_perms.can_unpublish():
        url = reverse('wagtailadmin_pages:unpublish', args=[page.id])
        if next_url: url += '?' + urlencode({'next': next_url})
        yield Button('Unpublish',url,attrs={'title': "Unpublish this page",'class': 'btn'},priority=40)
    # yield ButtonWithDropdownFromHook('More',hook_name='register_page_listing_more_buttons',page=page,page_perms=page_perms,is_parent=is_parent,next_url=next_url,attrs={'target': '_blank', 'rel': 'noopener noreferrer', 'title': "View more options for this page"},priority=40)
    if not page_perms.page_is_root: yield Button('History',reverse('wagtailadmin_pages:history', args=[page.id]),attrs={'title': "View history for this page",'class': 'btn'},priority=50)
    if page_perms.can_add_subpage(): yield Button('+ Sub-Page',reverse('wagtailadmin_pages:add_subpage', args=[page.id]),attrs={'title': "Add a sub-page to this page",},classes={'add_btn'},priority=1000)

# @hooks.register('register_page_listing_buttons')
# def page_listing_more_buttons(page, page_perms, is_parent=False, next_url=None):
#     if is_parent: yield Button('Sort menu order', '?ordering=ord',attrs={'title': "Change ordering of child pages of this page",'class': 'btn'},priority=60)

@hooks.register('register_admin_urls')
def register_viewsets_urls():
    viewsets.populate()
    return viewsets.get_urlpatterns()

class ReportsMenuItem(SubmenuMenuItem):
    template = 'cms/shared/menu_submenu_item.html'
    def is_shown(self, request): return request.user.is_superuser

class LockedPagesMenuItem(MenuItem):
    def is_shown(self, request): return UserPagePermissionsProxy(request.user).can_remove_locks()

class WorkflowReportMenuItem(MenuItem):
    def is_shown(self, request): return getattr(settings, 'CONSOLE_WORKFLOW_ENABLED', True)

class SiteHistoryReportMenuItem(MenuItem):
    def is_shown(self, request): return UserPagePermissionsProxy(request.user).explorable_pages().exists()

@hooks.register('register_reports_menu_item')
def register_locked_pages_menu_item(): return LockedPagesMenuItem('Locked Pages', reverse('wagtailadmin_reports:locked_pages'), icon_name='lock', order=700)

@hooks.register('register_reports_menu_item')
def register_workflow_report_menu_item(): return WorkflowReportMenuItem('Workflows', reverse('wagtailadmin_reports:workflow'), icon_name='tasks', order=800)

@hooks.register('register_reports_menu_item')
def register_workflow_tasks_report_menu_item(): return WorkflowReportMenuItem('Workflow tasks', reverse('wagtailadmin_reports:workflow_tasks'), icon_name='thumbtack', order=900)

@hooks.register('register_reports_menu_item')
def register_site_history_report_menu_item(): return SiteHistoryReportMenuItem('Global Activities', reverse('wagtailadmin_reports:site_history'), icon_name='history', order=1000)

@hooks.register('register_console_menu_item')
def register_reports_menu(): return ReportsMenuItem('🧾 Logs', reports_menu, icon_name='site', order=30000)

class PageAdminURLFinder:
    def __init__(self, user): self.page_perms = user and UserPagePermissionsProxy(user)
    def get_edit_url(self, instance):
        if self.page_perms and not self.page_perms.for_page(instance).can_edit(): return None
        else: return reverse('wagtailadmin_pages:edit', args=(instance.pk, ))
register_admin_url_finder(Page, PageAdminURLFinder)

class CollectionAdminURLFinder(ModelAdminURLFinder):
    permission_policy = collection_permission_policy
    edit_url_name = 'wagtailadmin_collections:edit'
register_admin_url_finder(Collection, CollectionAdminURLFinder)

class WorkflowAdminURLFinder(ModelAdminURLFinder):
    permission_policy = workflow_permission_policy
    edit_url_name = 'wagtailadmin_workflows:edit'
register_admin_url_finder(Workflow, WorkflowAdminURLFinder)

class WorkflowTaskAdminURLFinder(ModelAdminURLFinder):
    permission_policy = task_permission_policy
    edit_url_name = 'wagtailadmin_workflows:edit_task'
register_admin_url_finder(Task, WorkflowTaskAdminURLFinder)
for action_class in [DeleteBulkAction, MoveBulkAction, PublishBulkAction, UnpublishBulkAction]:
    hooks.register('register_bulk_action', action_class)
