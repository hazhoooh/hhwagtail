from django import template
from django.template.loader import render_to_string
from django.views.debug import SafeExceptionReporterFilter
from wagtail.admin.userbar import AddPageItem, AdminItem, ApproveModerationEditPageItem, EditPageItem, ExplorePageItem,RejectModerationEditPageItem
from wagtail.core import hooks
from wagtail.core.models import PAGE_TEMPLATE_VAR, Page, PageRevision

register = template.Library()

def get_page_instance(context):
    """ Given a template context, try and find a Page variable in the common places. Returns None if a page can not be found.  """
    possible_names = [PAGE_TEMPLATE_VAR, 'self']
    for name in possible_names:
        if name in context:
            page = context[name]
            if isinstance(page, Page): return page

@register.simple_tag(takes_context=True)
def userbar(context):
    try: request = context['request']
    except KeyError: return ''
    try: user = request.user
    except AttributeError: return ''
    if not user.has_perm('wagtailadmin.access_admin'): return ''
    page = get_page_instance(context)
    try: revision_id = request.revision_id
    except AttributeError: revision_id = None
    if page and page.id:
        if revision_id:
            items = [
                AdminItem(),
                ExplorePageItem(PageRevision.objects.get(id=revision_id).page),
                EditPageItem(PageRevision.objects.get(id=revision_id).page),
                ApproveModerationEditPageItem(PageRevision.objects.get(id=revision_id)),
                RejectModerationEditPageItem(PageRevision.objects.get(id=revision_id)),
            ]
        else:
            items = [
                AdminItem(),
                ExplorePageItem(Page.objects.get(id=page.id)),
                EditPageItem(Page.objects.get(id=page.id)),
                AddPageItem(Page.objects.get(id=page.id)),
            ]
    else: items = [AdminItem()]
    for fn in hooks.get_hooks('construct_console_userbar_for_visitors_end'): fn(request, items)
    rendered_items = [item.render(request) for item in items]
    # rendered_items = [item for item in rendered_items if item]
    return render_to_string('cms/userbar/base.html', {
        'request': request,
        'items': rendered_items,
        'debug_safe_settings':SafeExceptionReporterFilter().get_safe_settings() if user.is_superuser and request.GET.get("debug") else None, # ?debug=1 in the request url
        'context': context if user.is_superuser else None,
        'page': page,
        'revision_id': revision_id
    })
