from django.urls import include, path, reverse
from wagtail.admin.menu import MenuItem
from wagtail.admin.site_summary import SummaryItem
from wagtail.contrib.forms import urls
from wagtail.contrib.forms.utils import get_forms_for_user
from wagtail.core import hooks

@hooks.register('register_admin_urls')
def register_admin_urls():
    return [
        path('forms/', include(urls, namespace='wagtailforms')),
    ]

class FormsMenuItem(MenuItem):
    def is_shown(self, request):
        # show this only if the user has permission to retrieve submissions for at least one form
        return get_forms_for_user(request.user).exists()

@hooks.register('register_console_menu_item')
def register_forms_menu_item():
    return FormsMenuItem('📝 Forms', reverse('wagtailforms:index'),name='forms', icon_name='', order=400)

class FormSummaryItem(SummaryItem):
    label="Forms Submissions"
    order=400
    template_name='wagtailforms/console_boards/forms.html'
    icon_name=''
    def get_context_data(self, parent_context):
        context_data = super().get_context_data(parent_context)
        from base.models import FormPage,HHFormSubmission
        if self.request.user.is_superuser:
            context_data["submissions_counter"]=f"{HHFormSubmission.objects.count()} <sub>sub. of</sub> {FormPage.objects.count()} <sub>forms</sub>"
        return context_data
    def is_shown(self):
        # return self.request.user.has_perm('add')
        return get_forms_for_user(self.request.user).exists()

@hooks.register('construct_console_boards_summary_items')
def add_forms_summary_item(request, items):
    items.append(FormSummaryItem(request))
