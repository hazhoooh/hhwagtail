import pytz

from django.conf import settings
from django.utils.dates import MONTHS, WEEKDAYS, WEEKDAYS_ABBR
from django.utils.translation import gettext as _


# Wagtail languages with >=90% coverage
# This list is manually maintained
CONSOLE_PROVIDED_LANGUAGES = [
    # ('ar', 'Arabic'),
    # ('ca', 'Catalan'),
    # ('cs', 'Czech'),
    # ('de', 'German'),
    # ('el', 'Greek'),
    ('en', 'English'),
    # ('es', 'Spanish'),
    # ('et', 'Estonian'),
    # ('fi', 'Finnish'),
    # ('fr', 'French'),
    # ('gl', 'Galician'),
    # ('hr', 'Croatian'),
    # ('hu', 'Hungarian'),
    # ('id-id', 'Indonesian'),
    # ('is-is', 'Icelandic'),
    # ('it', 'Italian'),
    # ('ja', 'Japanese'),
    # ('ko', 'Korean'),
    # ('lt', 'Lithuanian'),
    # ('mn', 'Mongolian'),
    # ('nb', 'Norwegian Bokmål'),
    # ('nl', 'Dutch'),
    # ('fa', 'Persian'),
    # ('pl', 'Polish'),
    # ('pt-br', 'Brazilian Portuguese'),
    # ('pt-pt', 'Portuguese'),
    # ('ro', 'Romanian'),
    # ('ru', 'Russian'),
    # ('sv', 'Swedish'),
    # ('sk-sk', 'Slovak'),
    # ('th', 'Thai'),
    # ('tr', 'Turkish'),
    # ('uk', 'Ukrainian'),
    # ('zh-hans', 'Chinese (Simplified)'),
    # ('zh-hant', 'Chinese (Traditional)'),
]


# Translatable strings to be made available to JavaScript code
# as the wagtailConfig.STRINGS object
def get_js_translation_strings():
    return {
        'DELETE': "Delete",
        'EDIT': "Edit",
        'PAGE': "Page",
        'PAGES': "Pages",
        'LOADING': "Loading…",
        'NO_RESULTS': "No results",
        'SERVER_ERROR': "Server Error",
        'SEE_ALL': "See all",
        'CLOSE_EXPLORER': "Close explorer",
        'ALT_TEXT': "Alt text",
        'DECORATIVE_IMAGE': "Decorative image",
        'WRITE_HERE': "Write here…",
        'HORIZONTAL_LINE': "Horizontal line",
        'LINE_BREAK': "Line break",
        'UNDO': "Undo",
        'REDO': "Redo",
        'RELOAD_PAGE': "Reload the page",
        'RELOAD_EDITOR': "Reload saved content",
        'SHOW_LATEST_CONTENT': "Show latest content",
        'SHOW_ERROR': "Show error",
        'EDITOR_CRASH': "The editor just crashed. Content has been reset to the last saved version.",
        'BROKEN_LINK': "Broken link",
        'MISSING_DOCUMENT': "Missing document",
        'CLOSE': "Close",
        'EDIT_PAGE': 'Edit \'{title}\'',
        'VIEW_CHILD_PAGES_OF_PAGE': 'View child pages of \'{title}\'',
        'PAGE_EXPLORER': "Page explorer",
        'SAVE': "Save",
        'SAVING': "Saving...",
        'CANCEL': "Cancel",
        'DELETING': "Deleting...",
        'ADD_A_COMMENT': "Add a comment",
        'SHOW_COMMENTS': "Show comments",
        'REPLY': "Reply",
        'RESOLVE': "Resolve",
        'RETRY': "Retry",
        'DELETE_ERROR': "Delete error",
        'CONFIRM_DELETE_COMMENT': "Are you sure?",
        'SAVE_ERROR': "Save error",
        'SAVE_COMMENT_WARNING': "This will be saved when the page is saved",
        'FOCUS_COMMENT': "Focus comment",
        'UNFOCUS_COMMENT': "Unfocus comment",
        'COMMENT': "Comment",
        'MORE_ACTIONS': "More actions",
        'SAVE_PAGE_TO_ADD_COMMENT': "Save the page to add this comment",
        'SAVE_PAGE_TO_SAVE_COMMENT_CHANGES': "Save the page to save this comment",
        'SAVE_PAGE_TO_SAVE_REPLY': "Save the page to save this reply",
        'DASHBOARD': "Dashboard",
        'EDIT_YOUR_ACCOUNT': "Edit your account",
        'SEARCH': "Search",

        'MONTHS': [str(m) for m in MONTHS.values()],

        # Django's WEEKDAYS list begins on Monday, but ours should start on Sunday, so start
        # counting from -1 and use modulo 7 to get an array index
        'WEEKDAYS': [str(WEEKDAYS[d % 7]) for d in range(-1, 6)],
        'WEEKDAYS_SHORT': [str(WEEKDAYS_ABBR[d % 7]) for d in range(-1, 6)],

        # used by bulk actions
        'BULK_ACTIONS': {
            'PAGE': {
                'SINGULAR': "1 page selected",
                'PLURAL': "{0} pages selected",
                'ALL': "All {0} pages on this screen selected",
                'ALL_IN_LISTING': "All pages in listing selected",
            },
            'DOCUMENT': {
                'SINGULAR': "1 document selected",
                'PLURAL': "{0} documents selected",
                'ALL': "All {0} documents on this screen selected",
                'ALL_IN_LISTING': "All documents in listing selected",
            },
            'IMAGE': {
                'SINGULAR': "1 image selected",
                'PLURAL': "{0} images selected",
                'ALL': "All {0} images on this screen selected",
                'ALL_IN_LISTING': "All images in listing selected",
            },
            'USER': {
                'SINGULAR': "1 user selected",
                'PLURAL': "{0} users selected",
                'ALL': "All {0} users on this screen selected",
                'ALL_IN_LISTING': "All users in listing selected",
            },
            'ITEM': {
                'SINGULAR': "1 item selected",
                'PLURAL': "{0} items selected",
                'ALL': "All {0} items on this screen selected",
                'ALL_IN_LISTING': "All items in listing selected",
            },
        },
    }


def get_available_admin_languages():
    return getattr(settings, 'CONSOLE_PERMITTED_LANGUAGES', CONSOLE_PROVIDED_LANGUAGES)


def get_available_admin_time_zones():
    if not settings.USE_TZ: return []
    return getattr(settings, 'CONSOLE_USER_TIME_ZONES', pytz.all_timezones)
