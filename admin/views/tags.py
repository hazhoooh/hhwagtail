from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.http import Http404, JsonResponse
from taggit.models import Tag, TagBase

def autocomplete(request):
    app_name=request.GET.get('app_name', None)
    model_name=request.GET.get('model_name', None)
    if app_name and model_name:
        try: content_type = ContentType.objects.get_by_natural_key(app_name, model_name)
        except ContentType.DoesNotExist: raise Http404
        tag_model = content_type.model_class()
        if not issubclass(tag_model, TagBase): raise Http404
    else: tag_model = Tag
    term = request.GET.get('term', None)
    if term: tags = tag_model.objects.filter(name__istartswith=term).order_by('name')
    else: tags = tag_model.objects.none()
    return JsonResponse([tag.name for tag in tags], safe=False)

def create_tag(request):
    tag_name=request.GET.get('tag_name', None)
    object_id=request.GET.get('object_id', None)
    app_name=request.GET.get('app_name', None)
    model_name=request.GET.get('model_name', None)
    try: content_type = ContentType.objects.get_by_natural_key(app_name, model_name)
    except ContentType.DoesNotExist: raise Http404
    tag_model = content_type.model_class()
    tag, created = tag_model.objects.get_or_create(name=tag_name)
    tag_relation_model = tag_model._meta.related_objects[0].related_model
    tag_relation_model(tag=tag, content_type=content_type, object_id=object_id).save()
    return JsonResponse({'created': created, 'tag_name': tag.name})