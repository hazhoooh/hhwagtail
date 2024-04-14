from django.contrib.auth.models import Permission
from django.urls import reverse


from wagtail.admin.menu import MenuItem
from wagtail.admin.site_summary import SummaryItem
from wagtail.core import hooks
from wagtail.core.models import Site
from wagtail.core.permissions import site_permission_policy

from .views import SiteViewSet


@hooks.register('register_admin_viewset')
def register_viewset():
    return SiteViewSet('wagtailsites', url_prefix='sites')


class SitesMenuItem(MenuItem):
    def is_shown(self, request):return site_permission_policy.user_has_any_permission(request.user, ['add', 'change', 'delete'])


@hooks.register('register_console_menu_item')
def register_sites_menu_item():return SitesMenuItem(f'🌐 Sites ({Site.objects.count()})', reverse('wagtailsites:index'),icon_name='', order=3000)


@hooks.register('register_permissions')
def register_permissions():return Permission.objects.filter(content_type__app_label='wagtailcore',codename__in=['add_site', 'change_site', 'delete_site'])


class SiteSummaryItem(SummaryItem):
    order=500
    template_name='wagtailsettings/site_summary.html'
    def is_shown(self): return site_permission_policy.user_has_any_permission(self.request.user, ['add', 'change', 'delete'])

    def get_context_data(self, parent_context):
        # site_details = get_site_for_user(self.request.user)
        # root_page = site_details['root_page']
        # site_name = site_details['site_name']

        if self.request.user.is_superuser:
            site_count = f'{Site.objects.count()}'
        else:
            site_count = ''

        return {
            'total_sites': site_count,
        }

@hooks.register('construct_console_boards_summary_items')
def add_site_summary_item(request, items): items.append(SiteSummaryItem(request))

