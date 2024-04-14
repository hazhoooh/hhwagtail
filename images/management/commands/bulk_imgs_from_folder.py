# your_app/management/commands/create_images_from_folder.py
from django.core.management.base import BaseCommand
from wagtail.core.models import Collection
from wagtail.images import get_image_model
# from wagtail.images import get_image_model_string
import os

class Command(BaseCommand):
  help = 'Create image objects from files in a subfolder and assign them to a specified collection'
  def add_arguments(self, parser):
    # parser.add_argument('collection_id', type=int, help='ID of the collection to assign the images to')
    parser.add_argument('path', type=str, help='Path to the subfolder containing image files')
  def handle(self, *args, **options):
    # collection_id = options['collection_id']
    path = options['path']
    Image = get_image_model()
    if not os.path.exists(path):
      self.stdout.write(self.style.ERROR(f"Path '{path}' does not exist."))
      return
    self.stdout.write("Choose a collection:")
    collections = Collection.objects.all()
    for collection in collections: self.stdout.write(f"{collection.id} - {collection.name}")
    collection_id = input("Enter the ID of the collection you want to assign images to: ")
    try: collection_id = int(collection_id)
    except ValueError:
      self.stdout.write(self.style.ERROR("Invalid collection ID. Please enter a valid integer ID."))
      return

    for filename in os.listdir(path):
      if filename.endswith(('.jpg', '.jpeg', '.png', '.gif')):
        image = Image(file=os.path.join(path, filename), collection_id=collection_id)
        image.save()
        self.stdout.write(self.style.SUCCESS(f"Created image object for {filename}"))
