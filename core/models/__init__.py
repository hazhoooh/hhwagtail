from collections import namedtuple
import functools
import json
import logging
import warnings
from io import StringIO
from urllib.parse import urlparse
from collections import defaultdict
import posixpath
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core import checks
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.handlers.base import BaseHandler
from django.core.handlers.wsgi import WSGIRequest
from django.db import models, transaction
from django.db.models import DEFERRED, CharField, Prefetch, Q, Case, IntegerField, When, Value
from django.db.models.expressions import OuterRef, Subquery, Exists, OuterRef
from django.db.models.functions import Concat, Substr, Length
from django.db.models.query import BaseIterable, ModelIterable
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.http import Http404
from django.template.response import TemplateResponse
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils import translation as translation
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.cache import patch_cache_control
from django.utils.encoding import force_str
from django.utils.functional import cached_property
from django.utils.module_loading import import_string
from django.utils.text import capfirst, slugify
from django.http.request import split_domain_port
from modelcluster.fields import ParentalKey,ParentalManyToManyField
from modelcluster.models import ClusterableModel, get_all_child_relations
from modelcluster.contrib.taggit import ClusterTaggableManager
from treebeard.mp_tree import MP_Node, MP_NodeQuerySet
from taggit.models import TagBase, ItemBase
from wagtail.core.fields import StreamField
from wagtail.core.forms import TaskStateCommentForm
from wagtail.core.log_actions import log, registry as log_action_registry
from wagtail.core.signals import page_published, page_unpublished, post_page_move, pre_page_move, task_approved, task_cancelled, task_rejected, task_submitted, workflow_approved, workflow_cancelled, workflow_rejected, workflow_submitted
from wagtail.core.treebeard import TreebeardPathFixMixin
from wagtail.core.url_routing import RouteResult
from wagtail.core.utils import APPEND_SLASH, camelcase_to_underscore, find_available_slug, resolve_model_string
from wagtail.utils.deprecation import RemovedInWagtail217Warning
from wagtail.utils.decorators import cached_classmethod
from wagtail.search import index
from wagtail.search.queryset import SearchableQuerySetMixin
from .copying import _copy, _copy_m2m_relations, _extract_field_data  
from .view_restrictions import BaseViewRestriction

class LogEntryQuerySet(models.QuerySet):
    def get_user_ids(self): return set(self.order_by().values_list('user_id', flat=True).distinct())
    def get_users(self):
        User = get_user_model()
        return User.objects.filter(pk__in=self.get_user_ids()).order_by(User.USERNAME_FIELD)
    def get_content_type_ids(self): return set(self.order_by().values_list('content_type_id', flat=True).distinct())
    def filter_on_content_type(self, content_type):
        # custom method for filtering by content type, to allow overriding on log entry models
        # that have a concept of object types that doesn't correspond directly to ContentType
        # instances (e.g. PageLogEntry, which treats all page types as a single Page type)
        return self.filter(content_type_id=content_type.id)
    def with_instances(self):
        # return an iterable of (log_entry, instance) tuples for all log entries in this queryset.
        # instance is None if the instance does not exist.
        # Note: This is an expensive operation and should only be done on small querysets
        # (e.g. after pagination).
        # evaluate the queryset in full now, as we'll be iterating over it multiple times
        log_entries = list(self)
        ids_by_content_type = defaultdict(list)
        for log_entry in log_entries:
            ids_by_content_type[log_entry.content_type_id].append(log_entry.object_id)
        instances_by_id = {}  # lookup of (content_type_id, stringified_object_id) to instance
        for content_type_id, object_ids in ids_by_content_type.items():
            model = ContentType.objects.get_for_id(content_type_id).model_class()
            if model is not None:
                model_instances = model.objects.in_bulk(object_ids)
                for object_id, instance in model_instances.items():
                    instances_by_id[(content_type_id, str(object_id))] = instance
            else:
                # Handle the case where model is None
                instances_by_id.update({(content_type_id, str(object_id)): None for object_id in object_ids})
        for log_entry in log_entries:
            lookup_key = (log_entry.content_type_id, str(log_entry.object_id))
            yield (log_entry, instances_by_id.get(lookup_key))

class BaseLogEntryManager(models.Manager):
    def get_queryset(self): return LogEntryQuerySet(self.model, using=self._db)
    def get_instance_title(self, instance): return str(instance)
    def log_action(self, instance, action, **kwargs):
        """
        :param instance: The model instance we are logging an action for
        :param action: The action. Should be namespaced to app (e.g. created, workflow_started)
        :param kwargs: Addition fields to for the model deriving from BaseLogEntry
            - user: The user performing the action
            - uuid: uuid shared between log entries from the same user action
            - title: the instance title
            - data: any additional metadata
            - content_changed, deleted - Boolean flags
        :return: The new log entry
        """
        if instance.pk is None: raise ValueError("Attempted to log an action for object %r with empty primary key" % (instance, ))
        data = kwargs.pop('data', '')
        title = kwargs.pop('title', None)
        if not title: title = self.get_instance_title(instance)
        timestamp = kwargs.pop('timestamp', timezone.now())
        return self.model.objects.create(content_type=ContentType.objects.get_for_model(instance, for_concrete_model=False),label=title,action=action,timestamp=timestamp,data_json=json.dumps(data),**kwargs,)
    def viewable_by_user(self, user): return self.all()
    def get_for_model(self, model):
        if not issubclass(model, models.Model): return self.none()
        try: ct = ContentType.objects.get_for_model(model)
        except: return self.none()
        return self.filter(content_type=ct)
    def get_for_user(self, user_id): return self.filter(user=user_id)
    def for_instance(self, instance):
        """ Return a queryset of log entries from this log model that relate to the given object instance """
        raise NotImplementedError  # must be implemented by subclass

class BaseLogEntry(models.Model):
    content_type = models.ForeignKey(ContentType,models.SET_NULL,verbose_name="content type",blank=True, null=True,related_name='+',)
    label = models.TextField()
    action = models.CharField(max_length=255, blank=True, db_index=True)
    data_json = models.TextField(blank=True)
    timestamp = models.DateTimeField(verbose_name="timestamp (UTC)", db_index=True)
    uuid = models.UUIDField(blank=True, null=True, editable=False,help_text="Log entries that happened as part of the same user action are assigned the same UUID")
    user = models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.DO_NOTHING,db_constraint=False,related_name='+',)
    content_changed = models.BooleanField(default=False, db_index=True)
    deleted = models.BooleanField(default=False)
    objects = BaseLogEntryManager()
    class Meta:
        abstract = True
        verbose_name = "log entry"
        verbose_name_plural = "log entries"
        ordering = ['-timestamp']
    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
    def clean(self):
        if not log_action_registry.action_exists(self.action): raise ValidationError({'action': "The log action '{}' has not been registered.".format(self.action)})
    def __str__(self): return "LogEntry %d: '%s' on '%s'" % (self.pk, self.action, self.object_verbose_name())
    @cached_property
    def user_display_name(self):
        """
        Returns the display name of the associated user;
        get_full_name if available and non-empty, otherwise get_username.
        Defaults to 'system' when none is provided
        """
        if self.user_id:
            user = self.user
            if user is None: return "user %(id)s (deleted)" % {'id': self.user_id}
            try: full_name = user.get_full_name().strip()
            except AttributeError: full_name = ''
            return full_name or user.get_username()
        else: return "system"
    @cached_property
    def data(self):
        """ Provides deserialized data """
        if self.data_json: return json.loads(self.data_json)
        else: return {}
    @cached_property
    def object_verbose_name(self):
        model_class = self.content_type.model_class()
        if model_class is None: return self.content_type_id
        return model_class._meta.verbose_name.title
    def object_id(self): raise NotImplementedError

    @cached_property
    def formatter(self): return log_action_registry.get_formatter(self)

    @cached_property
    def message(self):
        if self.formatter: return self.formatter.format_message(self)
        else: return "Unknown %(action)s" % {'action': self.action}

    @cached_property
    def comment(self):
        if self.formatter: return self.formatter.format_comment(self)
        else: return ''

class ModelLogEntryManager(BaseLogEntryManager):
    def log_action(self, instance, action, **kwargs):
        kwargs.update(object_id=str(instance.pk))
        return super().log_action(instance, action, **kwargs)
    def for_instance(self, instance): return self.filter(content_type=ContentType.objects.get_for_model(instance, for_concrete_model=False),object_id=str(instance.pk))

class ModelLogEntry(BaseLogEntry):
    """ Simple logger for generic Django models """
    object_id = models.CharField(max_length=255, blank=False, db_index=True)
    objects = ModelLogEntryManager()
    class Meta:
        ordering = ['-timestamp', '-id']
        verbose_name = "model log entry"
        verbose_name_plural = "model log entries"
    def __str__(self): return "ModelLogEntry %d: '%s' on '%s' with id %s" % (self.pk, self.action, self.object_verbose_name(), self.object_id)

class TreeQuerySet(MP_NodeQuerySet):
    def delete(self): super().delete()
    delete.queryset_only = True
    def descendant_of_q(self, other, inclusive=False):
        q = Q(path__startswith=other.path) & Q(depth__gte=other.depth)
        if not inclusive: q &= ~Q(pk=other.pk)
        return q
    def descendant_of(self, other, inclusive=False): return self.filter(self.descendant_of_q(other, inclusive))
    def not_descendant_of(self, other, inclusive=False): return self.exclude(self.descendant_of_q(other, inclusive))
    def child_of_q(self, other): return self.descendant_of_q(other) & Q(depth=other.depth + 1)
    def child_of(self, other): return self.filter(self.child_of_q(other))
    def not_child_of(self, other): return self.exclude(self.child_of_q(other))
    def ancestor_of_q(self, other, inclusive=False):
        paths = [other.path[0:pos] for pos in range(0, len(other.path) + 1, other.steplen)[1:]]
        q = Q(path__in=paths)
        if not inclusive: q &= ~Q(pk=other.pk)
        return q
    def ancestor_of(self, other, inclusive=False): return self.filter(self.ancestor_of_q(other, inclusive))
    def not_ancestor_of(self, other, inclusive=False): return self.exclude(self.ancestor_of_q(other, inclusive))
    def parent_of_q(self, other): return Q(path=self.model._get_parent_path_from_path(other.path))
    def parent_of(self, other): return self.filter(self.parent_of_q(other))
    def not_parent_of(self, other): return self.exclude(self.parent_of_q(other))
    def sibling_of_q(self, other, inclusive=True):
        q = Q(path__startswith=self.model._get_parent_path_from_path(other.path)) & Q(depth=other.depth)
        if not inclusive: q &= ~Q(pk=other.pk)
        return q
    def sibling_of(self, other, inclusive=True): return self.filter(self.sibling_of_q(other, inclusive))
    def not_sibling_of(self, other, inclusive=True): return self.exclude(self.sibling_of_q(other, inclusive))

class PageQuerySet(SearchableQuerySetMixin, TreeQuerySet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._defer_streamfields = False
    def _clone(self):
        clone = super()._clone()
        clone._defer_streamfields = self._defer_streamfields
        return clone
    def live_q(self): return Q(live=True)
    def live(self): return self.filter(self.live_q())
    def not_live(self): return self.exclude(self.live_q())
    def in_menu_q(self): return Q(show_in_menus=True)
    def in_menu(self): return self.filter(self.in_menu_q())
    def not_in_menu(self): return self.exclude(self.in_menu_q())
    def page_q(self, other): return Q(id=other.id)
    def page(self, other): return self.filter(self.page_q(other))
    def not_page(self, other): return self.exclude(self.page_q(other))
    def type_q(self, *types):
        all_subclasses = set(model for model in apps.get_models() if issubclass(model, types))
        content_types = ContentType.objects.get_for_models(*all_subclasses)
        return Q(content_type__in=list(content_types.values()))
    def type(self, *types): return self.filter(self.type_q(*types))
    def not_type(self, *types): return self.exclude(self.type_q(*types))
    def exact_type_q(self, *types):
        # content_types = ContentType.objects.get_for_models(*types)
        return Q(content_type__in=list(ContentType.objects.get_for_models(*types).values()))
    def exact_type(self, *types): return self.filter(self.exact_type_q(*types))
    def not_exact_type(self, *types): return self.exclude(self.exact_type_q(*types))
    def public_q(self):
        q = Q()
        for restriction in PageViewRestriction.objects.select_related('page').all(): q &= ~self.descendant_of_q(restriction.page, inclusive=True)
        return q
    def public(self): return self.filter(self.public_q())
    def not_public(self): return self.exclude(self.public_q())
    def first_common_ancestor(self, include_self=False, strict=False):
        if not self.exists():
            if strict: raise self.model.DoesNotExist('Can not find ancestor of empty queryset')
            return self.model.get_first_root_node()
        if include_self: paths = self.order_by().values_list('path', flat=True)
        else: paths = self.order_by().annotate(parent_path=Substr('path', 1, Length('path') - self.model.steplen,output_field=CharField(max_length=255))).values_list('parent_path', flat=True).distinct()
        common_parent_path = posixpath.commonprefix(paths)
        extra_chars = len(common_parent_path) % self.model.steplen
        if extra_chars != 0: common_parent_path = common_parent_path[:-extra_chars]
        if common_parent_path == '':
            if strict: raise self.model.DoesNotExist('No common ancestor found!')
            return self.model.get_first_root_node()
        return self.model.objects.get(path=common_parent_path)
    def unpublish(self):
        for page in self.live(): page.unpublish()
    def defer_streamfields(self):
        clone = self._clone()
        clone._defer_streamfields = True  # used by specific_iterator()
        streamfield_names = self.model.get_streamfield_names()
        if not streamfield_names: return clone
        return clone.defer(*streamfield_names)
    def specific(self, defer=False):
        clone = self._clone()
        if defer: clone._iterable_class = DeferredSpecificIterable
        else: clone._iterable_class = SpecificIterable
        return clone
    def in_site(self, site): return self.descendant_of(site.root_page, inclusive=True)
    def translation_of(self, page, inclusive=False): return self.filter(self.translation_of_q(page, inclusive))
    def not_translation_of(self, page, inclusive=False): return self.exclude(self.translation_of_q(page, inclusive))
    def prefetch_workflow_states(self):
        workflow_states = WorkflowState.objects.active().select_related("current_task_state__task")
        return self.prefetch_related(Prefetch("workflow_states",queryset=workflow_states,to_attr="_current_workflow_states",))
    def annotate_approved_schedule(self): return self.annotate(_approved_schedule=Exists(PageRevision.objects.exclude(approved_go_live_at__isnull=True).filter(page__pk=OuterRef("pk"))))
    def annotate_site_root_state(self): return self.annotate(_is_site_root=Exists(Site.objects.all()))

def specific_iterator(qs, defer=False):
    annotation_aliases = qs.query.annotations.keys()
    values = qs.values('pk', 'content_type', *annotation_aliases)
    annotations_by_pk = defaultdict(list)
    if annotation_aliases:
        for data in values: annotations_by_pk[data['pk']] = {k: v for k, v in data.items() if k in annotation_aliases}
    pks_and_types = [[v['pk'], v['content_type']] for v in values]
    pks_by_type = defaultdict(list)
    for pk, content_type in pks_and_types: pks_by_type[content_type].append(pk)
    content_types = {pk: ContentType.objects.get_for_id(pk) for _, pk in pks_and_types}
    pages_by_type = {}
    missing_pks = []
    for content_type, pks in pks_by_type.items():
        model = content_types[content_type].model_class() or qs.model
        pages = model.objects.filter(pk__in=pks)
        if defer:
            fields = [field.attname for field in Page._meta.get_fields() if field.concrete]
            pages = pages.only(*fields)
        elif qs._defer_streamfields: pages = pages.defer_streamfields()
        pages_for_type = {page.pk: page for page in pages}
        pages_by_type[content_type] = pages_for_type
        missing_pks.extend(pk for pk in pks if pk not in pages_for_type)
    if missing_pks:
        generic_pages = Page.objects.filter(pk__in=missing_pks).select_related('content_type').in_bulk()
        warnings.warn("Specific versions of the following pages could not be found. This is most likely because a database migration has removed the relevant table or record since the page was created:\n{}".format([{'id': p.id, 'title': p.title, 'type': p.content_type} for p in generic_pages.values()]), category=RuntimeWarning)
    else: generic_pages = {}
    for pk, content_type in pks_and_types:
        try: page = pages_by_type[content_type][pk]
        except KeyError: page = generic_pages[pk]
        if annotation_aliases:
            for annotation, value in annotations_by_pk.get(page.pk, {}).items(): setattr(page, annotation, value)
        yield page

class SpecificIterable(BaseIterable):
    def __iter__(self): return specific_iterator(self.queryset)

class DeferredSpecificIterable(ModelIterable):
    def __iter__(self):
        for obj in super().__iter__():
            if obj.specific_class: yield obj.specific_deferred
            else:
                warnings.warn(f"A specific version of the following page could not be returned because the specific page model is not present on the active branch: <Page id='{obj.id}' title='{obj.title}' type='{obj.content_type}'>",category=RuntimeWarning)
                yield obj

class BaseCollectionManager(models.Manager):
    def get_queryset(self): return TreeQuerySet(self.model).order_by('path')

CollectionManager = BaseCollectionManager.from_queryset(TreeQuerySet)

class CollectionViewRestriction(BaseViewRestriction):
    collection = models.ForeignKey('Collection',verbose_name="collection",related_name='view_restrictions',on_delete=models.CASCADE)
    passed_view_restrictions_session_key = 'passed_collection_view_restrictions'
    class Meta:
        verbose_name = "collection view restriction"
        verbose_name_plural = "collection view restrictions"

class Collection(TreebeardPathFixMixin, MP_Node):
    name = models.CharField(max_length=255, verbose_name="name")
    objects = CollectionManager()
    node_order_by = None
    def __str__(self): return self.name
    def get_ancestors(self, inclusive=False): return Collection.objects.ancestor_of(self, inclusive)
    def get_descendants(self, inclusive=False): return Collection.objects.descendant_of(self, inclusive)
    def get_siblings(self, inclusive=True): return Collection.objects.sibling_of(self, inclusive)
    def get_next_siblings(self, inclusive=False): return self.get_siblings(inclusive).filter(path__gte=self.path).order_by('path')
    def get_prev_siblings(self, inclusive=False): return self.get_siblings(inclusive).filter(path__lte=self.path).order_by('-path')
    def get_view_restrictions(self): return CollectionViewRestriction.objects.filter(collection__in=self.get_ancestors(inclusive=True))
    def get_collection_contents(self):
        from wagtail.core import hooks
        collection_contents = [hook(self) for hook in hooks.get_hooks('describe_collection_contents')]
        # filter out any hook responses that report that the collection is empty (by returning None, or a dict with 'count': 0)
        def is_nonempty(item_type): return item_type and item_type['count'] > 0
        return list(filter(is_nonempty, collection_contents))
    def get_indented_name(self, indentation_start_depth=2, html=False):
        display_depth = self.depth - indentation_start_depth
        if display_depth <= 0: return self.name
        if html: return format_html("{indent}{icon} {name}",indent=mark_safe('&nbsp;' * 4 * display_depth),icon=mark_safe('&#x21b3'),name=self.name) # &#x21b3 is the hex HTML entity for ↳
        return "{}↳ {}".format(' ' * 4 * display_depth, self.name)
    class Meta:
        unique_together = ('name', 'path')
        verbose_name = "collection"
        verbose_name_plural = "collections"

def get_root_collection_id(): return Collection.get_first_root_node().id

class CollectionMember(models.Model):
    collection = models.ForeignKey(Collection,default=get_root_collection_id,verbose_name="collection",related_name='+',on_delete=models.CASCADE)
    search_fields = [index.FilterField('collection'),]
    class Meta: abstract = True

class GroupCollectionPermissionManager(models.Manager):
    def get_by_natural_key(self, group, collection, permission): return self.get(group=group,collection=collection,permission=permission)

class GroupCollectionPermission(models.Model):
    group = models.ForeignKey(Group,verbose_name="group",related_name='collection_permissions',on_delete=models.CASCADE)
    collection = models.ForeignKey(Collection,verbose_name="collection",related_name='group_permissions',on_delete=models.CASCADE)
    permission = models.ForeignKey(Permission,verbose_name="permission",on_delete=models.CASCADE)
    def __str__(self): return "Group %d ('%s') has permission '%s' on collection %d ('%s')" % (self.group.id, self.group,self.permission,self.collection.id, self.collection)
    def natural_key(self): return (self.group, self.collection, self.permission)
    objects = GroupCollectionPermissionManager()
    class Meta:
        unique_together = ('group', 'collection', 'permission')
        verbose_name = "group collection permission"
        verbose_name_plural = "group collection permissions"

logger = logging.getLogger('wagtail.core')
PAGE_TEMPLATE_VAR = 'page'
PAGE_MODEL_CLASSES = []
def get_page_models(): return PAGE_MODEL_CLASSES
def get_default_page_content_type(): return ContentType.objects.get_for_model(Page)

@functools.lru_cache(maxsize=None)
def get_streamfield_names(model_class): return tuple(field.name for field in model_class.concrete_fields() if isinstance(field, StreamField))

class BasePageManager(models.Manager):
    def get_queryset(self): return self._queryset_class(self.model).order_by('path')

PageManager = BasePageManager.from_queryset(PageQuerySet)

class PageBase(models.base.ModelBase):
    def __init__(cls, name, bases, dct):
        super(PageBase, cls).__init__(name, bases, dct)
        if 'template' not in dct: cls.template = "%s/%s.html" % (cls._meta.app_label, camelcase_to_underscore(name))
        if 'ajax_template' not in dct: cls.ajax_template = None
        cls._clean_subpage_models = None  
        cls._clean_parent_page_models = None 
        if 'is_creatable' not in dct: cls.is_creatable = not cls._meta.abstract
        if not cls._meta.abstract: PAGE_MODEL_CLASSES.append(cls)

class AbstractPage(TreebeardPathFixMixin, MP_Node):
    objects = PageManager()
    class Meta: abstract = True

class Page(AbstractPage, index.Indexed, ClusterableModel, metaclass=PageBase):
    """ Base Page Model """
    title = models.CharField(verbose_name="title", max_length=255, help_text="The page title as you'd like it to be seen by your team mates in the console-end")
    draft_title = models.CharField(max_length=255, editable=False)
    slug = models.SlugField(verbose_name="slug", allow_unicode=True, max_length=255, help_text="This value will appear in URLs e.g https://domain.com/[my-slug]/")
    content_type = models.ForeignKey(ContentType, verbose_name="content type", related_name='pages', on_delete=models.SET(get_default_page_content_type))
    live = models.BooleanField(verbose_name="live", default=True, editable=False)
    has_unpublished_changes = models.BooleanField(verbose_name="has unpublished changes", default=False, editable=False)
    url_path = models.TextField(verbose_name="URL path", blank=True, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="owner", null=True, blank=True, editable=True, on_delete=models.SET_NULL, related_name='owned_pages')
    seo_title = models.CharField(verbose_name="title tag", max_length=255, blank=True, help_text="The name of the page displayed on search engine results as the clickable headline.")
    show_in_menus_default = False
    show_in_menus = models.BooleanField(verbose_name="show in menus", default=False, help_text="Whether a link to this page will appear in automatically generated menus")
    search_description = models.TextField(verbose_name="meta description", blank=True, help_text="The descriptive text displayed underneath a headline in search engine results.")
    go_live_at = models.DateTimeField(verbose_name="go live date/time", blank=True, null=True)
    expire_at = models.DateTimeField(verbose_name="expiry date/time", blank=True, null=True)
    expired = models.BooleanField(verbose_name="expired", default=False, editable=False)
    locked = models.BooleanField(verbose_name="locked", default=False, editable=False)
    locked_at = models.DateTimeField(verbose_name="locked at", null=True, editable=False)
    locked_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="locked by", null=True, blank=True, editable=False, on_delete=models.SET_NULL, related_name='locked_pages')
    first_published_at = models.DateTimeField(verbose_name="first published at", blank=True, null=True, db_index=True)
    last_published_at = models.DateTimeField(verbose_name="last published at", null=True, editable=False)
    latest_revision_created_at = models.DateTimeField(verbose_name="latest revision created at", null=True, editable=False)
    live_revision = models.ForeignKey('PageRevision', related_name='+', verbose_name="live revision", on_delete=models.SET_NULL, null=True, blank=True, editable=False)
    alias_of = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, editable=False, related_name='aliases',)
    search_fields = [index.SearchField('title', partial_match=True, boost=2), index.AutocompleteField('title'), index.FilterField('title'), index.FilterField('id'), index.FilterField('live'), index.FilterField('owner'), index.FilterField('content_type'), index.FilterField('path'), index.FilterField('depth'), index.FilterField('locked'), index.FilterField('show_in_menus'), index.FilterField('first_published_at'), index.FilterField('last_published_at'), index.FilterField('latest_revision_created_at')]
    is_creatable = False
    max_count = None
    max_count_per_parent = None
    exclude_fields_in_copy = []
    default_exclude_fields_in_copy = ['id', 'path', 'depth', 'numchild', 'url_path', 'postgres_index_entries', 'index_entries']
    content_panels = []
    promote_panels = []
    settings_panels = []
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.id:
            if not self.content_type_id: self.content_type = ContentType.objects.get_for_model(self)
            if 'show_in_menus' not in kwargs: self.show_in_menus = self.show_in_menus_default
    @property
    def position(self):
        specific_self = self.specific
        parent=specific_self.get_parent()
        children_pages=[child.id for child in parent.get_children()]
        if children_pages: return children_pages.index(specific_self.id) + 1
        return 1
    def __str__(self): return self.title
    @classmethod
    def get_streamfield_names(cls): return get_streamfield_names(cls)
    def set_url_path(self, parent):
        if parent: self.url_path = parent.url_path + self.slug + '/'
        else: self.url_path = '/'
        return self.url_path
    @staticmethod
    def _slug_is_available(slug, parent_page, page=None):
        if parent_page is None: return True
        siblings = parent_page.get_children()
        if page: siblings = siblings.not_page(page)
        return not siblings.filter(slug=slug).exists()
    def _get_autogenerated_slug(self, base_slug):
        candidate_slug = base_slug
        suffix = 1
        parent_page = self.get_parent()
        while not Page._slug_is_available(candidate_slug, parent_page, self):
            suffix += 1
            candidate_slug = "%s-%d" % (base_slug, suffix)
        return candidate_slug
    def full_clean(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title, allow_unicode=True)
            if base_slug: self.slug = self._get_autogenerated_slug(base_slug)
        if not self.draft_title: self.draft_title = self.title
        super().full_clean(*args, **kwargs)
    def clean(self): super().clean()
    def is_site_root(self):
        if hasattr(self, "_is_site_root"): return self._is_site_root
        return Site.objects.all()
    @transaction.atomic
    def save(self, clean=True, user=None, log_action=False, **kwargs):
        if clean: self.full_clean()
        update_descendant_url_paths = False
        is_new = self.id is None
        if is_new: self.set_url_path(self.get_parent())
        else:
            if not ('update_fields' in kwargs and 'slug' not in kwargs['update_fields']):
                old_record = Page.objects.get(id=self.id)
                if old_record.slug != self.slug:
                    self.set_url_path(self.get_parent())
                    update_descendant_url_paths = True
                    old_url_path = old_record.url_path
                    new_url_path = self.url_path
        result = super().save(**kwargs)
        if not is_new and update_descendant_url_paths: self._update_descendant_url_paths(old_url_path, new_url_path)
        if self.is_site_root(): cache.delete('wagtail_site_root_paths')
        if is_new:
            cls = type(self)
            logger.info("Page created: \"%s\" id=%d content_type=%s.%s path=%s", self.title, self.id, cls._meta.app_label, cls.__name__, self.url_path)
        if log_action is not None:
            if is_new: log(instance=self, action='created', user=user or self.owner, content_changed=True)
            elif log_action: log(instance=self, action=log_action, user=user)
        return result
    def delete(self, *args, **kwargs):
        if type(self) is Page:
            user = kwargs.pop('user', None)
            def log_deletion(page, user): log(instance=page, action='deleted', user=user, deleted=True)
            if self.get_children().exists():
                for child in self.get_children(): log_deletion(child.specific, user)
            log_deletion(self.specific, user)
            return super().delete(*args, **kwargs)
        else: return Page.objects.get(id=self.id).delete(*args, **kwargs)
    @classmethod
    def check(cls, **kwargs):
        errors = super(Page, cls).check(**kwargs)
        field_exceptions = [field.name for model in [cls] + list(cls._meta.get_parent_list()) for field in model._meta.parents.values() if field]
        for field in cls._meta.fields:
            if isinstance(field, models.ForeignKey) and field.name not in field_exceptions:
                if field.remote_field.on_delete == models.CASCADE: errors.append( checks.Warning( "Field hasn't specified on_delete action", hint="Set on_delete=models.SET_NULL and make sure the field is nullable or set on_delete=models.PROTECT. Wagtail does not allow simple database CASCADE because it will corrupt its tree storage.", obj=field, id='wagtailcore.W001'))
        if not isinstance(cls.objects, PageManager): errors.append( checks.Error( "Manager does not inherit from PageManager", hint="Ensure that custom Page managers inherit from wagtail.core.models.PageManager", obj=cls, id='wagtailcore.E002'))
        try: cls.clean_subpage_models()
        except (ValueError, LookupError) as e: errors.append( checks.Error( "Invalid subpage_types setting for %s" % cls, hint=str(e), id='wagtailcore.E002'))
        try: cls.clean_parent_page_models()
        except (ValueError, LookupError) as e: errors.append( checks.Error( "Invalid parent_page_types setting for %s" % cls, hint=str(e), id='wagtailcore.E002'))
        return errors
    def _update_descendant_url_paths(self, old_url_path, new_url_path):
        (Page.objects.filter(path__startswith=self.path).exclude(pk=self.pk).update( url_path=Concat( Value(new_url_path), Substr('url_path', len(old_url_path) + 1))))
    def get_specific(self, deferred=False, copy_attrs=None, copy_attrs_exclude=None):
        model_class = self.specific_class
        if model_class is None: return self
        if isinstance(self, model_class): return self
        if deferred:
            values = tuple(getattr(self, f.attname, self.pk if f.primary_key else DEFERRED) for f in model_class.concrete_fields()) 
            specific_obj = model_class(*values)
            specific_obj._state.adding = self._state.adding
        else: specific_obj = model_class._default_manager.get(id=self.id)
        if copy_attrs is not None:
            for attr in (attr for attr in copy_attrs if attr in self.__dict__): setattr(specific_obj, attr, getattr(self, attr))
        else:
            exclude = copy_attrs_exclude or ()
            for k, v in ((k, v) for k, v in self.__dict__.items() if k not in exclude): specific_obj.__dict__.setdefault(k, v)
        return specific_obj
    @cached_property
    def specific(self): return self.get_specific()
    @cached_classmethod
    def concrete_fields(cls): return cls._meta.concrete_fields
    @cached_property
    def specific_deferred(self): return self.get_specific(deferred=True)
    @cached_property
    def specific_class(self): return self.cached_content_type.model_class()
    @property
    def cached_content_type(self): return ContentType.objects.get_for_id(self.content_type_id)
    def route(self, request, path_parts):
        if path_parts:
            child_slug = path_parts[0]
            remaining_parts = path_parts[1:]
            try: subpage = self.get_children().get(slug=child_slug)
            except Page.DoesNotExist: raise Http404
            return subpage.specific.route(request, remaining_parts)
        else:
            if self.live: return RouteResult(self)
            else: raise Http404
    def get_admin_display_title(self): return self.draft_title or self.title
    def save_revision(self, user=None, submitted_for_moderation=False, approved_go_live_at=None, changed=True, log_action=False, previous_revision=None, clean=True):
        if self.alias_of_id: raise RuntimeError("save_revision() was called on an alias page. Revisions are not required for alias pages as they are an exact copy of another page.")
        if clean: self.full_clean()
        # new_comments = getattr(self, COMMENTS_RELATION_NAME).filter(pk__isnull=True)
        # for comment in new_comments: comment.save()
        revision = self.revisions.create( content_json=self.to_json(), user=user, submitted_for_moderation=submitted_for_moderation, approved_go_live_at=approved_go_live_at) 
        # for comment in new_comments: comment.revision_created = revision
        # update_fields = [COMMENTS_RELATION_NAME]
        self.latest_revision_created_at = revision.created_at
        # update_fields.append('latest_revision_created_at')
        self.draft_title = self.title
        # update_fields.append('draft_title')
        if changed:
            self.has_unpublished_changes = True
            # update_fields.append('has_unpublished_changes')
        # if update_fields: self.save(update_fields=update_fields, clean=False)
        logger.info(f'Page edited: {self.title} id={self.id} revision_id={revision.id} u_id={user.id} at:{timezone.now()}')
        if log_action:
            if not previous_revision: log(instance=self, action=log_action if isinstance(log_action, str) else 'edited', user=user, revision=revision, content_changed=changed)
            else: log(instance=self, action=log_action if isinstance(log_action, str) else 'reverted', user=user, data={'revision': {'id': previous_revision.id, 'created': previous_revision.created_at.strftime("%d %b %Y %H:%M")}}, revision=revision, content_changed=changed)
        if submitted_for_moderation: logger.info("Page submitted for moderation: \"%s\" id=%d revision_id=%d", self.title, self.id, revision.id)
        return revision
    def get_latest_revision(self): return self.revisions.last()
    def get_latest_revision_as_page(self):
        # if not self.has_unpublished_changes: return self.specific
        latest_revision = self.get_latest_revision()
        if latest_revision: return latest_revision.as_page_object()
        else: return self.specific
    def update_aliases(self, *, revision=None, user=None, _content_json=None, _updated_ids=None):
        specific_self = self.specific
        if _content_json is None: _content_json = self.to_json()
        _updated_ids = _updated_ids or []
        for alias in self.specific_class.objects.filter(alias_of=self).exclude(id__in=_updated_ids):
            exclude_fields = ['id', 'path', 'depth', 'numchild', 'url_path', 'path', 'index_entries', 'postgres_index_entries']
            alias_updated = alias.with_content_json(_content_json)
            alias_updated.live = True
            alias_updated.has_unpublished_changes = False
            _copy_m2m_relations(specific_self, alias_updated, exclude_fields=exclude_fields)
            alias_updated.slug = alias.slug
            alias_updated.set_url_path(alias_updated.get_parent())
            alias_updated.draft_title = alias_updated.title
            alias_updated.latest_revision_created_at = self.latest_revision_created_at
            alias_updated.save(clean=False)
            page_published.send(sender=alias_updated.specific_class, instance=alias_updated, revision=revision, alias=True)
            log(instance=alias_updated, action='published', user=user)
            alias.update_aliases(revision=revision, _content_json=_content_json, _updated_ids=_updated_ids)
    update_aliases.alters_data = True
    def unpublish(self, set_expired=False, commit=True, user=None, log_action=True):
        if self.live:
            self.live = False
            self.has_unpublished_changes = True
            self.live_revision = None
            if set_expired: self.expired = True
            if commit: self.save(clean=False)
            page_unpublished.send(sender=self.specific_class, instance=self.specific)
            if log_action: log(instance=self, action=log_action if isinstance(log_action, str) else 'unpublished', user=user)
            logger.info("Page unpublished: \"%s\" id=%d", self.title, self.id)
            self.revisions.update(approved_go_live_at=None)
            for alias in self.aliases.all(): alias.unpublish()
    context_object_name = None
    def get_context(self, request, *args, **kwargs):
        context = {PAGE_TEMPLATE_VAR: self, 'self': self, 'request': request, }
        if self.context_object_name: context[self.context_object_name] = self
        return context
    def get_template(self, request, *args, **kwargs):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest': return self.ajax_template or self.template
        else: return self.template
    def serve(self, request, *args, **kwargs):
        request.is_preview = getattr(request, 'is_preview', False)
        return TemplateResponse(request, self.get_template(request, *args, **kwargs), self.get_context(request, *args, **kwargs))
    def is_navigable(self): return (not self.is_leaf()) or self.depth == 2
    def _get_site_root_paths(self, request=None):
        cache_object = request if request else self
        try: return cache_object._wagtail_cached_site_root_paths
        except AttributeError:
            cache_object._wagtail_cached_site_root_paths = Site.get_site_root_paths()
            return cache_object._wagtail_cached_site_root_paths
    def get_url_parts(self, request=None):
        possible_sites = [(pk, path, url) for pk, path, url in self._get_site_root_paths(request) if self.url_path.startswith(path)]
        if not possible_sites: return None
        site_id, root_path, root_url = possible_sites[0]
        site = Site.find_for_request(request)
        if site:
            for site_id, root_path, root_url in possible_sites:
                if site_id == site.pk: break
            else: site_id, root_path, root_url = possible_sites[0]        
        try: page_path = reverse('wagtail_serve', args=(self.url_path[len(root_path):],))
        except NoReverseMatch: return (site_id, None, None)
        if not APPEND_SLASH and page_path != '/': page_path = page_path.rstrip('/')
        return (site_id, root_url, page_path)
    def get_full_url(self, request=None):
        url_parts = self.get_url_parts(request=request)
        if url_parts is None or url_parts[1] is None and url_parts[2] is None: return
        site_id, root_url, page_path = url_parts
        return root_url + page_path
    full_url = property(get_full_url)
    def get_url(self, request=None, current_site=None):
        if current_site is None and request is not None: current_site = Site.find_for_request(request)
        url_parts = self.get_url_parts(request=request)
        if url_parts is None or url_parts[1] is None and url_parts[2] is None: return
        site_id, root_url, page_path = url_parts
        num_sites = len(set(root_path[0] for root_path in self._get_site_root_paths(request)))
        if (current_site is not None and site_id == current_site.id) or num_sites == 1: return page_path
        else: return root_url + page_path
    url = property(get_url)
    def relative_url(self, current_site, request=None): return self.get_url(request=request, current_site=current_site)
    def get_site(self):
        url_parts = self.get_url_parts()
        if url_parts is None: return
        site_id, root_url, page_path = url_parts
        return Site.objects.get(id=site_id)
    @classmethod
    def get_indexed_objects(cls):
        content_type = ContentType.objects.get_for_model(cls)
        return super(Page, cls).get_indexed_objects().filter(content_type=content_type)
    def get_indexed_instance(self):
        try: return self.specific
        except self.specific_class.DoesNotExist: return None
    @classmethod
    def clean_subpage_models(cls):
        if cls._clean_subpage_models is None:
            subpage_types = getattr(cls, 'subpage_types', [])
            if not subpage_types: cls._clean_subpage_models = get_page_models()
            else: 
                cls._clean_subpage_models = [resolve_model_string(model_string, cls._meta.app_label) for model_string in subpage_types]
                for model in cls._clean_subpage_models:
                    if not issubclass(model, Page): raise LookupError("%s is not a Page subclass" % model)
        return cls._clean_subpage_models
    @classmethod
    def clean_parent_page_models(cls):
        if cls._clean_parent_page_models is None:
            parent_page_types = getattr(cls, 'parent_page_types', None)
            if parent_page_types is None: cls._clean_parent_page_models = get_page_models()
            else:
                cls._clean_parent_page_models = [resolve_model_string(model_string, cls._meta.app_label) for model_string in parent_page_types]
                for model in cls._clean_parent_page_models:
                    if not issubclass(model, Page): raise LookupError("%s is not a Page subclass" % model)
        return cls._clean_parent_page_models
    @classmethod
    def allowed_parent_page_models(cls): return [parent_model for parent_model in cls.clean_parent_page_models() if cls in parent_model.clean_subpage_models()]
    @classmethod
    def allowed_subpage_models(cls): return [subpage_model for subpage_model in cls.clean_subpage_models() if cls in subpage_model.clean_parent_page_models()]
    @classmethod
    def creatable_subpage_models(cls): return [page_model for page_model in cls.allowed_subpage_models() if page_model.is_creatable]
    @classmethod
    def can_exist_under(cls, parent):
        return cls in parent.specific_class.allowed_subpage_models()
    @classmethod
    def can_create_at(cls, parent):
        can_create = cls.is_creatable and cls.can_exist_under(parent)
        if cls.max_count is not None: can_create = can_create and cls.objects.count() < cls.max_count
        if cls.max_count_per_parent is not None: can_create = can_create and parent.get_children().type(cls).count() < cls.max_count_per_parent
        return can_create
    def can_move_to(self, parent):
        parent_is_root = parent.depth == 1
        if not parent_is_root: return False
        return self.can_exist_under(parent)
    @classmethod
    def get_verbose_name(cls): return capfirst(cls._meta.verbose_name)
    @property
    def status_string(self):
        if not self.live:
            if self.expired:return "expired"
            elif self.approved_schedule:return "scheduled"
            elif self.workflow_in_progress:return "in moderation"
            else:return "draft"
        else:
            if self.approved_schedule: return "live + scheduled"
            elif self.workflow_in_progress: return "live + in moderation"
            elif self.has_unpublished_changes: return "live + draft"
            else: return "live"
    @property
    def approved_schedule(self):
        if hasattr(self, "_approved_schedule"): return self._approved_schedule
        return self.revisions.exclude(approved_go_live_at__isnull=True).exists()
    def has_unpublished_subtree(self): return (not self.live) and (not self.get_descendants().filter(live=True).exists())
    def move(self, target, pos=None, user=None):
        parent_before = self.get_parent()
        if pos in ('first-child', 'last-child', 'sorted-child'): parent_after = target
        else: parent_after = target.get_parent()
        old_self = Page.objects.get(id=self.id)
        old_url_path = old_self.url_path
        new_url_path = old_self.set_url_path(parent=parent_after)
        pre_page_move.send(sender=self.specific_class or self.__class__, instance=self, parent_page_before=parent_before, parent_page_after=parent_after, url_path_before=old_url_path, url_path_after=new_url_path)
        with transaction.atomic():
            super().move(target, pos=pos)
            new_self = Page.objects.get(id=self.id)
            new_self.url_path = new_url_path
            new_self.save()
            if old_url_path != new_url_path: new_self._update_descendant_url_paths(old_url_path, new_url_path)
        post_page_move.send(sender=self.specific_class or self.__class__, instance=new_self, parent_page_before=parent_before, parent_page_after=parent_after, url_path_before=old_url_path, url_path_after=new_url_path)
        log(instance=self,action='reordered' if parent_before.id == target.id else 'moved', user=user, data={'source': {'id': parent_before.id, 'title': parent_before.specific_deferred.get_admin_display_title()}, 'destination': {'id': parent_after.id, 'title': parent_after.specific_deferred.get_admin_display_title()}})
        logger.info("Page moved: \"%s\" id=%d path=%s", self.title, self.id, new_url_path)
    def copy(self, recursive=False, to=None, update_attrs=None, copy_revisions=True, keep_live=True, user=None, process_child_object=None, exclude_fields=None, log_action='copied', reset_translation_key=True, _mpnode_attrs=None):
        if self._state.adding: raise RuntimeError('Page.copy() called on an unsaved page')
        exclude_fields = self.default_exclude_fields_in_copy + self.exclude_fields_in_copy + (exclude_fields or [])
        specific_self = self.specific
        if keep_live: base_update_attrs = {'alias_of': None,}
        else: base_update_attrs = {'live': False, 'has_unpublished_changes': True, 'live_revision': None, 'first_published_at': None, 'last_published_at': None, 'alias_of': None, }
        if user: base_update_attrs['owner'] = user
        if update_attrs: base_update_attrs.update(update_attrs)
        page_copy, child_object_map = _copy(specific_self, exclude_fields=exclude_fields, update_attrs=base_update_attrs)
        for (child_relation, old_pk), child_object in child_object_map.items():
            if process_child_object: process_child_object(specific_self, page_copy, child_relation, child_object)
            # if reset_translation_key and isinstance(child_object, TranslatableMixin): child_object.translation_key = uuid.uuid4()
        if _mpnode_attrs:
            page_copy.path = _mpnode_attrs[0]
            page_copy.depth = _mpnode_attrs[1]
            page_copy.save(clean=False)
        else:
            if to:
                if recursive and (to == self or to.is_descendant_of(self)):
                    raise Exception("You cannot copy a tree branch recursively into itself")
                page_copy = to.add_child(instance=page_copy)
            else: page_copy = self.add_sibling(instance=page_copy)
            _mpnode_attrs = (page_copy.path, page_copy.depth)
        _copy_m2m_relations(specific_self, page_copy, exclude_fields=exclude_fields, update_attrs=base_update_attrs)
        if copy_revisions:
            for revision in self.revisions.all():
                revision.pk = None
                revision.submitted_for_moderation = False
                revision.approved_go_live_at = None
                revision.page = page_copy
                revision_content = json.loads(revision.content_json)
                revision_content['pk'] = page_copy.pk
                for child_relation in get_all_child_relations(specific_self):
                    accessor_name = child_relation.get_accessor_name()
                    try: child_objects = revision_content[accessor_name]
                    except KeyError: continue
                    for child_object in child_objects:
                        child_object[child_relation.field.name] = page_copy.pk
                        copied_child_object = child_object_map.get((child_relation, child_object['pk']))
                        child_object['pk'] = copied_child_object.pk if copied_child_object else None
                revision.content_json = json.dumps(revision_content)
                revision.save()
        latest_revision = page_copy.get_latest_revision_as_page()
        if update_attrs:
            for field, value in update_attrs.items(): setattr(latest_revision, field, value)
        latest_revision_as_page_revision = latest_revision.save_revision(user=user, changed=False, clean=False)
        if keep_live:
            page_copy.live_revision = latest_revision_as_page_revision
            page_copy.last_published_at = latest_revision_as_page_revision.created_at
            page_copy.first_published_at = latest_revision_as_page_revision.created_at
            page_copy.save(clean=False)
        if page_copy.live: page_published.send( sender=page_copy.specific_class, instance=page_copy, revision=latest_revision_as_page_revision)
        if log_action:
            parent = specific_self.get_parent()
            log(instance=page_copy,action=log_action,user=user,data={'page': {'id': page_copy.id,'title': page_copy.get_admin_display_title()},'source': {'id': parent.id, 'title': parent.specific_deferred.get_admin_display_title()} if parent else None,'destination': {'id': to.id, 'title': to.specific_deferred.get_admin_display_title()} if to else None,'keep_live': page_copy.live and keep_live},)
            if page_copy.live and keep_live: log(instance=page_copy,action='published',user=user,revision=latest_revision_as_page_revision,)
        logger.info("Page copied: \"%s\" id=%d from=%d", page_copy.title, page_copy.id, self.id)
        if recursive:
            numchild = 0
            for child_page in self.get_children().specific():
                newdepth = _mpnode_attrs[1] + 1
                child_mpnode_attrs = (Page._get_path(_mpnode_attrs[0], newdepth, numchild),newdepth)
                numchild += 1
                child_page.copy(recursive=True,to=page_copy,copy_revisions=copy_revisions,keep_live=keep_live,user=user,process_child_object=process_child_object,_mpnode_attrs=child_mpnode_attrs)
            if numchild > 0:
                page_copy.numchild = numchild
                page_copy.save(clean=False, update_fields=['numchild'])
        return page_copy
    copy.alters_data = True
    def create_alias(self, *, recursive=False, parent=None, update_slug=None, user=None, log_action='alias_created', reset_translation_key=True, _mpnode_attrs=None):
        specific_self = self.specific
        exclude_fields = ['id', 'path', 'depth', 'numchild', 'url_path', 'path', 'index_entries', 'postgres_index_entries']
        update_attrs = {'alias_of': self,'draft_title': self.title,'has_unpublished_changes': not self.live}
        if update_slug: update_attrs['slug'] = update_slug
        if user: update_attrs['owner'] = user
        alias, child_object_map = _copy(specific_self, update_attrs=update_attrs, exclude_fields=exclude_fields)
        if _mpnode_attrs:
            alias.path = _mpnode_attrs[0]
            alias.depth = _mpnode_attrs[1]
            alias.save(clean=False)
        else:
            if parent:
                if recursive and (parent == self or parent.is_descendant_of(self)): raise Exception("You cannot copy a tree branch recursively into itself")
                alias = parent.add_child(instance=alias)
            else: alias = self.add_sibling(instance=alias)
            _mpnode_attrs = (alias.path, alias.depth)
        _copy_m2m_relations(specific_self, alias, exclude_fields=exclude_fields)
        if log_action:
            source_parent = specific_self.get_parent()
            log(instance=alias,action=log_action,user=user,data={'page': {'id': alias.id,'title': alias.get_admin_display_title()},'source': {'id': source_parent.id, 'title': source_parent.specific_deferred.get_admin_display_title()} if source_parent else None,'destination': {'id': parent.id, 'title': parent.specific_deferred.get_admin_display_title()} if parent else None,},)
            if alias.live: log(instance=alias,action='published',user=user,)
        logger.info("Page alias created: \"%s\" id=%d from=%d", alias.title, alias.id, self.id)
        if recursive:
            numchild = 0
            for child_page in self.get_children().specific():
                newdepth = _mpnode_attrs[1] + 1
                child_mpnode_attrs = (Page._get_path(_mpnode_attrs[0], newdepth, numchild),newdepth)
                numchild += 1
                child_page.create_alias(recursive=True,parent=alias,user=user,log_action=log_action,reset_translation_key=reset_translation_key,_mpnode_attrs=child_mpnode_attrs)
            if numchild > 0:
                alias.numchild = numchild
                alias.save(clean=False, update_fields=['numchild'])
        return alias
    create_alias.alters_data = True
    def permissions_for_user(self, user):
        user_perms = UserPagePermissionsProxy(user)
        return user_perms.for_page(self)
    def make_preview_request(self, original_request=None, preview_mode=None, extra_request_attrs=None):
        dummy_meta = self._get_dummy_headers(original_request)
        request = WSGIRequest(dummy_meta)
        request.is_dummy = True
        if extra_request_attrs:
            for k, v in extra_request_attrs.items(): setattr(request, k, v)
        page = self
        class Handler(BaseHandler):
            def _get_response(self, request):
                response = page.serve_preview(request, preview_mode)
                if hasattr(response, 'render') and callable(response.render): response = response.render()
                return response
        handler = Handler()
        handler.load_middleware()
        return handler.get_response(request)
    def _get_dummy_headers(self, original_request=None):
        url = self._get_dummy_header_url(original_request)
        if url:
            url_info = urlparse(url)
            hostname = url_info.hostname
            path = url_info.path
            port = url_info.port or (443 if url_info.scheme == 'https' else 80)
            scheme = url_info.scheme
        else:
            try:
                hostname = settings.ALLOWED_HOSTS[0]
                if hostname == '*': raise IndexError
            except IndexError: hostname = 'localhost'
            path = '/'
            port = 80
            scheme = 'http'
        http_host = hostname
        if port != (443 if scheme == 'https' else 80): http_host = '%s:%s' % (http_host, port)
        dummy_values = {'REQUEST_METHOD': 'GET','PATH_INFO': path,'SERVER_NAME': hostname,'SERVER_PORT': port,'SERVER_PROTOCOL': 'HTTP/1.1','HTTP_HOST': http_host,'wsgi.version': (1, 0),'wsgi.input': StringIO(),'wsgi.errors': StringIO(),'wsgi.url_scheme': scheme,'wsgi.multithread': True,'wsgi.multiprocess': True,'wsgi.run_once': False}
        HEADERS_FROM_ORIGINAL_REQUEST = ['REMOTE_ADDR', 'HTTP_X_FORWARDED_FOR', 'HTTP_COOKIE', 'HTTP_USER_AGENT', 'HTTP_AUTHORIZATION', 'wsgi.version', 'wsgi.multithread', 'wsgi.multiprocess', 'wsgi.run_once', ]
        if settings.SECURE_PROXY_SSL_HEADER: HEADERS_FROM_ORIGINAL_REQUEST.append(settings.SECURE_PROXY_SSL_HEADER[0])
        if original_request:
            for header in HEADERS_FROM_ORIGINAL_REQUEST:
                if header in original_request.META: dummy_values[header] = original_request.META[header]
        return dummy_values
    def _get_dummy_header_url(self, original_request=None): return self.full_url
    DEFAULT_PREVIEW_MODES = [('', "Default")]
    @property
    def preview_modes(self): return Page.DEFAULT_PREVIEW_MODES
    @property
    def default_preview_mode(self): return self.preview_modes[0][0]
    def is_previewable(self):
        page = self
        try: 
            if page.specific_class.preview_modes != type(page).preview_modes: page = page.specific
        except: pass
        return bool(page.preview_modes)
    def serve_preview(self, request, mode_name):
        request.is_preview = True
        request.preview_mode = mode_name
        response = self.serve(request)
        patch_cache_control(response, private=True)
        return response
    def get_cached_paths(self): return ['/']
    def get_sitemap_urls(self, request=None): return [{'location': self.get_full_url(request),'lastmod': (self.last_published_at or self.latest_revision_created_at)}]
    def get_static_site_paths(self):
        yield '/'
        for child in self.get_children().live():
            for path in child.specific.get_static_site_paths(): yield '/' + child.slug + path
    def get_ancestors(self, inclusive=False): return Page.objects.ancestor_of(self, inclusive)
    def get_descendants(self, inclusive=False): return Page.objects.descendant_of(self, inclusive)
    def get_siblings(self, inclusive=True): return Page.objects.sibling_of(self, inclusive)
    def get_next_siblings(self, inclusive=False): return self.get_siblings(inclusive).filter(path__gte=self.path).order_by('path')
    def get_prev_siblings(self, inclusive=False): return self.get_siblings(inclusive).filter(path__lte=self.path).order_by('-path')
    def get_view_restrictions(self):
        page_ids_to_check = set()
        def add_page_to_check_list(page):
            if page.alias_of: add_page_to_check_list(page.alias_of)
            else: page_ids_to_check.add(page.id)
        add_page_to_check_list(self)
        for page in self.get_ancestors().only('alias_of'): add_page_to_check_list(page)
        return PageViewRestriction.objects.filter(page_id__in=page_ids_to_check)
    password_required_template = getattr(settings, 'PASSWORD_REQUIRED_TEMPLATE', 'wagtailcore/password_required.html')
    def serve_password_required_response(self, request, form, action_url):
        context = self.get_context(request)
        context['form'] = form
        context['action_url'] = action_url
        return TemplateResponse(request, self.password_required_template, context)
    def with_content_json(self, content_json):
        data = json.loads(content_json)
        obj = self.specific_class.from_serializable_data(data)
        obj.id = self.id
        obj.pk = self.pk
        obj.content_type = self.content_type
        obj.path = self.path
        obj.depth = self.depth
        obj.numchild = self.numchild
        obj.set_url_path(self.get_parent())
        obj.draft_title = self.draft_title
        obj.live = self.live
        obj.has_unpublished_changes = self.has_unpublished_changes
        obj.owner = self.owner
        obj.locked = self.locked
        obj.locked_by = self.locked_by
        obj.locked_at = self.locked_at
        obj.latest_revision_created_at = self.latest_revision_created_at
        obj.first_published_at = self.first_published_at
        obj.alias_of_id = self.alias_of_id
        return obj
    @property
    def has_workflow(self):
        return self.get_ancestors(inclusive=True).filter(workflowpage__isnull=False).filter(workflowpage__workflow__active=True).exists()
    def get_workflow(self):
        if hasattr(self, 'workflowpage') and self.workflowpage.workflow.active: return self.workflowpage.workflow
        else:
            try: workflow = self.get_ancestors().filter(workflowpage__isnull=False).filter(workflowpage__workflow__active=True).order_by('-depth').first().workflowpage.workflow
            except AttributeError: workflow = None
            return workflow
    @property
    def workflow_in_progress(self):
        if hasattr(self, "_current_workflow_states"):
            for state in self._current_workflow_states:
                if state.status == WorkflowState.STATUS_IN_PROGRESS: return True
            return False
        return WorkflowState.objects.filter(page=self, status=WorkflowState.STATUS_IN_PROGRESS).exists()
    @property
    def current_workflow_state(self):
        if hasattr(self, "_current_workflow_states"):
            try: return self._current_workflow_states[0]
            except IndexError: return
        try: return WorkflowState.objects.active().select_related("current_task_state__task").get(page=self)
        except WorkflowState.DoesNotExist: return
    @property
    def current_workflow_task_state(self):
        current_workflow_state = self.current_workflow_state
        if current_workflow_state and current_workflow_state.status == WorkflowState.STATUS_IN_PROGRESS and current_workflow_state.current_task_state: return current_workflow_state.current_task_state.specific
    @cached_classmethod
    def get_edit_handler(cls):
        from wagtail.admin.edit_handlers import ObjectList, TabbedInterface
        if hasattr(cls, 'edit_handler'): edit_handler = cls.edit_handler
        else:
            tabs = []
            if cls.content_panels: tabs.append(ObjectList(cls.content_panels,heading='Content'))
            if cls.promote_panels: tabs.append(ObjectList(cls.promote_panels,heading='Promote'))
            if cls.settings_panels: tabs.append(ObjectList(cls.settings_panels,heading='Settings',classname='settings'))
            edit_handler = TabbedInterface(tabs, base_form_class=cls.base_form_class)
        return edit_handler.bind_to(model=cls)
    @property
    def current_workflow_task(self):
        current_workflow_task_state = self.current_workflow_task_state
        if current_workflow_task_state: return current_workflow_task_state.task.specific
    class Meta:
        ordering = ['path']
        default_permissions=[]
        verbose_name = "page"
        verbose_name_plural = "pages"

class Orderable(models.Model):
    sort_order = models.IntegerField(null=True, blank=True, editable=False)
    sort_order_field = 'sort_order'
    class Meta:
        abstract = True
        ordering = ['sort_order']

class SiteManager(models.Manager):
    def get_queryset(self):return super(SiteManager, self).get_queryset()
    def get_by_natural_key(self, hostname, port):return self.get(hostname=hostname, port=port)
SiteRootPath = namedtuple('SiteRootPath', 'site_id root_path root_url')
class Site(Orderable):
    hostname = models.CharField(max_length=255, db_index=True)
    port = models.IntegerField(default=443)
    site_name = models.CharField(max_length=255,blank=True,help_text="Human-readable name for the site.")
    root_page = ParentalKey('Page',null=True,blank=True, related_name='sites_rooted_here',on_delete=models.CASCADE)
    is_default_site = models.BooleanField(default=False,help_text="to handle requests for all other hostnames that do not have a site entry of their own")
    objects = SiteManager()
    def natural_key(self):return (self.hostname, self.port)
    def __str__(self):
        default_suffix = " [{}]".format("default")
        if self.site_name:return (self.site_name + (default_suffix if self.is_default_site else ""))
        else: return ( self.hostname + ("" if self.port == 80 else (":%d" % self.port)) + (default_suffix if self.is_default_site else "") )
    @staticmethod
    def find_for_request(request):
        """
            Find the site object responsible for responding to this HTTP request object. Try:
            * unique hostname first
            * then hostname and port
            * if there is no matching hostname at all, or no matching
            hostname:port combination, fall back to the unique default site,
            or raise an exception
            NB this means that high-numbered ports on an extant hostname may
            still be routed to a different hostname which is set as the default
            The site will be cached via request._wagtail_site
        """
        if request is None:return None
        if not hasattr(request, '_wagtail_site'):
            site = Site._find_for_request(request)
            try: setattr(request, '_wagtail_site', site)
            except AttributeError: return None
        return request._wagtail_site
    @staticmethod
    def _find_for_request(request):
        def get_site_for_hostname(hostname, port):
            """Return the wagtailcore.Site object for the given hostname and port."""
            Site = apps.get_model('wagtailcore.Site')
            sites = list(Site.objects.annotate(match=Case(When(hostname=hostname, port=port, then=0),When(hostname=hostname, is_default_site=True, then=1),When(is_default_site=True, then=2),default=3,output_field=IntegerField(),)).filter(Q(hostname=hostname) | Q(is_default_site=True)).order_by('match').select_related('root_page'))
            if sites:
                if len(sites) == 1 or sites[0].match in (0, 1): return sites[0]
                # if there is a default match with a different hostname, see if there are many hostname matches. if only 1 then use that instead otherwise we use the default
                if sites[0].match == 2: return sites[len(sites) == 2]
            raise Site.DoesNotExist()
        site = None
        try:
            hostname = (split_domain_port(request.get_host())[0] if request else '/')
            port = request.get_port()
            site = get_site_for_hostname(hostname, port)
        except Site.DoesNotExist:pass
        except AttributeError:pass
        return site
    @property
    def root_url(self):
        if self.port == 80:return 'http://%s' % self.hostname
        elif self.port == 443:return 'https://%s' % self.hostname
        else:return 'http://%s:%d' % (self.hostname, self.port)
    def clean_fields(self, exclude=None):
        super().clean_fields(exclude)
        # Only one site can have the is_default_site flag set
        try:default = Site.objects.get(is_default_site=True)
        except Site.DoesNotExist:pass
        except Site.MultipleObjectsReturned:raise
        else:
            if self.is_default_site and self.pk != default.pk:
                default.is_default_site=False
                default.save()
        if not self.root_page:
            from base.models.pages import HomePage
            new_page=HomePage(slug=self.hostname.replace(".","_")[1],title=f"Home Page for ({self.hostname})")
            if self.host_only == "techodesign.pro": parent_page = HomePage.objects.get(id=770)
            elif self.host_only == "az-ecosys.com": parent_page = HomePage.objects.get(id=3)
            else: parent_page = Page.objects.get(id=780)
            parent_page.add_child(instance=new_page).save_revision().publish()
            self.root_page=new_page
    @staticmethod
    def get_site_root_paths():
        result = cache.get('wagtail_site_root_paths')
        if result is None or any(len(i) == 3 for i in result):
            result = []
            for s in Site.objects.select_related('root_page'): result.append(SiteRootPath(s.id, s.root_page.url_path, s.root_url))
            cache.set('wagtail_site_root_paths', result, 3600)
        return result
    def generate_cert_and_nginxconf(self, *args, **kwargs):
        import os
        os.system(f"certbot certonly --nginx --non-interactive -d {self.hostname} --cert-name {self.hostname}")
        config_path = f'/etc/nginx/sites-enabled/{self.hostname}.conf'
        with open(config_path, 'w') as config_file:
            config_content = f"""server {{server_name {self.hostname} {self.host_only if self.hostname.split(".", maxsplit=1)[0] == "www" else ""};listen 80;listen [::]:80;return 301 https://{self.hostname}$request_uri;}}
            server {{server_name {self.hostname} {self.host_only if self.hostname.split(".", maxsplit=1)[0] == "www" else ""};include sites-enabled/common_base_server_locations;include sites-enabled/common_locations;listen 443 ssl http2; include /etc/letsencrypt/options-ssl-nginx.conf; ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
            ssl_certificate /etc/letsencrypt/live/{self.hostname}/fullchain.pem; 
            ssl_certificate_key /etc/letsencrypt/live/{self.hostname}/privkey.pem; }}
            """
            config_file.write(config_content)
        os.system("nginx -s reload")
    @property
    def host_only(self):
        host = self.hostname.split(".", maxsplit=1)[1]
        return host
    class Meta(Orderable.Meta):
        unique_together = ('hostname', 'port')
        verbose_name = "site"
        verbose_name_plural = "sites"
        ordering = ["sort_order"]

@receiver(post_save, sender=Site)
def generate_nginx_config(sender, instance, created, **kwargs):
    if created: instance.generate_cert_and_nginxconf()

class SubmittedRevisionsManager(models.Manager):
    def get_queryset(self): return super().get_queryset().filter(submitted_for_moderation=True)
class PageRevision(models.Model):
    page = models.ForeignKey('Page', verbose_name="page", related_name='revisions', on_delete=models.CASCADE)
    submitted_for_moderation = models.BooleanField(verbose_name="submitted for moderation", default=False, db_index=True)
    created_at = models.DateTimeField(db_index=True, verbose_name="created at")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="user", null=True, blank=True, on_delete=models.SET_NULL)
    content_json = models.TextField(verbose_name="content JSON")
    approved_go_live_at = models.DateTimeField(verbose_name="approved go live at", null=True, blank=True, db_index=True)
    objects = models.Manager()
    submitted_revisions = SubmittedRevisionsManager()
    def save(self, user=None, *args, **kwargs):
        if self.created_at is None: self.created_at = timezone.now()
        super().save(*args, **kwargs)
        if self.submitted_for_moderation: self.page.revisions.exclude(id=self.id).update(submitted_for_moderation=False)
        if (self.approved_go_live_at is None and 'update_fields' in kwargs and 'approved_go_live_at' in kwargs['update_fields']):
            page = self.as_page_object()
            log(instance=page, action='publishing_schedule_canceled', data={'revision': {'id': self.id, 'created': self.created_at.strftime("%d %b %Y %H:%M"), 'go_live_at': page.go_live_at.strftime("%d %b %Y %H:%M") if page.go_live_at else None,}}, user=user, revision=self,)
    def as_page_object(self): return self.page.specific.with_content_json(self.content_json)
    def approve_moderation(self, user=None):
        if self.submitted_for_moderation:
            logger.info("Page moderation approved: \"%s\" id=%d revision_id=%d", self.page.title, self.page.id, self.id)
            log(instance=self.as_page_object(), action='approved', user=user, revision=self)
            self.publish()
    def reject_moderation(self, user=None):
        if self.submitted_for_moderation:
            logger.info("Page moderation rejected: \"%s\" id=%d revision_id=%d", self.page.title, self.page.id, self.id)
            log(instance=self.as_page_object(), action='rejected', user=user, revision=self)
            self.submitted_for_moderation = False
            self.save(update_fields=['submitted_for_moderation'])
    def is_latest_revision(self):
        if self.id is None: return True
        latest_revision = PageRevision.objects.filter(page_id=self.page_id).order_by('-created_at', '-id').first()
        return (latest_revision == self)
    def delete(self):
        try: next_revision = self.get_next()
        except PageRevision.DoesNotExist: next_revision = None
        return super().delete()
    def publish(self, user=None, changed=True, log_action=True, previous_revision=None):
        page = self.as_page_object()
        def log_scheduling_action(revision, user=None, changed=changed):
            log(instance=page, action='publishing_scheduled', user=user, data={'revision': {'id': revision.id, 'created': revision.created_at.strftime("%d %b %Y %H:%M"), 'go_live_at': page.go_live_at.strftime("%d %b %Y %H:%M"), 'has_live_version': page.live, }}, revision=revision, content_changed=changed)
        if page.go_live_at and page.go_live_at > timezone.now():
            page.has_unpublished_changes = True
            self.approved_go_live_at = page.go_live_at
            self.save()
            page.revisions.exclude(id=self.id).update(approved_go_live_at=None)
            if page.live_revision:
                if log_action:log_scheduling_action(self, user, changed)
                return
            page.live = False
        else:
            page.live = True
            page.has_unpublished_changes = not self.is_latest_revision()
            page.revisions.update(approved_go_live_at=None)
        page.expired = False  
        if page.live:
            now = timezone.now()
            page.last_published_at = now
            page.live_revision = self
            if page.first_published_at is None: page.first_published_at = now
            if previous_revision:
                previous_revision_page = previous_revision.as_page_object()
                old_page_title = previous_revision_page.title if page.title != previous_revision_page.title else None
            else:
                try: previous = self.get_previous()
                except PageRevision.DoesNotExist: previous = None
                old_page_title = previous.page.title if previous and page.title != previous.page.title else None
        else: page.live_revision = None
        page.save()
        self.submitted_for_moderation = False
        page.revisions.update(submitted_for_moderation=False)
        workflow_state = page.current_workflow_state
        if workflow_state: workflow_state.cancel(user=user)
        if page.live:
            page_published.send(sender=page.specific_class, instance=page.specific, revision=self)
            page.update_aliases(revision=self, user=user, _content_json=self.content_json)
            if log_action:
                data = None
                if previous_revision: data = {'revision': {'id': previous_revision.id, 'created': previous_revision.created_at.strftime("%d %b %Y %H:%M")}}
                if old_page_title:
                    data = data or {}
                    data['title'] = {'old': old_page_title, 'new': page.title,}
                    log(instance=page, action='renamed', user=user, data=data, revision=self)
                log(instance=page, action=log_action if isinstance(log_action, str) else 'published', user=user, data=data, revision=self, content_changed=changed)
            logger.info("Page published: \"%s\" id=%d revision_id=%d", page.title, page.id, self.id)
        elif page.go_live_at:
            logger.info("Page scheduled for publish: \"%s\" id=%d revision_id=%d go_live_at=%s", page.title, page.id, self.id, page.go_live_at.isoformat())
            if log_action: log_scheduling_action(self, user, changed)
    def get_previous(self): return self.get_previous_by_created_at(page=self.page)
    def get_next(self): return self.get_next_by_created_at(page=self.page)
    def __str__(self): return f"{str(self.page)} at {str(self.created_at)}"
    class Meta:
        verbose_name = "page revision"
        verbose_name_plural = "page revisions"

PAGE_PERMISSION_TYPES = [
    ('add', "Add", "Add/edit pages user owns"),
    ('edit', "Edit", "Edit any page"),
    ('publish', "Publish", "Publish any page"),
    ('bulk_delete', "Bulk delete", "Delete pages with children"),
    ('lock', "Lock", "Lock/unlock pages you've locked"),
    ('unlock', "Unlock", "Unlock any page"),
]

PAGE_PERMISSION_TYPE_CHOICES = [(identifier, long_label) for identifier, short_label, long_label in PAGE_PERMISSION_TYPES]

class GroupPagePermissionManager(models.Manager):
    def create(self, **kwargs):
        # Simplify creation of GroupPagePermission objects by allowing one
        # of permission or permission_type to be passed in.
        permission = kwargs.get("permission")
        permission_type = kwargs.get("permission_type")
        if not permission and permission_type:
            # Not raising a warning here as we will still support this even after
            # the permission_type field is removed.
            kwargs["permission"] = Permission.objects.get(content_type=get_default_page_content_type(),codename=f"{permission_type}_page",)
        if permission and not permission_type:
            kwargs["permission_type"] = permission.codename[:-5]
        return super().create(**kwargs)
    def _migrate_permission_type(self):
        # RemovedInWagtail60Warning: remove this method
        # This follows the same logic as the
        # 0086_populate_grouppagepermission_permission migration, but is run as
        # part of a system check to ensure any objects that are created after
        # that migration is run are also updated.
        return (
            self.filter(models.Q(permission__isnull=True) | models.Q(permission_type="edit"))
            .annotate(normalised_permission_type=models.Case(models.When(permission_type="edit", then=models.Value("change")),default=models.F("permission_type"),))
            .update(permission=Permission.objects.filter(content_type=get_default_page_content_type(),codename=Concat(models.OuterRef("normalised_permission_type"),models.Value("_page"),),).values_list("pk", flat=True)[:1],permission_type=models.F("normalised_permission_type"),)
        )

class GroupPagePermission(models.Model):
    group = models.ForeignKey(Group, verbose_name="group", related_name='page_permissions', on_delete=models.CASCADE)
    page = models.ForeignKey('Page', verbose_name="page", related_name='group_permissions', on_delete=models.CASCADE)
    permission_type = models.CharField(verbose_name="permission type",max_length=20,choices=PAGE_PERMISSION_TYPE_CHOICES)
    permission = models.ForeignKey(Permission,verbose_name="permission",null=True,blank=True,on_delete=models.CASCADE,)
    objects = GroupPagePermissionManager()
    class Meta:
        unique_together = ('group', 'page', 'permission_type')
        verbose_name = "group page permission"
        verbose_name_plural = "group page permissions"
    def __str__(self):
        return "Group %d ('%s') has permission '%s' on page %d ('%s')" % ( self.group.id, self.group, self.permission_type, self.page.id, self.page)

class UserPagePermissionsProxy:
    def __init__(self, user):
        self.user = user
        if user.is_active and not user.is_superuser: self.permissions = GroupPagePermission.objects.filter(group__user=self.user).select_related('page')
    def revisions_for_moderation(self):
        if not self.user.is_active: return PageRevision.objects.none()
        if self.user.is_superuser: return PageRevision.submitted_revisions.all()
        publishable_pages_paths = self.permissions.filter(permission_type='publish').values_list('page__path', flat=True).distinct()
        if not publishable_pages_paths: return PageRevision.objects.none()
        only_my_sections = Q(page__path__startswith=publishable_pages_paths[0])
        for page_path in publishable_pages_paths[1:]: only_my_sections = only_my_sections | Q(page__path__startswith=page_path)
        return PageRevision.submitted_revisions.filter(only_my_sections)
    def for_page(self, page): return PagePermissionTester(self, page)
    def explorable_pages(self):
        if not self.user.is_active: return Page.objects.none()
        if self.user.is_superuser: return Page.objects.all()
        explorable_pages = Page.objects.none()
        for perm in self.permissions.filter(Q(permission_type="add") | Q(permission_type="edit") | Q(permission_type="publish") | Q(permission_type="lock")):
            explorable_pages |= Page.objects.descendant_of(perm.page, inclusive=True)
        page_permissions = Page.objects.filter(group_permissions__in=self.permissions)
        for page in page_permissions:explorable_pages |= page.get_ancestors()
        first_common_ancestor_page = page_permissions.first_common_ancestor()
        explorable_pages = explorable_pages.filter(path__startswith=first_common_ancestor_page.path)
        return explorable_pages
    def editable_pages(self):
        if not self.user.is_active: return Page.objects.none()
        if self.user.is_superuser: return Page.objects.all()
        editable_pages = Page.objects.none()
        for perm in self.permissions.filter(permission_type='add'): editable_pages |= Page.objects.descendant_of(perm.page, inclusive=True).filter(owner=self.user)
        for perm in self.permissions.filter(permission_type='edit'): editable_pages |= Page.objects.descendant_of(perm.page, inclusive=True)
        return editable_pages
    def submissions_viewable_pages(self):
        if not self.user.is_active: return Page.objects.none()
        if self.user.is_superuser: return Page.objects.all()
        viewable_submissions_for_pages = Page.objects.none()
        for perm in self.permissions.filter(permission_type='add'): viewable_submissions_for_pages |= Page.objects.descendant_of(perm.page, inclusive=True)
        for perm in self.permissions.filter(permission_type='edit'): viewable_submissions_for_pages |= Page.objects.descendant_of(perm.page, inclusive=True)
        return viewable_submissions_for_pages
    def can_edit_pages(self): return self.editable_pages().exists()
    def publishable_pages(self):
        if not self.user.is_active: return Page.objects.none()
        if self.user.is_superuser: return Page.objects.all()
        publishable_pages = Page.objects.none()
        for perm in self.permissions.filter(permission_type='publish'): publishable_pages |= Page.objects.descendant_of(perm.page, inclusive=True)
        return publishable_pages
    def can_publish_pages(self): return self.publishable_pages().exists()
    def can_remove_locks(self):
        if self.user.is_superuser: return True
        if not self.user.is_active: return False
        else: return self.permissions.filter(permission_type='unlock').exists()

class PagePermissionTester:
    def __init__(self, user_perms, page):
        self.user = user_perms.user
        self.user_perms = user_perms
        self.page = page
        self.page_is_root = page.depth == 1  
        if self.user.is_active and not self.user.is_superuser: self.permissions = set(perm.permission_type for perm in user_perms.permissions if self.page.path.startswith(perm.page.path))
    def user_has_lock(self): return self.page.locked_by_id == self.user.pk
    def page_locked(self):
        current_workflow_task = self.page.current_workflow_task
        if current_workflow_task:
            if current_workflow_task.page_locked_for_user(self.page, self.user): return True
        if not self.page.locked: return False
        else: return not self.user_has_lock()
    def can_add_subpage(self):
        if not self.user.is_active: return False
        specific_class = self.page.specific_class
        if specific_class is None or not specific_class.creatable_subpage_models(): return False
        return self.user.is_superuser or ('add' in self.permissions)
    def can_edit(self):
        if not self.user.is_active or self.page_is_root:   return False
        if self.user.is_superuser or 'edit' in self.permissions or ('add' in self.permissions and self.page.owner_id == self.user.pk) or (self.page.current_workflow_task and self.page.current_workflow_task.user_can_access_editor(self.page, self.user)): return True
        return False
    def can_delete(self, ignore_bulk=False):
        if not self.user.is_active: return False
        if self.page_is_root:   return False
        if self.user.is_superuser: return True
        if 'bulk_delete' not in self.permissions and not self.page.is_leaf() and not ignore_bulk: return False
        if 'edit' in self.permissions:
            if 'publish' not in self.permissions:
                pages_to_delete = self.page.get_descendants(inclusive=True)
                if pages_to_delete.live().exists(): return False
            return True
        elif 'add' in self.permissions:
            pages_to_delete = self.page.get_descendants(inclusive=True)
            if 'publish' in self.permissions: return not pages_to_delete.exclude(owner=self.user).exists()
            else: return not pages_to_delete.exclude(live=False, owner=self.user).exists()
        else: return False
    def can_unpublish(self):
        if not self.user.is_active or (not self.page.live) or self.page_is_root or self.page_locked(): return False
        return self.user.is_superuser or ('publish' in self.permissions)
    def can_publish(self):
        if not self.user.is_active or self.page_is_root: return False
        return self.user.is_superuser or ('publish' in self.permissions)
    def can_submit_for_moderation(self): return not self.page_locked() and self.page.has_workflow and not self.page.workflow_in_progress
    def can_lock(self):
        if self.user.is_superuser: return True
        current_workflow_task = self.page.current_workflow_task
        if current_workflow_task: return current_workflow_task.user_can_lock(self.page, self.user)
        if 'lock' in self.permissions: return True
        return False
    def can_unlock(self):
        if self.user.is_superuser: return True
        if self.user_has_lock(): return True
        current_workflow_task = self.page.current_workflow_task
        if current_workflow_task: return current_workflow_task.user_can_unlock(self.page, self.user)
        if 'unlock' in self.permissions: return True
        return False
    def can_publish_subpage(self): 
        if not self.user.is_active: return False
        specific_class = self.page.specific_class
        if specific_class is None or not specific_class.creatable_subpage_models(): return False
        return self.user.is_superuser or ('publish' in self.permissions)
    def can_reorder_children(self): return self.can_publish_subpage()
    def can_move(self): return self.can_delete(ignore_bulk=True)
    def can_copy(self): return not self.page_is_root
    def can_move_to(self, destination):        
        if self.page == destination or destination.is_descendant_of(self.page): return False
        if not self.page.specific.can_move_to(destination): return False
        if not self.user.is_active: return False
        if self.user.is_superuser: return True
        if not self.can_move(): return False
        destination_perms = self.user_perms.for_page(destination)
        if 'add' not in destination_perms.permissions: return False
        if self.page.live or self.page.get_descendants().filter(live=True).exists(): return ('publish' in destination_perms.permissions)
        else: return True
    def can_copy_to(self, destination, recursive=False):
        if recursive and (self.page == destination or destination.is_descendant_of(self.page)): return False
        if not self.user.is_active: return False
        if not self.page.specific_class.can_create_at(destination): return False
        if self.user.is_superuser: return True
        destination_perms = self.user_perms.for_page(destination)
        if not destination.specific_class.creatable_subpage_models(): return False
        if 'add' not in destination_perms.permissions: return False
        return True
    
class PageViewRestriction(BaseViewRestriction):
    page = models.ForeignKey('Page', verbose_name="page", related_name='view_restrictions', on_delete=models.CASCADE)
    passed_view_restrictions_session_key = 'passed_page_view_restrictions'
    class Meta:
        verbose_name = "page view restriction"
        verbose_name_plural = "page view restrictions"
    def save(self, user=None, **kwargs):
        specific_instance = self.page.specific
        is_new = self.id is None
        super().save(**kwargs)
        if specific_instance: log(instance=specific_instance, action='view_restriction_added' if is_new else 'view_restriction_changed', user=user, data={'restriction': {'type': self.restriction_type, 'title': force_str(dict(self.RESTRICTION_CHOICES).get(self.restriction_type))}})
    def delete(self, user=None, **kwargs):
        specific_instance = self.page.specific
        if specific_instance: log(instance=specific_instance, action='view_restriction_deleted', user=user, data={'restriction': {'type': self.restriction_type, 'title': force_str(dict(self.RESTRICTION_CHOICES).get(self.restriction_type))}})
        return super().delete(**kwargs)

class WorkflowPage(models.Model):
    page = models.OneToOneField('Page', verbose_name="page", on_delete=models.CASCADE, primary_key=True, unique=True)
    workflow = models.ForeignKey('Workflow', related_name='workflow_pages', verbose_name="workflow", on_delete=models.CASCADE,)
    def get_pages(self):
        descendant_pages = Page.objects.descendant_of(self.page, inclusive=True)
        descendant_workflow_pages = WorkflowPage.objects.filter(page_id__in=descendant_pages.values_list('id', flat=True)).exclude(pk=self.pk)
        for path, depth in descendant_workflow_pages.values_list('page__path', 'page__depth'): descendant_pages = descendant_pages.exclude(path__startswith=path, depth__gte=depth)
        return descendant_pages
    class Meta:
        verbose_name = "workflow page"
        verbose_name_plural = "workflow pages"

class WorkflowTask(Orderable):
    workflow = ParentalKey('Workflow', on_delete=models.CASCADE, verbose_name="workflow_tasks", related_name='workflow_tasks')
    task = models.ForeignKey('Task', on_delete=models.CASCADE, verbose_name="Workflow Task", related_name='workflow_tasks', limit_choices_to={'active': True})
    class Meta(Orderable.Meta):
        unique_together = [('workflow', 'task')]
        verbose_name = "workflow task order"
        verbose_name_plural = "workflow task orders"

class TaskManager(models.Manager):
    def active(self): return self.filter(active=True)

class Task(models.Model):
    name = models.CharField(max_length=255, verbose_name="name")
    desc=models.TextField(null=True, blank=True, verbose_name="Description")
    content_type = models.ForeignKey(ContentType, verbose_name="content type", related_name='wagtail_tasks', on_delete=models.CASCADE)
    active = models.BooleanField(verbose_name="active", default=True, help_text="Active tasks can be added to workflows. Deactivating a task does not remove it from existing workflows.")
    objects = TaskManager()
    admin_form_fields = ['name','desc']
    admin_form_readonly_on_edit_fields = [] # HH changed: was ['name']
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.id: 
            if not self.content_type_id: self.content_type = ContentType.objects.get_for_model(self) 
    def __str__(self): return self.name
    @property
    def workflows(self): return Workflow.objects.filter(workflow_tasks__task=self)
    @property
    def active_workflows(self): return Workflow.objects.active().filter(workflow_tasks__task=self)
    @classmethod
    def get_verbose_name(cls): return capfirst(cls._meta.verbose_name)
    @cached_property
    def specific(self): 
        content_type = ContentType.objects.get_for_id(self.content_type_id)
        model_class = content_type.model_class()
        if model_class is None: return self
        elif isinstance(self, model_class): return self
        else: return content_type.get_object_for_this_type(id=self.id)
    task_state_class = None
    @classmethod
    def get_task_state_class(self): return self.task_state_class or TaskState
    def start(self, workflow_state, user=None):
        task_state = self.get_task_state_class()(workflow_state=workflow_state)
        task_state.status = TaskState.STATUS_IN_PROGRESS
        task_state.page_revision = workflow_state.page.get_latest_revision()
        task_state.task = self
        task_state.save()
        task_submitted.send(sender=task_state.specific.__class__, instance=task_state.specific, user=user)
        return task_state
    @transaction.atomic
    def on_action(self, task_state, user, action_name, **kwargs):
        if action_name == 'approve': task_state.approve(user=user, **kwargs)
        elif action_name == 'reject': task_state.reject(user=user, **kwargs)
    def user_can_access_editor(self, page, user): return False
    def page_locked_for_user(self, page, user): return False
    def user_can_lock(self, page, user): return False
    def user_can_unlock(self, page, user): return False
    def get_actions(self, page, user): return []
    def get_form_for_action(self, action): return TaskStateCommentForm
    def get_template_for_action(self, action): return ''
    def get_task_states_user_can_moderate(self, user, **kwargs): return TaskState.objects.none()
    @classmethod
    def get_description(cls): return ''
    @transaction.atomic
    def deactivate(self, user=None):
        self.active = False
        self.save()
        in_progress_states = TaskState.objects.filter(task=self, status=TaskState.STATUS_IN_PROGRESS)
        for state in in_progress_states: state.cancel(user=user)
    class Meta:
        verbose_name = "task"
        verbose_name_plural = "tasks"

class WorkflowManager(models.Manager):
    def active(self): return self.filter(active=True)

class Workflow(ClusterableModel):
    name = models.CharField(max_length=255, verbose_name="name")
    active = models.BooleanField(verbose_name="active", default=True, help_text="Active workflows can be added to pages. Deactivating a workflow does not remove it from existing pages.")
    objects = WorkflowManager()
    def __str__(self): return self.name
    @property
    def tasks(self): return Task.objects.filter(workflow_tasks__workflow=self).order_by('workflow_tasks__sort_order')
    @transaction.atomic
    def start(self, page, user):
        state = WorkflowState(page=page, workflow=self, status=WorkflowState.STATUS_IN_PROGRESS, requested_by=user)
        state.save()
        state.update(user=user)
        workflow_submitted.send(sender=state.__class__, instance=state, user=user)
        next_task_data = None
        if state.current_task_state: next_task_data = {'id': state.current_task_state.task.id, 'title': state.current_task_state.task.name, }
        log(instance=page, action='workflow_started', data={'workflow': {'id': self.id, 'title': self.name, 'status': state.status, 'next': next_task_data, 'task_state_id': state.current_task_state.id if state.current_task_state else None, }}, revision=page.get_latest_revision(), user=user)
        return state
    @transaction.atomic
    def deactivate(self, user=None):
        self.active = False
        in_progress_states = WorkflowState.objects.filter(workflow=self, status=WorkflowState.STATUS_IN_PROGRESS)
        for state in in_progress_states: state.cancel(user=user)
        WorkflowPage.objects.filter(workflow=self).delete()
        self.save()
    def all_pages(self):
        pages = Page.objects.none()
        for workflow_page in self.workflow_pages.all():pages |= workflow_page.get_pages()
        return pages
    class Meta:
        verbose_name = "workflow"
        verbose_name_plural = "workflows"

class GroupApprovalTask(Task):
    groups = models.ManyToManyField(Group, verbose_name="groups", help_text="Pages at this step in a workflow will be moderated or approved by these groups of users")
    admin_form_fields = Task.admin_form_fields + ['groups']
    admin_form_widgets = {'groups': forms.CheckboxSelectMultiple,}
    def start(self, workflow_state, user=None):
        if workflow_state.page.locked_by:
            if not workflow_state.page.locked_by.groups.filter(id__in=self.groups.all()).exists():
                workflow_state.page.locked = False
                workflow_state.page.locked_by = None
                workflow_state.page.locked_at = None
                workflow_state.page.save(update_fields=['locked', 'locked_by', 'locked_at'])
        return super().start(workflow_state, user=user)
    def user_can_access_editor(self, page, user): return self.groups.filter(id__in=user.groups.all()).exists() or user.is_superuser
    def page_locked_for_user(self, page, user): return not (self.groups.filter(id__in=user.groups.all()).exists() or user.is_superuser)
    def user_can_lock(self, page, user): return self.groups.filter(id__in=user.groups.all()).exists()
    def user_can_unlock(self, page, user): return False
    def get_actions(self, page, user):
        if self.groups.filter(id__in=user.groups.all()).exists() or user.is_superuser: return [('reject', "Request changes", True), ('approve', "Approve", False), ('approve', "Approve with comment", True), ]
        return []
    def get_task_states_user_can_moderate(self, user, **kwargs):
        if self.groups.filter(id__in=user.groups.all()).exists() or user.is_superuser: return TaskState.objects.filter(status=TaskState.STATUS_IN_PROGRESS, task=self.task_ptr)
        else: return TaskState.objects.none()

    @classmethod
    def get_description(cls): return "Members of the chosen User Groups can approve this task"

    class Meta:
        verbose_name = "Group approval task"
        verbose_name_plural = "Group approval tasks"

class WorkflowStateManager(models.Manager):
    def active(self): return self.filter(Q(status=WorkflowState.STATUS_IN_PROGRESS) | Q(status=WorkflowState.STATUS_NEEDS_CHANGES))

class WorkflowState(models.Model):
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_APPROVED = 'approved'
    STATUS_NEEDS_CHANGES = 'needs_changes'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = ((STATUS_IN_PROGRESS, "In progress"), (STATUS_APPROVED, "Approved"), (STATUS_NEEDS_CHANGES, "Needs changes"), (STATUS_CANCELLED, "Cancelled"),)
    page = models.ForeignKey('Page', on_delete=models.CASCADE, verbose_name="page", related_name='workflow_states')
    workflow = models.ForeignKey('Workflow', on_delete=models.CASCADE, verbose_name="workflow", related_name='workflow_states')
    status = models.fields.CharField(choices=STATUS_CHOICES, verbose_name="status", max_length=50, default=STATUS_IN_PROGRESS)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="created at")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="requested by", null=True, blank=True, editable=True, on_delete=models.SET_NULL, related_name='requested_workflows')
    current_task_state = models.OneToOneField('TaskState', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="current task state")
    on_finish ='pages.workflows.publish_workflow_state'
    objects = WorkflowStateManager()
    def clean(self):
        super().clean()
        if self.status in (self.STATUS_IN_PROGRESS, self.STATUS_NEEDS_CHANGES):
            if WorkflowState.objects.active().filter(page=self.page).exclude(pk=self.pk).exists(): raise ValidationError("There may only be one in progress or needs changes workflow state per page.")
    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
    def __str__(self): return "Workflow '{0}' on Page '{1}': {2}".format(self.workflow, self.page, self.status)
    def resume(self, user=None):
        if self.status != self.STATUS_NEEDS_CHANGES:
            raise PermissionDenied
        revision = self.current_task_state.page_revision
        current_task_state = self.current_task_state
        self.current_task_state = None
        self.status = self.STATUS_IN_PROGRESS
        self.save()

        log(instance=self.page.specific, action='workflow_resumed', data={
                'workflow': {
                    'id': self.workflow_id, 'title': self.workflow.name, 'status': self.status, 'task_state_id': current_task_state.id, 'task': {
                        'id': current_task_state.task.id, 'title': current_task_state.task.name, }, }
            }, revision=revision, user=user)
        return self.update(user=user, next_task=current_task_state.task)
    def user_can_cancel(self, user):
        if self.page.locked and self.page.locked_by != user:
            return False
        return user == self.requested_by or user == self.page.owner or (self.current_task_state and self.current_task_state.status == self.current_task_state.STATUS_IN_PROGRESS and 'approve' in [action[0] for action in self.current_task_state.task.get_actions(self.page, user)])
    def update(self, user=None, next_task=None):
        
        if self.status != self.STATUS_IN_PROGRESS:
            
            return
        try:
            current_status = self.current_task_state.status
        except AttributeError:
            current_status = None
        if current_status == TaskState.STATUS_REJECTED:
            self.status = self.STATUS_NEEDS_CHANGES
            self.save()
            workflow_rejected.send(sender=self.__class__, instance=self, user=user)
        else:
            if not next_task:
                next_task = self.get_next_task()
            if next_task:
                if (not self.current_task_state) or self.current_task_state.status != self.current_task_state.STATUS_IN_PROGRESS:
                    
                    self.current_task_state = next_task.specific.start(self, user=user)
                    self.save()
                    
                    if self.current_task_state.status != self.current_task_state.STATUS_IN_PROGRESS:
                        self.update(user=user)
                
            else:
                
                self.finish(user=user)
    @property
    def successful_task_states(self):
        successful_task_states = self.task_states.filter(Q(status=TaskState.STATUS_APPROVED) | Q(status=TaskState.STATUS_SKIPPED))
        return successful_task_states
    def get_next_task(self):
        

        return (Task.objects.filter(workflow_tasks__workflow=self.workflow, active=True)
            .exclude(task_states__in=self.successful_task_states
            ).order_by('workflow_tasks__sort_order').first()
        )
    def cancel(self, user=None):
        
        if self.status not in (self.STATUS_IN_PROGRESS, self.STATUS_NEEDS_CHANGES):
            raise PermissionDenied
        self.status = self.STATUS_CANCELLED
        self.save()

        log(instance=self.page.specific, action='workflow_canceled', data={
                'workflow': {
                    'id': self.workflow_id, 'title': self.workflow.name, 'status': self.status, 'task_state_id': self.current_task_state.id, 'task': {
                        'id': self.current_task_state.task.id, 'title': self.current_task_state.task.name, }, }
            }, revision=self.current_task_state.page_revision, user=user)

        for state in self.task_states.filter(status=TaskState.STATUS_IN_PROGRESS):
            
            state.specific.cancel(user=user)
        workflow_cancelled.send(sender=self.__class__, instance=self, user=user)
    @transaction.atomic
    def finish(self, user=None):
        
        if self.status != self.STATUS_IN_PROGRESS:
            raise PermissionDenied
        self.status = self.STATUS_APPROVED
        self.save()
        self.on_finish(user=user)
        workflow_approved.send(sender=self.__class__, instance=self, user=user)
    def copy_approved_task_states_to_revision(self, revision):
        
        approved_states = TaskState.objects.filter(workflow_state=self, status=TaskState.STATUS_APPROVED)
        for state in approved_states:
            state.copy(update_attrs={'page_revision': revision})
    def revisions(self):
        
        return PageRevision.objects.filter(page_id=self.page_id, id__in=self.task_states.values_list('page_revision_id', flat=True)
        ).defer('content_json')
    def _get_applicable_task_states(self): return TaskState.objects.filter(workflow_state_id=self.id)
    def all_tasks_with_status(self):
        
        
        task_states = self._get_applicable_task_states()

        tasks = list(self.workflow.tasks.annotate(status=Subquery(task_states.filter(task_id=OuterRef('id')).order_by('-started_at', '-id'
                    ).values('status')[:1]
                ))
        )

        
        status_choices = dict(TaskState.STATUS_CHOICES)
        for task in tasks:
            task.status_display = status_choices.get(task.status, "Not started")

        return tasks
    def all_tasks_with_state(self):
        
        task_states = self._get_applicable_task_states()

        tasks = list(self.workflow.tasks.annotate(task_state_id=Subquery(task_states.filter(task_id=OuterRef('id')).order_by('-started_at', '-id'
                    ).values('id')[:1]
                ))
        )

        task_states = {task_state.id: task_state for task_state in task_states}
        
        for task in tasks:
            task.task_state = task_states.get(task.task_state_id)

        return tasks
    @property
    def is_active(self):
        return self.status not in [self.STATUS_APPROVED, self.STATUS_CANCELLED]
    @property
    def is_at_final_task(self):
        

        last_task = Task.objects.filter(workflow_tasks__workflow=self.workflow, active=True)\
            .exclude(task_states__in=self.successful_task_states)\
            .order_by('workflow_tasks__sort_order').last()

        return self.get_next_task() == last_task

    class Meta:
        verbose_name = "Workflow state"
        verbose_name_plural = "Workflow states"
        
        constraints = [
            models.UniqueConstraint(fields=['page'], condition=Q(status__in=('in_progress', 'needs_changes')), name='unique_in_progress_workflow')
        ]

class TaskStateManager(models.Manager):
    def reviewable_by(self, user):
        tasks = Task.objects.filter(active=True)
        states = TaskState.objects.none()
        for task in tasks:
            states = states | task.specific.get_task_states_user_can_moderate(user=user)
        return states

class TaskState(models.Model):
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_SKIPPED = 'skipped'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = ((STATUS_IN_PROGRESS, "In progress"), (STATUS_APPROVED, "Approved"), (STATUS_REJECTED, "Rejected"), (STATUS_SKIPPED, "Skipped"), (STATUS_CANCELLED, "Cancelled"),)

    workflow_state = models.ForeignKey('WorkflowState', on_delete=models.CASCADE, verbose_name="workflow state", related_name='task_states')
    page_revision = models.ForeignKey('PageRevision', on_delete=models.CASCADE, verbose_name="page revision", related_name='task_states')
    task = models.ForeignKey('Task', on_delete=models.CASCADE, verbose_name="task", related_name='task_states')
    status = models.fields.CharField(choices=STATUS_CHOICES, verbose_name="status", max_length=50, default=STATUS_IN_PROGRESS)
    started_at = models.DateTimeField(verbose_name="started at", auto_now_add=True)
    finished_at = models.DateTimeField(verbose_name="finished at", blank=True, null=True)
    finished_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="finished by", null=True, blank=True, on_delete=models.SET_NULL, related_name='finished_task_states')
    comment = models.TextField(blank=True)
    content_type = models.ForeignKey(ContentType, verbose_name="content type", related_name='wagtail_task_states', on_delete=models.CASCADE)
    exclude_fields_in_copy = []
    default_exclude_fields_in_copy = ['id']

    objects = TaskStateManager()
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.id:
            
            if not self.content_type_id:
                
                self.content_type = ContentType.objects.get_for_model(self)
    def __str__(self):
        return "Task '{0}' on Page Revision '{1}': {2}".format(self.task, self.page_revision, self.status)

    @cached_property
    def specific(self):
        
        
        content_type = ContentType.objects.get_for_id(self.content_type_id)
        model_class = content_type.model_class()
        if model_class is None:
            
            return self
        elif isinstance(self, model_class):
            
            return self
        else:
            return content_type.get_object_for_this_type(id=self.id)

    @transaction.atomic
    def approve(self, user=None, update=True, comment=''):
        
        if self.status != self.STATUS_IN_PROGRESS:
            raise PermissionDenied
        self.status = self.STATUS_APPROVED
        self.finished_at = timezone.now()
        self.finished_by = user
        self.comment = comment
        self.save()

        self.log_state_change_action(user, 'approve')
        if update:
            self.workflow_state.update(user=user)
        task_approved.send(sender=self.specific.__class__, instance=self.specific, user=user)
        return self

    @transaction.atomic
    def reject(self, user=None, update=True, comment=''):
        
        if self.status != self.STATUS_IN_PROGRESS:
            raise PermissionDenied
        self.status = self.STATUS_REJECTED
        self.finished_at = timezone.now()
        self.finished_by = user
        self.comment = comment
        self.save()

        self.log_state_change_action(user, 'reject')
        if update:
            self.workflow_state.update(user=user)
        task_rejected.send(sender=self.specific.__class__, instance=self.specific, user=user)

        return self

    @cached_property
    def task_type_started_at(self):
        
        task_states = TaskState.objects.filter(workflow_state=self.workflow_state).order_by('-started_at').select_related('task')
        started_at = None
        for task_state in task_states:
            if task_state.task == self.task:
                started_at = task_state.started_at
            elif started_at:
                break
        return started_at

    @transaction.atomic
    def cancel(self, user=None, resume=False, comment=''):
        
        self.status = self.STATUS_CANCELLED
        self.finished_at = timezone.now()
        self.comment = comment
        self.finished_by = user
        self.save()
        if resume:
            self.workflow_state.update(user=user, next_task=self.task.specific)
        else:
            self.workflow_state.update(user=user)
        task_cancelled.send(sender=self.specific.__class__, instance=self.specific, user=user)
        return self
    def copy(self, update_attrs=None, exclude_fields=None):
        
        exclude_fields = self.default_exclude_fields_in_copy + self.exclude_fields_in_copy + (exclude_fields or [])
        instance, child_object_map = _copy(self.specific, exclude_fields, update_attrs)
        instance.save()
        _copy_m2m_relations(self, instance, exclude_fields=exclude_fields)
        return instance
    def get_comment(self): return self.comment
    def log_state_change_action(self, user, action):
        page = self.page_revision.as_page_object()
        next_task = self.workflow_state.get_next_task()
        next_task_data = None
        if next_task:
            next_task_data = {
                'id': next_task.id, 'title': next_task.name
            }
        log(instance=page, action='workflow_{}'.format(action), user=user, data={
                'workflow': {
                    'id': self.workflow_state.workflow.id, 'title': self.workflow_state.workflow.name, 'status': self.status, 'task_state_id': self.id, 'task': {
                        'id': self.task.id, 'title': self.task.name, }, 'next': next_task_data, }, 'comment': self.get_comment()
            }, revision=self.page_revision
        )

    class Meta:
        verbose_name = "Task state"
        verbose_name_plural = "Task states"

class PageLogEntryQuerySet(LogEntryQuerySet):
    def get_content_type_ids(self): 
        if self.exists(): return set([ContentType.objects.get_for_model(Page).pk])
        else: return set()
    def filter_on_content_type(self, content_type):
        if content_type == ContentType.objects.get_for_model(Page): return self
        else: return self.none()

class PageLogEntryManager(BaseLogEntryManager):
    def get_queryset(self): return PageLogEntryQuerySet(self.model, using=self._db)
    def get_instance_title(self, instance): return instance.specific_deferred.get_admin_display_title()
    def log_action(self, instance, action, **kwargs):
        kwargs.update(page=instance)
        return super().log_action(instance, action, **kwargs)
    def viewable_by_user(self, user):
        q = Q(page__in=UserPagePermissionsProxy(user).explorable_pages().values_list('pk', flat=True))
        root_page_permissions = Page.get_first_root_node().permissions_for_user(user)
        if (user.is_superuser or root_page_permissions.can_add_subpage() or root_page_permissions.can_edit()): q = q | Q(page_id__in=Subquery(PageLogEntry.objects.filter(deleted=True).values('page_id')))
        return PageLogEntry.objects.filter(q)

class PageLogEntry(BaseLogEntry):
    page = models.ForeignKey('wagtailcore.Page', on_delete=models.DO_NOTHING, db_constraint=False, related_name='+')
    revision = models.ForeignKey('wagtailcore.PageRevision', null=True, blank=True, on_delete=models.DO_NOTHING, db_constraint=False, related_name='+',)
    objects = PageLogEntryManager()
    class Meta:
        ordering = ['-timestamp', '-id']
        verbose_name = "page log entry"
        verbose_name_plural = "page log entries"
    def __str__(self): return "PageLogEntry %d: '%s' on '%s' with id %s" % (self.pk, self.action, self.object_verbose_name(), self.page_id)
    @cached_property
    def object_id(self): return self.page_id
    @cached_property
    def message(self):
        if self.action == 'edited': return "Draft saved"
        else: return super().message

class PageSubscription(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='page_subscriptions')
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name='subscribers')
    class Meta: unique_together = [('page', 'user')]
