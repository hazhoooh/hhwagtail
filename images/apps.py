from django.apps import AppConfig


from . import checks  # NOQA


class WagtailImagesAppConfig(AppConfig):
    name = 'wagtail.images'
    label = 'wagtailimages'
    verbose_name = "Wagtail images"
    default_auto_field = 'django.db.models.AutoField'

    def ready(self):
        from wagtail.images.signal_handlers import register_signal_handlers
        register_signal_handlers()
