from collections import OrderedDict

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash, views as auth_views
from django.db import transaction
from django.forms import Media
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, override
from django.views.decorators.debug import sensitive_post_parameters

from wagtail.admin.forms.account import AvatarPreferencesForm, IdentityForm, NotificationPreferencesForm
from wagtail.admin.forms.auth import LoginForm, PasswordChangeForm, PasswordResetForm
# from wagtail.admin.localization import get_available_admin_languages, get_available_admin_time_zones
# from wagtail.core import hooks
from wagtail.core.log_actions import log
from wagtail.core.models import UserPagePermissionsProxy
from wagtail.users.models import UserProfile
from wagtail.utils.loading import get_custom_form

def get_user_login_form():
    form_setting = 'CONSOLE_USER_LOGIN_FORM'
    if hasattr(settings, form_setting): return get_custom_form(form_setting)
    else: return LoginForm

# Helper functions to check password management settings to enable/disable views as appropriate.
# These are functions rather than class-level constants so that they can be overridden in tests
# by override_settings

def password_management_enabled(): return getattr(settings, 'CONSOLE_PASSWORD_MANAGEMENT_ENABLED', True)
def email_management_enabled(): return getattr(settings, 'CONSOLE_EMAIL_MANAGEMENT_ENABLED', True)
def password_reset_enabled(): return getattr(settings, 'CONSOLE_PASSWORD_RESET_ENABLED', password_management_enabled())

# Panels 
class BaseSettingsPanel:
    name = ''
    title = name.capitalize()
    help_text = None
    template_name = 'cms/account/settings_panels/panel_form.html'
    form_class = None
    def __init__(self, request, profile):
        self.title = self.name.capitalize()
        self.request = request
        self.profile = profile
    def is_active(self): return True
    def get_form(self):
        """ Returns an initialised form. """
        kwargs = {'instance': self.profile,'prefix': self.name}
        if self.request.method == 'POST': return self.form_class(self.request.POST, self.request.FILES, **kwargs)
        else: return self.form_class(**kwargs)
    def get_context_data(self):
        """ Returns the template context to use when rendering the template. """
        return {'form': self.get_form()}
    def render(self):
        """ Renders the panel using the template specified in .template_name and context from .get_context_data() """
        return render_to_string(self.template_name, self.get_context_data(), request=self.request)

class IdentitySettingsPanel(BaseSettingsPanel):
    name = 'identity'
    order = 100
    form_class = IdentityForm

class AvatarSettingsPanel(BaseSettingsPanel):
    name = 'main info'
    order = 300
    template_name = 'cms/account/settings_panels/avatar.html'
    form_class = AvatarPreferencesForm
    def get_context_data(self):
        context=super().get_context_data()
        context.update(self.profile.user_assets)
        return context

class ChangePasswordPanel(BaseSettingsPanel):
    name = 'password'
    title = gettext_lazy('Password')
    order = 500
    form_class = PasswordChangeForm
    def is_active(self):
        return password_management_enabled() and self.profile.user.has_usable_password()
    def get_form(self):
        # Note: don't bind the form unless a field is specified
        # This prevents the validation error from displaying if the user wishes to ignore this
        bind_form = False
        if self.request.method == 'POST':
            bind_form = any([
                self.request.POST.get(self.name + '-old_password'),
                self.request.POST.get(self.name + '-new_password1'),
                self.request.POST.get(self.name + '-new_password2'),
            ])
        if bind_form:
            return self.form_class(self.profile.user, self.request.POST, prefix=self.name)
        else:
            return self.form_class(self.profile.user, prefix=self.name)

class NotificationsSettingsPanel(BaseSettingsPanel):
    name = 'notifications'
    order = 100
    template_name = 'cms/account/settings_panels/notifications.html'
    form_class = NotificationPreferencesForm
    def is_active(self):
        user_perms = UserPagePermissionsProxy(self.request.user)
        if not user_perms.can_edit_pages() and not user_perms.can_publish_pages(): return False
        return True # self.get_form().fields

# Views
@sensitive_post_parameters()
def account(request, uid=0):
    try: profile = UserProfile.objects.get(user_id=uid)
    except: return TemplateResponse(request, 'cms/account/account.html', {'no_profile': "User and Profile are not found...!"})
    # Panels
    panels = [
        AvatarSettingsPanel(request, profile),
        # IdentitySettingsPanel(request, profile),
        NotificationsSettingsPanel(request, profile),
        ChangePasswordPanel(request, profile),
    ]
    panels = [panel for panel in panels if panel.is_active()]
    panel_forms = [panel.get_form() for panel in panels]
    if request.method == 'POST':
        if all(form.is_valid() or not form.is_bound for form in panel_forms):
            with transaction.atomic():
                for form in panel_forms:
                    if form.is_bound: form.save()
            log(profile.user, 'edited')
            update_session_auth_hash(request, profile.user) # Prevent a password change from logging this user out
            return redirect('wagtailadmin_account', uid=uid)
    media = Media()
    for form in panel_forms: media += form.media
    return TemplateResponse(request, 'cms/account/account.html', {'panels': panels,'media': media,'profile': profile,})

class PasswordResetEnabledViewMixin:
    """
    Class based view mixin that disables the view if password reset is disabled by one of the following settings:
    - CONSOLE_PASSWORD_RESET_ENABLED
    - CONSOLE_PASSWORD_MANAGEMENT_ENABLED
    """
    def dispatch(self, *args, **kwargs):
        if not password_reset_enabled(): raise Http404
        return super().dispatch(*args, **kwargs)

class PasswordResetView(PasswordResetEnabledViewMixin, auth_views.PasswordResetView):
    template_name = 'cms/account/password_reset/form.html'
    email_template_name = 'cms/account/password_reset/email.txt'
    subject_template_name = 'cms/account/password_reset/email_subject.txt'
    form_class = PasswordResetForm
    success_url = reverse_lazy('wagtailadmin_password_reset_done')

class PasswordResetDoneView(PasswordResetEnabledViewMixin, auth_views.PasswordResetDoneView):
    template_name = 'cms/account/password_reset/done.html'

class PasswordResetConfirmView(PasswordResetEnabledViewMixin, auth_views.PasswordResetConfirmView):
    template_name = 'cms/account/password_reset/confirm.html'
    success_url = reverse_lazy('wagtailadmin_password_reset_complete')

class PasswordResetCompleteView(PasswordResetEnabledViewMixin, auth_views.PasswordResetCompleteView):
    template_name = 'cms/account/password_reset/complete.html'

class LoginView(auth_views.LoginView):
    template_name = 'cms/login.html'
    def get_success_url(self):
        return self.get_redirect_url() or reverse('wagtailadmin_home')
    def get(self, *args, **kwargs):
        # If user is already logged in, redirect them to the dashboard
        if self.request.user.is_authenticated and self.request.user.has_perm('wagtailadmin.access_admin'):
            return redirect(self.get_success_url())
        return super().get(*args, **kwargs)
    def get_form_class(self):
        return get_user_login_form()
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['show_password_reset'] = password_reset_enabled()
        from django.contrib.auth import get_user_model
        User = get_user_model()
        context['username_field'] = User._meta.get_field(User.USERNAME_FIELD).verbose_name
        return context

class LogoutView(auth_views.LogoutView):
    next_page = 'wagtailadmin_login'
    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        messages.success(self.request, "You have been successfully logged out.")
        # By default, logging out will generate a fresh sessionid cookie. We want to use the
        # absence of sessionid as an indication that front-end pages are being viewed by a
        # non-logged-in user and are therefore cacheable, so we forcibly delete the cookie here.
        response.delete_cookie(
            settings.SESSION_COOKIE_NAME,
            domain=settings.SESSION_COOKIE_DOMAIN,
            path=settings.SESSION_COOKIE_PATH
        )
        # HACK: pretend that the session hasn't been modified, so that SessionMiddleware
        # won't override the above and write a new cookie.
        self.request.session.modified = False
        return response
 