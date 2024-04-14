import os

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.urls.exceptions import NoReverseMatch
from django.utils.decorators import method_decorator
from django.utils.http import urlencode
from django.utils.translation import gettext as _
from django.views.generic import TemplateView, ListView
from django.views.decorators.cache import never_cache
from wagtail.admin import messages
from wagtail.admin.auth import PermissionPolicyChecker
from wagtail.admin.forms.search import SearchForm
from wagtail.admin.models import popular_tags_for_model
from wagtail.admin.views.pages.utils import get_valid_next_url_from_request
from wagtail.core.models import Collection, Site
from wagtail.images import get_image_model
from wagtail.images.exceptions import InvalidFilterSpecError
from wagtail.images.forms import URLGeneratorForm, get_image_form
from wagtail.images.models import Filter, SourceImageIOError
from wagtail.images.permissions import permission_policy
from wagtail.images.utils import generate_signature
from wagtail.search import index as search_index

permission_checker = PermissionPolicyChecker(permission_policy)

INDEX_PAGE_SIZE = getattr(settings, 'CONSOLE_IMAGES_INDEX_PAGE_SIZE', 200)
USAGE_PAGE_SIZE = getattr(settings, 'CONSOLE_IMAGES_USAGE_PAGE_SIZE', 200)
Image = get_image_model()

class BaseListingView(TemplateView):
    @method_decorator(permission_checker.require_any('add', 'change', 'delete'))
    def get(self, request): return super().get(request)
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        images = permission_policy.instances_user_has_any_permission_for(self.request.user, ['change', 'delete']).order_by('-created_at').select_related('collection')
        query_string = None
        if 'q' in self.request.GET:
            self.form = SearchForm(self.request.GET, placeholder="Search images")
            if self.form.is_valid():
                query_string = self.form.cleaned_data['q']
                images = images.search(query_string)
        else: self.form = SearchForm(placeholder="Search images")
        self.current_collection = None
        collection_id = self.request.GET.get('collection_id')
        if collection_id:
            try:
                self.current_collection = Collection.objects.get(id=collection_id)
                images = images.filter(collection=self.current_collection)
            except (ValueError, Collection.DoesNotExist): pass
        # Filter by tag
        self.current_tag = self.request.GET.get('tag')
        if self.current_tag:
            try: images = images.filter(tags__name=self.current_tag)
            except (AttributeError): self.current_tag = None
        paginator = Paginator(images, per_page=INDEX_PAGE_SIZE)
        images = paginator.get_page(self.request.GET.get('p'))
        next_url = reverse("wagtailimages:index")
        request_query_string = self.request.META.get("QUERY_STRING")
        if request_query_string: next_url += "?" + request_query_string
        context.update({'images': images,'query_string': query_string,'is_searching': bool(query_string),'next': next_url,})
        return context

class IndexView(BaseListingView):
    template_name = 'wagtailimages/images/index.html'
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        collections = permission_policy.collections_user_has_any_permission_for(self.request.user, ['add', 'change'])
        if len(collections) < 2: collections = None
        context.update({
            'search_form': self.form,
            'popular_tags': popular_tags_for_model(Image),
            'current_tag': self.current_tag,
            'collections': collections,
            'current_collection': self.current_collection,
            'user_can_add': permission_policy.user_has_permission(self.request.user, 'add'),
            'app_label': Image._meta.app_label,
            'model_name': Image._meta.model_name,
        })
        return context

class ListingResultsView(BaseListingView): template_name = 'wagtailimages/images/index.html'

@permission_checker.require('change')
@never_cache
def edit(request, image_id):
    Image = get_image_model()
    ImageForm = get_image_form(Image, view="edit")
    image = get_object_or_404(Image, id=image_id)
    if not permission_policy.user_has_permission_for_instance(request.user, 'change', image): raise PermissionDenied
    next_url = get_valid_next_url_from_request(request)
    
    if request.method == 'POST':
        original_file = image.file
        # for updated_file in request.FILES.getlist('file'):
        form = ImageForm(request.POST,request.FILES, instance=image, user=request.user)
        if form.is_valid():
            if 'file' in form.changed_data:
                # Set new image file size
                image.file_size = image.file.size
                # Set new image file hash
                image.file.seek(0)
                image._set_file_hash(image.file.read())
                image.file.seek(0)
            form.save()
            if 'file' in form.changed_data:
                # if providing a new image file, delete the old one and all renditions.
                # NB Doing this via original_file.delete() clears the file field,
                # which definitely isn't what we want...
                original_file.storage.delete(original_file.name)
                image.renditions.all().delete()

            # Reindex the image to make sure all tags are indexed
            search_index.insert_or_update_object(image)

            edit_url = reverse('wagtailimages:edit', args=(image.id,))
            redirect_url = 'wagtailimages:index'
            if next_url:
                edit_url = f"{edit_url}?{urlencode({'next': next_url})}"
                redirect_url = next_url

            messages.success(request, "Image '{0}' updated.".format(image.title), buttons=[
                messages.button(edit_url, "Edit again")
            ])
            return redirect(redirect_url)
        else: messages.error(request, "The image could not be saved due to errors.")
    else: form = ImageForm(instance=image, user=request.user)
    # Check if we should enable the frontend url generator
    try:
        reverse('wagtailimages_serve', args=('foo', '1', 'bar'))
        url_generator_enabled = True
    except NoReverseMatch:
        url_generator_enabled = False

    if image.is_stored_locally():
        # Give error if image file doesn't exist
        if not os.path.isfile(image.file.path):
            messages.error(request, "The source image file could not be found. Please change the source or delete the image.", buttons=[messages.button(reverse('wagtailimages:delete', args=(image.id,)), "Delete")])

    try: filesize = image.get_file_size()
    except SourceImageIOError: filesize = None

    return TemplateResponse(request, "wagtailimages/images/edit.html", {
        'image': image,
        'form': form,
        'url_generator_enabled': url_generator_enabled,
        'filesize': filesize,
        'user_can_delete': permission_policy.user_has_permission_for_instance(request.user, 'delete', image),
        'next': next_url,
    })

def url_generator(request, image_id):
    image = get_object_or_404(get_image_model(), id=image_id)
    if not permission_policy.user_has_permission_for_instance(request.user, 'change', image): raise PermissionDenied
    form = URLGeneratorForm(initial={'filter_method': 'original','width': image.width,'height': image.height,})
    return TemplateResponse(request, "wagtailimages/images/url_generator.html", {'image': image,'form': form,})

def generate_url(request, image_id, filter_spec):
    Image = get_image_model()
    try: image = Image.objects.get(id=image_id)
    except Image.DoesNotExist: return JsonResponse({'error': "Cannot find image."}, status=404)
    if not permission_policy.user_has_permission_for_instance(request.user, 'change', image): return JsonResponse({'error': "You do not have permission to generate a URL for this image."}, status=403)
    try: Filter(spec=filter_spec).operations
    except InvalidFilterSpecError: return JsonResponse({'error': "Invalid filter spec."}, status=400)
    signature = generate_signature(image_id, filter_spec)
    url = reverse('wagtailimages_serve', args=(signature, image_id, filter_spec))
    try: site_root_url = Site.objects.get(is_default_site=True).root_url
    except Site.DoesNotExist: site_root_url = Site.objects.first().root_url
    preview_url = reverse('wagtailimages:preview', args=(image_id, filter_spec))
    return JsonResponse({'url': site_root_url + url, 'preview_url': preview_url}, status=200)

def preview(request, image_id, filter_spec):
    image = get_object_or_404(get_image_model(), id=image_id)
    try:
        response = HttpResponse()
        image = Filter(spec=filter_spec).run(image, response)
        response['Content-Type'] = 'image/' + image.format_name
        return response
    except InvalidFilterSpecError: return HttpResponse("Invalid filter spec: " + filter_spec, content_type='text/plain', status=400)

@permission_checker.require('delete')
def delete(request, image_id):
    image = get_object_or_404(get_image_model(), id=image_id)
    if not permission_policy.user_has_permission_for_instance(request.user, 'delete', image): raise PermissionDenied
    next_url = get_valid_next_url_from_request(request)
    if request.method == 'POST':
        image.delete()
        messages.success(request, "Image '{0}' deleted.".format(image.title))
        return redirect(next_url) if next_url else redirect('wagtailimages:index')
    return TemplateResponse(request, "wagtailimages/images/confirm_delete.html", {'image': image,'next': next_url,})

@permission_checker.require('add')
def add(request):
    ImageModel = get_image_model()
    ImageForm = get_image_form(ImageModel)
    form = ImageForm(user=request.user)
    if request.method == 'POST':
        images = []
        titles = request.POST.get('title').split(',')
        # Handle multiple file uploads
        for idx, uploaded_file in enumerate(request.FILES.getlist('file')):
            image = ImageModel(uploaded_by_user=request.user)
            form = ImageForm(request.POST,{'file': uploaded_file}, instance=image, user=request.user)
            if form.is_valid():
                image.file_size = image.file.size
                image.file.seek(0)
                image._set_file_hash(image.file.read())
                image.file.seek(0)
                image.title = form.cleaned_data["title"] = titles[idx].strip()
                form.save()
                search_index.insert_or_update_object(image)
                images.append(image)
            else:
                messages.error(request, "Image '{0}' could not be created due to errors: {1}".format(image.title, form.errors))
        if images:
            messages.success(request, "Images added.")
            return redirect('wagtailimages:index')
        else: messages.error(request, "No images were uploaded.")
    return TemplateResponse(request, "wagtailimages/images/add.html", {'form': form,})

def usage(request, image_id):
    image = get_object_or_404(get_image_model(), id=image_id)
    paginator = Paginator(image.get_usage(), per_page=USAGE_PAGE_SIZE)
    used_by = paginator.get_page(request.GET.get('p'))
    return TemplateResponse(request, "wagtailimages/images/usage.html", {'image': image,'used_by': used_by})
