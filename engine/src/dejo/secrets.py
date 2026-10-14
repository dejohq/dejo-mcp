"""Passwords never go into memory.

Dejo remembers *that* a step types a password, never *which* password. The trail stored in
Sibyl holds a marker like `secret: "password"`; the value itself is looked up at replay time
from the machine it runs on.

Two places are checked, in order:

1. An environment variable, the usual place for a secret:
       DEJO_SECRET_BILLING_ACME_COM_PASSWORD
2. `~/.dejo/secrets.json`, which is easier for a person to manage:
       { "billing.acme.com": { "password": "..." } }

Neither lives in the repo, and neither is ever written to memory. If a secret is missing,
replay stops and says exactly which one to set — it never guesses and never falls back to
something stored earlier.
"""

from __future__ import annotations

import contextlib
import json
import re
from pathlib import Path
from typing import Any

from .home import HOME, setting

SECRETS_FILE = HOME / "secrets.json"
ENV_PREFIX = "DEJO_SECRET"


class MissingSecret(RuntimeError):
    """A step needs a password that this machine does not have.

    Deliberately loud. Quietly skipping the field would leave the browser sitting on a
    login page and the failure would surface three steps later as something confusing.
    """


def env_var_name(domain: str, field: str, profile: str | None = None) -> str:
    """The environment variable a given secret would come from."""
    parts = f"{domain}_{profile}_{field}" if profile else f"{domain}_{field}"
    slug = re.sub(r"[^A-Za-z0-9]+", "_", parts).strip("_").upper()
    return f"{ENV_PREFIX}_{slug}"


def resolve(
    domain: str,
    field: str,
    *,
    profile: str | None = None,
    secrets_file: Path | None = None,
) -> str:
    """Find one secret, or explain precisely how to provide it.

    A domain is not one identity. A marketplace has a customer sign-in, a vendor sign-in
    and an admin sign-in on the same host, each with its own password — so one password per
    domain meant two of three saved trails could never replay, and the third would try the
    wrong password against a real login and risk locking the account out.

    So the PROFILE is asked for first, and the plain domain entry is the fallback. That
    keeps every secrets file anybody already has working exactly as it did.
    """
    path = secrets_file or SECRETS_FILE
    for where in _places_to_look(domain, field, profile, path):
        if where:
            return str(where)
    raise MissingSecret(_how_to_provide_it(domain, field, profile, path))


def _places_to_look(domain: str, field: str, profile: str | None, path: Path) -> list[str | None]:
    """Every place this secret could be, most specific first.

    BOTH of the profile's own places come before EITHER of the domain-wide ones. Ordered
    the other way round — which is how this was written — an unprofiled environment
    variable beat the profile's own entry in the file: with DEJO_SECRET_SHOP_PASSWORD
    exported for the customer sign-in and the admin password sitting in secrets.json,
    running as `admin` typed the CUSTOMER's password into the admin login. Silently, with
    no error. That is the account lockout profiles exist to prevent.
    """
    for_domain = _read_file(path).get(domain, {})
    per_profile = for_domain.get(profile) if profile else None
    return [
        setting(env_var_name(domain, field, profile)) if profile else None,
        per_profile.get(field) if isinstance(per_profile, dict) else None,
        setting(env_var_name(domain, field)),
        # Only a string is a value. A nested object here is another profile's block.
        for_domain.get(field) if isinstance(for_domain.get(field), str) else None,
    ]


def _how_to_provide_it(domain: str, field: str, profile: str | None, path: Path) -> str:
    """Say exactly what to set, and — usually the real answer — who it was looked up as."""
    whose = f' (profile "{profile}")' if profile else ""
    shape = (
        f'{{"{domain}": {{"{profile}": {{"{field}": "..."}}}}}}'
        if profile
        else f'{{"{domain}": {{"{field}": "..."}}}}'
    )
    return (
        f'Dejo needs the "{field}" for {domain}{whose}, and never stores it. Provide it '
        f"either as the environment variable {env_var_name(domain, field, profile)}, or in "
        f"{path} as {shape}." + _but_these_profiles_have_it(domain, field, profile, path)
    )


def _but_these_profiles_have_it(domain: str, field: str, profile: str | None, path: Path) -> str:
    """Name the profiles that DO have this secret for this site.

    Everything needed is already in the file just read, and it turns "your secrets file is
    wrong" into "you are signed in as the wrong identity" — which is what it usually is.
    """
    others = sorted(
        name
        for name, block in _read_file(path).get(domain, {}).items()
        if name != profile and isinstance(block, dict) and block.get(field)
    )
    if not others:
        return ""
    named = ", ".join(f'"{name}"' for name in others)
    return (
        f" This machine does have a {field} for {domain} under {named} — "
        f"switch profile with dejo_profile if you meant one of those."
    )


def store(domain: str, field: str, value: str, *, secrets_file: Path | None = None) -> Path:
    """Write one secret to the local secrets file, for convenience.

    Only ever called because a person asked for it. The file is created private to the
    user where the platform allows it.
    """
    path = secrets_file or SECRETS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)

    everything = _read_file(path)
    everything.setdefault(domain, {})[field] = value
    path.write_text(json.dumps(everything, indent=2), encoding="utf-8")

    # Windows ignores POSIX modes; the file still sits in the user's own profile.
    with contextlib.suppress(OSError):
        path.chmod(0o600)
    return path


def known_fields(domain: str, *, secrets_file: Path | None = None) -> list[str]:
    """Which secrets this machine already has for a site. Names only, never values.

    A profile's block is named too, so `["admin", "password"]` reads as "there is an admin
    block and a domain-wide password" — which is what somebody looking for a missing one
    needs to see.
    """
    return sorted(_read_file(secrets_file or SECRETS_FILE).get(domain, {}))


def _read_file(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}
