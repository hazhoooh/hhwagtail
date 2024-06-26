from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from wagtail.admin.forms.collections import CollectionViewRestrictionForm
from wagtail.admin.modal_workflow import render_modal_workflow
from wagtail.core.models import Collection, CollectionViewRestriction
from wagtail.core.permissions import collection_permission_policy


def set_privacy(request, collection_id):
    collection = get_object_or_404(Collection, id=collection_id)
    if not collection_permission_policy.user_has_permission(request.user, 'change'): raise PermissionDenied
    restrictions = collection.get_view_restrictions().order_by('collection__depth')
    if restrictions:
        restriction = restrictions[0]
        restriction_exists_on_ancestor = (restriction.collection != collection)
    else:
        restriction = None
        restriction_exists_on_ancestor = False
    if request.method == 'POST':
        form = CollectionViewRestrictionForm(request.POST, instance=restriction)
        if form.is_valid() and not restriction_exists_on_ancestor:
            if form.cleaned_data['restriction_type'] == CollectionViewRestriction.NONE:
                if restriction: restriction.delete()
            else:
                restriction = form.save(commit=False)
                restriction.collection = collection
                form.save()
            return render_modal_workflow(request, None, None,None, json_data={'step': 'set_privacy_done','is_public': (form.cleaned_data['restriction_type'] == 'none')})
    else:
        if not restriction_exists_on_ancestor:
            if restriction:form = CollectionViewRestrictionForm(instance=restriction)
            else: form = CollectionViewRestrictionForm(initial={'restriction_type': 'none'})
    if restriction_exists_on_ancestor: return render_modal_workflow(request, 'cms/collections/ancestor_privacy.html', None,{'collection_with_restriction': restriction.collection,})
    else: return render_modal_workflow(request, 'cms/collections/set_privacy.html', None, {'collection': collection,'form': form,}, json_data={'step': 'set_privacy'})
