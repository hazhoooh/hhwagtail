from django.apps import AppConfig

class WagtailCoreAppConfig(AppConfig):
    name = 'wagtail.core'
    label = 'wagtailcore'
    verbose_name = "Wagtail core"
    default_auto_field = 'django.db.models.AutoField'

    def ready(self):
        from wagtail.core.signal_handlers import register_signal_handlers
        register_signal_handlers()
        from wagtail.core import widget_adapters  # noqa
