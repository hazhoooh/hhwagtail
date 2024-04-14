from django.urls import include, path, reverse
from django.utils.html import format_html
from django.utils.translation import gettext
from django.utils.translation import ngettext
from wagtail.admin.admin_url_finder import ModelAdminURLFinder, register_admin_url_finder
from wagtail.admin.menu import MenuItem
from wagtail.admin.navigation import get_site_for_user
from wagtail.admin.search import SearchArea
from wagtail.admin.site_summary import SummaryItem
from wagtail.core import hooks
from wagtail.images import admin_urls, get_image_model, image_operations
from wagtail.images.api.admin.views import ImagesAdminAPIViewSet
from wagtail.images.forms import GroupImagePermissionFormSet
from wagtail.images.permissions import permission_policy
from wagtail.images.views.bulk_actions import AddTagsBulkAction, AddToCollectionBulkAction, DeleteBulkAction

@hooks.register('register_admin_urls')
def register_admin_urls():
    return [
        path('images/', include(admin_urls, namespace='wagtailimages')),
    ]

@hooks.register('construct_admin_api')
def construct_admin_api(router):
    router.register_endpoint('images', ImagesAdminAPIViewSet)

class ImagesMenuItem(MenuItem):
    def is_shown(self, request): return permission_policy.user_has_any_permission(request.user, ['add', 'change', 'delete'])

@hooks.register('register_console_menu_item')
def register_images_menu_item(): return ImagesMenuItem('📸 Images', reverse('wagtailimages:index'),name='images', icon_name='', order=250)

@hooks.register('insert_editor_js')
def editor_js(): return format_html("<script>window.chooserUrls.imageChooser = '{0}';</script>",reverse('wagtailimages:chooser'))

@hooks.register('register_image_operations')
def register_image_operations():
    return [
        ('original', image_operations.DoNothingOperation),
        ('fill', image_operations.FillOperation),
        ('min', image_operations.MinMaxOperation),
        ('max', image_operations.MinMaxOperation),
        ('width', image_operations.WidthHeightOperation),
        ('height', image_operations.WidthHeightOperation),
        ('scale', image_operations.ScaleOperation),
        ('jpegquality', image_operations.JPEGQualityOperation),
        ('webpquality', image_operations.WebPQualityOperation),
        ('format', image_operations.FormatOperation),
        ('bgcolor', image_operations.BackgroundColorOperation),
    ]

class ImagesSummaryItem(SummaryItem):
    order = 200
    template_name = 'wagtailimages/console_boards/images.html'
    def get_context_data(self, parent_context):
        site_name = get_site_for_user(self.request.user)['site_name']
        return {
            'total_images': get_image_model().objects.count(),
            'site_name': site_name,
        }
    def is_shown(self):
        return permission_policy.user_has_any_permission(self.request.user, ['add', 'change', 'delete'])

@hooks.register('construct_console_boards_summary_items')
def add_images_summary_item(request, items):
    items.append(ImagesSummaryItem(request))

class ImagesSearchArea(SearchArea):
    def is_shown(self, request):
        return permission_policy.user_has_any_permission(request.user, ['add', 'change', 'delete'])

@hooks.register('register_admin_search_area')
def register_images_search_area():
    return ImagesSearchArea('📷 Images', reverse('wagtailimages:index'),name='images',icon_name='',order=200)

@hooks.register('register_group_permission_panel')
def register_image_permissions_panel():
    return GroupImagePermissionFormSet

@hooks.register('describe_collection_contents')
def describe_collection_docs(collection):
    images_count = get_image_model().objects.filter(collection=collection).count()
    if images_count:
        url = reverse('wagtailimages:index') + f'?collection_id={collection.id}'
        return {'count': images_count,'count_text': ngettext("%(count)s image","%(count)s images",images_count) % {'count': images_count},'url': url,}

class ImageAdminURLFinder(ModelAdminURLFinder):
    edit_url_name = 'wagtailimages:edit'
    permission_policy = permission_policy

register_admin_url_finder(get_image_model(), ImageAdminURLFinder)

for action_class in [AddTagsBulkAction, AddToCollectionBulkAction, DeleteBulkAction]:
    hooks.register('register_bulk_action', action_class)
