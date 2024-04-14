from django.apps import AppConfig



class WagtailUsersAppConfig(AppConfig):
    name = 'wagtail.users'
    label = 'wagtailusers'
    verbose_name = "Wagtail users"
    default_auto_field = 'django.db.models.AutoField'
    group_viewset = 'wagtail.users.views.groups.GroupViewSet'
