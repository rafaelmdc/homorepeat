# No Admin Mode Implementation Details

## Current Code Context

Relevant files:

| Concern | File |
|---------|------|
| Env parsing and middleware list | `config/settings.py` |
| Admin URL mount and Flower proxy URL | `config/urls.py` |
| Flower staff gate | `apps/core/views.py` |
| Imports staff gate | `apps/imports/views.py` |
| Base nav links to Imports/Admin | `templates/base.html` |
| Compose web env | `compose.yaml` |
| Example env | `.env.example` |
| Config docs | `docs/configuration.md` |
| Staff redirect tests | `web_tests/test_smoke.py`, `web_tests/test_import_views.py` |

Current gates:

- `apps/imports/views.py` imports `staff_member_required` and wraps `StaffOnlyMixin.dispatch`.
- `apps/core/views.py` decorates `flower_proxy` with `@staff_member_required`.
- `config/urls.py` mounts `admin.site.urls` at `/admin/`.

## Implementation Plan

### 1. Add the setting

In `config/settings.py`, add:

```python
NO_ADMIN = _env_flag("no_admin", False)
```

Keep the external env var lowercase to match the issue. Use the existing `_env_flag` parser so accepted true values are already `1`, `true`, `yes`, and `on`.

### 2. Add a no-op-by-default middleware

Create `apps/core/no_admin.py`:

```python
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

    def has_perm(self, perm, obj=None):
        return True

    def has_perms(self, perm_list, obj=None):
        return True

    def has_module_perms(self, app_label):
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
```

Then add the middleware to `MIDDLEWARE` immediately after `django.contrib.auth.middleware.AuthenticationMiddleware`:

```python
"apps.core.no_admin.NoAdminMiddleware",
```

Make it always installed so `override_settings(NO_ADMIN=True)` works in tests.

### 3. Suppress admin logging in no-admin mode

Django admin add/change/delete actions can write `LogEntry` records with `request.user.pk`. A synthetic user has no primary key, so admin writes may fail unless logging is skipped.

Patch admin logging in `apps/core/apps.py`, but make the patched methods check `settings.NO_ADMIN` at call time. That keeps tests using `override_settings(NO_ADMIN=True)` valid after app startup:

```python
from django.apps import AppConfig
from django.conf import settings


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = "Core"

    def ready(self):
        from django.contrib import admin

        if getattr(admin.ModelAdmin, "_homorepeat_no_admin_log_patch", False):
            return

        original_log_addition = admin.ModelAdmin.log_addition
        original_log_change = admin.ModelAdmin.log_change
        original_log_deletion = admin.ModelAdmin.log_deletion

        def log_addition(self, request, obj, message):
            if getattr(settings, "NO_ADMIN", False):
                return None
            return original_log_addition(self, request, obj, message)

        def log_change(self, request, obj, message):
            if getattr(settings, "NO_ADMIN", False):
                return None
            return original_log_change(self, request, obj, message)

        def log_deletion(self, request, obj, object_repr):
            if getattr(settings, "NO_ADMIN", False):
                return None
            return original_log_deletion(self, request, obj, object_repr)

        admin.ModelAdmin.log_addition = log_addition
        admin.ModelAdmin.log_change = log_change
        admin.ModelAdmin.log_deletion = log_deletion
        admin.ModelAdmin._homorepeat_no_admin_log_patch = True
```

Before applying this exactly, check the local Django version signatures. If a signature differs, use separate wrappers matching the installed Django API. This project pins Django `>=5,<6`, where the signatures above are the expected shape.

### 4. Update Compose and env docs

In `.env.example`, add near the Django section:

```dotenv
# Local-first mode: bypass Django staff/admin login for trusted local use only.
no_admin=0
```

In `compose.yaml`, add only to the `web.environment` block:

```yaml
no_admin: ${no_admin:-0}
```

The `migrate`, Celery, and Flower containers do not process browser requests, so they do not need the variable.

In `docs/configuration.md`, add the option to the Django table:

| `no_admin` | `0` | Bypass Django staff/admin login and grant full permissions to every web request. Use only on trusted local machines. |

### 5. Tests

Add focused tests, preferably in a new `web_tests/test_no_admin.py`.

Recommended test cases:

```python
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(NO_ADMIN=True)
class NoAdminModeTests(TestCase):
    def test_imports_home_allows_anonymous_user(self):
        response = self.client.get(reverse("imports:home"))
        self.assertEqual(response.status_code, 200)

    def test_admin_index_allows_anonymous_user(self):
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)

    def test_import_history_allows_anonymous_user(self):
        response = self.client.get(reverse("imports:history"))
        self.assertEqual(response.status_code, 200)
```

Also add one admin write-path regression if practical:

- POST an `ImportBatch` add form through `admin:imports_importbatch_add`.
- Assert the response is a redirect or 200 without a `LogEntry` user failure.

Keep the existing redirect tests unchanged. They should still pass because `NO_ADMIN` defaults to false.

### 6. Validation Commands

Run the focused tests first:

```bash
python manage.py test web_tests.test_smoke web_tests.test_import_views web_tests.test_no_admin
```

Then run the full Django suite if dependencies are available:

```bash
python manage.py test web_tests
```

For Compose behavior:

```bash
no_admin=1 docker compose up web
```

Then manually check:

- `http://localhost:8000/imports/`
- `http://localhost:8000/imports/history/`
- `http://localhost:8000/admin/`
- `http://localhost:8000/admin/flower/`

## Possible Issues and Mitigations

| Issue | Mitigation |
|-------|------------|
| Lowercase `no_admin` is inconsistent with existing env names | Keep lowercase for the requested API; expose uppercase Django setting `NO_ADMIN` internally. |
| Middleware ordering breaks `staff_member_required` | Place `NoAdminMiddleware` immediately after `AuthenticationMiddleware`, before any view decorators run. |
| Admin writes fail because the synthetic user has no DB id | Suppress admin log methods in no-admin mode and add a write-path test. |
| A future feature expects `request.user` to be a saved `User` | Check for `request.user.pk` before persisting ownership fields; keep nullable user FKs nullable. |
| Accidental network exposure grants full control | Keep default false and document the local-only risk next to `.env.example` and config docs. |
| Tests cannot toggle mode | Always install middleware; make it branch on `settings.NO_ADMIN` per request. |

## Optimized File Change Set

Minimum likely files:

- `config/settings.py`
- `apps/core/no_admin.py`
- `apps/core/apps.py`
- `.env.example`
- `compose.yaml`
- `docs/configuration.md`
- `web_tests/test_no_admin.py`

Avoid touching `apps/imports/views.py` and `apps/core/views.py` unless a test proves the middleware approach is insufficient. The existing decorators then remain the default security boundary when `no_admin` is false.
