import jinja2

from jinja2.ext import Extension

from .templatetags.userbar import userbar


class WagtailUserbarExtension(Extension):
    def __init__(self, environment):
        super().__init__(environment)

        self.environment.globals.update({
            'userbar': jinja2.contextfunction(userbar),
        })


# Nicer import names
userbar = WagtailUserbarExtension
