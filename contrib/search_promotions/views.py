from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Sum, functions
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.vary import vary_on_headers
from wagtail.admin import messages
from wagtail.admin.auth import any_permission_required, permission_required
from wagtail.admin.forms.search import SearchForm
from wagtail.contrib.search_promotions import forms
from wagtail.core.log_actions import log
from wagtail.search import forms as search_forms
from wagtail.search.models import Query

@any_permission_required('wagtailsearchpromotions.add_searchpromotion','wagtailsearchpromotions.change_searchpromotion','wagtailsearchpromotions.delete_searchpromotion')
@vary_on_headers('X-Requested-With')
def index(request):
    valid_ordering = ['query_string', '-query_string', 'views', '-views']
    ordering = valid_ordering[0]
    if 'ordering' in request.GET and request.GET['ordering'] in valid_ordering: ordering = request.GET['ordering']
    queries = Query.objects.filter(editors_picks__isnull=False).distinct()
    if 'views' in ordering: queries = queries.annotate(views=functions.Coalesce(Sum('daily_hits__hits'), 0))
    queries = queries.order_by(ordering)
    is_searching = False
    query_string = request.GET.get('q', '')
    if query_string:
        queries = queries.filter(query_string__icontains=query_string)
        is_searching = True
    paginator = Paginator(queries, per_page=150)
    queries = paginator.get_page(request.GET.get('p'))
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return TemplateResponse(request, "wagtailsearchpromotions/results.html", { 'is_searching': is_searching, 'ordering': ordering, 'queries': queries, 'query_string': query_string, })
    else:
        return TemplateResponse(request, 'wagtailsearchpromotions/index.html', { 'is_searching': is_searching, 'ordering': ordering, 'queries': queries, 'query_string': query_string,
            'search_form': SearchForm(data=dict(q=query_string) if query_string else None, placeholder="Search promoted results"),
        })

def save_searchpicks(query, new_query, searchpicks_formset):
    if searchpicks_formset.is_valid():
        for i, form in enumerate(searchpicks_formset.ordered_forms):
            form.instance.sort_order = i
            form.has_changed = lambda: True
        items_for_deletion = [form.instance for form in searchpicks_formset.deleted_forms if form.instance.pk]
        with transaction.atomic():
            for search_pick in items_for_deletion: log(search_pick, 'deleted')
            searchpicks_formset.save()
            for search_pick in searchpicks_formset.new_objects: log(search_pick, 'created')
            if query != new_query:
                searchpicks_formset.get_queryset().update(query=new_query)
                for search_pick, changed_fields in searchpicks_formset.changed_objects: log(search_pick, 'edited')
            else:
                for search_pick, changed_fields in searchpicks_formset.changed_objects:
                    if changed_fields: log(search_pick, 'edited')
        return True
    else:
        return False

@permission_required('wagtailsearchpromotions.add_searchpromotion')
def add(request):
    if request.method == 'POST':
        query_form = search_forms.QueryForm(request.POST)
        if query_form.is_valid():
            query = Query.get(query_form['query_string'].value())
            searchpicks_formset = forms.SearchPromotionsFormSet(request.POST, instance=query)
            if save_searchpicks(query, query, searchpicks_formset):
                for search_pick in searchpicks_formset.new_objects: log(search_pick, 'created')
                messages.success(request, "Editor's picks for '{0}' created.".format(query), buttons=[messages.button(reverse('wagtailsearchpromotions:edit', args=(query.id,)), "Edit")])
                return redirect('wagtailsearchpromotions:index')
            else:
                if len(searchpicks_formset.non_form_errors()): messages.error(request, " ".join(error for error in searchpicks_formset.non_form_errors()))
                else: messages.error(request, "Recommendations have not been created due to errors")
        else: searchpicks_formset = forms.SearchPromotionsFormSet()
    else:
        query_form = search_forms.QueryForm()
        searchpicks_formset = forms.SearchPromotionsFormSet()
    return TemplateResponse(request, 'wagtailsearchpromotions/add.html', { 'query_form': query_form, 'searchpicks_formset': searchpicks_formset, 'form_media': query_form.media + searchpicks_formset.media, })

@permission_required('wagtailsearchpromotions.change_searchpromotion')
def edit(request, query_id):
    query = get_object_or_404(Query, id=query_id)
    if request.method == 'POST':
        query_form = search_forms.QueryForm(request.POST)
        searchpicks_formset = forms.SearchPromotionsFormSet(request.POST, instance=query)
        if query_form.is_valid():
            new_query = Query.get(query_form['query_string'].value())
            if save_searchpicks(query, new_query, searchpicks_formset):
                messages.success(request, "Editor's picks for '{0}' updated.".format(new_query), buttons=[ messages.button(reverse('wagtailsearchpromotions:edit', args=(query.id,)), "Edit") ])
                return redirect('wagtailsearchpromotions:index')
            else:
                if len(searchpicks_formset.non_form_errors()): messages.error(request, " ".join(error for error in searchpicks_formset.non_form_errors()))
                else: messages.error(request, "Recommendations have not been saved due to errors")
    else:
        query_form = search_forms.QueryForm(initial=dict(query_string=query.query_string))
        searchpicks_formset = forms.SearchPromotionsFormSet(instance=query)
    return TemplateResponse(request, 'wagtailsearchpromotions/edit.html', { 'query_form': query_form, 'searchpicks_formset': searchpicks_formset, 'query': query, 'form_media': query_form.media + searchpicks_formset.media})

@permission_required('wagtailsearchpromotions.delete_searchpromotion')
def delete(request, query_id):
    query = get_object_or_404(Query, id=query_id)
    if request.method == 'POST':
        editors_picks = query.editors_picks.all()
        with transaction.atomic():
            for search_pick in editors_picks: log(search_pick, 'deleted')
            editors_picks.delete()
        messages.success(request, "Editor's picks deleted.")
        return redirect('wagtailsearchpromotions:index')
    return TemplateResponse(request, 'wagtailsearchpromotions/confirm_delete.html', {'query': query,})
