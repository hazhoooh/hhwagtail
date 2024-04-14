import warnings

from collections import OrderedDict

from django import forms
from django.contrib.admin import FieldListFilter
from django.contrib.admin.options import IncorrectLookupParameters
from django.contrib.admin.utils import (
    get_fields_from_path, label_for_field, lookup_field, lookup_spawns_duplicates,
    prepare_lookup_value, quote, unquote)
from django.contrib.auth.decorators import login_required
from django.core.exceptions import (
    FieldDoesNotExist, ImproperlyConfigured, ObjectDoesNotExist, PermissionDenied,
    SuspiciousOperation)
from django.core.paginator import InvalidPage, Paginator
from django.db import models, transaction
from django.db.models.fields.related import ManyToManyField, OneToOneRel
from django.shortcuts import get_object_or_404, redirect
from django.template.defaultfilters import filesizeformat
from django.utils.decorators import method_decorator
from django.utils.encoding import force_str
from django.utils.functional import cached_property
from django.utils.http import urlencode
from django.utils.safestring import mark_safe
from django.utils.text import capfirst
from django.views.generic import TemplateView
from django.views.generic.edit import FormView
from django.views.generic.list import MultipleObjectMixin

from wagtail.admin import messages
from wagtail.admin.ui.components import Column, DateColumn, Table, UserColumn
from wagtail.admin.views.generic.base import WagtailAdminTemplateMixin
from wagtail.admin.views.mixins import SpreadsheetExportMixin
from wagtail.core.log_actions import log
from wagtail.core.log_actions import registry as log_registry

from .forms import ParentChooserForm


QUERY_TERMS = {
    'contains', 'day', 'endswith', 'exact', 'gt', 'gte', 'hour',
    'icontains', 'iendswith', 'iexact', 'in', 'iregex', 'isnull',
    'istartswith', 'lt', 'lte', 'minute', 'month', 'range', 'regex',
    'search', 'second', 'startswith', 'week_day', 'year',
}


class WMABaseView(TemplateView):
    """
    Groups together common functionality for all app views.
    """
    model_admin = None
    meta_title = ''
    page_title = ''
    page_subtitle = ''

    def __init__(self, model_admin):
        self.model_admin = model_admin
        self.model = model_admin.model
        self.opts = self.model._meta
        self.app_label = force_str(self.opts.app_label)
        self.model_name = force_str(self.opts.model_name)
        self.verbose_name = force_str(self.opts.verbose_name)
        self.verbose_name_plural = force_str(self.opts.verbose_name_plural)
        self.pk_attname = self.opts.pk.attname
        self.is_pagemodel = model_admin.is_pagemodel
        self.permission_helper = model_admin.permission_helper
        self.url_helper = model_admin.url_helper

    def check_action_permitted(self, user):
        return True

    @method_decorator(login_required)
    def dispatch(self, request, *args, **kwargs):
        if not self.check_action_permitted(request.user):
            raise PermissionDenied
        button_helper_class = self.model_admin.get_button_helper_class()
        self.button_helper = button_helper_class(self, request)
        return super().dispatch(request, *args, **kwargs)

    @cached_property
    def menu_icon(self):
        return self.model_admin.get_menu_icon()

    @cached_property
    def header_icon(self):
        return self.menu_icon

    def get_page_title(self):
        return self.page_title or capfirst(self.opts.verbose_name_plural)

    def get_meta_title(self):
        return self.meta_title or self.get_page_title()

    @cached_property
    def index_url(self):
        return self.url_helper.index_url

    @cached_property
    def create_url(self):
        return self.url_helper.create_url

    def get_base_queryset(self, request=None):
        return self.model_admin.get_queryset(request or self.request)

    def get_context_data(self, **kwargs):
        context = {
            'view': self,
            'model_admin': self.model_admin,
        }
        context.update(kwargs)
        return super().get_context_data(**context)


class ModelFormView(WMABaseView, FormView):
    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.edit_handler = self.get_edit_handler()

    def get_form(self):
        form = super().get_form()
        self.edit_handler = self.edit_handler.bind_to(form=form)
        return form

    def get_edit_handler(self):
        instance = self.get_instance()
        edit_handler = self.model_admin.get_edit_handler(
            instance=instance, request=self.request
        )
        return edit_handler.bind_to(
            model=self.model_admin.model, request=self.request, instance=instance
        )

    def get_form_class(self):
        return self.edit_handler.get_form_class()

    def get_success_url(self):
        return self.index_url

    def get_instance(self):
        return getattr(self, 'instance', None) or self.model()

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update({'instance': self.get_instance()})
        return kwargs

    @property
    def media(self):
        return forms.Media(
            css={'all': self.model_admin.get_form_view_extra_css()},
            js=self.model_admin.get_form_view_extra_js()
        )

    def get_context_data(self, form=None, **kwargs):
        if form is None:
            form = self.get_form()

        prepopulated_fields = self.get_prepopulated_fields(form)
        context = {
            'is_multipart': form.is_multipart(),
            'edit_handler': self.edit_handler,
            'form': form,
            'prepopulated_fields': prepopulated_fields,
        }
        context.update(kwargs)
        return super().get_context_data(**context)

    def get_prepopulated_fields(self, form):
        fields = []
        for field_name, dependencies in self.model_admin.get_prepopulated_fields(self.request).items():
            missing_dependencies = [f"'{f}'" for f in dependencies if f not in form.fields]
            if len(missing_dependencies) != 0:
                missing_deps_string = ", ".join(missing_dependencies)
                dependency_string = "dependencies" if len(missing_dependencies) > 1 else "dependency"
                warnings.warn(
                    f"Missing {dependency_string} {missing_deps_string} for prepopulated_field '{field_name}''.",
                    category=RuntimeWarning
                )
            elif field_name in form.fields:
                fields.append({'field': form[field_name], 'dependencies': [form[f] for f in dependencies]})
        return fields

    def get_success_message(self, instance):
        return "%(model_name)s '%(instance)s' created." % {
            'model_name': capfirst(self.opts.verbose_name), 'instance': instance
        }

    def get_success_message_buttons(self, instance):
        button_url = self.url_helper.get_action_url('edit', quote(instance.pk))
        return [
            messages.button(button_url, "Edit")
        ]

    def get_error_message(self):
        model_name = self.verbose_name
        return "The %s could not be created due to errors." % model_name

    def form_valid(self, form):
        self.instance = form.save()
        messages.success(
            self.request, self.get_success_message(self.instance),
            buttons=self.get_success_message_buttons(self.instance)
        )
        return redirect(self.get_success_url())

    def form_invalid(self, form):
        messages.validation_error(
            self.request, self.get_error_message(), form
        )
        return self.render_to_response(self.get_context_data(form=form))


class InstanceSpecificView(WMABaseView):

    instance_pk = None
    pk_quoted = None
    instance = None

    def __init__(self, model_admin, instance_pk):
        super().__init__(model_admin)
        self.instance_pk = unquote(instance_pk)
        self.pk_quoted = quote(self.instance_pk)
        filter_kwargs = {}
        filter_kwargs[self.pk_attname] = self.instance_pk
        object_qs = model_admin.model._default_manager.get_queryset().filter(
            **filter_kwargs)
        self.instance = get_object_or_404(object_qs)

    def get_page_subtitle(self):
        return self.instance

    @cached_property
    def edit_url(self):
        return self.url_helper.get_action_url('edit', self.pk_quoted)

    @cached_property
    def delete_url(self):
        return self.url_helper.get_action_url('delete', self.pk_quoted)

    def get_context_data(self, **kwargs):
        context = {'instance': self.instance}
        context.update(kwargs)
        return super().get_context_data(**context)


class IndexView(SpreadsheetExportMixin, WMABaseView):

    ORDER_VAR = 'o'
    ORDER_TYPE_VAR = 'ot'
    PAGE_VAR = 'p'
    SEARCH_VAR = 'q'
    ERROR_FLAG = 'e'
    EXPORT_VAR = 'export'
    IGNORED_PARAMS = (ORDER_VAR, ORDER_TYPE_VAR, SEARCH_VAR, EXPORT_VAR)

    # sortable_by is required by the django.contrib.admin.templatetags.admin_list.result_headers
    # template tag - see https://docs.djangoproject.com/en/stable/ref/contrib/admin/#django.contrib.admin.ModelAdmin.sortable_by
    sortable_by = None

    @method_decorator(login_required)
    def dispatch(self, request, *args, **kwargs):
        # Only continue if logged in user has list permission
        if not self.permission_helper.user_can_list(request.user):
            raise PermissionDenied

        self.list_export = self.model_admin.get_list_export(request)
        self.list_display = self.model_admin.get_list_display(request)
        self.list_filter = self.model_admin.get_list_filter(request)
        self.search_fields = self.model_admin.get_search_fields(request)
        self.items_per_page = self.model_admin.list_per_page
        self.select_related = self.model_admin.list_select_related
        self.search_handler = self.model_admin.get_search_handler(request, self.search_fields)
        self.export = (request.GET.get(self.EXPORT_VAR))

        # Get search parameters from the query string.
        try:
            self.page_num = int(request.GET.get(self.PAGE_VAR, 0))
        except ValueError:
            self.page_num = 0

        self.params = dict(request.GET.items())
        if self.PAGE_VAR in self.params:
            del self.params[self.PAGE_VAR]
        if self.ERROR_FLAG in self.params:
            del self.params[self.ERROR_FLAG]
        if self.EXPORT_VAR in self.params:
            del self.params[self.EXPORT_VAR]

        self.query = request.GET.get(self.SEARCH_VAR, '')

        self.queryset = self.get_queryset(request)

        if self.export in self.FORMATS:
            return self.as_spreadsheet(self.queryset, self.export)
        return super().dispatch(request, *args, **kwargs)
    def get_filename(self):
        """ Get filename for exported spreadsheet, without extension """
        return getattr(self.model_admin, 'export_filename', super().get_filename())
    def get_heading(self, queryset, field):
        """ Get headings for exported spreadsheet column for the relevant field """
        heading_override = self.export_headings.get(field)
        if heading_override:
            return force_str(heading_override)
        return force_str(label_for_field(field, model=self.model, model_admin=self.model_admin).title())
    def to_row_dict(self, item):
        """ Returns an OrderedDict (in the order given by list_export) of the exportable information for a model instance"""
        row_dict = OrderedDict()
        for field in self.list_export:
            f, attr, value = lookup_field(field, item, self.model_admin)
            if not value:
                value = getattr(attr, 'empty_value_display', self.model_admin.get_empty_value_display(field))
            row_dict[field] = value
        return row_dict
    @property
    def media(self):
        return forms.Media(css={'all': self.model_admin.get_index_view_extra_css()},js=self.model_admin.get_index_view_extra_js())
    def get_buttons_for_obj(self, obj):
        return self.button_helper.get_buttons_for_obj(obj, classnames_add=['btn'])
    def get_search_results(self, request, queryset, search_term):
        kwargs = self.model_admin.get_extra_search_kwargs(request, search_term)
        kwargs['preserve_order'] = self.ORDER_VAR in request.GET
        return self.search_handler.search_queryset(queryset, search_term, **kwargs)
    def get_filters_params(self, params=None):
        """ Returns all params except IGNORED_PARAMS """
        if not params: params = self.params
        lookup_params = params.copy()  # a dictionary of the query string
        # Remove all the parameters that are globally and systematically ignored.
        for ignored in self.IGNORED_PARAMS:
            if ignored in lookup_params: del lookup_params[ignored]
        return lookup_params
    def get_filters(self, request):
        lookup_params = self.get_filters_params()
        use_distinct = False
        filter_specs = []
        if self.list_filter:
            for list_filter in self.list_filter:
                if callable(list_filter): spec = list_filter(request,lookup_params,self.model,self.model_admin) # This is simply a custom list filter class.
                else:
                    field_path = None
                    if isinstance(list_filter, (tuple, list)): field, field_list_filter_class = list_filter # This is a custom FieldListFilter class for a given field.
                    else:
                        # This is simply a field name, so use the default FieldListFilter class that has been registered for the type of the given field.
                        field = list_filter
                        field_list_filter_class = FieldListFilter.create
                    if not isinstance(field, models.Field):
                        field_path = field
                        field = get_fields_from_path(self.model,field_path)[-1]
                    spec = field_list_filter_class(field,request,lookup_params,self.model,self.model_admin,field_path=field_path)
                    use_distinct = (use_distinct or lookup_spawns_duplicates(self.opts,field_path)) 
                if spec and spec.has_output(): filter_specs.append(spec)
        # At this point, all the parameters used by the various ListFilters have been removed from lookup_params, which now only contains other parameters passed via the query string.
        # We now loop through the remaining parameters both to ensure that all the parameters are valid fields and to determine if at least one of them needs distinct().
        # If the lookup parameters aren't real fields, then bail out.
        try:
            for key, value in lookup_params.items():
                lookup_params[key] = prepare_lookup_value(key, value)
                use_distinct = (use_distinct or lookup_spawns_duplicates(self.opts, key))
            return (filter_specs, bool(filter_specs), lookup_params, use_distinct)
        except FieldDoesNotExist as e: raise IncorrectLookupParameters from e

    def get_query_string(self, new_params=None, remove=None):
        if new_params is None: new_params = {}
        if remove is None: remove = []
        p = self.params.copy()
        for r in remove:
            for k in list(p):
                if k.startswith(r):
                    del p[k]
        for k, v in new_params.items():
            if v is None:
                if k in p:
                    del p[k]
            else:
                p[k] = v
        return '?%s' % urlencode(sorted(p.items()))

    def get_queryset(self, request=None):
        request = request or self.request
        # First, we collect all the declared list filters.
        (self.filter_specs, self.has_filters, remaining_lookup_params,
         filters_use_distinct) = self.get_filters(request)
        # Then, we let every list filter modify the queryset to its liking.
        qs = self.get_base_queryset(request)
        for filter_spec in self.filter_specs:
            new_qs = filter_spec.queryset(request, qs)
            if new_qs is not None:
                qs = new_qs
        try:
            # Finally, we apply the remaining lookup parameters from the query
            # string (i.e. those that haven't already been processed by the
            # filters).
            qs = qs.filter(**remaining_lookup_params)
        except (SuspiciousOperation, ImproperlyConfigured):
            # Allow certain types of errors to be re-raised as-is so that the
            # caller can treat them in a special way.
            raise
        except Exception as e:
            # Every other error is caught with a naked except, because we don't
            # have any other way of validating lookup parameters. They might be
            # invalid if the keyword arguments are incorrect, or if the values
            # are not in the correct type, so we might get FieldError,
            # ValueError, ValidationError, or ?.
            raise IncorrectLookupParameters(e)
        if not qs.query.select_related:
            qs = self.apply_select_related(qs)
        ordering = self.model._meta.ordering
        qs = qs.order_by(*ordering)
        # Remove duplicates from results, if necessary
        if filters_use_distinct:
            qs = qs.distinct()
        # Apply search results
        return self.get_search_results(request, qs, self.query)
    def apply_select_related(self, qs):
        if self.select_related is True:
            return qs.select_related()
        if self.select_related is False:
            if self.has_related_field_in_list_display():
                return qs.select_related()
        if self.select_related:
            return qs.select_related(*self.select_related)
        return qs
    def has_related_field_in_list_display(self):
        for field_name in self.list_display:
            try:
                field = self.opts.get_field(field_name)
            except FieldDoesNotExist:
                pass
            else:
                if isinstance(field, models.ManyToOneRel):
                    return True
        return False
    def get_context_data(self, **kwargs):
        user = self.request.user
        all_count = self.get_base_queryset().count()
        queryset = self.get_queryset()
        result_count = queryset.count()
        paginator = Paginator(queryset, self.items_per_page)
        try:
            page_obj = paginator.page(self.page_num + 1)
        except InvalidPage:
            page_obj = paginator.page(1)
        context = {
            'view': self,
            'all_count': all_count,
            'result_count': result_count,
            'paginator': paginator,
            'page_obj': page_obj,
            'object_list': page_obj.object_list,
            'user_can_create': self.permission_helper.user_can_create(user),
            'show_search': self.search_handler.show_search_form,
        }

        if self.is_pagemodel:
            models = self.model.allowed_parent_page_models()
            allowed_parent_types = [m._meta.verbose_name for m in models]
            valid_parents = self.permission_helper.get_valid_parent_pages(user)
            valid_parent_count = valid_parents.count()
            context.update({
                'no_valid_parents': not valid_parent_count,
                'required_parent_types': allowed_parent_types,
            })
        context.update(kwargs)
        return super().get_context_data(**context)
    def get_template_names(self):
        return self.model_admin.get_index_template()

class CreateView(ModelFormView):
    page_title = 'New'
    def check_action_permitted(self, user):
        return self.permission_helper.user_can_create(user)
    def dispatch(self, request, *args, **kwargs):
        if self.is_pagemodel:
            user = request.user
            parents = self.permission_helper.get_valid_parent_pages(user)
            parent_count = parents.count()
            # There's only one available parent for this page type for this
            # user, so we send them along with that as the chosen parent page
            if parent_count == 1:
                parent = parents.get()
                parent_pk = quote(parent.pk)
                return redirect(self.url_helper.get_action_url(
                    'add', self.app_label, self.model_name, parent_pk))
            # The page can be added in multiple places, so redirect to the
            # choose_parent view so that the parent can be specified
            return redirect(self.url_helper.get_action_url('choose_parent'))
        return super().dispatch(request, *args, **kwargs)
    def form_valid(self, form):
        response = super().form_valid(form)
        log(instance=self.instance, action='created')
        return response
    def get_meta_title(self): return "Create new %s" % self.verbose_name
    def get_page_subtitle(self): return capfirst(self.verbose_name)
    def get_template_names(self): return self.model_admin.get_create_template()

class EditView(ModelFormView, InstanceSpecificView):
    page_title = 'Editing'
    def check_action_permitted(self, user): return self.permission_helper.user_can_edit_obj(user, self.instance)
    @method_decorator(login_required)
    def dispatch(self, request, *args, **kwargs):
        if self.is_pagemodel: return redirect(self.url_helper.get_action_url('edit', self.pk_quoted))
        return super().dispatch(request, *args, **kwargs)
    def get_meta_title(self): return "Editing %s" % self.verbose_name
    def get_success_message(self, instance): return "%(model_name)s '%(instance)s' updated." % {'model_name': capfirst(self.verbose_name), 'instance': instance}
    def get_context_data(self, **kwargs):
        context = {'user_can_delete': self.permission_helper.user_can_delete_obj(self.request.user, self.instance)}
        context.update(kwargs)
        if self.model_admin.history_view_enabled:
            context['latest_log_entry'] = log_registry.get_logs_for_instance(self.instance).first()
            context['history_url'] = self.url_helper.get_action_url('history', quote(self.instance.pk))
        else: context['latest_log_entry'],context['history_url'] = None,None
        return super().get_context_data(**context)
    def get_error_message(self): return f"The {self.verbose_name} could not be saved due to errors."
    def get_template_names(self): return self.model_admin.get_edit_template()
    def form_valid(self, form):
        response = super().form_valid(form)
        log(instance=self.instance, action='edited')
        return response

class ChooseParentView(WMABaseView):
    def dispatch(self, request, *args, **kwargs):
        if not self.permission_helper.user_can_create(request.user): raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
    def get_page_title(self): return "Add %s" % self.verbose_name
    def get_form(self, request):
        parents = self.permission_helper.get_valid_parent_pages(request.user)
        return ParentChooserForm(parents, request.POST or None)

    def get(self, request, *args, **kwargs):
        form = self.get_form(request)
        context = self.get_context_data(form=form)
        return self.render_to_response(context)

    def post(self, request, *args, **kargs):
        form = self.get_form(request)
        if form.is_valid():
            return self.form_valid(form)
        return self.form_invalid(form)

    def form_valid(self, form):
        parent_pk = quote(form.cleaned_data['parent_page'].pk)
        return redirect(self.url_helper.get_action_url(
            'add', self.app_label, self.model_name, parent_pk))

    def form_invalid(self, form):
        context = self.get_context_data(form=form)
        return self.render_to_response(context)

    def get_template_names(self):
        return self.model_admin.get_choose_parent_template()


class DeleteView(InstanceSpecificView):
    page_title = 'Delete'

    def check_action_permitted(self, user):
        return self.permission_helper.user_can_delete_obj(user, self.instance)

    @method_decorator(login_required)
    def dispatch(self, request, *args, **kwargs):
        if not self.check_action_permitted(request.user):
            raise PermissionDenied
        if self.is_pagemodel:
            return redirect(
                self.url_helper.get_action_url('delete', self.pk_quoted)
            )
        return super().dispatch(request, *args, **kwargs)

    def get_meta_title(self):
        return "Confirm deletion of %s" % self.verbose_name

    def confirmation_message(self):
        return f"Are you sure you want to delete this {self.verbose_name}? If other things in your site are related to it, they may also be affected." 

    def delete_instance(self):
        self.instance.delete()

    def post(self, request, *args, **kwargs):
        try:
            msg = "%(model_name)s '%(instance)s' deleted." % {
                'model_name': self.verbose_name, 'instance': self.instance
            }
            with transaction.atomic():
                log(instance=self.instance, action='deleted')
                self.delete_instance()
            messages.success(request, msg)
            return redirect(self.index_url)
        except models.ProtectedError:
            linked_objects = []
            fields = self.model._meta.fields_map.values()
            fields = (obj for obj in fields if not isinstance(
                obj.field, ManyToManyField))
            for rel in fields:
                if rel.on_delete == models.PROTECT:
                    if isinstance(rel, OneToOneRel):
                        try:
                            obj = getattr(self.instance, rel.get_accessor_name())
                        except ObjectDoesNotExist:
                            pass
                        else:
                            linked_objects.append(obj)
                    else:
                        qs = getattr(self.instance, rel.get_accessor_name())
                        for obj in qs.all():
                            linked_objects.append(obj)
            context = self.get_context_data(
                protected_error=True,
                linked_objects=linked_objects
            )
            return self.render_to_response(context)

    def get_template_names(self):
        return self.model_admin.get_delete_template()


class InspectView(InstanceSpecificView):

    page_title = 'Inspecting'

    def check_action_permitted(self, user):
        return self.permission_helper.user_can_inspect_obj(user, self.instance)

    @property
    def media(self):
        return forms.Media(
            css={'all': self.model_admin.get_inspect_view_extra_css()},
            js=self.model_admin.get_inspect_view_extra_js()
        )

    def get_meta_title(self):
        return "Inspecting %s" % self.verbose_name

    def get_field_label(self, field_name, field=None):
        """ Return a label to display for a field """
        return label_for_field(field_name, model=self.model)

    def get_field_display_value(self, field_name, field=None):
        """ Return a display value for a field/attribute """

        # First we check for a 'get_fieldname_display' property/method on
        # the model, and return the value of that, if present.
        val_funct = getattr(self.instance, 'get_%s_display' % field_name, None)
        if val_funct is not None:
            if callable(val_funct):
                return val_funct()
            return val_funct

        # Now let's get the attribute value from the instance itself and see if
        # we can render something useful. raises AttributeError appropriately.
        val = getattr(self.instance, field_name)

        if isinstance(val, models.Manager):
            val = val.all()

        if isinstance(val, models.QuerySet):
            if val.exists():
                return ', '.join(['%s' % obj for obj in val])
            return self.model_admin.get_empty_value_display(field_name)

        # wagtail.images might not be installed
        try:
            from wagtail.images.models import AbstractImage
            if isinstance(val, AbstractImage):
                # Render a rendition of the image
                return self.get_image_field_display(field_name, field)
        except RuntimeError:
            pass

        # wagtail.wagtaildocuments might not be installed
        try:
            from wagtail.documents.models import AbstractDocument
            if isinstance(val, AbstractDocument):
                # Render a link to the document
                return self.get_document_field_display(field_name, field)
        except RuntimeError:
            pass

        # Resort to returning the real value or 'empty value'
        if val or val is False:
            return val
        return self.model_admin.get_empty_value_display(field_name)

    def get_image_field_display(self, field_name, field):
        """ Render an image """
        from wagtail.images.shortcuts import get_rendition_or_not_found
        image = getattr(self.instance, field_name)
        if image:
            return get_rendition_or_not_found(image, 'max-400x400').img_tag
        return self.model_admin.get_empty_value_display(field_name)

    def get_document_field_display(self, field_name, field):
        """ Render a link to a document """
        document = getattr(self.instance, field_name)
        if document:
            return mark_safe(
                '<a href="%s">%s <span class="meta">(%s, %s)</span></a>' % (
                    document.url,
                    document.title,
                    document.file_extension.upper(),
                    filesizeformat(document.file.size),
                )
            )
        return self.model_admin.get_empty_value_display(field_name)

    def get_dict_for_field(self, field_name):
        """
        Return a dictionary containing `label` and `value` values to display
        for a field.
        """
        try:
            field = self.model._meta.get_field(field_name)
        except FieldDoesNotExist:
            field = None
        return {
            'label': self.get_field_label(field_name, field),
            'value': self.get_field_display_value(field_name, field),
        }

    def get_fields_dict(self):
        """
        Return a list of `label`/`value` dictionaries to represent the
        fields named by the model_admin class's `get_inspect_view_fields` method
        """
        fields = []
        for field_name in self.model_admin.get_inspect_view_fields():
            fields.append(self.get_dict_for_field(field_name))
        return fields

    def get_context_data(self, **kwargs):
        context = {'fields': self.get_fields_dict(),'buttons': self.button_helper.get_buttons_for_obj(self.instance, exclude=['inspect']),}
        context.update(kwargs)
        return super().get_context_data(**context)

    def get_template_names(self): return self.model_admin.get_inspect_template()


class HistoryView(MultipleObjectMixin, WagtailAdminTemplateMixin, InstanceSpecificView):
    page_title = 'History'
    paginate_by = 50
    columns = [Column('message', label="Action"),UserColumn('user', blank_display_name='system'),DateColumn('timestamp', label="Date")]
    def get_page_subtitle(self): return str(self.instance)
    def get_template_names(self): return self.model_admin.get_history_template()
    def get_queryset(self): return log_registry.get_logs_for_instance(self.instance).prefetch_related('user__wagtail_userprofile')

    def get_context_data(self, **kwargs):
        self.object_list = self.get_queryset()
        context = super().get_context_data(**kwargs)
        index_url = self.url_helper.get_action_url('history', quote(self.instance.pk))
        table = Table(self.columns, context['object_list'], base_url=index_url, ordering=self.model._meta.ordering)

        context['table'] = table
        context['media'] = table.media
        context['index_url'] = index_url
        context['is_paginated'] = True
        return context
