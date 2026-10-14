"""Passwords must never end up in memory.

Dejo writes its trail to a file on disk. A password in that file is a password in a
backup, a sync folder, and eventually a support ticket. So a step remembers *that* it
types a password, never *which* one, and the value is looked up on the machine that runs
the replay.
"""

from __future__ import annotations

import json

import pytest
from tests.conftest import TASK, cold_run

from dejo.browser import Browser, Element, domain_of
from dejo.operations import Session, secret_name
from dejo.secrets import MissingSecret, env_var_name, known_fields, resolve, store
from dejo.store import DejoStore


class TestRecognisingASecret:
    def test_a_password_box_is_a_secret(self):
        field = Element(
            ref="e1", role="textbox", name="Password", tag="input", css="#p", type="password"
        )

        assert secret_name(field) == "password"

    def test_an_ordinary_box_is_not(self):
        field = Element(ref="e1", role="textbox", name="Email", tag="input", css="#e", type="email")

        assert secret_name(field) is None

    def test_nothing_is_not_a_secret(self):
        assert secret_name(None) is None


class TestNothingSecretIsWrittenDown:
    def test_the_password_is_absent_from_the_saved_trail(
        self, browser: Browser, store: DejoStore, demo_server: str
    ):
        """The test that matters. Search the whole stored trail for the password."""
        session = Session(browser, store)
        cold_run(session, demo_server)
        session.save(TASK, domain=domain_of(demo_server))

        written = json.dumps(store.load_playbook(domain_of(demo_server)).to_dict())

        assert "hunter2" not in written, "the password was written into memory"

    def test_the_step_still_knows_a_password_belongs_there(
        self, browser: Browser, store: DejoStore, demo_server: str
    ):
        session = Session(browser, store)
        cold_run(session, demo_server)
        playbook = session.save(TASK, domain=domain_of(demo_server))

        password_steps = [step for step in playbook.steps if step.secret]

        assert len(password_steps) == 1
        assert password_steps[0].secret == "password"
        assert password_steps[0].value is None, "the value must not be kept"

    def test_the_email_is_still_remembered(
        self, browser: Browser, store: DejoStore, demo_server: str
    ):
        """Only secrets are dropped. Ordinary values are what make replay work."""
        session = Session(browser, store)
        cold_run(session, demo_server)
        playbook = session.save(TASK, domain=domain_of(demo_server))

        assert any(step.value == "finance@acme.com" for step in playbook.steps)

    def test_act_tells_the_caller_it_did_not_remember(self, browser: Browser, demo_server: str):
        session = Session(browser)
        session.act("open", "goto", value=f"{demo_server}/")
        page = session.look()
        password = next(e for e in page["elements"] if e["name"] == "Password")

        outcome = session.act("type the password", "fill", ref=password["ref"], value="hunter2")

        assert outcome["secret"] == "password"
        assert "did not remember" in outcome["note"]

    def test_look_never_reports_what_is_in_a_password_box(self, browser: Browser, demo_server: str):
        browser.goto(f"{demo_server}/")

        snapshot = browser.snapshot()

        password = next(e for e in snapshot.elements if e.name == "Password")
        assert password.value == "(filled)", "it may say a value exists, never what it is"
        assert "hunter2" not in str(snapshot.to_dict())


class TestFindingTheSecretAtReplayTime:
    def test_an_environment_variable_is_used(self, monkeypatch):
        monkeypatch.setenv(env_var_name("acme.com", "password"), "from-the-environment")

        assert resolve("acme.com", "password") == "from-the-environment"

    def test_the_variable_name_is_predictable(self):
        assert env_var_name("billing.acme.com", "password") == (
            "DEJO_SECRET_BILLING_ACME_COM_PASSWORD"
        )

    def test_a_secrets_file_is_used_when_there_is_no_variable(self, tmp_path):
        secrets = tmp_path / "secrets.json"
        store("acme.com", "password", "from-the-file", secrets_file=secrets)

        assert resolve("acme.com", "password", secrets_file=secrets) == "from-the-file"

    def test_the_environment_wins_over_the_file(self, tmp_path, monkeypatch):
        secrets = tmp_path / "secrets.json"
        store("acme.com", "password", "from-the-file", secrets_file=secrets)
        monkeypatch.setenv(env_var_name("acme.com", "password"), "from-the-environment")

        assert resolve("acme.com", "password", secrets_file=secrets) == "from-the-environment"

    def test_a_missing_secret_says_exactly_what_to_set(self, tmp_path):
        with pytest.raises(MissingSecret) as raised:
            resolve("acme.com", "password", secrets_file=tmp_path / "nothing.json")

        message = str(raised.value)
        assert "DEJO_SECRET_ACME_COM_PASSWORD" in message
        assert "acme.com" in message

    def test_it_never_guesses(self, tmp_path):
        """Falling back to a blank or an old value would fail three steps later,
        somewhere confusing. Better to stop here."""
        with pytest.raises(MissingSecret):
            resolve("acme.com", "password", secrets_file=tmp_path / "nothing.json")

    def test_the_file_lists_names_but_never_values(self, tmp_path):
        secrets = tmp_path / "secrets.json"
        store("acme.com", "password", "top-secret", secrets_file=secrets)

        assert known_fields("acme.com", secrets_file=secrets) == ["password"]

    def test_a_broken_secrets_file_is_survived(self, tmp_path):
        secrets = tmp_path / "secrets.json"
        secrets.write_text("this is not json", encoding="utf-8")

        with pytest.raises(MissingSecret):
            resolve("acme.com", "password", secrets_file=secrets)


class TestReplayWithoutTheSecret:
    def test_replay_stops_and_explains(
        self, browser: Browser, store: DejoStore, demo_server: str, monkeypatch
    ):
        """Someone running this with no setup should get a clear instruction, not a crash."""
        from dejo.executor import Executor

        session = Session(browser, store)
        cold_run(session, demo_server)
        session.save(TASK, domain=domain_of(demo_server))

        domain = domain_of(demo_server)
        monkeypatch.delenv(env_var_name(domain, "password"), raising=False)
        monkeypatch.setattr(
            "dejo.secrets.SECRETS_FILE", tmp_missing := __import__("pathlib").Path("nowhere.json")
        )
        assert not tmp_missing.exists()

        with pytest.raises(MissingSecret) as raised:
            Executor(store, browser).run(domain, start_url=f"{demo_server}/")

        assert "never stores it" in str(raised.value)


class TestOneDomainWithSeveralSignIns:
    """A domain is not one identity.

    Found on a real marketplace: a customer sign-in, a vendor sign-in and an admin sign-in,
    all on the same host, each with its own password. One password per domain meant two of
    three saved trails could never replay — and the third would try the wrong password
    against a real login, which is how an account gets locked out.
    """

    def test_each_profile_gets_its_own_password(self, tmp_path) -> None:
        where = tmp_path / "secrets.json"
        where.write_text(
            json.dumps(
                {
                    "shop.example.com": {
                        "admin": {"password": "admin-one"},
                        "vendor": {"password": "vendor-one"},
                    }
                }
            ),
            encoding="utf-8",
        )

        as_admin = resolve("shop.example.com", "password", profile="admin", secrets_file=where)
        as_vendor = resolve("shop.example.com", "password", profile="vendor", secrets_file=where)

        assert as_admin == "admin-one"
        assert as_vendor == "vendor-one"

    def test_a_domain_wide_password_still_answers_when_a_profile_has_none(self, tmp_path) -> None:
        """Nobody's existing secrets file may stop working because profiles now exist."""
        where = tmp_path / "secrets.json"
        where.write_text(
            json.dumps({"shop.example.com": {"password": "the-only-one"}}), encoding="utf-8"
        )

        assert resolve("shop.example.com", "password", secrets_file=where) == "the-only-one"
        assert (
            resolve("shop.example.com", "password", profile="admin", secrets_file=where)
            == "the-only-one"
        )

    def test_a_profile_beats_the_domain_wide_one(self, tmp_path) -> None:
        where = tmp_path / "secrets.json"
        where.write_text(
            json.dumps(
                {"shop.example.com": {"password": "fallback", "admin": {"password": "specific"}}}
            ),
            encoding="utf-8",
        )

        assert (
            resolve("shop.example.com", "password", profile="admin", secrets_file=where)
            == "specific"
        )

    def test_the_environment_can_scope_by_profile_too(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("DEJO_SECRET_SHOP_EXAMPLE_COM_ADMIN_PASSWORD", "from-the-env")

        got = resolve(
            "shop.example.com", "password", profile="admin", secrets_file=tmp_path / "none.json"
        )

        assert got == "from-the-env"

    def test_a_missing_secret_says_which_profile_it_wants(self, tmp_path) -> None:
        with pytest.raises(MissingSecret) as refused:
            resolve("shop.example.com", "password", profile="admin", secrets_file=tmp_path / "x")

        said = str(refused.value)
        assert 'profile "admin"' in said
        assert "DEJO_SECRET_SHOP_EXAMPLE_COM_ADMIN_PASSWORD" in said

    def test_a_profile_block_is_never_mistaken_for_a_value(self, tmp_path) -> None:
        """`{"admin": {...}}` is another profile, not a secret called "admin"."""
        where = tmp_path / "secrets.json"
        where.write_text(
            json.dumps({"shop.example.com": {"admin": {"password": "a"}}}), encoding="utf-8"
        )

        with pytest.raises(MissingSecret):
            resolve("shop.example.com", "admin", secrets_file=where)


class TestTheWrongPasswordIsNeverTypedIn:
    """The fault nobody reported, and the worst one in this file.

    `_places_to_look` used to run: profile env, PLAIN env, profile file, plain file. So an
    unprofiled environment variable — the ordinary way anyone sets one password for a site —
    outranked the profile's OWN entry in secrets.json. Working as `admin`, Dejo typed the
    CUSTOMER's password into the admin login, silently, and a few of those lock an account.

    Both of a profile's places now come before both of the domain-wide ones.
    """

    def test_the_profiles_own_entry_beats_an_unprofiled_environment_variable(
        self, tmp_path, monkeypatch
    ) -> None:
        where = tmp_path / "secrets.json"
        where.write_text(
            json.dumps({"shop.example.com": {"admin": {"password": "the-admin-one"}}}),
            encoding="utf-8",
        )
        monkeypatch.setenv("DEJO_SECRET_SHOP_EXAMPLE_COM_PASSWORD", "the-customer-one")

        got = resolve("shop.example.com", "password", profile="admin", secrets_file=where)

        assert got == "the-admin-one"

    def test_a_profiles_own_environment_variable_still_wins_over_everything(
        self, tmp_path, monkeypatch
    ) -> None:
        """Most specific first is the whole rule. Reordering must not break the top of it."""
        where = tmp_path / "secrets.json"
        where.write_text(
            json.dumps({"shop.example.com": {"admin": {"password": "from-the-file"}}}),
            encoding="utf-8",
        )
        monkeypatch.setenv("DEJO_SECRET_SHOP_EXAMPLE_COM_ADMIN_PASSWORD", "from-the-env")

        got = resolve("shop.example.com", "password", profile="admin", secrets_file=where)

        assert got == "from-the-env"


class TestSayingWhoItLookedAs:
    """A missing password is usually the wrong identity, not a missing entry.

    The password IS in the file, under `admin`, and the active profile has quietly gone
    back to `default`. The old message said the site had no password at all, which sent a
    person to edit a file that was already correct.
    """

    def test_the_default_profile_is_named_too(self, tmp_path) -> None:
        with pytest.raises(MissingSecret) as refused:
            resolve("shop.example.com", "password", profile="default", secrets_file=tmp_path / "x")

        assert 'profile "default"' in str(refused.value)

    def test_it_names_the_profiles_that_do_have_one(self, tmp_path) -> None:
        where = tmp_path / "secrets.json"
        where.write_text(
            json.dumps(
                {
                    "shop.example.com": {
                        "admin": {"password": "a"},
                        "vendor": {"password": "v"},
                    }
                }
            ),
            encoding="utf-8",
        )

        with pytest.raises(MissingSecret) as refused:
            resolve("shop.example.com", "password", profile="default", secrets_file=where)

        said = str(refused.value)
        assert '"admin"' in said
        assert '"vendor"' in said
        assert "dejo_profile" in said

    def test_but_never_the_value(self, tmp_path) -> None:
        where = tmp_path / "secrets.json"
        where.write_text(
            json.dumps({"shop.example.com": {"admin": {"password": "hunter2"}}}), encoding="utf-8"
        )

        with pytest.raises(MissingSecret) as refused:
            resolve("shop.example.com", "password", profile="default", secrets_file=where)

        assert "hunter2" not in str(refused.value)

    def test_and_says_nothing_when_no_other_profile_has_one(self, tmp_path) -> None:
        """Advice about switching profile is noise on a machine with only one."""
        with pytest.raises(MissingSecret) as refused:
            resolve("acme.com", "password", secrets_file=tmp_path / "nothing.json")

        assert "dejo_profile" not in str(refused.value)
