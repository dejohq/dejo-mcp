"""The step language: several browser steps in one call, read as data and never run as code.

A learning run used to cost one model turn per action, and every turn re-reads the whole
conversation, about 28k tokens before any tool says a word. On 20 Oct 2026 a Dejo learning
run took 8-12 turns where Playwright MCP took 4-7. Letting the agent send its steps as a short
program, one per line, is how a learning run gets down to three turns:

    click link "Travel"
    click css "article.product_pod h3 a" first
    read css "p.price_color" as price

This module only READS a program. It splits each line like a shell does, checks every word
against a fixed table, and hands back plain data for the runner. Nothing an agent writes is
evaluated: no `eval`, no `exec`, no `ast`, and the one way to run JavaScript is the existing
`js` escape hatch, which must stand alone and is never recorded. So a program can do nothing
that a list of single `dejo_act` calls could not already do, and needs no sandbox.

Every action verb comes from `actions.ACTIONS` and every read from `reads.READS`, so the
registries stay the one list of what Dejo can do. A few verbs are shorter names for the same
entries (`go` for goto, `js` for evaluate), chosen to read like the commands agents already
know from browser CLIs.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field, replace
from typing import Literal

from . import actions, reads, waits
from .snapshot import INTERACTIVE_ROLES

# Limits on one program. Thirty lines is several times the longest task measured on 20 Oct
# (an 8-step government form), and 4,000 characters keeps a program well under any client's
# argument size, while a runaway paste is refused before anything runs.
MAX_LINES = 30
MAX_CHARS = 4000

# A fixed wait longer than this is a mistake, not a strategy: `wait_for` exists for waiting
# on something real, and every second here is paid again on every replay.
MAX_WAIT_SECONDS = 30

# Short verbs for registry entries, so a program reads like the commands agents already
# write for browser CLIs. Every other registry action is also a verb under its own name.
ALIASES = {
    "go": "goto",
    "js": "evaluate",
    "dismiss": "dismiss_when_seen",
    "restart": "restart_trail",
}

# Verbs whose arguments do not follow the plain `VERB [T] [VALUE] [to T]` shape, so each has
# its own reader below. `scroll` takes a target OR a direction, `wait` a target, seconds or a
# `kind:subject`, `tab` a number or `new`, `press` a key first and then maybe a target.
SHAPED_VERBS = frozenset({"press", "scroll", "wait", "tab"})

# Registry actions the help line already shows in their own words, so the plain list after
# it does not repeat them.
DESCRIBED = frozenset(
    {
        "click",
        "fill",
        "select",
        "press",
        "scroll",
        "scroll_to",
        "wait",
        "wait_for",
        "back",
        "switch_tab",
        "new_tab",
    }
)

# Actions that must be the only line of a program. They are never recorded, so mixing them
# into a trail would leave a step that silently does nothing on replay.
ALONE = frozenset({"evaluate", "screenshot"})

# Registry actions that take a value only sometimes.
OPTIONAL_VALUE = frozenset({"new_tab", "screenshot"})

# Words that name how to find an element, besides an ARIA role. They match the locator kinds
# Dejo already stores (`models.Locator`), so a target written by an agent can be kept as it
# was written.
TARGET_KINDS = frozenset({"text", "label", "placeholder", "alt", "title", "testid", "css"})

# Roles an agent may name in a target. The interactive ones come from the snapshot module;
# the rest are the structural roles a view prints and a task can point at (a heading, a
# table cell, a row of results).
ROLES = INTERACTIVE_ROLES | frozenset(
    {
        "alert",
        "alertdialog",
        "article",
        "banner",
        "cell",
        "columnheader",
        "complementary",
        "contentinfo",
        "dialog",
        "form",
        "grid",
        "gridcell",
        "group",
        "heading",
        "list",
        "listitem",
        "main",
        "menu",
        "menubar",
        "navigation",
        "paragraph",
        "progressbar",
        "region",
        "row",
        "rowheader",
        "status",
        "table",
        "tablist",
        "tabpanel",
        "toolbar",
        "tooltip",
        "tree",
    }
)

# Short read kinds, as the design names them, for registry entries with longer names.
READ_ALIASES = {"all": "all_text", "attr": "attribute"}

# A Dejo ref as views print it: `e16` on the main page, `f1e3` inside the first iframe.
REF = re.compile(r"^(?:f\d+)?e\d+$")
GROUP = re.compile(r"^g\d+$")
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

PickKind = Literal["first", "last", "nth", "has"]
LookMode = Literal["page", "words", "from", "group", "all", "raw"]


class ProgramError(ValueError):
    """A program that cannot run as written. Says which line and what to write instead."""

    def __init__(self, line: int, message: str) -> None:
        self.line = line
        self.message = message
        super().__init__(f"line {line}: {message}" if line else message)


@dataclass(frozen=True)
class Pick:
    """Which one of several matches. `nth` counts from 1, as a person would."""

    kind: PickKind
    number: int = 0
    text: str = ""


@dataclass(frozen=True)
class Target:
    """How a line names an element: a ref from the latest view, or a kind and a string."""

    kind: str
    """`ref`, an ARIA role, or one of TARGET_KINDS."""
    value: str
    pick: Pick | None = None


@dataclass(frozen=True)
class Action:
    line: int
    text: str
    action: str
    """The `actions.ACTIONS` entry this line runs."""
    target: Target | None = None
    value: str | None = None
    second: Target | None = None
    risky: bool = False
    """Written with `!`: the agent says this buys, pays, sends, deletes or submits."""
    reason: str = ""


@dataclass(frozen=True)
class Read:
    line: int
    text: str
    kind: str
    """The `reads.READS` entry this line asks."""
    name: str
    target: Target | None = None
    attribute: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class Expect:
    line: int
    text: str
    kind: str
    """A `models.Postcondition` kind. It replaces the one the step before would infer."""
    value: str = ""
    target: Target | None = None
    reason: str = ""


@dataclass(frozen=True)
class Look:
    line: int
    text: str
    mode: LookMode
    argument: str = ""
    reason: str = ""


@dataclass(frozen=True)
class Note:
    line: int
    text: str
    fact: str
    reason: str = ""


Step = Action | Read | Expect | Look | Note


@dataclass(frozen=True)
class Program:
    steps: tuple[Step, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------- the reader


def parse(text: str) -> Program:
    """Read a whole program, or raise ProgramError naming the first line that is wrong.

    Every line is checked before any of them runs, so a typo on line 5 never leaves the
    browser halfway through lines 1-4."""
    if len(text) > MAX_CHARS:
        raise ProgramError(0, f"a program is at most {MAX_CHARS} characters; send it in parts")
    steps: list[Step] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        body, reason = _split_comment(raw, number)
        if not body.strip():
            continue
        steps.append(_parse_line(body.strip(), number, reason))
    if len(steps) > MAX_LINES:
        raise ProgramError(0, f"a program is at most {MAX_LINES} lines; send it in parts")
    if not steps:
        raise ProgramError(0, "the program is empty. " + verbs_help())
    _check_order(steps)
    return Program(tuple(steps))


def verbs_help() -> str:
    """Every verb, on one line, for error messages and the tool description."""
    plain = sorted(set(actions.ACTIONS) - DESCRIBED - set(ALIASES.values()) - ALONE)
    return (
        "Verbs: go URL, click T, fill T TEXT, select T OPTION, press KEY [T], scroll T|down, "
        "wait T|SECONDS, tab N|new [URL], back, " + ", ".join(plain) + "; "
        "read [KIND] [T] as NAME; expect url|text|see|gone|count|value ...; "
        "look [WORDS|from REF|gN|all|raw]; note TEXT; js CODE (alone). "
        'T is a ref like e12, or KIND "string" with KIND a role, text, label, placeholder, '
        'alt, title, testid or css, then optionally first, last, nth N or has "text".'
    )


def _split_comment(raw: str, number: int) -> tuple[str, str]:
    """Split ` # reason` off a line, ignoring a `#` inside quotes.

    shlex can drop comments but not keep them, and the reason is worth keeping: it becomes
    the step's intent, which is what a later repair is shown. A `#` that starts a CSS id is
    inside quotes (`css "#total"`), which is why the quotes are tracked here by hand."""
    quote = ""
    escaped = False
    for at, char in enumerate(raw):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
            continue
        if char == "#" and (at == 0 or raw[at - 1].isspace()):
            return raw[:at], raw[at + 1 :].strip()
    if quote:
        raise ProgramError(number, f"a {quote} quote is never closed")
    return raw, ""


def _parse_line(body: str, number: int, reason: str) -> Step:
    try:
        words = shlex.split(body, posix=True)
    except ValueError as broken:
        raise ProgramError(number, f"cannot split this line: {broken}") from None
    head, rest = words[0], words[1:]
    reader = _Words(rest, number)

    if head == "read":
        step: Step = _read(reader, number, body, reason)
    elif head == "expect":
        step = _expect(reader, number, body, reason)
    elif head == "look":
        step = _look(reader, number, body, reason)
    elif head == "note":
        step = Note(number, body, reader.string("note needs the fact, in quotes"), reason)
    else:
        step = _action(head, reader, number, body, reason)
    reader.done()
    return step


# --------------------------------------------------------------------------- actions


def _action(head: str, reader: _Words, number: int, body: str, reason: str) -> Action:
    risky = head.endswith("!")
    verb = head[:-1] if risky else head
    if verb in SHAPED_VERBS:
        found = _shaped(verb, reader, number, body, reason)
        return replace(found, risky=risky)
    name = ALIASES.get(verb, verb)
    spec = actions.ACTIONS.get(name)
    if spec is None:
        raise ProgramError(number, f"no verb {head!r}. {verbs_help()}")

    target = reader.target() if spec.needs_target else None
    if name == "dismiss_when_seen":
        # Kept against the site as a CSS selector, so the line says so: dismiss css "...".
        reader.keyword("css", 'dismiss needs a CSS selector: dismiss css "#accept-cookies"')
    value: str | None = None
    if spec.value_means:
        if name in OPTIONAL_VALUE:
            value = reader.optional_string()
        else:
            value = reader.string(f"{verb} needs {spec.value_means}")
    second = None
    if spec.needs_second_target:
        reader.keyword("to", f'{verb} needs "to" and a second target, like: drag e4 to e9')
        second = reader.target()

    if name == "goto":
        value = _checked_address(value or "", number)
    return Action(number, body, name, target, value, second, risky, reason)


def _shaped(verb: str, reader: _Words, number: int, body: str, reason: str) -> Action:
    """The verbs whose arguments have their own shape."""
    if verb == "press":
        key = reader.string("press needs a key, like: press Enter, or press Escape e4")
        target = reader.target() if reader.more() else None
        return Action(number, body, "press", target, key, reason=reason)

    if verb == "scroll":
        word = reader.peek()
        if word in ("down", "up", "top", "bottom") or (word or "").isdigit():
            return Action(number, body, "scroll", None, reader.take(), reason=reason)
        return Action(number, body, "scroll_to", reader.target(), reason=reason)

    if verb == "wait":
        word = reader.peek() or ""
        if _is_number(word):
            seconds = float(reader.take())
            if not 0 < seconds <= MAX_WAIT_SECONDS:
                raise ProgramError(
                    number, f"wait at most {MAX_WAIT_SECONDS} seconds; wait for something real"
                )
            return Action(number, body, "wait", None, word, reason=reason)
        if ":" in word and word.split(":", 1)[0] in waits.WAITS:
            try:
                waits.parse(word)
            except ValueError as wrong:
                raise ProgramError(number, str(wrong)) from None
            return Action(number, body, "wait_for", None, reader.take(), reason=reason)
        return Action(number, body, "wait_for", reader.target(), reason=reason)

    # tab N | tab latest | tab main | tab new [URL]
    word = reader.string('tab needs a number, "latest", "main" or "new"')
    if word == "new":
        url = reader.optional_string()
        return Action(
            number,
            body,
            "new_tab",
            None,
            _checked_address(url, number) if url else None,
            reason=reason,
        )
    if word not in ("latest", "main") and not word.isdigit():
        raise ProgramError(number, f'tab takes a number, "latest", "main" or "new", not {word!r}')
    return Action(number, body, "switch_tab", None, word, reason=reason)


def _checked_address(url: str, number: int) -> str:
    """Only web pages: `javascript:`, `file:` and `data:` addresses would let a program do
    what a click never could. A path is allowed and joined to the current page later."""
    if url.startswith("/") or re.match(r"^https?://", url, re.IGNORECASE):
        return url
    raise ProgramError(number, f"go takes an http(s) address or a path like /issues, not {url!r}")


# --------------------------------------------------------------------------- reads


def _read(reader: _Words, number: int, body: str, reason: str) -> Read:
    """`read [KIND] [T] as NAME`. A word that is both a read kind and a target kind (`text`,
    `title`) is read as the kind only when what follows still makes a whole line; otherwise
    it starts the target, so `read text "Total" as t` reads the element whose text is Total."""
    first = reader.peek() or ""
    is_kind = READ_ALIASES.get(first, first) in reads.READS
    starts_target = bool(REF.match(first)) or first in ROLES or first in TARGET_KINDS
    if is_kind:
        attempt = reader.fork()
        try:
            found = _read_with_kind(attempt, number, body, reason)
            reader.adopt(attempt)
            return found
        except ProgramError:
            # Only a word that could also start a target gets a second reading. For any
            # other kind, what went wrong with the kind is the useful message.
            if not starts_target:
                raise
    target = reader.target()
    return Read(number, body, "text", _named(reader, number), target, reason=reason)


def _read_with_kind(reader: _Words, number: int, body: str, reason: str) -> Read:
    word = reader.take() if reader.more() else ""
    kind = READ_ALIASES.get(word, word)
    spec = reads.READS.get(kind)
    if spec is None:
        raise ProgramError(number, f"cannot read {word!r}. Kinds: {_read_kinds()}")
    attribute = None
    if spec.needs_attribute:
        attribute = reader.string("read attr needs the attribute name, like: read attr href e4")
    target = reader.target() if spec.needs_target else None
    return Read(number, body, kind, _named(reader, number), target, attribute, reason)


def _named(reader: _Words, number: int) -> str:
    reader.keyword("as", 'a read ends with "as NAME", like: read e12 as price')
    name = reader.string('a read ends with "as NAME", like: read e12 as price')
    if not NAME.match(name):
        raise ProgramError(number, f"{name!r} is not a name: use letters, digits and _")
    return name


def _read_kinds() -> str:
    return ", ".join(sorted({*reads.READS, *READ_ALIASES}))


# --------------------------------------------------------------------------- expect


def _expect(reader: _Words, number: int, body: str, reason: str) -> Expect:
    """Each form maps to an existing `models.Postcondition` kind, so nothing new is ever
    checked on replay."""
    word = reader.string("expect needs what to check: url, text, see, gone, count or value")
    if word == "url":
        value = reader.string("expect url needs text")
        return Expect(number, body, "url_contains", value, reason=reason)
    if word == "text":
        value = reader.string("expect text needs text")
        return Expect(number, body, "text_present", value, reason=reason)
    if word == "gone":
        if reader.peek() == "text" and reader.more(2) and not reader.more(3):
            reader.take()
            value = reader.string("expect gone text needs text")
            return Expect(number, body, "text_gone", value, reason=reason)
        return Expect(number, body, "element_gone", target=reader.target(), reason=reason)
    if word == "see":
        return Expect(number, body, "element_present", target=reader.target(), reason=reason)
    if word == "count":
        target = reader.target()
        count = reader.string('expect count needs a number: expect count css ".row" 11')
        if not count.isdigit():
            raise ProgramError(number, f"expect count needs a whole number, not {count!r}")
        return Expect(number, body, "count_is", count, target, reason)
    if word == "value":
        target = reader.target()
        return Expect(
            number, body, "value_is", reader.string("expect value needs the value"), target, reason
        )
    raise ProgramError(number, f"cannot expect {word!r}: use url, text, see, gone, count or value")


# --------------------------------------------------------------------------- look


def _look(reader: _Words, number: int, body: str, reason: str) -> Look:
    if not reader.more():
        return Look(number, body, "page", reason=reason)
    word = reader.peek() or ""
    if word == "from":
        reader.take()
        return Look(number, body, "from", _ref(reader, number), reason)
    if word == "all" and not reader.more(2):
        reader.take()
        return Look(number, body, "all", reason=reason)
    if word == "raw":
        reader.take()
        if reader.more():
            reader.keyword("from", "look raw takes nothing, or: look raw from e40")
            return Look(number, body, "raw", _ref(reader, number), reason)
        return Look(number, body, "raw", reason=reason)
    if GROUP.match(word) and not reader.more(2):
        return Look(number, body, "group", reader.take(), reason)
    return Look(number, body, "words", " ".join(reader.rest()), reason)


def _ref(reader: _Words, number: int) -> str:
    ref = reader.string("this needs a ref from the view, like e40")
    if not REF.match(ref):
        raise ProgramError(number, f"{ref!r} is not a ref; refs look like e40 or f1e3")
    return ref


# --------------------------------------------------------------------------- order


def _check_order(steps: list[Step]) -> None:
    """Rules about where lines may go, checked before anything runs."""
    for at, step in enumerate(steps):
        if isinstance(step, Action) and step.action in ALONE and len(steps) > 1:
            verb = "js" if step.action == "evaluate" else step.action
            raise ProgramError(step.line, f"{verb} must be the only line of a program")
        if isinstance(step, Look) and at != len(steps) - 1:
            raise ProgramError(step.line, "look ends a program, so it must be the last line")
        if isinstance(step, Expect):
            before = steps[at - 1] if at else None
            if not isinstance(before, Action):
                raise ProgramError(step.line, "expect checks the action on the line just before it")
    _check_after_risky(steps)


def _check_after_risky(steps: list[Step]) -> None:
    """After a `!` line only checks and reads may follow. A program that pays and then keeps
    clicking could pay twice on a retry, or act on a page nobody has looked at."""
    risky = next((step for step in steps if isinstance(step, Action) and step.risky), None)
    if risky is None:
        return
    for step in steps[steps.index(risky) + 1 :]:
        if isinstance(step, Action | Note):
            raise ProgramError(
                step.line,
                f"line {risky.line} is marked ! so only expect, read and look may follow it; "
                "send the rest in the next call, after you have seen what it did",
            )


# --------------------------------------------------------------------------- words


def _is_number(word: str) -> bool:
    return bool(re.match(r"^\d+(\.\d+)?$", word))


class _Words:
    """The words of one line, read left to right, with errors that name the line."""

    def __init__(self, words: list[str], number: int, at: int = 0) -> None:
        self._words = words
        self._number = number
        self._at = at

    def fork(self) -> _Words:
        return _Words(self._words, self._number, self._at)

    def adopt(self, other: _Words) -> None:
        self._at = other._at

    def more(self, count: int = 1) -> bool:
        return len(self._words) - self._at >= count

    def peek(self) -> str | None:
        return self._words[self._at] if self.more() else None

    def take(self) -> str:
        word = self._words[self._at]
        self._at += 1
        return word

    def rest(self) -> list[str]:
        words, self._at = self._words[self._at :], len(self._words)
        return words

    def string(self, missing: str) -> str:
        if not self.more():
            raise ProgramError(self._number, missing)
        return self.take()

    def optional_string(self) -> str | None:
        return self.take() if self.more() else None

    def keyword(self, word: str, missing: str) -> None:
        if self.peek() != word:
            raise ProgramError(self._number, missing)
        self.take()

    def done(self) -> None:
        if self.more():
            raise ProgramError(
                self._number, f"did not expect {' '.join(self._words[self._at :])!r} here"
            )

    def target(self) -> Target:
        """`e12`, or `KIND "string"`, then optionally a pick."""
        if self.peek() in ("as", "to"):
            raise ProgramError(
                self._number,
                f'a target is missing before "{self.peek()}": a ref like e12, or KIND "string"',
            )
        word = self.string('this needs a target: a ref like e12, or KIND "string"')
        if REF.match(word):
            return Target("ref", word, self._pick())
        if word in ROLES and self.peek() == "has":
            # `row has "Lagos"`: the row that contains Lagos, whatever the row is called.
            # Only `has` may come straight after a role. The quotes are gone by now, so
            # `link first` and `link "first"` look the same, and a link may be named first.
            return Target(word, "", self._pick())
        if word in ROLES or word in TARGET_KINDS:
            value = self.string(f'{word} needs a string after it, like: {word} "Sign in"')
            return Target(word, value, self._pick())
        raise ProgramError(
            self._number,
            f"{word!r} is not a target. Use a ref like e12, or a role, text, label, "
            "placeholder, alt, title, testid or css followed by a quoted string",
        )

    def _pick(self) -> Pick | None:
        word = self.peek()
        if word in ("first", "last"):
            self.take()
            return Pick(word)  # type: ignore[arg-type]
        if word == "nth":
            self.take()
            count = self.string("nth needs a number counted from 1, like: nth 3")
            if not count.isdigit() or int(count) < 1:
                raise ProgramError(self._number, f"nth counts from 1, so {count!r} cannot be one")
            return Pick("nth", number=int(count))
        if word == "has":
            self.take()
            return Pick("has", text=self.string('has needs text, like: has "Lagos"'))
        return None
