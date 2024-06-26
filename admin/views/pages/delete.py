from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.contrib import messages
from django.db import models

from wagtail.admin import messages
from wagtail.admin.views.pages.utils import get_valid_next_url_from_request
from wagtail.core import hooks
from wagtail.core.models import Page


def delete(request, page_id):
    page = get_object_or_404(Page, id=page_id).specific
    if not page.permissions_for_user(request.user).can_delete(): raise PermissionDenied
    with transaction.atomic():
        for fn in hooks.get_hooks('before_delete_page'):
            result = fn(request, page)
            if hasattr(result, 'status_code'): return result
        next_url = get_valid_next_url_from_request(request)
        if request.method == 'POST':
            parent_id = page.get_parent().id
            try:
                page.delete(user=request.user)
                messages.success(request, "Page '{0}' deleted.".format(page.get_admin_display_title()))
            except models.ProtectedError: messages.warning(request, f"Page '{page.get_admin_display_title()}' could not be deleted because it has a linked/related page (most probably a page had select this page as a refrence to itself)")
            
            for fn in hooks.get_hooks('after_delete_page'):
                result = fn(request, page)
                if hasattr(result, 'status_code'): return result
            if next_url: return redirect(next_url)
            return redirect('wagtailadmin_pages:explore', parent_id)
    return TemplateResponse(request, 'cms/pages/confirm_delete.html', {'page': page,'descendant_count': page.get_descendant_count(),'next': next_url,})
