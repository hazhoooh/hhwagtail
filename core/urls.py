from django.conf import settings
from django.contrib.auth import views as auth_views
from django.urls import path, re_path

from wagtail.core import views
from wagtail.core.utils import APPEND_SLASH


if APPEND_SLASH:
    # If APPEND_SLASH is True (the default value), we match a
    # (possibly empty) list of path segments ending in slashes.
    # CommonMiddleware will redirect requests without a trailing slash to
    # a URL with a trailing slash
    serve_pattern = r'^((?:[\w\-]+/)*)$'
else:
    # If APPEND_SLASH is False, allow Wagtail to serve pages on URLs
    # with and without trailing slashes
    serve_pattern = r'^([\w\-/]*)$'

CONSOLE_FRONTEND_LOGIN_TEMPLATE = getattr(settings, 'CONSOLE_FRONTEND_LOGIN_TEMPLATE', 'wagtailcore/login.html')

urlpatterns = [
    path('_util/authenticate_with_password/<int:page_view_restriction_id>/<int:page_id>/',views.authenticate_with_password,name='wagtailcore_authenticate_with_password'),
    path('_util/login/',auth_views.LoginView.as_view(template_name=CONSOLE_FRONTEND_LOGIN_TEMPLATE),name='wagtailcore_login'),
    # Front-end page views are handled through Wagtail's core.views.serve mechanism
    re_path(serve_pattern, views.serve, name='wagtail_serve')
]
