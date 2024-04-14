from django.contrib.auth.models import Group
from django.urls import re_path
from wagtail.admin.ui.components import TitleColumn
from wagtail.admin.views import generic, mixins
from wagtail.admin.viewsets.model import ModelViewSet
from wagtail.core import hooks
from wagtail.users.forms import GroupForm, GroupPagePermissionFormSet
from wagtail.users.views.users import index

_permission_panel_classes = None

def get_permission_panel_classes():
    global _permission_panel_classes
    if _permission_panel_classes is None:
        _permission_panel_classes = [GroupPagePermissionFormSet]
        for fn in hooks.get_hooks('register_group_permission_panel'): _permission_panel_classes.append(fn())
    return _permission_panel_classes

class PermissionPanelFormsMixin:
    def get_permission_panel_form_kwargs(self, cls):
        kwargs = {}
        if self.request.method in ('POST', 'PUT'): kwargs.update({'data': self.request.POST,'files': self.request.FILES,})
        if hasattr(self, 'object'): kwargs.update({'instance': self.object})
        return kwargs
    def get_permission_panel_forms(self): return [cls(**self.get_permission_panel_form_kwargs(cls)) for cls in get_permission_panel_classes()]
    def get_context_data(self, **kwargs):
        if 'permission_panels' not in kwargs: kwargs['permission_panels'] = self.get_permission_panel_forms()
        return super().get_context_data(**kwargs)

class IndexView(mixins.SearchableListMixin, generic.IndexView):
    page_title = "Groups"
    add_item_label = "Add a group"
    search_box_placeholder = "Search groups"
    search_fields = ['name']
    context_object_name = 'groups'
    paginate_by = 100
    ordering = ['name']
    default_ordering = 'name'
    columns = [TitleColumn('name', label="Name", sort_key='name', url_name='wagtailusers_groups:edit'),]
    def get_template_names(self):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest': return ['wagtailusers/groups/results.html']
        else: return ['wagtailusers/groups/index.html']

class CreateView(generic.CreateView):
    page_title = "Add group"
    success_message = "Group created."
    template_name = 'wagtailusers/groups/create.html'
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # add a 'form_media' variable for the collected js/css media from the form and all formsets
        form_media = context['form'].media
        # for panel in context['permission_panels']: form_media += panel.media
        context['form_media'] = form_media
        return context

class EditView(PermissionPanelFormsMixin, generic.EditView):
    success_message = "Group '{0}' updated."
    error_message = "The group could not be saved due to errors."
    delete_item_label = "Delete group"
    context_object_name = 'group'
    template_name = 'wagtailusers/groups/edit.html'

    def post(self, request, *args, **kwargs):
        """ Handle POST requests: instantiate a form instance with the passed POST variables and then check if it's valid. """
        self.object = self.get_object()
        form = self.get_form()
        permission_panels = self.get_permission_panel_forms()
        if form.is_valid() and all(panel.is_valid() for panel in permission_panels):
            response = self.form_valid(form)
            for panel in permission_panels: panel.save()
            return response
        else: return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # add a 'form_media' variable for the collected js/css media from the form and all formsets
        form_media = context['form'].media
        for panel in context['permission_panels']: form_media += panel.media
        context['form_media'] = form_media
        return context

class DeleteView(generic.DeleteView):
    success_message = "Group '{0}' deleted."
    page_title = "Delete group"
    confirmation_message = "Are you sure you want to delete this group?"
    template_name = 'wagtailusers/groups/confirm_delete.html'

class GroupViewSet(ModelViewSet):
    icon = 'group'
    model = Group
    index_view_class = IndexView
    add_view_class = CreateView
    edit_view_class = EditView
    delete_view_class = DeleteView
    @property
    def users_view(self): return index
    def get_form_class(self, for_update=False): return GroupForm
    def get_urlpatterns(self): return super().get_urlpatterns() + [re_path(r'(\d+)/users/$', self.users_view, name='users'),]
