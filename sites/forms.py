from django import forms


from wagtail.admin.widgets import AdminPageChooser
from wagtail.core.models import Site


class SiteForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['root_page'].widget = AdminPageChooser(show_clear_link=False)

    class Meta:
        model = Site
        fields = ('hostname', 'port', 'site_name', 'root_page', 'is_default_site')
