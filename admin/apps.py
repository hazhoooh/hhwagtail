from django.apps import AppConfig


from . import checks  # NOQA


class WagtailAdminAppConfig(AppConfig):
    name = 'wagtail.admin'
    label = 'wagtailadmin'
    verbose_name = "console"
    default_auto_field = 'django.db.models.AutoField'

    def ready(self):
        from wagtail.admin.signal_handlers import register_signal_handlers
        register_signal_handlers()
