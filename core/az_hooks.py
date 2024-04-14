from django.conf import settings
from django.contrib.auth.models import Permission
from django.contrib.auth.views import redirect_to_login
from django.db import models
from django.forms import Media
from django.templatetags.static import static
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.text import capfirst
from wagtail.admin.auth import user_has_any_page_permission
from wagtail.admin.menu import MenuItem
from wagtail.admin.site_summary import SummaryItem
from wagtail.core import hooks
from wagtail.core.log_actions import LogFormatter
from wagtail.core.models import ModelLogEntry, Page, PageLogEntry, PageViewRestriction
from wagtail.core.permissions import collection_permission_policy
from wagtail.core.rich_text.pages import PageLinkHandler

def require_wagtail_login(next):
    login_url = getattr(settings, 'CONSOLE_FRONTEND_LOGIN_URL', reverse('wagtailcore_login'))
    return redirect_to_login(next, login_url)

@hooks.register('before_serve_page')
def check_view_restrictions(page, request, serve_args, serve_kwargs):
    """
    Check whether there are any view restrictions on this page which are
    not fulfilled by the given request object. If there are, return an
    HttpResponse that will notify the user of that restriction (and possibly
    include a password / login form that will allow them to proceed). If
    there are no such restrictions, return None
    """
    for restriction in page.get_view_restrictions():
        if not restriction.accept_request(request):
            if restriction.restriction_type == PageViewRestriction.PASSWORD:
                from wagtail.core.forms import PasswordViewRestrictionForm
                form = PasswordViewRestrictionForm(instance=restriction, initial={'return_url': request.get_full_path()})
                action_url = reverse('wagtailcore_authenticate_with_password', args=[restriction.id, page.id])
                return page.serve_password_required_response(request, form, action_url)
            elif restriction.restriction_type in [PageViewRestriction.LOGIN, PageViewRestriction.GROUPS]: return require_wagtail_login(next=request.get_full_path())

@hooks.register('register_rich_text_features')
def register_core_features(features):
    features.default_features.append('hr')
    features.default_features.append('link')
    features.register_link_type(PageLinkHandler)
    features.default_features.append('bold')
    features.default_features.append('italic')
    features.default_features.append('ol')
    features.default_features.append('ul')

if getattr(settings, 'CONSOLE_WORKFLOW_ENABLED', True):
    @hooks.register('register_permissions')
    def register_workflow_permissions(): return Permission.objects.filter(content_type__app_label='wagtailcore',codename__in=['add_workflow', 'change_workflow', 'delete_workflow'])
    @hooks.register('register_permissions')
    def register_task_permissions(): return Permission.objects.filter(content_type__app_label='wagtailcore',codename__in=['add_task', 'change_task', 'delete_task'])

@hooks.register('describe_collection_contents')
def describe_collection_children(collection):
    descendant_count = collection.get_descendants().count()
    if descendant_count:
        url = reverse('wagtailadmin_collections:index')
        return {'count': descendant_count,'count_text': f"{descendant_count} descendant collections",'url': url,}
collection_label='Collections'

class CollectionsMenuItem(MenuItem):
    def is_shown(self, request): return collection_permission_policy.user_has_any_permission(request.user, ['add', 'change', 'delete'])

@hooks.register('register_console_menu_item')
def register_collections_menu_item(): return CollectionsMenuItem(collection_label, reverse('wagtailadmin_collections:index'),classnames="i_layer-group gold_b", order=200)

class CollectionsBoeard(SummaryItem):
    label = collection_label
    order = 200
    template_name = 'cms/console_boards/collections.html'
    def get_context_data(self, parent_context):
        context_data = super().get_context_data(parent_context)
        total_collections=collection_permission_policy.instances_user_has_any_permission_for(self.request.user, ['add', 'change', 'delete']).count()
        context_data["total_collections"]=total_collections
        return context_data
    def is_shown(self): return collection_permission_policy.user_has_any_permission(self.request.user, ['add', 'change', 'delete'])

@hooks.register('construct_console_boards_summary_items')
def add_collections_summary_item(request, items): items.append(CollectionsBoeard(request))

class PageExplorerMenuItem(MenuItem):
    template = 'cms/shared/explorer_menu_item.html'
    def is_shown(self, request): return user_has_any_page_permission(request.user)

@hooks.register('register_console_menu_item')
def register_explorer_menu_item(): return PageExplorerMenuItem('📑 Pages', reverse('wagtailadmin_pages:explore_root'),name='explorer',order=0)

class PagesBoard(SummaryItem):
    label = 'Pages Tree'
    order = 2
    template_name = 'cms/console_boards/pages.html'
    def get_context_data(self, parent_context):
        from wagtail.admin.navigation import get_site_for_user
        from wagtail.core.models import Page, Site
        context_data = super().get_context_data(parent_context)
        site_details = get_site_for_user(self.request.user)
        root_page = site_details['root_page']
        site_name = site_details['site_name']
        if root_page:
            page_count = Page.objects.descendant_of(root_page, inclusive=True).count()
            if root_page.is_root():
                page_count -= 1
                try: root_page = Site.objects.get().root_page
                except (Site.DoesNotExist, Site.MultipleObjectsReturned): pass
        else: page_count = 0
        context_data["root_page"]=root_page
        context_data["total_pages"]=page_count
        context_data["site_name"]=site_name
        return context_data
    def is_shown(self): return user_has_any_page_permission(self.request.user)
    @cached_property
    def media(self): return Media(css={'only screen and (color)':[static("testing.css")+"?v0"]})
    
    def render_html(self, parent_context=None):
        template_name = self.template_name
        print(f"Using template: {template_name}")
        return super().render_html(parent_context)

@hooks.register('construct_console_boards_summary_items')
def add_pages_summary_item(request, items): items.append(PagesBoard(request))

@hooks.register('register_log_actions')
def register_core_log_actions(actions):
    actions.register_model(models.Model, ModelLogEntry)
    actions.register_model(Page, PageLogEntry)
    actions.register_action('created', "Create", "Created")
    actions.register_action('edited', "Edit", "Edited")
    actions.register_action('deleted', "Delete", "Deleted")
    actions.register_action('published', "Publish", "Published")
    actions.register_action('publishing_scheduled', "Publish scheduled draft", "Published scheduled draft")
    actions.register_action('unpublished', "Unpublish", "Unpublished")
    actions.register_action('unpublishing_scheduled', "Unpublish scheduled draft", "Unpublished scheduled draft")
    actions.register_action('locked', "Lock", "Locked")
    actions.register_action('unlocked', "Unlock", "Unlocked")
    actions.register_action('approved', "Approve", "Approved")
    actions.register_action('rejected', "Reject", "Rejected")
    @actions.register_action('renamed')
    class RenameActionFormatter(LogFormatter):
        label = "Rename"
        def format_message(self, log_entry):
            try: return "Renamed from '%(old)s' to '%(new)s'" % {'old': log_entry.data['title']['old'],'new': log_entry.data['title']['new'],}
            except KeyError: return "Renamed"
    @actions.register_action('reverted')
    class RevertActionFormatter(LogFormatter):
        label = "Revert"
        def format_message(self, log_entry):
            try: return "Reverted to previous revision with id %(revision_id)s from %(created_at)s" % { 'revision_id': log_entry.data['revision']['id'], 'created_at': log_entry.data['revision']['created'], }
            except KeyError: return "Reverted to previous revision"
    @actions.register_action('copied')
    class CopyActionFormatter(LogFormatter):
        label = "Copy"
        def format_message(self, log_entry):
            try: return "Copied from %(title)s" % { 'title': log_entry.data['source']['title'], }
            except KeyError: return "Copied"
    @actions.register_action('alias_created')
    class CreateAliasActionFormatter(LogFormatter):
        label = "Create alias"
        def format_message(self, log_entry):
            try: return "Created an alias of %(title)s" % {'title': log_entry.data['source']['title'],}
            except KeyError: return "Created an alias"
    @actions.register_action('alias_converted')
    class ConvertAliasActionFormatter(LogFormatter):
        label = "Convert alias into ordinary page"
        def format_message(self, log_entry):
            try: return "Converted the alias '%(title)s' into an ordinary page" % { 'title': log_entry.data['page']['title'], }
            except KeyError: return "Converted an alias into an ordinary page"
    @actions.register_action('moved')
    class MoveActionFormatter(LogFormatter):
        label = "Move"
        def format_message(self, log_entry):
            try: return "Moved from '%(old_parent)s' to '%(new_parent)s'" % { 'old_parent': log_entry.data['source']['title'], 'new_parent': log_entry.data['destination']['title'], }
            except KeyError: return "Moved"
    @actions.register_action('reordered')
    class ReorderActionFormatter(LogFormatter):
        label = "Reorder"
        def format_message(self, log_entry):
            try: return "Reordered under '%(parent)s'" % { 'parent': log_entry.data['destination']['title'], }
            except KeyError: return "Reordered"
    @actions.register_action('publishing_scheduled')
    class SchedulePublishActionFormatter(LogFormatter):
        label = "Schedule publication"
        def format_message(self, log_entry):
            try:
                if log_entry.data['revision']['has_live_version']: return "Revision %(revision_id)s from %(created_at)s scheduled for publishing at %(go_live_at)s." % {'revision_id': log_entry.data['revision']['id'],'created_at': log_entry.data['revision']['created'],'go_live_at': log_entry.data['revision']['go_live_at'],}
                else: return "Page scheduled for publishing at %(go_live_at)s" % {'go_live_at': log_entry.data['revision']['go_live_at'],}
            except KeyError: return "Page scheduled for publishing"
    @actions.register_action('publishing_schedule_canceled')
    class UnschedulePublicationActionFormatter(LogFormatter):
        label = "Unschedule publication"
        def format_message(self, log_entry):
            try:
                if log_entry.data['revision']['has_live_version']: return "Revision %(revision_id)s from %(created_at)s unscheduled from publishing at %(go_live_at)s." % {'revision_id': log_entry.data['revision']['id'],'created_at': log_entry.data['revision']['created'],'go_live_at': log_entry.data['revision']['go_live_at'],}
                else: return "Page unscheduled for publishing at %(go_live_at)s" % {'go_live_at': log_entry.data['revision']['go_live_at'],}
            except KeyError: return "Page unscheduled from publishing"
    @actions.register_action('view_restriction_added')
    class AddViewRestrictionActionFormatter(LogFormatter):
        label = "Add view restrictions"
        def format_message(self, log_entry):
            try: return "Added the '%(restriction)s' view restriction" % { 'restriction': log_entry.data['restriction']['title'], }
            except KeyError: return "Added view restriction"
    @actions.register_action('view_restriction_changed')
    class EditViewRestrictionActionFormatter(LogFormatter):
        label = "Update view restrictions"
        def format_message(self, log_entry):
            try: return "Updated the view restriction to '%(restriction)s'" % { 'restriction': log_entry.data['restriction']['title'], }
            except KeyError: return "Updated view restriction"
    @actions.register_action('view_restriction_deleted')
    class DeleteViewRestrictionActionFormatter(LogFormatter):
        label = "Remove view restrictions"
        def format_message(self, log_entry):
            try: return "Removed the '%(restriction)s' view restriction" % { 'restriction': log_entry.data['restriction']['title'], }
            except KeyError: return "Removed view restriction"
    class WorkflowLogFormatter(LogFormatter):
        def format_comment(self, log_entry): return log_entry.data.get('comment', '')
    @actions.register_action('workflow_started')
    class StartWorkflowActionFormatter(WorkflowLogFormatter): 
        label = "Workflow: start"
        def format_message(self, log_entry):
            try: return "'%(workflow)s' started. Next step '%(task)s'" % {'workflow': log_entry.data['workflow']['title'],'task': log_entry.data['workflow']['next']['title'],}
            except (KeyError, TypeError): return "Workflow started"
    @actions.register_action('workflow_approved')
    class ApproveWorkflowActionFormatter(WorkflowLogFormatter):
        label = "Workflow: approve task"
        def format_message(self, log_entry):
            try:
                if log_entry.data['workflow']['next']: return "Approved at '%(task)s'. Next step '%(next_task)s'" % {'task': log_entry.data['workflow']['task']['title'],'next_task': log_entry.data['workflow']['next']['title'],}
                else: return "Approved at '%(task)s'. '%(workflow)s' complete" % {'task': log_entry.data['workflow']['task']['title'],'workflow': log_entry.data['workflow']['title'],}
            except (KeyError, TypeError): return "Workflow task approved"
    @actions.register_action('workflow_rejected')
    class RejectWorkflowActionFormatter(WorkflowLogFormatter):
        label = "Workflow: reject task"
        def format_message(self, log_entry):
            try: return "Rejected at '%(task)s'. Changes requested" % {'task': log_entry.data['workflow']['task']['title'],}
            except (KeyError, TypeError): return "Workflow task rejected. Workflow complete"
    @actions.register_action('workflow_resumed')
    class ResumeWorkflowActionFormatter(WorkflowLogFormatter):
        label = "Workflow: resume task"
        def format_message(self, log_entry):
            try: return "Resubmitted '%(task)s'. Workflow resumed'" % {'task': log_entry.data['workflow']['task']['title'],}
            except (KeyError, TypeError): return "Workflow task resubmitted. Workflow resumed"
    @actions.register_action('workflow_canceled')
    class CancelWorkflowActionFormatter(WorkflowLogFormatter):
        label = "Workflow: cancel"
        def format_message(self, log_entry):
            try: return "Cancelled '%(workflow)s' at '%(task)s'" % {'workflow': log_entry.data['workflow']['title'],'task': log_entry.data['workflow']['task']['title'],}
            except (KeyError, TypeError): return "Workflow cancelled"
