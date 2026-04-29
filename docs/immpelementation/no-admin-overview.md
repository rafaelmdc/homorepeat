# No Admin Mode Overview

## Problem

HomoRepeat is intended to be local-first, but two local operator surfaces currently require a Django staff account:

- `/imports/` and `/imports/history/`, gated by `StaffOnlyMixin` in `apps/imports/views.py`
- `/admin/flower/`, gated by `@staff_member_required` in `apps/core/views.py`

The Django admin itself is also mounted at `/admin/` in `config/urls.py`, so using the built-in admin requires a staff/superuser row in the local database. That is awkward for a workstation-oriented tool where the person running the app already controls the machine and the database.

Add a `.env` option named `no_admin` that defaults to false. When true, all local web requests should be treated as fully trusted: no login, no staff check, and all permission checks succeed.

## Goals

- Keep the default security behavior unchanged.
- Make `no_admin=true` enough to use imports, Flower, and Django admin without creating a user.
- Centralize the bypass so individual views do not grow one-off permission branches.
- Preserve normal Django authentication when `no_admin` is unset or false.
- Keep the implementation small and testable.

## Non-Goals

- Do not remove `django.contrib.auth`, sessions, or the Django admin app.
- Do not change browser routes, which are already public.
- Do not replace CSRF protection. No-admin mode is about local authorization, not request integrity.
- Do not create or persist a hidden superuser unless a later admin write-path test proves that is safer than suppressing admin logging.

## Proposed Shape

Expose a Django setting:

```python
NO_ADMIN = _env_flag("no_admin", False)
```

Install one middleware after `AuthenticationMiddleware`. When `settings.NO_ADMIN` is true, it replaces `request.user` with a lightweight trusted user object that reports:

- `is_authenticated = True`
- `is_active = True`
- `is_staff = True`
- `is_superuser = True`
- `has_perm(...) = True`
- `has_module_perms(...) = True`

That single request-user substitution lets existing `staff_member_required` decorators and most Django admin checks pass without touching each view.

Because Django admin writes normally create `LogEntry` rows tied to a real user id, no-admin mode should also suppress admin log creation rather than creating a database user. This keeps the feature aligned with the issue: no local admin account is required.

## User-Facing Behavior

With default configuration:

- Anonymous `/imports/` redirects to the Django admin login.
- Anonymous `/admin/flower/` redirects to the Django admin login.
- Anonymous `/admin/` redirects to the Django admin login.

With `no_admin=true`:

- `/imports/` renders for any local visitor.
- `/imports/history/` renders for any local visitor.
- `/admin/flower/` proxies to Flower for any local visitor.
- `/admin/` opens without login and grants full model permissions.

## Configuration Surface

Add `no_admin=0` to `.env.example`.

Pass `no_admin: ${no_admin:-0}` into the Compose `web` service. Worker services do not need it because this is request authorization behavior.

Document the option in `docs/configuration.md` with a warning that it should only be used for local trusted deployments.

## Main Risks

- **Case-sensitive env naming:** the issue asks for lowercase `no_admin`. Python and Compose can read it, but this differs from the project’s current uppercase convention.
- **Django admin write logging:** an unsaved synthetic user can fail admin add/change/delete logging. Suppressing admin logging in no-admin mode avoids creating a real account.
- **Public exposure:** if someone exposes the web service on a LAN or internet host with `no_admin=true`, every visitor gets full admin access. Documentation should be explicit.
- **Tests with `override_settings`:** if the middleware is only conditionally inserted during settings import, tests cannot easily toggle it. Keep the middleware always installed and make it a no-op unless `settings.NO_ADMIN` is true.
- **Future user-specific features:** `DownloadBuild.requested_by` is currently nullable and unused, but any future feature that assumes a real authenticated user id must handle the no-admin synthetic user.

## Success Criteria

- Existing tests pass with default `NO_ADMIN=False`.
- New tests prove anonymous users can reach imports and admin routes with `NO_ADMIN=True`.
- No database user is required to use the local admin mode.
- Configuration docs and `.env.example` make the feature discoverable.
