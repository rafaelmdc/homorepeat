from __future__ import annotations

from django.conf import settings
from django.utils.functional import SimpleLazyObject


class NoAdminUser:
    pk = None
    id = None
    username = "no_admin"
    is_active = True
    is_staff = True
    is_superuser = True
    is_authenticated = True
    is_anonymous = False

    def __str__(self):
        return self.username

    def get_username(self):
        return self.username

    def get_full_name(self):
        return self.username

    def get_short_name(self):
        return self.username

    def has_perm(self, _perm, obj=None):
        return True

    def has_perms(self, _perm_list, obj=None):
        return True

    def has_module_perms(self, _app_label):
        return True

    def get_all_permissions(self, obj=None):
        return set()


class NoAdminMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(settings, "NO_ADMIN", False):
            request.user = SimpleLazyObject(lambda: NoAdminUser())
        return self.get_response(request)
