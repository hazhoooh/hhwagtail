from django.utils.html import escape


from wagtail.utils.apps import get_app_submodules

from .shortcuts import get_rendition_or_not_found


class Format:
    def __init__(self, name, label, classnames, filter_spec):
        self.name = name
        self.label = label
        self.classnames = classnames
        self.filter_spec = filter_spec

    def __str__(self):
        return f'"{self.name}", "{self.label}", "{self.classnames}", "{self.filter_spec}"'

    def __repr__(self):
        return f"Format({self})"

    def editor_attributes(self, image, alt_text):
        """
        Return additional attributes to go on the HTML element
        when outputting this image within a rich text editor field
        """
        return {
            'data-embedtype': "image",
            'data-id': image.id,
            'data-format': self.name,
            'data-alt': escape(alt_text),
        }

    def image_to_editor_html(self, image, alt_text):
        return self.image_to_html(
            image, alt_text, self.editor_attributes(image, alt_text)
        )

    def image_to_html(self, image, alt_text, extra_attributes=None):
        if extra_attributes is None:
            extra_attributes = {}
        rendition = get_rendition_or_not_found(image, self.filter_spec)

        extra_attributes['alt'] = escape(alt_text)
        if self.classnames:
            extra_attributes['class'] = " %s" % escape(self.classnames)

        return rendition.img_tag(extra_attributes)


FORMATS = []
FORMATS_BY_NAME = {}


def register_image_format(format):
    if format.name in FORMATS_BY_NAME:
        raise KeyError("Image format '%s' is already registered" % format.name)
    FORMATS_BY_NAME[format.name] = format
    FORMATS.append(format)


def unregister_image_format(format_name):
    global FORMATS
    # handle being passed a format object rather than a format name string
    try:
        format_name = format_name.name
    except AttributeError:
        pass

    try:
        del FORMATS_BY_NAME[format_name]
        FORMATS = [fmt for fmt in FORMATS if fmt.name != format_name]
    except KeyError:
        raise KeyError("Image format '%s' is not registered" % format_name)


def get_image_formats():
    search_for_image_formats()
    return FORMATS


def get_image_format(name):
    search_for_image_formats()
    return FORMATS_BY_NAME[name]


_searched_for_image_formats = False


def search_for_image_formats():
    global _searched_for_image_formats
    if not _searched_for_image_formats:
        list(get_app_submodules('image_formats'))
        _searched_for_image_formats = True


# Define default image formats
# register_image_format(Format('fullwidth', "Full width", 'richtext-image full-width', 'width-800'))
# register_image_format(Format('left', "Left-aligned", 'richtext-image left', 'width-500'))
# register_image_format(Format('right', "Right-aligned", 'richtext-image right', 'width-500'))

register_image_format(Format('width300',  'Width 300',  'richtext-image', 'width-300'))
register_image_format(Format('width500',  'Width 500',  'richtext-image', 'width-500'))
register_image_format(Format('width700',  'Width 700',  'richtext-image', 'width-700'))
register_image_format(Format('width800',  'Width 800',  'richtext-image', 'width-800'))
register_image_format(Format('width1000', 'Width 1000', 'richtext-image', 'width-1000'))

register_image_format(Format('fullwidth', 'Full Width', 'richtext-image full-width', 'original'))

register_image_format(Format('fil_300x300',  'Exactly 300x300',  'richtext-image', 'fill-300x300'))
register_image_format(Format('fil_500x300',  'Exactly 500x300',  'richtext-image', 'fill-500x300'))
register_image_format(Format('fil_700x300',  'Exactly 700x300',  'richtext-image', 'fill-700x300'))
register_image_format(Format('fil_300x500',  'Exactly 300x500',  'richtext-image', 'fill-300x500'))
register_image_format(Format('fil_300x700',  'Exactly 300x700',  'richtext-image', 'fill-300x700'))

register_image_format(Format('fil_500x500',  'Exactly 500x500',  'richtext-image', 'fill-500x500'))
register_image_format(Format('fil_700x500',  'Exactly 700x500',  'richtext-image', 'fill-700x500'))
register_image_format(Format('fil_500x700',  'Exactly 500x700',  'richtext-image', 'fill-500x700'))
register_image_format(Format('fil_500x900',  'Exactly 500x900',  'richtext-image', 'fill-500x900'))

register_image_format(Format('fil_700x700',  'Exactly 700x700',  'richtext-image', 'fill-700x700'))
register_image_format(Format('fil_700x900',  'Exactly 700x900',  'richtext-image', 'fill-700x900'))

register_image_format(Format('left', 'To-Left 500x500', 'richtext-image left', 'fill-500x500'))

register_image_format(Format('left_300', 'To-Left width-300px', 'richtext-image left', 'width-300'))
register_image_format(Format('left_500', 'To-Left width-500px', 'richtext-image left', 'width-500'))
register_image_format(Format('left_700', 'To-Left width-700px', 'richtext-image left', 'width-700'))

register_image_format(Format('right_300', 'To-Right width-300px', 'richtext-image right', 'width-300'))
register_image_format(Format('right_500', 'To-Right width-500px', 'richtext-image right', 'width-500'))
register_image_format(Format('right_700', 'To-Right width-700px', 'richtext-image right', 'width-700'))

register_image_format(Format('width30',  'Social Media Icon Small',  'richtext-image small', 'width-30'))
register_image_format(Format('width50',  'Social Media Icon Medium',  'richtext-image medium', 'width-50'))
register_image_format(Format('width70',  'Social Media Icon Large',  'richtext-image large', 'width-70'))

register_image_format(Format('width30floated',  'Social Media Icon Small floated',  'richtext-image small left', 'width-30'))
register_image_format(Format('width50floated',  'Social Media Icon Medium floated',  'richtext-image medium left', 'width-50'))
register_image_format(Format('width70floated',  'Social Media Icon Large floated',  'richtext-image large left', 'width-70'))
