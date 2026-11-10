"""Dates a task names relative to today, and the fixed dates a trail picked for them.

"Download this month's invoice", learned in September, clicks "September 2026". The words
say "this month", and the trail holds September. Asked in October, a replay that clicks
September again passes every check and hands back the wrong invoice, so before a replay
Dejo works out which date the words mean today and aims the trail at it, the way a changed
subject is aimed (see `executor.with_values`). A date it cannot work out is named, and the
replay stops rather than guess.

Plain Python and no network, so it is safe on the replay path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

DAY, WEEK, MONTH, YEAR = "day", "week", "month", "year"

# "latest", "current" and the like say "now" without saying how precisely. A date the trail
# picked is then moved to now at its own precision: a month to this month, a day to today.
ITS_OWN = "its own"

# What a task's words mean, as (unit, how many of them from now). Longest phrases first, so
# "last month" is read before "month" alone could be.
_PHRASES: list[tuple[str, str, int]] = [
    ("this month", MONTH, 0),
    ("current month", MONTH, 0),
    ("last month", MONTH, -1),
    ("previous month", MONTH, -1),
    ("next month", MONTH, 1),
    ("this week", WEEK, 0),
    ("last week", WEEK, -1),
    ("previous week", WEEK, -1),
    ("next week", WEEK, 1),
    ("this year", YEAR, 0),
    ("current year", YEAR, 0),
    ("last year", YEAR, -1),
    ("previous year", YEAR, -1),
    ("next year", YEAR, 1),
    ("today", DAY, 0),
    ("tonight", DAY, 0),
    ("yesterday", DAY, -1),
    ("tomorrow", DAY, 1),
    ("latest", ITS_OWN, 0),
    ("newest", ITS_OWN, 0),
    ("most recent", ITS_OWN, 0),
    ("current", ITS_OWN, 0),
]

# The words of every phrase above, so a caller comparing two tasks can tell a time word from
# a value: "last" in "last month's invoice" is not a new subject.
TIME_WORDS = frozenset(word for phrase, _, _ in _PHRASES for word in phrase.split())

MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
# Three letters, the way most sites shorten a month. "Sept" is common enough to know too.
_SHORT = {name[:3]: number for number, name in enumerate(MONTHS, start=1)} | {"Sept": 9}
_FULL = {name: number for number, name in enumerate(MONTHS, start=1)}
_ANY_MONTH = "|".join(sorted([*_FULL, *_SHORT], key=len, reverse=True))

# The fixed dates a trail can hold, most precise first so a day is never read as its month.
# A month name stands alone only capitalised: "may" is far more often a verb.
_DATES = re.compile(
    rf"(?<![0-9A-Za-z])(?:"
    rf"(?P<iso_day>(?P<dy>\d{{4}})-(?P<dm>\d{{2}})-(?P<dd>\d{{2}}))"
    rf"|(?P<iso_month>(?P<my>\d{{4}})-(?P<mm>\d{{2}}))"
    rf"|(?P<day_month>(?P<nd>\d{{1,2}}) (?P<nm>{_ANY_MONTH}) (?P<ny>\d{{4}}))"
    rf"|(?P<month_year>(?P<ym>{_ANY_MONTH}) (?P<yy>\d{{4}}))"
    rf"|(?P<month>{_ANY_MONTH})"
    rf"|(?P<year>(?:19|20)\d{{2}})"
    rf")(?![0-9A-Za-z])"
)


@dataclass(frozen=True)
class Relative:
    """What a task's words say about time: the phrase, its unit, and how many from now."""

    phrase: str
    unit: str
    offset: int


@dataclass(frozen=True)
class Dated:
    """A fixed date found in a trail, how precise it is, and how it was written."""

    text: str
    when: date
    precision: str
    form: str


def relative_to_today(task: str | None) -> Relative | None:
    """The time a task's words name relative to today, or None when they name none."""
    said = " " + " ".join(re.sub(r"[^0-9a-z]+", " ", (task or "").lower()).split()) + " "
    for phrase, unit, offset in _PHRASES:
        if f" {phrase} " in said:
            return Relative(phrase=phrase, unit=unit, offset=offset)
    return None


def dates_in(text: str | None) -> list[Dated]:
    """Every fixed date written in this text, as a site writes them."""
    found = []
    for match in _DATES.finditer(text or ""):
        dated = _read(match)
        if dated is not None:
            found.append(dated)
    return found


def meant_now(dated: Dated, relative: Relative, today: date) -> str | None:
    """The same date, written the same way, for what the words mean today. None when the
    words do not say enough to place it: "this month" names no day, so a trail that
    picked 15 September cannot be told which day of October to pick."""
    unit = dated.precision if relative.unit == ITS_OWN else relative.unit
    target = _moved(today, unit, relative.offset)
    if unit == WEEK:
        target = target - timedelta(days=target.weekday())
    if _finer(dated.precision, unit):
        # Still right when it falls inside what the words mean: a day picked "this week"
        # is fine for the rest of that week.
        return dated.text if _within(dated.when, target, unit) else None
    return _written(target, dated.form)


def _read(match: re.Match[str]) -> Dated | None:
    text = match.group(0)
    try:
        if match.group("iso_day"):
            when = date(int(match["dy"]), int(match["dm"]), int(match["dd"]))
            return Dated(text, when, DAY, "iso_day")
        if match.group("iso_month"):
            return Dated(text, date(int(match["my"]), int(match["mm"]), 1), MONTH, "iso_month")
        if match.group("day_month"):
            when = date(int(match["ny"]), _number(match["nm"]), int(match["nd"]))
            return Dated(text, when, DAY, _named("day_month", match["nm"]))
        if match.group("month_year"):
            when = date(int(match["yy"]), _number(match["ym"]), 1)
            return Dated(text, when, MONTH, _named("month_year", match["ym"]))
        if match.group("month"):
            return Dated(text, date(2000, _number(text), 1), MONTH, _named("month", text))
        return Dated(text, date(int(text), 1, 1), YEAR, "year")
    except ValueError:
        # Looked like a date and is not one (2026-13). Not a date the trail picked.
        return None


def _number(month: str) -> int:
    return _FULL.get(month) or _SHORT[month]


def _named(form: str, month: str) -> str:
    """The form, and whether the month was written in full or shortened."""
    return f"{form}:{'full' if month in _FULL else 'short'}"


# How precise each unit is, coarsest first.
_PRECISION = [YEAR, MONTH, WEEK, DAY]


def _finer(precision: str, unit: str) -> bool:
    """Is a date of this precision more precise than the words can place? A day named by
    "this week" is: the week does not say which of its days."""
    return _PRECISION.index(precision) > _PRECISION.index(unit)


def _within(day: date, start: date, unit: str) -> bool:
    """Is this day inside the week, month or year that begins at `start`?"""
    if unit == WEEK:
        return start <= day < start + timedelta(weeks=1)
    if unit == MONTH:
        return (day.year, day.month) == (start.year, start.month)
    return day.year == start.year


def _moved(today: date, unit: str, offset: int) -> date:
    if unit == DAY:
        return today + timedelta(days=offset)
    if unit == WEEK:
        return today + timedelta(weeks=offset)
    if unit == MONTH:
        months = today.year * 12 + today.month - 1 + offset
        return date(months // 12, months % 12 + 1, 1)
    return date(today.year + offset, 1, 1)


def _written(when: date, form: str) -> str:
    kind, _, length = form.partition(":")
    month = MONTHS[when.month - 1] if length == "full" else MONTHS[when.month - 1][:3]
    if kind == "iso_day":
        return when.isoformat()
    if kind == "iso_month":
        return f"{when.year:04d}-{when.month:02d}"
    if kind == "day_month":
        return f"{when.day} {month} {when.year}"
    if kind == "month_year":
        return f"{month} {when.year}"
    if kind == "month":
        return month
    return str(when.year)
