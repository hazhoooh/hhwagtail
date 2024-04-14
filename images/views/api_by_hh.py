
from django.contrib.auth.models import User
from django.conf import settings
from rest_framework.permissions import BasePermission
from rest_framework import serializers
from wagtail.admin.forms.search import SearchForm
from wagtail.images.permissions import permission_policy
from wagtail.images import get_image_model
from wagtail.core.models import Collection, Site
from wagtail.images.shortcuts import get_rendition_or_not_found
from utilities.viewsets import BaseListViewSet

Image=get_image_model()

class ImageSerializer(serializers.ModelSerializer):
  class Meta:
    model = Image
    fields = ['id', 'title', 'file', 'width', 'height', 'created_at', 'uploaded_by_user','collection'] #, 'file_hash'] # 'tags', TypeError: Object of type _TaggableManager is not JSON serializable, see the Object:
      
class ImageListViewSet(BaseListViewSet):
  serializer_class=ImageSerializer
  def get_queryset(self):
    images=permission_policy.instances_user_has_any_permission_for(self.request.user, ['add', 'change', 'delete'])
    q = None
    if 'q' in self.request.GET:
      self.form = SearchForm(self.request.GET, placeholder="Search images")
      if self.form.is_valid():
        q = self.form.cleaned_data['q']
        images = images.search(q) if q and len(q) >= int(getattr(settings,"SEARCH_MIN_LENGTH",4)) else []
    # else: self.form = SearchForm(placeholder="Search images")
    self.current_collection = None
    collection_id = self.request.GET.get('cid')
    if collection_id:
      try:
        self.current_collection = Collection.objects.get(id=collection_id)
        images = images.filter(collection=self.current_collection)
      except (ValueError, Collection.DoesNotExist): pass
    self.current_tag = self.request.GET.get('tag')
    if self.current_tag:
      try: images = images.filter(tags__name=self.current_tag)
      except (AttributeError): self.current_tag = None
    return images
  
  def list(self, request, *args, **kwargs):
    queryset = self.filter_queryset(self.get_queryset())
    serializer = self.get_serializer(queryset, many=True)
    images_data = serializer.data
    width = self.request.GET.get('width')
    from django.http import JsonResponse
    if width:
      images = []
      for image in queryset:
        rendition = image.get_rendition(f'width-{width}')
        combined_data = {
            'id': rendition.id,
            'orig_id': image.id,
            'title': image.title,
            'file': rendition.file.url,
            'orig_file': image.file.url,
            'width': rendition.width,
            'orig_width': image.width,
            'height': rendition.height,
            'orig_height': image.height,
            'created_at': image.created_at,
            'uploaded_by_user': image.uploaded_by_user,
            'collection': image.collection.id if image.collection else None,
        }
        images.append(combined_data)
      # print(images)
      return JsonResponse(images, safe=False)
    return JsonResponse(images_data, safe=False)
  
'''
from django.test import RequestFactory
from wagtail.images.views import api_views_by_hh
from rest_framework.test import APIClient
print(
    api_views_by_hh.ImageListViewSet.as_view({"get": "list", "post": "create"})(
      RequestFactory().get("l_i_s_t/")
    ).render()
  )
'''