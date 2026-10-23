"""The step language: every line an agent may write, read as data, never run as code.

No browser here. A program is checked whole before the first line runs, so everything a
program can get wrong has to show up as a ProgramError from text alone.
"""

from __future__ import annotations

import ast
import contextlib
import random
from pathlib import Path

import pytest

from dejo import actions, program, reads
from dejo.program import Action, Expect, Look, Note, Pick, ProgramError, Read, Target


def only(text: str):
    """The single step of a one-line program."""
    (step,) = program.parse(text).steps
    return step


# ------------------------------------------------------------ the 20 Oct tasks, as programs


def test_the_books_task_reads_as_three_steps() -> None:
    steps = program.parse(
        'click link "Travel"\n'
        'click css "article.product_pod h3 a" first   # the first book, by place\n'
        'read css "p.price_color" as price\n'
    ).steps
    assert steps[0] == Action(1, 'click link "Travel"', "click", Target("link", "Travel"))
    assert steps[1].target == Target("css", "article.product_pod h3 a", Pick("first"))
    assert steps[1].reason == "the first book, by place"
    assert steps[2] == Read(
        3, 'read css "p.price_color" as price', "text", "price", Target("css", "p.price_color")
    )


def test_blank_lines_are_ignored() -> None:
    assert len(program.parse("\n\nclick e1\n\n   \nclick e2\n").steps) == 2


# ----------------------------------------------------------------------- targets


@pytest.mark.parametrize(
    ("written", "target"),
    [
        ("e12", Target("ref", "e12")),
        ("f1e3", Target("ref", "f1e3")),
        ('link "Sign in"', Target("link", "Sign in")),
        ('button "Pay"', Target("button", "Pay")),
        ('heading "Travel"', Target("heading", "Travel")),
        ('text "In stock"', Target("text", "In stock")),
        ('label "Email"', Target("label", "Email")),
        ('placeholder "Search"', Target("placeholder", "Search")),
        ('alt "Logo"', Target("alt", "Logo")),
        ('title "Close"', Target("title", "Close")),
        ('testid "submit"', Target("testid", "submit")),
        ('css "#total"', Target("css", "#total")),
        ("e12 first", Target("ref", "e12", Pick("first"))),
        ('link "Edit" last', Target("link", "Edit", Pick("last"))),
        ('link "Edit" nth 3', Target("link", "Edit", Pick("nth", number=3))),
        ('row has "Lagos"', Target("row", "", Pick("has", text="Lagos"))),
        ('link "Edit" has "Lagos"', Target("link", "Edit", Pick("has", text="Lagos"))),
    ],
)
def test_every_kind_of_target(written: str, target: Target) -> None:
    assert only(f"click {written}").target == target


@pytest.mark.parametrize(
    ("line", "says"),
    [
        ("click", "needs a target"),
        ("click link", 'needs a string after it, like: link "Sign in"'),
        ('click banana "x"', "is not a target"),
        ('click link "a" nth 0', "nth counts from 1"),
        ('click link "a" nth', "nth needs a number"),
        ("click row has", "has needs text"),
    ],
)
def test_a_bad_target_says_what_to_write(line: str, says: str) -> None:
    with pytest.raises(ProgramError, match=says):
        program.parse(line)


# ----------------------------------------------------------------------- verbs


def _sample(name: str, spec: actions.ActionSpec) -> str:
    """The shortest correct line for one registry action."""
    special = {
        "goto": "go https://example.com/",
        "evaluate": 'js "() => document.title"',
        "dismiss_when_seen": 'dismiss css "#cookies"',
        "restart_trail": "restart",
        "press": "press Enter",
        "scroll": "scroll down",
        "scroll_to": "scroll e4",
        "wait": "wait 2",
        "wait_for": "wait element:#total",
        "switch_tab": "tab latest",
        "new_tab": "tab new https://example.com/",
    }
    if name in special:
        return special[name]
    line = name + (" e4" if spec.needs_target else "")
    if spec.value_means and name not in program.OPTIONAL_VALUE:
        line += ' "x"'
    if spec.needs_second_target:
        line += " to e9"
    return line


@pytest.mark.parametrize("name", sorted(actions.ACTIONS))
def test_every_registry_action_has_a_verb(name: str) -> None:
    """The registry is the one list of what Dejo can do. A new action that the language
    cannot write would be invisible to every agent using programs."""
    step = only(_sample(name, actions.ACTIONS[name]))
    assert isinstance(step, Action)
    assert step.action == name


@pytest.mark.parametrize(
    ("line", "action", "value", "target"),
    [
        ("go /issues", "goto", "/issues", None),
        ("press Enter e4", "press", "Enter", Target("ref", "e4")),
        ("press Escape", "press", "Escape", None),
        ("scroll bottom", "scroll", "bottom", None),
        ("scroll 400", "scroll", "400", None),
        ('wait css "#x"', "wait_for", None, Target("css", "#x")),
        ("wait 0.5", "wait", "0.5", None),
        ("tab 2", "switch_tab", "2", None),
        ("tab main", "switch_tab", "main", None),
        ("tab new", "new_tab", None, None),
        ('select e3 "label:September"', "select", "label:September", Target("ref", "e3")),
        ('fill e3 "say \\"hi\\""', "fill", 'say "hi"', Target("ref", "e3")),
        ("fill e3 'it''s'", "fill", "its", Target("ref", "e3")),
    ],
)
def test_shaped_verbs(line: str, action: str, value: str | None, target: Target | None) -> None:
    step = only(line)
    assert (step.action, step.value, step.target) == (action, value, target)


def test_drag_names_both_ends() -> None:
    step = only("drag e4 to e9")
    assert (step.target, step.second) == (Target("ref", "e4"), Target("ref", "e9"))


@pytest.mark.parametrize(
    ("line", "says"),
    [
        ("frobnicate e1", "no verb 'frobnicate'"),
        ("go javascript:alert(1)", "http"),
        ("go file:///etc/passwd", "http"),
        ("go data:text/html,hi", "http"),
        ("wait 99", "at most 30 seconds"),
        ("wait 0", "at most 30 seconds"),
        ("tab sideways", "tab takes a number"),
        ('dismiss "#x"', "dismiss needs a CSS selector"),
        ("fill e3", "fill needs the text to put in"),
        ("click e1 extra", "did not expect 'extra'"),
        ("drag e4 e9", '"to"'),
        ('click "unclosed', "never closed"),
    ],
)
def test_a_bad_action_says_what_to_write(line: str, says: str) -> None:
    with pytest.raises(ProgramError, match=says):
        program.parse(line)


def test_the_error_names_the_line() -> None:
    with pytest.raises(ProgramError) as raised:
        program.parse("click e1\nclick e2\nfrobnicate e3")
    assert raised.value.line == 3
    assert str(raised.value).startswith("line 3: ")


def test_an_unknown_verb_lists_the_verbs() -> None:
    with pytest.raises(ProgramError, match="Verbs: go URL, click T"):
        program.parse("open e1")


# ----------------------------------------------------------------------- reads


@pytest.mark.parametrize("name", sorted(reads.READS))
def test_every_registry_read_can_be_written(name: str) -> None:
    spec = reads.READS[name]
    line = "read " + name
    if spec.needs_attribute:
        line += " href"
    if spec.needs_target:
        line += " e4"
    step = only(line + " as answer")
    assert isinstance(step, Read)
    assert (step.kind, step.name) == (name, "answer")


@pytest.mark.parametrize(
    ("line", "kind", "target", "attribute"),
    [
        ("read e12 as price", "text", Target("ref", "e12"), None),
        ('read text "Total" as total', "text", Target("text", "Total"), None),
        ("read text e12 as total", "text", Target("ref", "e12"), None),
        ('read count css ".row" as rows', "count", Target("css", ".row"), None),
        ('read all css "td" as cells', "all_text", Target("css", "td"), None),
        ("read attr href e5 as link", "attribute", Target("ref", "e5"), "href"),
        ("read url as address", "url", None, None),
        ("read title as page", "title", None, None),
        ('read title "Close" as tip', "text", Target("title", "Close"), None),
        ("read value e7 as typed", "value", Target("ref", "e7"), None),
    ],
)
def test_read_shapes(line: str, kind: str, target: Target | None, attribute: str | None) -> None:
    step = only(line)
    assert (step.kind, step.target, step.attribute) == (kind, target, attribute)


@pytest.mark.parametrize(
    ("line", "says"),
    [
        ("read e1", 'ends with "as NAME"'),
        ("read e1 as", 'ends with "as NAME"'),
        ("read e1 as 9lives", "is not a name"),
        ("read count as n", 'a target is missing before "as"'),
    ],
)
def test_a_bad_read_says_what_to_write(line: str, says: str) -> None:
    with pytest.raises(ProgramError, match=says):
        program.parse(line)


# ----------------------------------------------------------------------- expect


@pytest.mark.parametrize(
    ("line", "kind", "value", "target"),
    [
        ('expect url "travel"', "url_contains", "travel", None),
        ('expect text "In stock"', "text_present", "In stock", None),
        ('expect gone text "Loading"', "text_gone", "Loading", None),
        ("expect see e4", "element_present", "", Target("ref", "e4")),
        ("expect gone e4", "element_gone", "", Target("ref", "e4")),
        ('expect gone text "Loading" first', "element_gone", "", None),
        ('expect count css ".row" 11', "count_is", "11", Target("css", ".row")),
        ('expect value e4 "a@b.c"', "value_is", "a@b.c", Target("ref", "e4")),
    ],
)
def test_expect_maps_to_an_existing_postcondition(
    line: str, kind: str, value: str, target: Target | None
) -> None:
    """Every kind is one `models.Postcondition` already checks, so replay learns nothing new."""
    step = program.parse(f"click e1\n{line}  # why").steps[1]
    assert isinstance(step, Expect)
    assert (step.kind, step.value) == (kind, value)
    if target is not None:
        assert step.target == target
    assert step.reason == "why"


@pytest.mark.parametrize(
    "line",
    ["expect sees e4", 'expect count css ".row" many', "expect"],
)
def test_a_bad_expect_is_refused(line: str) -> None:
    with pytest.raises(ProgramError):
        program.parse(f"click e1\n{line}")


# ----------------------------------------------------------------------- look and note


@pytest.mark.parametrize(
    ("line", "mode", "argument"),
    [
        ("look", "page", ""),
        ("look price stock", "words", "price stock"),
        ("look from e758", "from", "e758"),
        ("look g2", "group", "g2"),
        ("look all", "all", ""),
        ("look all prices", "words", "all prices"),
        ("look raw", "raw", ""),
        ("look raw from e9", "raw", "e9"),
    ],
)
def test_look_shapes(line: str, mode: str, argument: str) -> None:
    assert only(line) == Look(1, line, mode, argument)


def test_look_from_needs_a_ref() -> None:
    with pytest.raises(ProgramError, match="is not a ref"):
        program.parse("look from price")


def test_a_note_is_a_fact() -> None:
    assert only('note "the export takes two minutes"') == Note(
        1, 'note "the export takes two minutes"', "the export takes two minutes"
    )


# ----------------------------------------------------------------------- comments


def test_a_hash_inside_quotes_is_not_a_comment() -> None:
    step = only('click css "#submit" # the #1 button')
    assert step.target == Target("css", "#submit")
    assert step.reason == "the #1 button"


def test_a_hash_glued_to_a_word_is_not_a_comment() -> None:
    assert only("go https://example.com/page#top").value == "https://example.com/page#top"


def test_a_whole_line_comment_is_skipped() -> None:
    assert len(program.parse("# open the first book\nclick e1").steps) == 1


# ----------------------------------------------------------------------- order rules


@pytest.mark.parametrize(
    ("text", "says"),
    [
        ('js "1"\nclick e1', "js must be the only line"),
        ("screenshot\nclick e1", "screenshot must be the only line"),
        ('expect url "x"', "expect checks the action on the line just before it"),
        ('click e1\nread e2 as x\nexpect url "y"', "expect checks the action"),
        ('click e1\nexpect url "a"\nexpect url "b"', "expect checks the action"),
        ("click! e1\nclick e2", "marked ! so only expect, read and look may follow"),
        ('click! e1\nnote "x"', "marked !"),
    ],
)
def test_order_rules(text: str, says: str) -> None:
    with pytest.raises(ProgramError, match=says):
        program.parse(text)


def test_a_look_may_come_before_other_lines() -> None:
    """Agents write "look, then read". Refusing it cost a turn; the runner skips it."""
    assert len(program.parse("look price\nread e2 as price").steps) == 2


def test_after_a_risky_line_checks_and_reads_may_follow() -> None:
    steps = program.parse('click! button "Pay"\nexpect text "Paid"\nread e4 as receipt\nlook').steps
    assert steps[0].risky
    assert [type(step) for step in steps] == [Action, Expect, Read, Look]


def test_a_shaped_verb_can_be_risky() -> None:
    assert only("press! Enter e4").risky


def test_limits() -> None:
    with pytest.raises(ProgramError, match="at most 30 lines"):
        program.parse("click e1\n" * 31)
    with pytest.raises(ProgramError, match="at most 4000 characters"):
        program.parse('click link "' + "x" * 4000 + '"')
    with pytest.raises(ProgramError, match="empty"):
        program.parse("\n  \n# only a comment\n")


# ----------------------------------------------------------------------- safety


def test_random_text_only_ever_raises_program_error() -> None:
    """Whatever an agent sends, the reader answers with a ProgramError or a Program, never
    a crash that would surface as a stack trace."""
    rng = random.Random(20261021)
    vocabulary = [
        *program.ALIASES,
        *actions.ACTIONS,
        "read",
        "expect",
        "look",
        "note",
        "as",
        "to",
        "first",
        "last",
        "nth",
        "has",
        "from",
        "all",
        "raw",
        "e1",
        "f1e2",
        "g3",
        "css",
        "link",
        '"x"',
        "'y'",
        '"',
        "'",
        "#",
        "!",
        "\\",
        "3",
        "-1",
        "url",
        "text",
        "gone",
        "see",
        "count",
        "value",
        "attr",
        "href",
        ":",
        "element:#a",
        "click!",
        "\n",
    ]
    for _ in range(4000):
        text = " ".join(rng.choice(vocabulary) for _ in range(rng.randint(0, 12)))
        with contextlib.suppress(ProgramError):
            program.parse(text)


def test_the_reader_cannot_run_code() -> None:
    """Safe by construction: nothing in the reader can evaluate what an agent wrote."""
    source = Path(program.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not imported & {"ast", "subprocess", "os", "importlib", "pickle", "code"}
    assert not called & {"eval", "exec", "compile", "__import__", "getattr"}


# ------------------------------------------------- what agents actually wrote, 21 Oct


@pytest.mark.parametrize(
    ("line", "says"),
    [
        ("read text as born", 'a target is missing before "as"'),
        ("click first", "first goes AFTER a target"),
        ("click first link", "first goes AFTER a target"),
    ],
)
def test_lines_agents_really_wrote_get_the_right_hint(line: str, says: str) -> None:
    """Each of these was sent by Claude in the 21 Oct benchmark and got a misleading error."""
    with pytest.raises(ProgramError, match=says):
        program.parse(line)
