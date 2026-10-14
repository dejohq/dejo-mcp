"""`~/.dejo`, and the one-time copy from `~/.cairn`.

Dejo was called Cairn and kept its signed-in browser profiles in `~/.cairn`. Losing that
folder in the rename would sign every existing user out of every site, with nothing to say
why. These tests pin the promise: copied once, never moved, never half-done, and never
silently skipped.
"""

from __future__ import annotations

import shutil

import pytest

from dejo import home


def old_home_with_a_signed_in_profile(root):
    old = root / ".cairn"
    profile = old / "browser-profile"
    profile.mkdir(parents=True)
    (profile / "Cookies").write_text("signed in", encoding="utf-8")
    (profile / home.OLD_PROFILE_OWNER).write_text("chrome", encoding="utf-8")
    (profile / "SingletonLock").write_text("held by a running browser", encoding="utf-8")
    admin = old / "profiles" / "admin"
    admin.mkdir(parents=True)
    (admin / home.OLD_PROFILE_OWNER).write_text("chromium", encoding="utf-8")
    (old / "secrets.json").write_text('{"acme.com": {"password": "x"}}', encoding="utf-8")
    (old / "wallet.env").write_text("DEJO_WALLET_KEY=0xsecret", encoding="utf-8")
    return old


class TestTheOldFolderIsBroughtAcross:
    def test_sign_ins_and_secrets_arrive_in_the_new_folder(self, tmp_path) -> None:
        old = old_home_with_a_signed_in_profile(tmp_path)
        new = tmp_path / ".dejo"

        assert home.adopt_old_home(new, old) is True

        assert (new / "browser-profile" / "Cookies").read_text(encoding="utf-8") == "signed in"
        assert (new / "secrets.json").is_file()

    def test_the_old_folder_is_copied_never_moved(self, tmp_path) -> None:
        old = old_home_with_a_signed_in_profile(tmp_path)

        home.adopt_old_home(tmp_path / ".dejo", old)

        assert (old / "browser-profile" / "Cookies").is_file()
        assert (old / "browser-profile" / home.OLD_PROFILE_OWNER).is_file()

    def test_every_profile_keeps_the_name_of_the_browser_that_made_it(self, tmp_path) -> None:
        """The marker is renamed, not dropped. Without it, a profile made by Chromium is
        opened with Chrome first, which is the direction that can lose a login."""
        old = old_home_with_a_signed_in_profile(tmp_path)
        new = tmp_path / ".dejo"

        home.adopt_old_home(new, old)

        for profile, made_by in (
            (new / "browser-profile", "chrome"),
            (new / "profiles" / "admin", "chromium"),
        ):
            assert (profile / home.PROFILE_OWNER).read_text(encoding="utf-8") == made_by
            assert not (profile / home.OLD_PROFILE_OWNER).exists()

    def test_lock_files_and_wallet_keys_are_left_behind(self, tmp_path) -> None:
        old = old_home_with_a_signed_in_profile(tmp_path)
        new = tmp_path / ".dejo"

        home.adopt_old_home(new, old)

        assert not (new / "browser-profile" / "SingletonLock").exists()
        assert not (new / "wallet.env").exists()


class TestItHappensOnlyOnce:
    def test_an_existing_new_folder_is_never_overwritten(self, tmp_path) -> None:
        old = old_home_with_a_signed_in_profile(tmp_path)
        new = tmp_path / ".dejo"
        new.mkdir()

        assert home.adopt_old_home(new, old) is False
        assert not (new / "browser-profile").exists()

    def test_nothing_to_do_without_an_old_folder(self, tmp_path) -> None:
        new = tmp_path / ".dejo"

        assert home.adopt_old_home(new, tmp_path / ".cairn") is False
        assert not new.exists()


class TestAFailedCopyIsNeverMistakenForADoneOne:
    def test_it_stops_with_a_reason_and_leaves_nothing_half_copied(
        self, tmp_path, monkeypatch
    ) -> None:
        old = old_home_with_a_signed_in_profile(tmp_path)
        new = tmp_path / ".dejo"

        def locked(*args, **kwargs):
            raise PermissionError("the profile is in use")

        monkeypatch.setattr(shutil, "copytree", locked)

        with pytest.raises(home.OldHomeNotCopied) as stuck:
            home.adopt_old_home(new, old)

        said = str(stuck.value)
        assert "the profile is in use" in said
        assert "Close any Cairn or Dejo" in said, "it must say what to do next"
        assert not new.exists(), "an empty ~/.dejo would stop the copy ever being retried"
        assert not (tmp_path / ".dejo.partial").exists()


class TestOldSettingsStillWork:
    def test_the_new_name_wins(self, monkeypatch) -> None:
        monkeypatch.setenv("DEJO_AGENT", "new")
        monkeypatch.setenv("CAIRN_AGENT", "old")

        assert home.setting("DEJO_AGENT") == "new"

    def test_the_old_name_is_read_when_the_new_one_is_unset(self, monkeypatch) -> None:
        monkeypatch.delenv("DEJO_AGENT", raising=False)
        monkeypatch.setenv("CAIRN_AGENT", "old")

        assert home.setting("DEJO_AGENT") == "old"

    def test_an_empty_value_counts_as_unset(self, monkeypatch) -> None:
        monkeypatch.setenv("DEJO_PROFILE", "")
        monkeypatch.delenv("CAIRN_PROFILE", raising=False)

        assert home.setting("DEJO_PROFILE") is None

    def test_an_old_password_variable_is_still_found(self, monkeypatch, tmp_path) -> None:
        from dejo.secrets import resolve

        monkeypatch.setenv("CAIRN_SECRET_ACME_COM_PASSWORD", "hunter2")

        assert resolve("acme.com", "password", secrets_file=tmp_path / "none.json") == "hunter2"


def test_the_commands_bring_the_old_folder_across_and_the_library_does_not() -> None:
    """Only `dejo` and `dejo-mcp` may touch the real home folder. `main` is what tests and
    programs call, so it must not."""
    import inspect

    from dejo import cli

    assert "adopt_old_home" in inspect.getsource(cli.console)
    assert "adopt_old_home" not in inspect.getsource(cli.main)
