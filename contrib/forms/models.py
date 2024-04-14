import datetime
import os
from django.conf import settings
from django.core.checks import Info
from django.core.exceptions import FieldError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import DatabaseError, models
from django.template.response import TemplateResponse
from django.utils.formats import date_format
from django.utils.text import slugify
from wagtail.admin.edit_handlers import FieldPanel
from wagtail.admin.mail import send_mail
from wagtail.contrib.forms.utils import get_field_clean_name
from wagtail.core.models import Orderable, Page
from .forms import FormBuilder, WagtailAdminFormPageForm

FORM_FIELD_CHOICES = (
    ('singleline', "Single line text"),
    ('multiline', "Multi-line text"),
    ('email', "Email Or PhoneNumber"),
    ('number', "Number"),
    ('url', "URL"),
    ('checkbox', "Checkbox"),
    ('checkboxes', "Checkboxes"),
    ('dropdown', "Drop down"),
    ('multiselect', "Multiple select"),
    ('radio', "Radio buttons"),
    ('date', "Date"),
    ('datetime', "Date/time"),
    ('hidden', "Hidden field"),
    # TODO: add a descriptive field that shows the visitors an explanatory in the form, render the replace markdown strings (i.e. [nl]...etc.)
)

class AbstractFormSubmission(models.Model):
    form_data = models.JSONField(encoder=DjangoJSONEncoder)
    page = models.ForeignKey(Page, on_delete=models.CASCADE)
    submit_time = models.DateTimeField(verbose_name="submit time", auto_now_add=True)
    def get_data(self): return {**self.form_data,"submit_time": self.submit_time,}
    def __str__(self): return f" submission of {self.page} at {self.submit_time}"
    class Meta:
        abstract = True
        verbose_name = "form submission"
        verbose_name_plural = "form submissions"

class FormSubmission(AbstractFormSubmission): pass

class AbstractFormField(Orderable):
    """ Database Fields required for building a Django Form field. """
    clean_name = models.CharField(verbose_name="name",max_length=255,blank=True,default='',help_text="Safe name of the form field, the label converted to ascii_snake_case")
    label = models.CharField(verbose_name="label",max_length=255,help_text="The label of the form field")
    field_type = models.CharField(verbose_name="field type", max_length=26, choices=FORM_FIELD_CHOICES)
    required = models.BooleanField(verbose_name="required", default=True)
    choices = models.TextField(verbose_name="choices",blank=True,help_text="Comma separated list of choices. Only applicable in checkboxes, radio and dropdown.")
    default_value = models.TextField(verbose_name="default value",blank=True,help_text="Default value. Comma separated values supported for checkboxes.")
    help_text = models.TextField(verbose_name="help text", blank=True) # Changed by HH
    panels = [
        FieldPanel('label', classname="col8"),
        FieldPanel('required', classname="col1"),
        FieldPanel('field_type', classname="col3"),
        FieldPanel('help_text', classname="col12"),
        FieldPanel('default_value', classname="col3 fb_default"),
        FieldPanel('choices', classname="col9 fb_choices"),
    ]
    def save(self, *args, **kwargs):
        """ When new fields are created, generate a template safe ascii name to use as the JSON storage reference for this field. Previously created fields will be updated to use the legacy unidecode method via checks & _migrate_legacy_clean_name. """
        print(self.label, self.is_section)
        is_new = self.pk is None
        if is_new:
            print("AbstractFormField.save() executed and the field is new with ID: ",self.id)
            clean_name = get_field_clean_name(self.label)
            self.clean_name = clean_name
        else:
            print("AbstractFormField.save() executed and the field is NOT new with ID: ",self.id)
        super().save(*args, **kwargs)
    @classmethod
    def _migrate_legacy_clean_name(cls):
        """ Ensure that existing data stored will be accessible via the legacy clean_name. When checks run, replace any blank clean_name values with the unidecode conversion. """
        try:
            objects = cls.objects.filter(clean_name__exact='')
            if objects.count() == 0: return None
        except (FieldError, DatabaseError): return None # attempting to query on clean_name before field has been added
        try: from unidecode import unidecode
        except ImportError as error:
            description = "You have form submission data that was created on an older version of Wagtail and requires the unidecode library to retrieve it correctly. Please install the unidecode package."
            raise Exception(description) from error
        for obj in objects:
            legacy_clean_name = str(slugify(str(obj.label)))
            obj.clean_name = legacy_clean_name
            obj.save()
        return Info('Added `clean_name` on %s form field(s)' % objects.count(),obj=cls)
    @classmethod
    def check(cls, **kwargs):
        # print("AbstractFormField.check() executed")
        errors = super().check(**kwargs)
        messages = cls._migrate_legacy_clean_name()
        if messages: errors.append(messages)
        return errors
    class Meta:
        abstract = True
        ordering = ['sort_order']

class AbstractForm(Page):
    """ A Form Page. Pages implementing a form should inherit from it """
    base_form_class = WagtailAdminFormPageForm
    form_builder = FormBuilder
    submissions_list_view_class = None
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not hasattr(self, 'landing_page_template'):
            name, ext = os.path.splitext(self.template)
            self.landing_page_template = name + '_landing' + ext
    def get_form_fields(self):
        """ Form page expects `form_fields` to be declared. If you want to change backwards relation name, you need to override this method. """
        return self.form_fields.all()
    def get_data_fields(self):
        """ Returns a list of tuples with (field_name, field_label). """
        data_fields = [('submit_time', "Submission Time"),]
        data_fields += [(field.clean_name, field.label) for field in self.get_form_fields()]
        return data_fields
    def get_form_class(self): return self.form_builder(self.get_form_fields()).get_form_class()
    def get_form_parameters(self): return {}
    def get_form(self, *args, **kwargs):
        form_class = self.get_form_class()
        form_params = self.get_form_parameters()
        form_params.update(kwargs)
        return form_class(*args, **form_params)
    def get_landing_page_template(self, request, *args, **kwargs): return self.landing_page_template
    def get_submission_class(self):
        """ Returns submission class. You can override this method to provide custom submission class. Your class must be inherited from AbstractFormSubmission. """
        return FormSubmission
    def get_submissions_list_view_class(self):
        from .views import SubmissionsListView
        return self.submissions_list_view_class or SubmissionsListView
    def process_form_submission(self, form):
        """ Accepts form instance with submitted data, user and page. Creates submission instance. You can override this method if you want to have custom creation logic. For example, if you want to save reference to a user. """
        return self.get_submission_class().objects.create(form_data=form.cleaned_data,page=self,)
    def render_landing_page(self, request, form_submission=None, *args, **kwargs):
        """ Renders the landing page. You can override this method to return a different HttpResponse as landing page. E.g. you could return a redirect to a separate page. """
        context = self.get_context(request)
        context['form_submission'] = form_submission
        return TemplateResponse(request,self.get_landing_page_template(request),context)
    def serve_submissions_list_view(self, request, *args, **kwargs):
        """ Returns list submissions view for admin. `list_submissions_view_class` can be set to provide custom view class. Your class must be inherited from SubmissionsListView. """
        view = self.get_submissions_list_view_class().as_view()
        return view(request, form_page=self, *args, **kwargs)
    def serve(self, request, *args, **kwargs):
        if request.method == 'POST':
            form = self.get_form(request.POST, request.FILES, page=self, user=request.user)
            if form.is_valid():
                form_submission = self.process_form_submission(form)
                return self.render_landing_page(request, form_submission, *args, **kwargs)
        else: form = self.get_form(page=self, user=request.user)
        context = self.get_context(request)
        context['form'] = form
        print(form.fields)
        for i in form.fields: print(i)
        return TemplateResponse(request,self.get_template(request),context)
    preview_modes = [('form', "Form"),] # ('landing', "Results")
    def serve_preview(self, request, mode_name):
        if mode_name == 'landing':
            request.is_preview = True
            request.preview_mode = mode_name
            return self.render_landing_page(request)
        else: return super().serve_preview(request, mode_name)
    class Meta: abstract = True

class AbstractEmailForm(AbstractForm):
    """ A Form Page that sends email. Pages implementing a form to be send to an email should inherit from it """
    to_address = models.CharField(verbose_name="to address", max_length=255, blank=True,help_text="Optional - form submissions will be emailed to these addresses. Separate multiple addresses by comma.")
    from_address = models.CharField(verbose_name="from address", max_length=255, blank=True)
    subject = models.CharField(verbose_name="subject", max_length=255, blank=True)
    def process_form_submission(self, form):
        submission = super().process_form_submission(form)
        if self.to_address: self.send_mail(form)
        return submission
    @property
    def get_submissions_count(self): return self.get_submission_class().objects.filter(page=self).count()
    def send_mail(self, form):
        addresses = [x.strip() for x in self.to_address.split(',')]
        send_mail(self.subject, self.render_email(form), addresses, self.from_address,)
    def render_email(self, form):
        content = []
        cleaned_data = form.cleaned_data
        for field in form:
            if field.name not in cleaned_data: continue
            value = cleaned_data.get(field.name)
            if isinstance(value, list): value = ', '.join(value)
            content.append('{}: {}'.format(field.label, value))
        return '\n'.join(content)
    class Meta: abstract = True
