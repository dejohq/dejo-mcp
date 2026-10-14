"""`dejo doctor` — the command a stranger runs when nothing works.

Everything Dejo needs that is not Python code has produced a confusing failure at some
point in this project: a browser that installs separately, a profile Chrome refused, a
missing screen, a home folder it cannot write to. This command exists so none of those has
to be met as a traceback in the middle of a run.

These tests are about the REPORTING, not the environment: what it says when something is
broken, and whether it knows the difference between essential and optional.
"""

from __future__ import annotations

from dejo import doctor


def a_check(**changes) -> doctor.Check:
    base = {"name": "thing", "ok": True, "detail": "fine", "fix": "", "essential": True}
    return doctor.Check(**{**base, **changes})


class TestItReportsHonestly:
    def test_everything_working_exits_zero(self, capsys, monkeypatch) -> None:
        monkeypatch.setattr(doctor, "run_checks", lambda: [a_check()])

        assert doctor.cmd_doctor(None) == 0
        assert "Everything Dejo needs is here" in capsys.readouterr().out

    def test_a_broken_essential_check_exits_non_zero(self, capsys, monkeypatch) -> None:
        """Non-zero on purpose, so this is usable in somebody's setup script."""
        monkeypatch.setattr(
            doctor,
            "run_checks",
            lambda: [
                a_check(name="browser", ok=False, fix="python -m playwright install chromium")
            ],
        )

        assert doctor.cmd_doctor(None) == 1
        said = capsys.readouterr().out
        assert "FAIL" in said
        assert "playwright install chromium" in said, "the fix has to be printed, not implied"

    def test_a_missing_optional_is_not_a_failure(self, capsys, monkeypatch) -> None:
        """A profile that has not been made yet is optional. Nobody should be told their
        setup is broken because of it."""
        monkeypatch.setattr(
            doctor,
            "run_checks",
            lambda: [a_check(name="profile", ok=False, essential=False, fix="optional")],
        )

        assert doctor.cmd_doctor(None) == 0
        assert "FAIL" not in capsys.readouterr().out

    def test_every_broken_thing_is_named_at_the_end(self, capsys, monkeypatch) -> None:
        monkeypatch.setattr(
            doctor,
            "run_checks",
            lambda: [
                a_check(name="browser", ok=False),
                a_check(name="memory", ok=False),
                a_check(name="python"),
            ],
        )

        doctor.cmd_doctor(None)
        said = capsys.readouterr().out
        assert "browser, memory" in said


class TestTheChecksThemselves:
    def test_python_is_checked_against_what_the_readme_promises(self) -> None:
        assert doctor.MINIMUM_PYTHON == (3, 11)
        assert doctor._python().ok, "the interpreter running the tests must qualify"

    def test_memory_reports_what_it_can_reach(self) -> None:
        got = doctor._memory()

        assert got.ok
        assert "remembered" in got.detail

    def test_a_missing_profile_is_fine_rather_than_broken(self, monkeypatch, tmp_path) -> None:
        """A profile that does not exist yet is made on first use. Reporting that as a
        problem would send somebody looking for a fault that is not there."""
        monkeypatch.setattr(doctor, "DEFAULT_PROFILE", tmp_path / "never-made", raising=False)
        import dejo.browser as browser_module

        monkeypatch.setattr(browser_module, "DEFAULT_PROFILE", tmp_path / "never-made")

        got = doctor._profile()

        assert got.ok
        assert got.essential is False

    def test_run_checks_covers_everything_that_has_ever_broken(self) -> None:
        """A list, so adding a check is a one-line change and forgetting one is visible."""
        names = {check.name for check in doctor.run_checks()}

        assert names == {"python", "dejo", "browser", "profile", "memory", "downloads"}


def test_doctor_is_reachable_from_the_command_line() -> None:
    from dejo.cli import build_parser

    args = build_parser().parse_args(["doctor"])

    assert args.func is doctor.cmd_doctor
