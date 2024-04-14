from django.forms import widgets

class SwitchInput(widgets.CheckboxInput): template_name = 'cms/widgets/switch.html'
