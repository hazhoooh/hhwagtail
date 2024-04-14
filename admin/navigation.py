from django.conf import settings

from wagtail.core.models import Page, Site


def get_pages_with_direct_explore_permission(user):
    # Get all pages that the user has direct add/edit/publish/lock permission on
    if user.is_superuser: return Page.objects.filter(depth=1)
    else: return Page.objects.filter(group_permissions__group__in=user.groups.all(),group_permissions__permission_type__in=['add', 'edit', 'publish', 'lock'])


def get_pages_with_direct_edit_and_publish_permission(user):
    from django.db.models import Q
    if user.is_superuser: return Page.objects.filter(depth=1)
    else:
        edit_permission_query = Q(group_permissions__group__in=user.groups.all(), group_permissions__permission_type='edit')
        publish_permission_query = Q(group_permissions__group__in=user.groups.all(), group_permissions__permission_type='publish')
        combined_query = edit_permission_query & publish_permission_query
        return Page.objects.filter(combined_query)
    
    # else: return Page.objects.filter(group_permissions__group__in=user.groups.all(),group_permissions__permission_type__in=['edit'])


def get_explorable_root_page(user):
    pages = get_pages_with_direct_explore_permission(user)
    try: return pages.first_common_ancestor(include_self=True,strict=True)
    except Page.DoesNotExist: return None

def get_site_admins_root_page(user):
    pages = get_pages_with_direct_edit_and_publish_permission(user)
    try: return pages.first_common_ancestor(include_self=True,strict=True)
    except Page.DoesNotExist: return None


def get_site_for_user(user):
    root_page = get_explorable_root_page(user)
    default_site=Site.objects.get(is_default_site=True)
    if root_page: root_pg_site = root_page.get_site() or default_site
    else: root_pg_site = default_site
    if root_pg_site: sn = root_pg_site.site_name or root_pg_site.hostname
    else: sn = settings.CONSOLE_SITE_NAME
    return {
        'root_page': root_page,
        'root_pg_site': root_pg_site,
        'site_name': sn,
    }

def get_sites_for_user(user):
    root_page = get_explorable_root_page(user)
    user_sites = []
    for site in Site.objects.all():
        if root_page and root_page.get_site() == site: user_sites.append(site)
    return user_sites

# def get_sites_for_site_admin_user(user):
#     from wagtail.core.models import Site
#     root_page = get_site_admins_root_page(user)
#     default_site=Site.objects.get(is_default_site=True)
#     return 
