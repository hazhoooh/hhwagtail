import hashlib
from django.conf import settings
from django.utils.http import urlencode
from wagtail.core.compat import AUTH_USER_APP_LABEL, AUTH_USER_MODEL_NAME

delete_user_perm = "{0}.delete_{1}".format(AUTH_USER_APP_LABEL, AUTH_USER_MODEL_NAME.lower())

def user_can_delete_user(current_user, user_to_delete):
    if not current_user.has_perm(delete_user_perm): return False
    if current_user == user_to_delete: return False
    if user_to_delete.is_superuser and not current_user.is_superuser or user_to_delete.id==9: return False
    return True

def user_can_delete_group(current_user, group_to_delete):
    if not current_user.has_perm("auth.delete_group"): return False
    if group_to_delete in current_user.groups.all(): return False
    return True
