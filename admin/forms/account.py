import warnings
from django import forms
from django.contrib.auth import get_user_model
from wagtail.core.models import UserPagePermissionsProxy
from wagtail.users.models import UserProfile

User = get_user_model()

class NotificationPreferencesForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user_perms = UserPagePermissionsProxy(self.instance.user)
        if not user_perms.can_publish_pages():
            del self.fields['submitted_notifications']
        if not user_perms.can_edit_pages():
            del self.fields['approved_notifications']
            del self.fields['rejected_notifications']
            del self.fields['updated_comments_notifications']
    class Meta:
        model = UserProfile
        fields = ['submitted_notifications', 'approved_notifications', 'rejected_notifications']

class IdentityForm(forms.ModelForm):
    first_name = forms.CharField(required=True, label="First Name")
    last_name = forms.CharField(required=True, label="Last Name")
    email = forms.EmailField(required=True, label="Email")
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']

class AvatarPreferencesForm(forms.ModelForm):
    avatar = forms.ImageField(label="Upload a profile picture", required=False)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_avatar = self.instance.avatar
    def save(self, commit=True):
        if commit and self._original_avatar and (self._original_avatar != self.cleaned_data['avatar']):
            # Call delete() on the storage backend directly, as calling self._original_avatar.delete()
            # will clear the now-updated field on self.instance too
            try:
                self._original_avatar.storage.delete(self._original_avatar.name)
            except IOError:
                # failure to delete the old avatar shouldn't prevent us from continuing
                warnings.warn("Failed to delete old avatar file: %s" % self._original_avatar.name)
        super().save(commit=commit)
    class Meta:
        model = UserProfile
        fields = ["avatar"]
