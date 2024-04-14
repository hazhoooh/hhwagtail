from django.apps import AppConfig



class WagtailFormsAppConfig(AppConfig):
    name = 'wagtail.contrib.forms'
    label = 'wagtailforms'
    verbose_name = "Wagtail forms"
    default_auto_field = 'django.db.models.AutoField'
