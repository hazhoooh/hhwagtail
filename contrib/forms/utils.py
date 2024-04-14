from wagtail.core import hooks
from wagtail.core.models import UserPagePermissionsProxy
from wagtail.core.utils import safe_snake_case, get_formpage_content_types


def get_field_clean_name(label):
    """ Converts a user entered field label to a template and JSON safe ascii value to be used as the internal key (clean name) for the field. """
    return safe_snake_case(label)

def get_forms_for_user(user):
    """ Return a queryset of form pages that this user is allowed to access the submissions for """
    viewable_submissions_for_pages = UserPagePermissionsProxy(user).submissions_viewable_pages()
    viewable_submissions_for_pages = viewable_submissions_for_pages.filter(content_type__in=get_formpage_content_types())
    # Apply hooks
    for fn in hooks.get_hooks('filter_form_submissions_for_user'): viewable_submissions_for_pages = fn(user, viewable_submissions_for_pages)
    return viewable_submissions_for_pages
