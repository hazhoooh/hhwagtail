"""
The definitions here should remain generic and not depend on the base wagtail.core.models module or specific models defined there.
"""
from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models

class BaseViewRestriction(models.Model):
    NONE = 'none'
    PASSWORD = 'password'
    GROUPS = 'groups'
    LOGIN = 'login'

    RESTRICTION_CHOICES = (
        (NONE, "Public"),
        (LOGIN, "Private, accessible to logged-in users"),
        (PASSWORD, "Private, accessible with the following password"),
        (GROUPS, "Private, accessible to users in specific groups"),
    )

    restriction_type = models.CharField(max_length=20, choices=RESTRICTION_CHOICES)
    password = models.CharField(verbose_name="password", max_length=255, blank=True)
    groups = models.ManyToManyField(Group, verbose_name="groups", blank=True)

    def accept_request(self, request):
        if request.user.is_superuser: return True
        if self.restriction_type == BaseViewRestriction.PASSWORD:
            passed_restrictions = request.session.get(self.passed_view_restrictions_session_key, [])
            if self.id not in passed_restrictions: return False
        elif self.restriction_type == BaseViewRestriction.LOGIN:
            if not request.user.is_authenticated: return False
        elif self.restriction_type == BaseViewRestriction.GROUPS:
            current_user_groups = request.user.groups.all()
            if not any(group in current_user_groups for group in self.groups.all()): return False
        return True

    def mark_as_passed(self, request):
        """ Update the session data in the request to mark the user as having passed this view restriction """
        has_existing_session = (settings.SESSION_COOKIE_NAME in request.COOKIES)
        passed_restrictions = request.session.setdefault(self.passed_view_restrictions_session_key, [])
        if self.id not in passed_restrictions:
            passed_restrictions.append(self.id)
            request.session[self.passed_view_restrictions_session_key] = passed_restrictions
        if not has_existing_session: request.session.set_expiry(0) # if this is a session we've created, set it to expire at the end of the browser session

    class Meta:
        abstract = True
        verbose_name = "view restriction"
        verbose_name_plural = "view restrictions"
