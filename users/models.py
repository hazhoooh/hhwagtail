import os
import uuid
# import pyotp
import qrcode

from django.urls import reverse
from django.conf import settings
from django.db import models
from django.utils.translation import get_language
from django.utils import timezone

from modelcluster.models import ClusterableModel

from wagtail.core.models import Site
# from wagtail.admin.edit_handlers import InlinePanel, FieldPanel

def upload_avatar_to(instance, filename):
    filename, ext = os.path.splitext(filename)
    return os.path.join('avatar_images','avatar_{uuid}_{filename}{ext}'.format(uuid=uuid.uuid4(), filename=filename, ext=ext))

class UserProfile(ClusterableModel):
    sites = models.ManyToManyField(Site, related_name='users')
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wagtail_userprofile')
    # TODO: convert all notification fields to one JSONField
    submitted_notifications = models.BooleanField(verbose_name="Page submitted notifications",default=True,help_text="Receive notification when a page is submitted for moderation")
    approved_notifications = models.BooleanField(verbose_name="Page approved notifications",default=True,help_text="Receive notification when your page edit is approved")
    rejected_notifications = models.BooleanField(verbose_name="Page rejected notifications",default=True,help_text="Receive notification when your page edit is rejected")
    updated_comments_notifications = models.BooleanField(verbose_name="updated comments notifications",default=False,help_text="Receive notification when comments have been created, resolved, or deleted on a page that you have subscribed to receive comment notifications on")
    preferred_language = models.CharField(verbose_name="preferred language",max_length=10,help_text="Select language for the admin",default='en')
    current_time_zone = models.CharField(verbose_name="current time zone",max_length=40,help_text="Select your current time zone",default='')
    avatar = models.ImageField(verbose_name="profile picture",upload_to=upload_avatar_to,blank=True)
    created_at = models.DateTimeField(verbose_name="secret key updated at", default=timezone.now)
    qrcode = models.ImageField(verbose_name="QR code",upload_to="user_qrs",blank=True)
    secret_key = models.CharField(verbose_name="secret key", max_length=16, default="")
    def generate_or_update_secret_key(self):
        from io import BytesIO
        from django.core.files import File
        # self.secret_key = pyotp.random_base32()
        qr_code_img = qrcode.make(self.get_qr_code_url())
        buffer = BytesIO()
        qr_code_img.save(buffer, "PNG")
        file = File(buffer)
        self.qrcode.save(f"{self.user.id}_qr.png", file, save=False)
        buffer.close()
        file.close()
        self.save()
    # def get_qr_code_url(self): return pyotp.totp.TOTP(self.secret_key).provisioning_uri(name=self.user.email, issuer_name="UserProfile")
    def get_qr_code_image(self):
        qr_url = self.get_qr_code_url()
        img = qrcode.make(qr_url)
        img_url = reverse("qr_code_image", kwargs={"user_id": self.user.id})
        return (img, img_url)
    @classmethod
    def get_for_user(cls, user): return cls.objects.get_or_create(user=user)[0]
    @property
    def user_assets(self):
        from wagtail.core.models import Page
        from wagtail.images.models import Image
        from wagtail.documents.models import Document
        usr_pgs=Page.objects.filter(owner=self.user)
        usr_imgs=Image.objects.filter(uploaded_by_user=self.user)
        usr_docs=Document.objects.filter(uploaded_by_user=self.user)
        def all_counts(): return usr_pgs.count()+usr_imgs.count()+usr_docs.count()
        def pg_count(): return usr_pgs.count()
        def img_count(): return usr_imgs.count()
        def doc_count(): return usr_docs.count()
        return {"pgs":[asset for asset in usr_pgs],"imgs":[asset for asset in usr_imgs],"docs":[asset for asset in usr_docs], "pgs_count":pg_count, "imgs_count":img_count, "docs_count":doc_count, "all_counts":all_counts}
    def get_preferred_language(self): return self.preferred_language or get_language()
    def get_current_time_zone(self): return self.current_time_zone or settings.TIME_ZONE
    def __str__(self): return self.user.get_username() + "(" + str(self.user.id) + ")"
    class Meta:
        verbose_name = "user profile"
        verbose_name_plural = "user profiles"
