from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.forms import PasswordChangeForm as DjangoPasswordChangeForm
from django.contrib.auth.forms import PasswordResetForm as DjangoPasswordResetForm


class LoginForm(AuthenticationForm):
    username = forms.CharField(max_length=254, widget=forms.TextInput())
    password = forms.CharField(widget=forms.PasswordInput(attrs={'placeholder': "Enter password",}))

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request=request, *args, **kwargs)
        self.fields['username'].widget.attrs['placeholder'] = (f"Enter your {self.username_field.verbose_name}")

    @property
    def extra_fields(self):
        for field_name, field in self.fields.items():
            if field_name not in ['username', 'password']: yield field_name, field


class PasswordResetForm(DjangoPasswordResetForm):
    email = forms.EmailField(label="Enter your email address to reset your password",max_length=254, required=True)


class PasswordChangeForm(DjangoPasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['old_password'].required = False
        self.fields['new_password1'].required = False
        self.fields['new_password2'].required = False
