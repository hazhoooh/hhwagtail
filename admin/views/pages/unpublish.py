from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _

from wagtail.admin import messages
from wagtail.admin.views.pages.utils import get_valid_next_url_from_request
from wagtail.core import hooks
from wagtail.core.models import Page, UserPagePermissionsProxy


def unpublish(request, page_id):
    page = get_object_or_404(Page, id=page_id).specific

    user_perms = UserPagePermissionsProxy(request.user)
    if not user_perms.for_page(page).can_unpublish():
        raise PermissionDenied

    next_url = get_valid_next_url_from_request(request)

    if request.method == 'POST':
        include_descendants = request.POST.get("include_descendants", False)

        for fn in hooks.get_hooks('before_unpublish_page'):
            result = fn(request, page)
            if hasattr(result, 'status_code'):
                return result

        page.unpublish(user=request.user)

        if include_descendants:
            for live_descendant_page in page.get_descendants().live().defer_streamfields().specific():
                if user_perms.for_page(live_descendant_page).can_unpublish():
                    live_descendant_page.unpublish()

        for fn in hooks.get_hooks('after_unpublish_page'):
            result = fn(request, page)
            if hasattr(result, 'status_code'):
                return result

        messages.success(request, "Page '{0}' unpublished.".format(page.get_admin_display_title()), buttons=[
            messages.button(reverse('wagtailadmin_pages:edit', args=(page.id,)), "Edit")
        ])

        if next_url:
            return redirect(next_url)
        return redirect('wagtailadmin_pages:explore', page.get_parent().id)

    return TemplateResponse(request, 'cms/pages/confirm_unpublish.html', {
        'page': page,
        'next': next_url,
        'live_descendant_count': page.get_descendants().live().count(),
    })
