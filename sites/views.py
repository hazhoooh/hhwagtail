

from wagtail.admin.ui.components import Column, TitleColumn
from wagtail.admin.views import generic
from wagtail.admin.viewsets.model import ModelViewSet
from wagtail.core.models import Site
from wagtail.core.permissions import site_permission_policy
from wagtail.sites.forms import SiteForm

class IndexView(generic.IndexView):
    page_title = "Sites"
    add_item_label = "Add a site"
    context_object_name = 'sites'
    columns = [
        TitleColumn('hostname', label="Site", url_name='wagtailsites:edit'),
        Column('port'),
        Column('site_name'),
        Column('root_page'),
        Column('is_default_site') ,
    ]

class CreateView(generic.CreateView):
    page_title = "Add site"
    success_message = "Site '{0}' created."
    template_name = 'wagtailsites/create.html'

class EditView(generic.EditView):
    success_message = "Site '{0}' updated."
    error_message = "The site could not be saved due to errors."
    delete_item_label = "Delete site"
    context_object_name = 'site'
    template_name = 'wagtailsites/edit.html'

class DeleteView(generic.DeleteView):
    success_message = "Site '{0}' deleted."
    page_title = "Delete site"
    confirmation_message = "Are you sure you want to delete this site?"

class SiteViewSet(ModelViewSet):
    icon = '🌐'
    model = Site
    permission_policy = site_permission_policy
    index_view_class = IndexView
    add_view_class = CreateView
    edit_view_class = EditView
    delete_view_class = DeleteView
    def get_form_class(self, for_update=False): return SiteForm
