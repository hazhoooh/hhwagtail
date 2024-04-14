from warnings import warn
from django.forms import Media
from django.template.loader import get_template, render_to_string
from django.utils.functional import cached_property
from wagtail.admin.ui.components import Component
from wagtail.core import hooks
from wagtail.utils.deprecation import RemovedInWagtail217Warning

class SummaryItem(Component):
    label = 'Summary Item' 
    order = 1
    template = None
    def __init__(self, request): self.request = request
    def get_context(self): return {"default_context_var":"defaultVar"}
    get_context.is_base_method = True
    def render(self): return render_to_string(self.template, self.get_context(), request=self.request)
    render.is_base_method = True
    def get_context_data(self, parent_context):
        if parent_context is None: parent_context=self.get_context()
        context_data = super().get_context_data(parent_context)
        context_data["label"]=self.label
        return context_data
    def render_html(self, parent_context=None):
        if not getattr(self.render, 'is_base_method', False):
            # this SummaryItem subclass has overridden render() - use their implementation in preference to following the Component.render_html path
            message = (f"Summary item {self} should provide render_html(self, parent_context) rather than render(self). See https://docs.wagtail.io/en/stable/releases/2.15.html#template-components-2-15")
            warn(message, category=RemovedInWagtail217Warning)
            return self.render()
        elif not getattr(self.get_context, 'is_base_method', False):
            # this SummaryItem subclass has overridden get_context() - use their implementation in preference to Component.get_context_data
            message = (f"Summary item {self} should provide get_context_data(self, parent_context) rather than get_context(self). See https://docs.wagtail.io/en/stable/releases/2.15.html#template-components-2-15")
            warn(message, category=RemovedInWagtail217Warning)
            context_data = self.get_context()
        else: context_data = self.get_context_data(parent_context)
        if self.template is not None:
            warn(f"{type(self).__name__} should define template_name instead of template. See https://docs.wagtail.io/en/stable/releases/2.15.html#template-components-2-15",category=RemovedInWagtail217Warning)
            template_name = self.template
        else: template_name = self.template_name
        template = get_template(template_name)
        return template.render(context_data)
    def is_shown(self): return True

class SiteSummaryPanel(Component):
    name = 'site_summary'
    template_name = 'console/boards.html'
    order = 1
    def __init__(self, request):
        self.request = request
        items = []
        for fn in hooks.get_hooks('construct_console_boards_summary_items'): fn(request, items)
        self.items = [i for i in items if i.is_shown()]
        self.items.sort(key=lambda i: i.order)
    def get_context_data(self, parent_context):
        context = super().get_context_data(parent_context)
        context['summary_items'] = self.items
        return context
    @cached_property
    def media(self):
        media = Media()
        for i in self.items: media += i.media
        return media
