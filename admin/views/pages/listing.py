from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from wagtail.admin.auth import user_has_any_page_permission, user_passes_test
from wagtail.admin.navigation import get_explorable_root_page
from wagtail.core import hooks
from wagtail.core.models import Page, UserPagePermissionsProxy

@user_passes_test(user_has_any_page_permission)
def index(request, parent_page_id=None):
    if parent_page_id: parent_page = get_object_or_404(Page, id=parent_page_id)
    else: parent_page = Page.get_first_root_node()
    # This will always succeed because of the @user_passes_test above.
    root_page = get_explorable_root_page(request.user)
    # If this page isn't a descendant of the user's explorable root page, then redirect to that explorable root page instead.
    if not (parent_page.pk == root_page.pk or parent_page.is_descendant_of(root_page)): return redirect('wagtailadmin_pages:explore', root_page.pk)
    parent_page = parent_page.specific
    user_perms = UserPagePermissionsProxy(request.user)
    pages = (parent_page.get_children().prefetch_related("content_type", "sites_rooted_here") & user_perms.explorable_pages())
    # We want specific page instances, but do not need streamfield values here
    pages = pages.defer_streamfields().specific()
    ordering = 'path'
    pages.order_by(ordering)
    do_paginate = False
    # allow hooks defer_streamfields queryset
    for hook in hooks.get_hooks('construct_explorer_page_queryset'): pages = hook(parent_page, pages, request)
    # Annotate queryset with various states to be used later for performance optimisations
    if getattr(settings, 'CONSOLE_WORKFLOW_ENABLED', True): pages = pages.prefetch_workflow_states()
    pages = pages.annotate_site_root_state().annotate_approved_schedule()
    # Pagination
    # if do_paginate:
    #     paginator = Paginator(pages, per_page=50)
    #     pages = paginator.get_page(request.GET.get('p'))
    context = {
        'parent_page': parent_page.specific,
        'ordering': ordering,
        'pagination_query_params': "ordering=%s" % ordering,
        'pages': pages,
        # 'do_paginate': do_paginate
    }
    return TemplateResponse(request, 'cms/pages/index.html', context)
