from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db.models import Q
from django.utils.functional import cached_property

class BasePermissionPolicy:
    """ The only method that subclasses need to implement is users_with_any_permission;
        all other methods can be derived from that (but in practice, subclasses will probably want to override additional methods, either for efficiency or to implement more fine-grained permission logic).
    # Per-instance permission tests. In the simplest cases - corresponding to the basic Django permission model - permissions are enforced on a per-model basis and so these methods can simply defer to the per-model tests.
    # Policies that require per-instance permission logic must override, at minimum:
    #     user_has_permission_for_instance
    #     instances_user_has_any_permission_for
    #     users_with_any_permission_for_instance
    """
    def __init__(self, model): self.model = model
    """ Return whether the given user has permission to perform the given action on some or all instances of this model """
    def user_has_permission(self, user, action): return (user in self.users_with_permission(action))
    """ Return whether the given user has permission to perform any of the given actions on some or all instances of this model """
    def user_has_any_permission(self, user, actions): return any(self.user_has_permission(user, action) for action in actions)
    """ Return a queryset of users who have permission to perform any of the given actions on some or all instances of this model """
    def users_with_any_permission(self, actions): raise NotImplementedError
    """ Return a queryset of users who have permission to perform the given action on some or all instances of this model """
    def users_with_permission(self, action): return self.users_with_any_permission([action])
    """ Return whether the given user has permission to perform the given action on the given model instance """
    def user_has_permission_for_instance(self, user, action, instance): return self.user_has_permission(user, action)
    """ Return whether the given user has permission to perform any of the given actions on the given model instance """
    def user_has_any_permission_for_instance(self, user, actions, instance): return any(self.user_has_permission_for_instance(user, action, instance) for action in actions)
    """ Return a queryset of all instances of this model for which the given user has permission to perform any of the given actions """
    def instances_user_has_any_permission_for(self, user, actions):
        if self.user_has_any_permission(user, actions): return self.model.objects.all()
        else: return self.model.objects.none()
    """ Return a queryset of all instances of this model for which the given user has permission to perform the given action """
    def instances_user_has_permission_for(self, user, action): return self.instances_user_has_any_permission_for(user, [action])
    """ Return a queryset of all users who have permission to perform any of the given actions on the given model instance """
    def users_with_any_permission_for_instance(self, actions, instance): return self.users_with_any_permission(actions)
    def users_with_permission_for_instance(self, action, instance): return self.users_with_any_permission_for_instance([action], instance)

class AuthenticationOnlyPermissionPolicy(BasePermissionPolicy):
    """ A permission policy that gives all active authenticated users full permission over the given model """
    def user_has_permission(self, user, action): return user.is_authenticated and user.is_active
    def user_has_any_permission(self, user, actions): return user.is_authenticated and user.is_active
    def users_with_any_permission(self, actions): return get_user_model().objects.filter(is_active=True)
    def users_with_permission(self, action): return get_user_model().objects.filter(is_active=True)

class BaseDjangoAuthPermissionPolicy(BasePermissionPolicy):
    """
    Extends BasePermissionPolicy with helper methods useful for policies that need to
    perform lookups against the django.contrib.auth permission model
    """
    def __init__(self, model, auth_model=None):
        # `auth_model` specifies the model to be used for permission record lookups;
        # usually this will match `model` (which specifies the type of instances that
        # `instances_user_has_permission_for` will return), but this may differ when
        # swappable models are in use - for example, an interface for editing user
        # records might use a custom User model but will typically still refer to the
        # permission records for auth.user.
        super().__init__(model)
        self.auth_model = auth_model or self.model
        self.app_label = self.auth_model._meta.app_label
        self.model_name = self.auth_model._meta.model_name

    @cached_property
    def _content_type(self): return ContentType.objects.get_for_model(self.auth_model)

    def _get_permission_name(self, action):
        """
        Get the full app-label-qualified permission name (as required by
        user.has_perm(...) ) for the given action on this model
        """
        return '%s.%s_%s' % (self.app_label, action, self.model_name)

    def _get_users_with_any_permission_codenames_filter(self, permission_codenames):
        """
        Given a list of permission codenames, return a filter expression which
        will find all users which have any of those permissions - either
        through group permissions, user permissions, or implicitly through
        being a superuser.
        """
        permissions = Permission.objects.filter(content_type=self._content_type,codename__in=permission_codenames)
        return (Q(is_superuser=True) | Q(user_permissions__in=permissions) | Q(groups__permissions__in=permissions)) & Q(is_active=True)

    def _get_users_with_any_permission_codenames(self, permission_codenames):
        """
        Given a list of permission codenames, return a queryset of users which
        have any of those permissions - either through group permissions, user
        permissions, or implicitly through being a superuser.
        """
        filter_expr = self._get_users_with_any_permission_codenames_filter(permission_codenames)
        return get_user_model().objects.filter(filter_expr).distinct()

class ModelPermissionPolicy(BaseDjangoAuthPermissionPolicy):
    def user_has_permission(self, user, action): return user.has_perm(self._get_permission_name(action))
    def users_with_any_permission(self, actions):
        permission_codenames = ['%s_%s' % (action, self.model_name) for action in actions]
        return self._get_users_with_any_permission_codenames(permission_codenames)

class OwnershipPermissionPolicy(BaseDjangoAuthPermissionPolicy):
    """ A permission policy for objects that support a concept of 'ownership', where the owner is typically the user who created the object.
        This policy piggybacks off 'add' and 'change' permissions defined through the django.contrib.auth Permission model, as follows:
            * any user with 'add' permission can create instances, and ALSO edit and delete instances that they own
            * any user with 'change' permission can edit and delete instances regardless of ownership
    """
    def __init__(self, model, auth_model=None, owner_field_name='owner'):
        super().__init__(model, auth_model=auth_model)
        self.owner_field_name = owner_field_name
        try: self.model._meta.get_field(self.owner_field_name)
        except FieldDoesNotExist: raise ImproperlyConfigured( "%s has no field named '%s'. To use this model with OwnershipPermissionPolicy, you must specify a valid field name as owner_field_name." % (self.model, self.owner_field_name) )
    def user_has_permission(self, user, action):
        if action == 'add': return user.has_perm(self._get_permission_name('add'))
        elif action == 'change' or action == 'delete': return (user.has_perm(self._get_permission_name('add')) or user.has_perm(self._get_permission_name('change')))
        else: return user.is_active and user.is_superuser
    def users_with_any_permission(self, actions):
        if 'change' in actions or 'delete' in actions: permission_codenames = ['add_%s' % self.model_name,'change_%s' % self.model_name]
        elif 'add' in actions: permission_codenames = ['add_%s' % self.model_name,]
        else: return get_user_model().objects.filter(is_active=True, is_superuser=True)
        return self._get_users_with_any_permission_codenames(permission_codenames)
    def user_has_permission_for_instance(self, user, action, instance): return self.user_has_any_permission_for_instance(user, [action], instance)
    def user_has_any_permission_for_instance(self, user, actions, instance):
        if 'change' in actions or 'delete' in actions:
            if user.has_perm(self._get_permission_name('change')):return True
            elif (user.has_perm(self._get_permission_name('add')) and getattr(instance, self.owner_field_name) == user):return True
            else:return False
        else: return user.is_active and user.is_superuser
    def instances_user_has_any_permission_for(self, user, actions):
        if user.is_active and user.is_superuser: return self.model.objects.all()
        elif 'change' in actions or 'delete' in actions:
            if user.has_perm(self._get_permission_name('change')): return self.model.objects.all()
            elif user.has_perm(self._get_permission_name('add')): return self.model.objects.filter(**{self.owner_field_name: user})
            else: return self.model.objects.none()
        else: return self.model.objects.none()
    def users_with_any_permission_for_instance(self, actions, instance):
        if 'change' in actions or 'delete' in actions: 
            filter_expr = self._get_users_with_any_permission_codenames_filter(['change_%s' % self.model_name])
            # add on the item's owner, if they still have 'add' permission (and the owner field isn't blank)
            owner = getattr(instance, self.owner_field_name)
            if owner is not None and owner.has_perm(self._get_permission_name('add')): filter_expr = filter_expr | Q(pk=owner.pk)
            return get_user_model().objects.filter(filter_expr).distinct()
        else: return get_user_model().objects.filter(is_active=True, is_superuser=True)
