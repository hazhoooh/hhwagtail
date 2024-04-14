from collections import OrderedDict
from collections.abc import Mapping
from typing import List, Any, Mapping
from django.forms import MediaDefiningClass
from django.template import Context
from django.template.loader import get_template
from django.forms import MediaDefiningClass
from django.template.loader import get_template
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.text import capfirst
from wagtail.core.utils import multigetattr

class Component(metaclass=MediaDefiningClass):
    def get_context_data(self, parent_context: Mapping[str, Any]) -> Mapping[str, Any]: return {}
    def render_html(self, parent_context: Mapping[str, Any] = None) -> str:
        if parent_context is None: parent_context = Context()
        context_data = self.get_context_data(parent_context)
        if context_data is None: raise TypeError("Expected a dict from get_context_data, got None")
        template = get_template(self.template_name)
        return template.render(context_data)

class MenuItem:
    def __init__(self, name: str, label: str, icon_name: str = '', classnames: str = ''):
        self.name = name
        self.label = label
        self.icon_name = icon_name
        self.classnames = classnames
    def js_args(self): return [{'name': self.name,'label': self.label,'icon_name': self.icon_name,'classnames': self.classnames,}]

class LinkMenuItem(MenuItem):
    def __init__(self, name: str, label: str, url: str, icon_name: str = '', classnames: str = ''):
        super().__init__(name, label, icon_name=icon_name, classnames=classnames)
        self.url = url
    def js_args(self):
        args = super().js_args()
        args[0]['url'] = self.url
        return args
    def __eq__(self, other): return (self.__class__ == other.__class__ and self.name == other.name and self.label == other.label and self.url == other.url and self.icon_name == other.icon_name and self.classnames == other.classnames)

class SubMenuItem(MenuItem):
    def __init__(self, name: str, label: str, menu_items: List[MenuItem], icon_name: str = '', classnames: str = '', footer_text: str = ''):
        super().__init__(name, label, icon_name=icon_name, classnames=classnames)
        self.menu_items = menu_items
        self.footer_text = footer_text
    def js_args(self):
        args = super().js_args()
        args[0]['footer_text'] = self.footer_text
        args.append(self.menu_items)
        return args
    def __eq__(self, other): return (self.__class__ == other.__class__ and self.name == other.name and self.label == other.label and self.menu_items == other.menu_items and self.icon_name == other.icon_name and self.classnames == other.classnames and self.footer_text == other.footer_text)

class Column(metaclass=MediaDefiningClass):
    class Header:
        def __init__(self, column): self.column = column
        def render_html(self, parent_context): return self.column.render_header_html(parent_context)

    class Cell:
        def __init__(self, column, instance):
            self.column = column
            self.instance = instance

        def render_html(self, parent_context): return self.column.render_cell_html(self.instance, parent_context)

    header_template_name = "cms/tables/header.html"
    cell_template_name = "cms/tables/cell.html"

    def __init__(self, name, label=None, accessor=None, classname=None, sort_key=None):
        self.name = name
        self.accessor = accessor or name
        self.label = label or capfirst(name.replace('_', ' '))
        self.classname = classname
        self.sort_key = sort_key
        self.header = Column.Header(self)

    def get_header_context_data(self, parent_context):
        """
        Compiles the context dictionary to pass to the header template when rendering the column header
        """
        table = parent_context['table']
        return {
            'column': self,
            'table': table,
            'is_orderable': bool(self.sort_key),
            'is_ascending': self.sort_key and table.ordering == self.sort_key,
            'is_descending': self.sort_key and table.ordering == ('-' + self.sort_key),
            'request': parent_context.get('request'),
        }

    @cached_property
    def header_template(self):
        return get_template(self.header_template_name)

    @cached_property
    def cell_template(self):
        return get_template(self.cell_template_name)

    def render_header_html(self, parent_context):
        """
        Renders the column's header
        """
        context = self.get_header_context_data(parent_context)
        return self.header_template.render(context)

    def get_value(self, instance):
        """
        Given an instance (i.e. any object containing data), extract the field of data to be
        displayed in a cell of this column
        """
        if callable(self.accessor):
            return self.accessor(instance)
        else:
            return multigetattr(instance, self.accessor)

    def get_cell_context_data(self, instance, parent_context):
        """
        Compiles the context dictionary to pass to the cell template when rendering a table cell for
        the given instance
        """
        return {
            'instance': instance,
            'column': self,
            'value': self.get_value(instance),
            'request': parent_context.get('request'),
        }

    def render_cell_html(self, instance, parent_context):
        """
        Renders a table cell containing data for the given instance
        """
        context = self.get_cell_context_data(instance, parent_context)
        return self.cell_template.render(context)

    def get_cell(self, instance):
        """
        Return an object encapsulating this column and an item of data, which we can use for
        rendering a table cell into a template
        """
        return Column.Cell(self, instance)

    def __repr__(self):
        return "<%s.%s: %s>" % (self.__class__.__module__, self.__class__.__qualname__, self.name)

class TitleColumn(Column):
    """A column where data is styled as a title and wrapped in a link"""
    cell_template_name = "cms/tables/title_cell.html"

    def __init__(self, name, url_name=None, get_url=None, **kwargs):
        super().__init__(name, **kwargs)
        self.url_name = url_name
        self._get_url_func = get_url

    def get_cell_context_data(self, instance, parent_context):
        context = super().get_cell_context_data(instance, parent_context)
        context['link_url'] = self.get_link_url(instance, parent_context)
        return context

    def get_link_url(self, instance, parent_context):
        if self._get_url_func: return self._get_url_func(instance)
        else: return reverse(self.url_name, args=(instance.pk,))

class StatusFlagColumn(Column):
    cell_template_name = "cms/tables/status_flag_cell.html"

    def __init__(self, name, true_label=None, false_label=None, **kwargs):
        super().__init__(name, **kwargs)
        self.true_label = true_label
        self.false_label = false_label

class DateColumn(Column): cell_template_name = "cms/tables/date_cell.html"

class UserColumn(Column):
    cell_template_name = "cms/tables/user_cell.html"

    def __init__(self, name, blank_display_name='', **kwargs):
        super().__init__(name, **kwargs)
        self.blank_display_name = blank_display_name

    def get_cell_context_data(self, instance, parent_context):
        context = super().get_cell_context_data(instance, parent_context)
        user = context['value']
        if user:
            try: full_name = user.get_full_name().strip()
            except AttributeError: full_name = ''
            context['display_name'] = full_name or user.get_username()
        else: context['display_name'] = self.blank_display_name
        return context

class Table(Component):
    template_name = "cms/tables/table.html"
    classname = 'styled listing'

    def __init__(self, columns, data, template_name=None, base_url=None, ordering=None):
        self.columns = OrderedDict([
            (column.name, column)
            for column in columns
        ])
        self.data = data
        if template_name:
            self.template_name = template_name
        self.base_url = base_url
        self.ordering = ordering

    def get_context_data(self, parent_context):
        context = super().get_context_data(parent_context)
        context['table'] = self
        context['request'] = parent_context.get('request')
        return context

    @property
    def media(self):
        media = super().media
        for col in self.columns.values():
            media += col.media
        return media

    @property
    def rows(self):
        for instance in self.data:
            yield Table.Row(self.columns, instance)

    class Row(Mapping):
        # behaves as an OrderedDict whose items are the rendered results of the corresponding column's format_cell method applied to the instance
        def __init__(self, columns, instance):
            self.columns = columns
            self.instance = instance

        def __len__(self):
            return len(self.columns)

        def __getitem__(self, key):
            return self.columns[key].get_cell(self.instance)

        def __iter__(self):
            for name in self.columns:
                yield name

        def __repr__(self):
            return repr([col.get_cell(self.instance) for col in self.columns.values()])
 