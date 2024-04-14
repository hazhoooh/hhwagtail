from django import forms
from django.conf import settings
from django.utils import timezone
from wagtail.admin import widgets, messages, signals
from wagtail.core.models import Page, PageViewRestriction
from .models import WagtailAdminModelForm
from .view_restrictions import BaseViewRestrictionForm

class CopyForm(forms.Form):
    def __init__(self, *args, **kwargs):
        # CopyPage must be passed a 'page' kwarg indicating the page to be copied
        self.page = kwargs.pop('page')
        self.user = kwargs.pop('user', None)
        can_publish = kwargs.pop('can_publish')
        super().__init__(*args, **kwargs)
        self.fields['new_title'] = forms.CharField(initial=self.page.title, label="New title")
        allow_unicode = getattr(settings, 'CONSOLE_ALLOW_UNICODE_SLUGS', True)
        self.fields['new_slug'] = forms.SlugField(initial=self.page.slug, label="New slug", allow_unicode=allow_unicode)
        self.fields['new_parent_page'] = forms.ModelChoiceField(initial=self.page.get_parent(),queryset=Page.objects.all(),widget=widgets.AdminPageChooser(can_choose_root=True, user_perms='copy_to'),label="New parent page",help_text="This copy will be a child of this given parent page.")
        pages_to_copy = self.page.get_descendants(inclusive=True)
        subpage_count = pages_to_copy.count() - 1
        if subpage_count > 0: self.fields['copy_subpages'] = forms.BooleanField(required=False, initial=True, label="Copy subpages")
        if can_publish:
            pages_to_publish_count = pages_to_copy.live().count()
            if pages_to_publish_count > 0: self.fields['publish_copies'] = forms.BooleanField(required=False, initial=False, label="Publish copies")
            self.fields['alias'] = forms.BooleanField(required=False, initial=False, label="Alias",help_text="Keep the new pages updated with future changes")
    def clean(self):
        cleaned_data = super().clean()
        slug = cleaned_data.get('new_slug')
        parent_page = cleaned_data.get('new_parent_page') or self.page.get_parent()
        if not parent_page.permissions_for_user(self.user).can_add_subpage(): self._errors['new_parent_page'] = self.error_class([f"You do not have permission to copy to page '{parent_page.specific_deferred.get_admin_display_title()}"])
        if slug and parent_page.get_children().filter(slug=slug).count():
            self._errors['new_slug'] = self.error_class([f"This slug is already in use within the context of its parent page '{parent_page}'"])
            del cleaned_data['new_slug']
        if cleaned_data.get('copy_subpages') and (self.page == parent_page or parent_page.is_descendant_of(self.page)): self._errors['new_parent_page'] = self.error_class(["You cannot copy a page into itself when copying subpages"])
        return cleaned_data

class PageViewRestrictionForm(BaseViewRestrictionForm):
    class Meta:
        model = PageViewRestriction
        fields = ('restriction_type', 'password', 'groups')

class WagtailAdminPageForm(WagtailAdminModelForm):
    class Meta: exclude = ['content_type', 'path', 'depth', 'numchild'] # (dealing with Treebeard's tree-related fields that really should have been editable=False)
    def __init__(self, data=None, files=None, parent_page=None, subscription=None, *args, **kwargs):
        self.subscription = subscription
        super().__init__(data, files, *args, **kwargs)
        self.parent_page = parent_page
    def save(self, commit=True):
        if commit: self.subscription.save()
        return super().save(commit=commit)
    def is_valid(self):
        return super().is_valid()
    def clean(self):
        cleaned_data = super().clean()
        if 'slug' in self.cleaned_data:
            if not Page._slug_is_available(cleaned_data['slug'], self.parent_page, self.instance):
                self.add_error('slug', forms.ValidationError("This slug is already in use"))
        go_live_at = cleaned_data.get('go_live_at')
        expire_at = cleaned_data.get('expire_at')
        if go_live_at and expire_at:
            if go_live_at > expire_at:
                msg = "Go live date/time must be before expiry date/time"
                self.add_error('go_live_at', forms.ValidationError(msg))
                self.add_error('expire_at', forms.ValidationError(msg))
        if expire_at and expire_at < timezone.now(): self.add_error('expire_at', forms.ValidationError("Expiry date/time must be in the future"))
        if 'first_published_at' in cleaned_data and not cleaned_data['first_published_at']: del cleaned_data['first_published_at']
        return cleaned_data
