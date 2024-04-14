from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q
from django.urls import include, path, reverse
from django.utils.module_loading import import_string
from django.http import HttpResponseForbidden

from wagtail.admin.admin_url_finder import ModelAdminURLFinder, register_admin_url_finder
from wagtail.admin.menu import MenuItem
from wagtail.admin.site_summary import SummaryItem
from wagtail.admin.search import SearchArea
from wagtail.core import hooks
from wagtail.core.compat import AUTH_USER_APP_LABEL, AUTH_USER_MODEL_NAME
from wagtail.core.permission_policies import ModelPermissionPolicy
from wagtail.users.urls import users
from wagtail.users.utils import user_can_delete_user, user_can_delete_group
from wagtail.users.views.bulk_actions import AssignRoleBulkAction, DeleteBulkAction, SetActiveStateBulkAction
from wagtail.users.widgets import UserListingButton

@hooks.register('register_admin_urls')
def register_admin_urls(): return [path('users/', include(users, namespace='wagtailusers_users'))]

@hooks.register('register_log_actions')
def register_core_log_actions(actions):
    actions.register_action('users.create', "Create", "Created")
    actions.register_action('users.edit', "Edit", "Edited")
    actions.register_action('users.delete', "Delete", "Deleted")

def get_group_viewset_cls(app_config):
    try: group_viewset_cls = import_string(app_config.group_viewset)
    except (AttributeError, ImportError) as e: raise ImproperlyConfigured("Invalid setting for {appconfig}.group_viewset: {message}".format(appconfig=app_config.__class__.__name__,message=e))
    return group_viewset_cls

@hooks.register('register_admin_viewset')
def register_viewset():
    app_config = apps.get_app_config("wagtailusers")
    group_viewset_cls = get_group_viewset_cls(app_config)
    return group_viewset_cls('wagtailusers_groups', url_prefix='groups') # TODO: know why the viewset is not needing the URLs

# Typically we would check the permission 'auth.change_user' (and 'auth.add_user'  'auth.delete_user') for user management actions, but this may vary according to the AUTH_USER_MODEL setting
add_user_perm = "{0}.add_{1}".format(AUTH_USER_APP_LABEL, AUTH_USER_MODEL_NAME.lower())
change_user_perm = "{0}.change_{1}".format(AUTH_USER_APP_LABEL, AUTH_USER_MODEL_NAME.lower())
delete_user_perm = "{0}.delete_{1}".format(AUTH_USER_APP_LABEL, AUTH_USER_MODEL_NAME.lower())
User=get_user_model()

class UsersMenuItem(MenuItem):
    def is_shown(self, request): return (request.user.has_perm(add_user_perm) or request.user.has_perm(change_user_perm) or request.user.has_perm(delete_user_perm))

@hooks.register('register_console_menu_item')
def register_users_menu_item(): return UsersMenuItem('🤵 Users',reverse('wagtailusers_users:index'),icon_name='',order=1400)

class UsersSummaryItem(SummaryItem):
    order=600
    template_name='wagtailusers/users_summary.html'
    def is_shown(self): return (self.request.user.has_perm(add_user_perm) or self.request.user.has_perm(change_user_perm) or self.request.user.has_perm(delete_user_perm))
    def get_context_data(self, parent_context):
        if self.request.user.is_superuser: user_count = f'{User.objects.count()}'
        else: user_count = ''
        return {'total_users': user_count,}

@hooks.register('construct_console_boards_summary_items')
def users_summary_item(request, items): items.append(UsersSummaryItem(request))

class GroupsMenuItem(MenuItem, SummaryItem):
    def is_shown(self, request): return (request.user.has_perm('auth.add_group')or request.user.has_perm('auth.change_group')or request.user.has_perm('auth.delete_group'))

@hooks.register('register_console_menu_item')
def register_groups_menu_item(): return GroupsMenuItem('👪 Groups',reverse('wagtailusers_groups:index'),icon_name='',order=1401)

class GroupsSummaryItem(SummaryItem):
    order=601
    template_name='wagtailusers/groups_summary.html'
    def is_shown(self): return (self.request.user.has_perm('auth.add_group') or self.request.user.has_perm('auth.change_group') or self.request.user.has_perm('auth.delete_group'))
    def get_context_data(self, parent_context):
        from django.contrib.auth.models import Group
        if self.request.user.is_superuser: group_count = f'{Group.objects.count()}'
        else: group_count = ''
        return {'total_groups': group_count,}

@hooks.register('construct_console_boards_summary_items')
def groups_summary_item(request, items): items.append(GroupsSummaryItem(request))

@hooks.register('register_permissions')
def register_permissions():
    user_permissions = Q(content_type__app_label=AUTH_USER_APP_LABEL, codename__in=[
        'add_%s' % AUTH_USER_MODEL_NAME.lower(),
        'change_%s' % AUTH_USER_MODEL_NAME.lower(),
        'delete_%s' % AUTH_USER_MODEL_NAME.lower(),
    ])
    group_permissions = Q(content_type__app_label='auth', codename__in=['add_group', 'change_group', 'delete_group'])
    return Permission.objects.filter(user_permissions | group_permissions)

class UsersSearchArea(SearchArea):
    def is_shown(self, request): return (request.user.has_perm(add_user_perm) or request.user.has_perm(change_user_perm) or request.user.has_perm(delete_user_perm))

@hooks.register('register_admin_search_area')
def register_users_search_area():
    return UsersSearchArea("Users", reverse('wagtailusers_users:index'),name='users',icon_name='user',order=600)

@hooks.register('register_user_listing_buttons')
def user_listing_buttons(context, user):
    yield UserListingButton("✎", reverse('wagtailusers_users:edit', args=[user.pk]), attrs={'title': "Edit this user"}, priority=10)
    if user_can_delete_user(context.request.user, user):
        yield UserListingButton(" ", reverse('wagtailusers_users:delete', args=[user.pk]), classes={'no i_doughnut i_trash'}, attrs={'title': "Delete this user"}, priority=20)

@hooks.register('register_group_listing_buttons')
def group_listing_buttons(context, group):
    yield UserListingButton("View Group Users", reverse('wagtailusers_groups:users', args=[group.pk]), attrs={'title': "See Users of this Group"}, priority=10)
    yield UserListingButton("✎", reverse('wagtailusers_groups:edit', args=[group.pk]), attrs={'title': "Edit this Group"}, priority=20)
    if user_can_delete_group(context.request.user, group):
        yield UserListingButton(" ", reverse('wagtailusers_groups:delete', args=[group.pk]), classes={'no i_doughnut i_trash'}, attrs={'title': "Delete this Group"}, priority=30)

class UserAdminURLFinder(ModelAdminURLFinder):
    edit_url_name = 'wagtailusers_users:edit'
    permission_policy = ModelPermissionPolicy(User)

register_admin_url_finder(User, UserAdminURLFinder)

for action_class in [AssignRoleBulkAction, DeleteBulkAction, SetActiveStateBulkAction]:
    hooks.register('register_bulk_action', action_class)

# @hooks.register('before_edit_user')
# def check_user_permissions(request, user):
#     from wagtail.core.models import UserPagePermissionsProxy, Site
#     # Get the current site from the request
#     site = Site.find_for_request(request)

#     # Get the user's permissions for the current site
#     site_perms = UserPagePermissionsProxy(user).for_site(site)

#     # Check if the user can edit users on this site and if the user instance belongs to this site
#     if not (site_perms.can_edit_users() and site in user.wagtail_userprofile.sites.all()):
#         # Return a forbidden response
#         return HttpResponseForbidden("You don't have permission to edit this user on this site.")
