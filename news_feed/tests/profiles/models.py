import logging

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models
from django.template.defaultfilters import slugify
from django.utils.translation import ugettext_lazy as _

logger = logging.getLogger(__name__)


class Organization(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, db_index=False, blank=True)


class CustomUserBase(AbstractBaseUser):

    email = models.EmailField(
        max_length=255, blank=False, null=False, unique=True)
    first_name = models.CharField(max_length=100, blank=True, default="")
    last_name = models.CharField(max_length=100, blank=True, default="")

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    date_of_birth = models.DateField(null=True, blank=True)
    wedding_date = models.DateField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_admin_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(
        _('superuser status'), default=False,
        help_text=_('Designates that this user has all permissions without '
                    'explicitly assigning them.'))

    class Meta:
        abstract = True

    def has_perm(self, perm, obj=None):
        """
        Returns True if the user has the specified permission. This method
        queries all available auth backends, but returns immediately if any
        backend returns True. Thus, a user who has permission from a single
        auth backend is assumed to have permission in general. If an object is
        provided, permissions for this specific object are checked.
        """
        # Active superusers have all permissions.
        if self.is_active and self.is_superuser:
            return True

        if self.is_staff and hasattr(obj, "organization_id") and perm:
            return self.organization_id == obj.organization_id

        return False

    def has_perms(self, perm_list, obj=None):
        """
        Returns True if the user has each of the specified permissions. If
        object is passed, it checks if the user has all required perms for this
        object.
        """
        for perm in perm_list:
            if not self.has_perm(perm, obj):
                return False
        return True

    def has_module_perms(self, *args, **kwargs):
        """
        Returns True if the user has any permissions in the given app label.
        Uses pretty much the same logic as has_perm, above.
        """
        # Active superusers have all permissions.
        if self.is_active and self.is_superuser:
            return True

        return False

    def get_username(self):
        return self.email

    def get_short_name(self):
        return self.first_name or self.email


class DefaultCustomUserQueryset(models.QuerySet):

    def delete(self):
        self.update(is_active=False)


class DefaultCustomUserManager(BaseUserManager):

    def get_queryset(self):
        users = DefaultCustomUserQueryset(self.model)
        return users.all()


class CustomUser(CustomUserBase):
    organization = models.ForeignKey(Organization, related_name="users")
    employee_id = models.TextField(default="", editable=True, unique=True)
    is_p2p_staff = models.BooleanField(default=False, help_text="p2p staff is not limited by p2p_points_limit, but can "
                                       "recognize users in the same org only")

    objects = DefaultCustomUserManager()

    USERNAME_FIELD = 'email'

    def get_departments(self):
        return ",".join([str(p) for p in self.departments.all()])

    def add_departments(self, department_list):
        # Takes a list of department name strings
        for dept in department_list:
            name = dept.strip().title()
            # pylint: disable=unused-variable
            department, created = Department.objects.get_or_create(
                organization=self.organization,
                slug=slugify(name),
                defaults={"name": name}
            )
            self.departments.add(department)

    @property
    def department(self):
        return self.departments.first()

    def send_welcome_email(self):
        pass

    def __unicode__(self):
        return self.email

    def delete(self, *args, **kwargs):
        self.is_active = False
        self.save()

    class Meta:
        verbose_name = "user"

    def save(self, *args, **kwargs):
        self.email = self.email.lower()
        if not self.employee_id:
            employee_id = self.email
            while True:
                q = CustomUser.objects.filter(employee_id=employee_id)
                if self.id:
                    q = q.exclude(pk=self.id)
                if not q.exists():
                    self.employee_id = employee_id
                    break
                else:
                    employee_id = "_" + employee_id
        super(CustomUser, self).save(*args, **kwargs)

    def set_password(self, raw_password):
        if raw_password != '':
            super(CustomUser, self).set_password(raw_password)
            # Record new password in the password history
            # The very first password will not be recorded though, Sudhanshu says its fine
            if self.pk:
                PasswordHistory.objects.add_password(self, raw_password)

    def using_default_password(self):
        """
        Default password is not recorded in PasswordHistory model, so if user has no entries in PasswordHistory
        then he must be using default password.
        """
        return not self.password_history.exists()


class Department(models.Model):
    """
    Make department codes selectable and stuff
    """
    organization = models.ForeignKey(Organization, related_name="departments")
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=200)
    users = models.ManyToManyField("CustomUser", related_name="departments", blank=True)

    def __unicode__(self):
        return "%s - %s" % (self.name, self.organization.name)

    class Meta:
        ordering = ("slug", "pk")
        unique_together = (
            ("organization", "slug"),
        )


class PasswordHistoryQueryset(models.QuerySet):

    salt = "Pas_1Hist9"

    def make_password(self, password):
        return make_password(password, self.salt)

    def add_password(self, user, password):
        password = self.make_password(password)
        inst = PasswordHistory(user=user, password=password)
        # User should only have 3 entries in password history, delete any extra entries
        while user.password_history.count() >= 3:
            user.password_history.order_by("pk").first().delete()
        inst.save()

    def password_already_used(self, user_email, password):
        password = self.make_password(password)
        return self.filter(user__email=user_email, password=password).exists()


class PasswordHistory(models.Model):
    user = models.ForeignKey("profiles.CustomUser", related_name="password_history")
    password = models.CharField(max_length=100, blank=True, null=False)
    created = models.DateTimeField(auto_now_add=True)
    objects = PasswordHistoryQueryset.as_manager()

    def __unicode__(self):
        return "Password history for {0}".format(self.user)

    class Meta:
        verbose_name = "Password history entry"
        verbose_name_plural = "Password history entries"
