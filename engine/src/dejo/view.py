"""The page as an agent reads it: one line per element, in page order, inside a budget.

Playwright's own snapshot is the only format that held every target in the 20 Oct lab
(44/44), at 5 to 60 times the size of anything else: 166k tokens for one IANA table. Dejo's
old view was small only because it stopped at 60 controls without saying so, and it missed 9
of 36 click targets. This view keeps the lab's recommended shape (DESIGN-v2 §3): controls and
short text lines with Dejo's refs, look-alike rows folded to their first three, a character
budget with an honest "+N more" note, and the lines that best match the task when something
had to be left out.

Pure and deterministic: the same snapshot and words always give the same text. No browser,
no model. The lines come from `snapshot.lines`, the same reader `parse` uses, so the refs here
are the refs `dejo_act` resolves.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from .snapshot import FIELD_ROLES, INTERACTIVE_ROLES, Node, lines
from .words import COMMON_WORDS

# Characters of element lines in one look. The lab's recommended budget: median 2,099
# tokens, 34 of 36 click targets, against Dejo's old 2,780 and 27 (lab-results.md §3). The
# header, "best for", note and pager lines come on top.
LINE_BUDGET = 6_000

# `look all` has no budget, only this cap. Every reply must stay under 30,000 chars
# (DESIGN §3.5 and the Phase 5 size test); the parts around the lines (header, best block,
# note, pager, the caller's `next:`) stay well under the 3,000 left over.
ALL_BUDGET = 27_000

# Longest text or name printed on a line. Long enough for a book title or a price with its
# label, short enough that one paragraph cannot eat the budget.
TEXT_LIMIT = 120

# Characters of a native select's options printed on its line. Under TEXT_LIMIT so the
# " · +246 more" ending always fits before the line is cut (a country list has 249).
CHOICES_LIMIT = 100

# An element whose text is longer than this is one long text (a plain-text page, an article
# in one block): `look <words>` shows the parts of it that say them, PASSAGE_SIDE characters
# either side of each, at most PASSAGES_SHOWN of them.
LONG_TEXT = 1_000
PASSAGE_SIDE = 120
PASSAGES_SHOWN = 6

# Controls that are often only an icon. With no words, the view says what the icon is, or
# that it has no name (devhunt.org's GitHub and Google sign-in buttons were bare `button`).
ICON_ROLES = frozenset({"button", "link"})

# A run of siblings that repeats word for word is printed once (see `_without_repeats`):
# runs of up to REPEAT_PERIOD siblings, holding at least REPEAT_MIN_LINES lines between them.
# A carousel shows a handful of cards; a single repeated line is a fold's job, not this.
REPEAT_PERIOD = 12
REPEAT_MIN_LINES = 3

# Siblings of the same shape that make a fold. Three is where a run reads as a list.
FOLD_MIN = 3
# Rows a fold shows. The first rows are what "the first X" tasks need; `look gK` shows all.
FOLD_SHOWN = 3
# A sibling with more elements than this is a section, not a row: printed on one line it
# would be a wall. It also keeps any one line far under the budget (30 elements of at most
# ~150 chars each), so a cut never has to split a line.
ROW_MAX_ITEMS = 30

# How many lines the "best for" block holds (the lab's top 15).
BEST_COUNT = 15
# Text limit for a line in the best block. The block is there to point at refs; at the full
# 120 chars, 15 paragraphs made it 1,800 chars on a docs page, past the 1,500 DESIGN §3.3
# allows for everything around the element lines.
BEST_TEXT_LIMIT = 60
# Rarity weight: log((lines + 1) / (lines with the word + 1)) plus this floor, so a word on
# every line still counts a little. The lab's formula (lab-results.md §3, row g2).
IDF_FLOOR = 0.1
# A word in the element's own text counts three times a word in its link target or in the
# heading above it; a control wins a tie with plain text. The lab's measured weights.
OWN_WEIGHT = 3.0
CONTROL_BONUS = 0.5
# A task word shorter than this matches too much to rank anything.
MIN_WORD_LENGTH = 2

# How far up a nameless link looks for a named link with the same target: in a book or
# product card the cover link and the title link share a parent (one level on both lab shops),
# and two levels leave room for one more wrapper without reaching the next card.
ROW_REACH = 2

# Longest `pager:` line. A real pager is a handful of controls; past this, the page has a
# "more" button on every item, and listing them all would only repeat the page.
PAGER_LIMIT = 600

# Roles that are something to act on. A picture is not a control: in the view it only counts
# when the page says it is clickable and it has a name (DESIGN §3.7: 396 of 8,696 lab
# elements were images). `img` stays in `snapshot.INTERACTIVE_ROLES` on purpose: `parse` lists
# named images so an icon can be acted on by ref and given an `alt` locator (docs/BROWSING.md
# §3, and test_locators checks that locator on a plain, unclickable logo).
CONTROL_ROLES = INTERACTIVE_ROLES - {"img"}

# Roles that hold what a person types. With no name of their own, Playwright prints the
# typed text where a name would go (`textbox [ref=e3]: hunter2`), so for these the text after
# the colon is never shown. A nameless `combobox` is different: its text is the label the
# widget shows (`snapshot.parse` names it the same way), never something typed.
_TYPED_ROLES = FIELD_ROLES - {"combobox"}

# States worth a word on a control line. `pressed` is a toggle's on/off, the same kind of
# fact as `checked`, so it is shown too.
STATES = ("checked", "disabled", "expanded", "selected", "pressed")

# Roles that keep their name on the line because the role itself says something: a dialog is
# open, a cell sits in a table. A row is printed as an anchor for reading the whole row
# (the lab's Lagos row was only readable through its cells).
SPECIAL_ROLES = frozenset(
    {"alert", "alertdialog", "dialog", "row", "cell", "gridcell", "columnheader", "rowheader"}
)
# Special roles worth a line even with no words: an open dialog matters by being there.
_ALWAYS_SHOWN = frozenset({"dialog", "alertdialog"})
# A row with no words of its own is printed only when something inside it is (a spacer row
# says nothing).
_ANCHOR_ROLES = frozenset({"row"})

# Roles that run inside a sentence. A ref'd child with one of these roles joins its parent's
# line when the parent has loose text of its own: `generic: strong "11" + text "results."`
# reads `e126: 11 results.`. A paragraph or list item is a line of its own.
_INLINE_ROLES = frozenset(
    {
        "generic",
        "strong",
        "emphasis",
        "code",
        "mark",
        "subscript",
        "superscript",
        "time",
        "deletion",
        "insertion",
    }
)

# Characters that make a name look empty when it is not: a zero-width space was the whole
# name of one search button in the lab.
_INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿"))
# Unicode's "private use" category: icon-font glyphs (books.toscrape's stars and its
# "in stock" tick are U+F00C and friends). They draw a picture and read as nothing.
_PRIVATE_USE = "Co"

# A pager control's name, once arrows and trailing dots are taken off: "Next →", "Show more
# results", "Load more", "Older posts", or nothing but an arrow.
_PAGER = re.compile(
    r"(next|older|more|(load|show|see|view) more)"
    r"( (page|posts|entries|results|items|stories|topics))?"
)
_ARROWS = "›»→>"
# Dots come off the end only: "Next..." is a pager, ".next" is a top-level domain (IANA).
_TRAILING_DOTS = ".…"

_WORD = re.compile(r"[a-z0-9]+")
_HAS_WORD = re.compile(r"\w")


class ViewError(ValueError):
    """The look asked for something this page does not have. The message says what to do."""


@dataclass(frozen=True)
class Item:
    """One element as the agent sees it, kept in pieces so it can be printed at two lengths."""

    ref: str
    role: str
    """What follows the ref: `link`, `h1`, `alert`; "" for plain text (`e147: £45.17`)."""
    kind: str
    """What the element is, for comparing row shapes: a control's role, "heading", "text"..."""
    node: Node
    order: int
    """Position of the element's line in the snapshot: page order."""
    words: str
    """Every word the line stands for, uncut, for ranking against a task."""
    control: bool = False
    name: str = ""
    """Printed in quotes after the role."""
    tail: str = ""
    """Printed after the name: states (` [checked] [filled]`) or an iframe's ` (f1)`."""
    said: str = ""
    """Printed after a colon: the element's text."""
    bare: bool = False
    """A row with no words of its own: an anchor, printed bare in its fold (its cells follow
    it there) and with its row's words away from it. Kept only when something under it
    shows."""

    @property
    def line(self) -> str:
        """The element's line: `e145 link "It's Only the Himalayas"`, `e147: £45.17`."""
        return self.render(TEXT_LIMIT)

    @property
    def short(self) -> str:
        """In a one-line fold of single controls the fold names the role once."""
        return self.render(TEXT_LIMIT, with_role=not self.control)

    @property
    def brief(self) -> str:
        """The line in the best block: shorter text, and an anchor shows its row's words."""
        return self.render(BEST_TEXT_LIMIT, alone=True)

    def render(self, limit: int, *, with_role: bool = True, alone: bool = False) -> str:
        role = self.role if with_role or not self.ref else ""
        head = " ".join(part for part in (self.ref, role) if part)
        named = f" {_quoted(self.name, limit)}" if self.name else ""
        said = self.said if alone or not self.bare else ""
        line = f"{head}{named}{self.tail}" + (f": {_cut_text(said, limit)}" if said else "")
        return line.lstrip()


@dataclass(frozen=True)
class Group:
    """Three or more look-alike siblings, one row each."""

    id: str
    noun: str
    rows: tuple[tuple[Item, ...], ...]

    @property
    def singles(self) -> bool:
        """Every row is one element, so the fold reads as a single line."""
        return all(len(row) == 1 for row in self.rows)


@dataclass(frozen=True)
class Target:
    """What a printed ref points at: enough to act on it or read it again."""

    ref: str
    node: Node
    frame: str | None
    """CSS selector of the iframe the element sits in, when the caller gave one."""

    @property
    def aria_ref(self) -> str:
        """Playwright's ref for the node, the one `aria-ref=` resolves."""
        return self.node.aria_ref


@dataclass(frozen=True)
class View:
    """One look: the text, and what every ref in it points at."""

    text: str
    """Header, best block, element lines, note and pager. The caller adds `next:`."""
    targets: dict[str, Target]
    """Every ref printed anywhere in `text`."""
    groups: dict[str, Group]
    """Every fold on the page, all rows, whether shown or not."""
    hidden_lines: int
    """Element lines left out by the budget (0 when everything fitted)."""
    known: dict[str, Target] = field(default_factory=dict)
    """Every ref on the page, printed or not: rows folded away, lines past the budget, and
    the refs `look raw` shows. A ref the page has is a ref an agent may use (agenticskills.io:
    a folded row's ref was refused while the page plainly had it)."""


@dataclass
class _Branch:
    """A snapshot line with its place in the tree."""

    node: Node
    order: int
    children: list[_Branch] = field(default_factory=list)
    parent: _Branch | None = None
    blocky: bool = False
    """This line or one under it has a line of its own whatever its parent is: a control,
    a heading, an iframe or a special role. Such a subtree never melts into a sentence."""


@dataclass(frozen=True)
class _Line:
    text: str
    items: tuple[Item, ...] = ()


@dataclass(frozen=True)
class _Fold:
    rows: tuple[tuple[Item, ...], ...]


@dataclass(frozen=True)
class _Repeat:
    """Siblings that say exactly what the ones before them said, left out (see REPEAT_*)."""

    order: int
    lines: int
    times: int

    @property
    def text(self) -> str:
        return (
            f"(the {self.lines} lines above appear {self.times} more times, word for word; "
            "their refs work too)"
        )


_Block = Item | Group | _Repeat
_Draft = Item | _Fold | _Repeat


def render(
    snapshot: str,
    *,
    url: str,
    title: str,
    focus: str = "",
    frames: Mapping[str, str] | None = None,
    start: str = "",
    group: str = "",
    everything: bool = False,
    budget: int = LINE_BUDGET,
    find: str = "",
    icons: Mapping[str, str] | None = None,
) -> View:
    """Turn Playwright's ai snapshot into the view an agent reads.

    `focus` is every word that says what the agent is after (the task, a failed line, the
    words of `look <words>`). `frames` maps an iframe's Playwright ref to a CSS selector for
    it, as in `snapshot.parse`. At most one of the paging inputs may be given: `start` (a
    ref: the next slice from there), `group` (`g2`: every row of that fold) or `everything`
    (no budget, only the 30,000-char reply cap). `icons` names the icons of nameless
    controls, by Playwright ref (`Browser.icon_names`, asked about `nameless_controls`).
    `find` is the words of `look <words>`:
    where one element holds a long text, the passages of it that say them are shown too.
    """
    if sum((bool(start), bool(group), everything)) > 1:
        raise ViewError("Ask for one of: from <ref>, a group, or all, not several at once.")
    page = _Page(snapshot, url, icons or {})
    if group:
        sequence, limit = page.group_lines(group.strip()), budget
    elif start:
        sequence, limit = page.lines_from(start.strip()), budget
    elif everything:
        sequence, limit = page.sequence(expand=True), ALL_BUDGET
    else:
        sequence, limit = page.sequence(expand=False), budget
    shown, rest = _cut(sequence, limit)
    view = _assemble(page, shown, rest, focus_words(focus), title, frames or {})
    found = _passages(page, focus_words(find))
    if not found:
        return view
    lines = view.text.split("\n")
    text = "\n".join([lines[0], *found, *lines[1:]])
    return View(text, view.targets, view.groups, view.hidden_lines, view.known)


def nameless_controls(snapshot: str) -> list[str]:
    """Playwright refs of the buttons and links with no name: icons mostly, whose names
    `Browser.icon_names` can look for in the page."""
    return [
        branch.node.aria_ref
        for branch in _walk(_tree(lines(snapshot)))
        if branch.node.ref
        and branch.node.role in ICON_ROLES
        and not branch.node.name
        and not _clean(branch.node.trailing or _words(branch))
    ]


def focus_words(text: str) -> list[str]:
    """The words worth ranking lines by: everything but the common words, CSS names split.

    `price_color` becomes price and color, `author-born-date` author, born and date, because
    agents write class names into their steps and the page shows the words."""
    found: list[str] = []
    for word in _WORD.findall(text.lower()):
        if word in COMMON_WORDS or len(word) < MIN_WORD_LENGTH or word in found:
            continue
        found.append(word)
    return found


class _Page:
    """The snapshot read once: its tree, every printable element, and the folds."""

    def __init__(self, snapshot: str, url: str, icons: Mapping[str, str]):
        self.url = url
        self.icons = icons
        self.root = _tree(lines(snapshot))
        self.frame_number = _iframe_numbers(self.root)
        self.order_of = {b.node.ref: b.order for b in _walk(self.root) if b.node.ref}
        _mark_blocky(self.root)
        self.blocks = _name_groups(self._blocks(self.root, absorb=False))
        self.groups = {block.id: block for block in self.blocks if isinstance(block, Group)}
        self.items = sorted(_flatten(self.blocks), key=lambda item: item.order)

    # ---------------------------------------------------------------- what each line is

    def _blocks(self, branch: _Branch, *, absorb: bool) -> list[_Draft]:
        if self._dropped(branch):
            return []
        item, melted, inner = self._item(branch, absorb)
        kids = [kid for index, kid in enumerate(branch.children) if index not in melted]
        drafts = _fold(kids, [self._blocks(kid, absorb=inner) for kid in kids], self.url)
        if item is None or (item.bare and not drafts):
            return drafts
        return [item, *drafts]

    def _dropped(self, branch: _Branch) -> bool:
        """A picture nobody can click, or a second, nameless link to a card's own target."""
        node = branch.node
        if node.role == "img" and not _is_control(node):
            return True
        return node.role == "link" and not node.name and self._has_named_twin(branch)

    def _has_named_twin(self, branch: _Branch) -> bool:
        """Is there a named link to the same place in the same card?

        A book or product card links its cover image and its title to the same page. The
        cover link has no name of its own, so it only repeats the title line."""
        if not branch.node.href:
            return False
        scope = branch
        for _ in range(ROW_REACH):
            if scope.parent is None:
                break
            scope = scope.parent
        return any(
            other is not branch
            and other.node.role == "link"
            and other.node.name
            and other.node.href == branch.node.href
            for other in _walk(scope)
        )

    def _item(self, branch: _Branch, absorb: bool) -> tuple[Item | None, set[int], bool]:
        """The line for one branch, which children melted into it, and whether the words
        under it belong to it (inside a control or heading they are its name)."""
        node = branch.node
        if not node.ref:
            if _disabled_control(node):
                return self._control(branch), set(), True
            return None, set(), absorb
        if _is_control(node):
            return self._control(branch), set(), True
        if absorb:
            return None, set(), True
        if node.role == "heading":
            return self._heading(branch), set(), True
        if node.role == "iframe":
            return self._iframe(branch), set(), False
        text, melted = self._own_text(branch)
        return self._text(branch, text), melted, False

    def _control(self, branch: _Branch) -> Item:
        node = branch.node
        # A field's text after the colon is what it holds, unless it is a nameless widget
        # whose text is its label (see _TYPED_ROLES). What it holds is never printed.
        holds_input = node.role in _TYPED_ROLES or (node.role in FIELD_ROLES and node.name)
        if holds_input:
            label, filled = node.name, bool(node.trailing)
        else:
            label, filled = node.name or node.trailing or self._words_under(branch), False
        label = _clean(label)
        states = [f"[{flag}]" for flag in node.flags.split() if flag.split("=")[0] in STATES]
        if not label and node.role in ICON_ROLES:
            # A state, not a name: `button "github"` would find nothing, the ref does.
            states.append(f"[{self.icons.get(node.aria_ref) or 'icon, no name'}]")
        if filled:
            states.append("[filled]")
        choices = _choices(branch)
        chosen = next((name for name, picked in choices if picked), "")
        if chosen:
            states.append(f"[chosen {_quoted(chosen)}]")
        return Item(
            ref=node.ref,
            role=node.role,
            kind=node.role,
            node=node,
            order=branch.order,
            # Every option, uncut: "look India" must find the country select.
            words=" ".join([label, *(name for name, _ in choices)]),
            control=True,
            name=label,
            tail="".join(f" {state}" for state in states),
            said=_choice_line([name for name, _ in choices]),
        )

    def _heading(self, branch: _Branch) -> Item | None:
        node = branch.node
        label = _clean(node.name or node.trailing or self._words_under(branch))
        if not label:
            return None
        level = next(
            (flag.split("=")[1] for flag in node.flags.split() if flag.startswith("level=")), ""
        )
        role = f"h{level}" if level else "heading"
        return Item(node.ref, role, "heading", node, branch.order, label, name=label)

    def _iframe(self, branch: _Branch) -> Item:
        node = branch.node
        name = _clean(node.name)
        tail = f" (f{self.frame_number[node.aria_ref]})"
        return Item(node.ref, "iframe", "iframe", node, branch.order, name, name=name, tail=tail)

    def _text(self, branch: _Branch, text: str) -> Item | None:
        node = branch.node
        name = _clean(node.name)
        if node.role in SPECIAL_ROLES:
            if not (name or text or node.role in _ALWAYS_SHOWN or node.role in _ANCHOR_ROLES):
                return None
            role, kind = node.role, node.role
        elif name:
            role, kind = node.role, "text"
        elif text and _HAS_WORD.search(text):
            # Separators like "/" or "|" have nothing to read or act on.
            role, kind = "", "text"
        else:
            return None
        bare = node.role in _ANCHOR_ROLES and not (name or text)
        if bare:
            # An anchor stands for its whole row, so the row's words are what it matches: the
            # lab's "Lagos row" was found only through its cells, never as a row.
            text = _clean(_words(branch))
        words = f"{name} {text}".strip()
        return Item(
            node.ref, role, kind, node, branch.order, words, name=name, said=text, bare=bare
        )

    def _own_text(self, branch: _Branch) -> tuple[str, set[int]]:
        """The element's own words, and the children that melted into them.

        A child joins the line when the element has loose text of its own (a `text:` child
        or text after its colon) and the child is only words: Playwright splits one sentence
        into pieces at every `<strong>` or `<code>`, and printed apart the pieces mean
        nothing. Without loose text, every child keeps its own line and ref."""
        node = branch.node
        loose = bool(node.trailing) or any(
            not kid.node.ref and not kid.blocky and _words(kid) for kid in branch.children
        )
        if not loose:
            return "", set()
        parts = [node.trailing] if node.trailing else []
        melted: set[int] = set()
        for index, kid in enumerate(branch.children):
            if kid.blocky or (kid.node.ref and not _inline_only(kid)):
                continue
            parts.append(_words(kid))
            melted.add(index)
        return _clean(" ".join(parts)), melted

    def _words_under(self, branch: _Branch) -> str:
        """What a nameless control or heading shows: the words under it, minus any control
        inside it, which has a line of its own."""
        return " ".join(_words(kid) for kid in branch.children if not _is_control(kid.node))

    # ------------------------------------------------------------------ line sequences

    def sequence(self, *, expand: bool) -> list[_Line]:
        """The page in order. Folded: every fold shows its first rows. Expanded: all rows."""
        return _block_lines(self.blocks, expand=expand)

    def group_lines(self, group_id: str) -> list[_Line]:
        found = self.groups.get(group_id)
        if found is None:
            known = ", ".join(self.groups)
            hint = f"the groups here are {known}" if known else "this page has no folded groups"
            raise ViewError(f"{group_id} is not a group on this page; {hint}.")
        return _expanded(found, 0)

    def lines_from(self, ref: str) -> list[_Line]:
        """The page from the line holding `ref` on. A ref inside a fold opens that fold from
        its row. A ref with no line of its own (its words melted into a line above, or it was
        a dropped picture) starts at the last line at or before it in page order."""
        order = self.order_of.get(ref)
        if order is None:
            raise ViewError(
                f"{ref} is not on this page. Refs last until the page changes: "
                "look again to get fresh ones."
            )
        place, row = 0, 0
        for index, block in enumerate(self.blocks):
            if _first_order(block) > order:
                break
            place, row = index, 0
            if isinstance(block, Group):
                row = max(i for i, cells in enumerate(block.rows) if cells[0].order <= order)
        block = self.blocks[place] if self.blocks else None
        if isinstance(block, Group):
            return _expanded(block, row) + _block_lines(self.blocks[place + 1 :], expand=False)
        return _block_lines(self.blocks[place:], expand=False)


# ------------------------------------------------------------------------- the tree


def _tree(every: Sequence[Node]) -> _Branch:
    """Hang every line under the nearest line above it with a smaller indent."""
    root = _Branch(Node("", "root", "", "", "", "", 0, depth=-1), -1)
    open_ = [root]
    for order, node in enumerate(every):
        while len(open_) > 1 and open_[-1].node.depth >= node.depth:
            open_.pop()
        branch = _Branch(node, order, parent=open_[-1])
        open_[-1].children.append(branch)
        open_.append(branch)
    return root


def _walk(branch: _Branch) -> Iterator[_Branch]:
    """Every branch under `branch`, itself first, in page order. Iterative: real pages nest
    deeper than is comfortable for recursion inside a generator."""
    stack = [branch]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def _choices(branch: _Branch) -> list[tuple[str, bool]]:
    """A native `<select>`'s options, each with whether it is the one chosen.

    Playwright gives them no ref, and a line without a ref is never printed, so before this
    the choices of every plain dropdown were missing from the view (mcpservers.org's
    "Category"). A custom listbox's options have refs and lines of their own."""
    if branch.node.role != "combobox":
        return []
    return [
        (_clean(kid.node.name), "selected" in kid.node.flags.split())
        for kid in _walk(branch)
        if kid.node.role == "option" and not kid.node.ref and _clean(kid.node.name)
    ]


def _choice_line(names: Sequence[str]) -> str:
    """`options A · B · C`, cut to CHOICES_LIMIT with how many were left out."""
    if not names:
        return ""
    shown = [names[0]]
    for name in names[1:]:
        if len(" · ".join([*shown, name])) > CHOICES_LIMIT:
            return f"options {' · '.join(shown)} · +{len(names) - len(shown)} more"
        shown.append(name)
    return f"options {' · '.join(shown)}"


def _iframe_numbers(root: _Branch) -> dict[str, int]:
    """Number the iframes in document order from 1, as `snapshot.lines` does for the refs
    inside them, so `iframe (f1)` names the prefix its elements carry."""
    found = [b.node.aria_ref for b in _walk(root) if b.node.role == "iframe" and b.node.aria_ref]
    return {ref: number for number, ref in enumerate(found, start=1)}


def _is_control(node: Node) -> bool:
    """Something to act on: a control role, or a named element the page says is clickable
    (the `div` acting as a button). The same rule as `snapshot.parse`, minus pictures."""
    if not node.ref:
        return False
    if node.role in CONTROL_ROLES:
        return True
    return "cursor=pointer" in node.flags and bool(node.name or node.trailing)


def _disabled_control(node: Node) -> bool:
    """A control Playwright gave no ref because it cannot be clicked now, and says why.

    A button that is disabled with pointer events turned off (how shadcn styles every
    disabled button) has no ref, and every line without one used to be left out: after
    `click! Submit` on mcpserver.dev the button was simply gone from the view, and the agent
    could not tell "busy" from "gone". It is printed, with no ref to act on."""
    return node.role in CONTROL_ROLES and bool(node.name) and "disabled" in node.flags.split()


def _mark_blocky(root: _Branch) -> None:
    for branch in reversed(list(_walk(root))):
        node = branch.node
        own = _disabled_control(node) or (
            bool(node.ref)
            and (
                _is_control(node)
                or node.role in ("heading", "iframe")
                or node.role in SPECIAL_ROLES
            )
        )
        branch.blocky = own or any(kid.blocky for kid in branch.children)


def _inline_only(branch: _Branch) -> bool:
    """Is every element in this subtree a piece of a sentence? A `generic` can be a `<span>`
    or a `<div>` full of paragraphs; only the first may melt into its parent's line."""
    return all(not b.node.ref or b.node.role in _INLINE_ROLES for b in _walk(branch))


def _words(branch: _Branch) -> str:
    """Every word a subtree shows, in order. A named node stands for its subtree: an
    accessible name already sums up what is inside it."""
    node = branch.node
    if not node.ref and not node.trailing and not branch.children:
        # Playwright points a ref at everything it can find on screen. A line with no ref,
        # no content and only a name is a `title` on an empty box: Wikipedia's citation
        # metadata (`ctx_ver=Z39.88-2004&rft...`, hundreds of chars each) reads like this.
        return ""
    if node.name and (not node.trailing or node.role in _TYPED_ROLES):
        # What a field holds is never words of the page: a row holding a password box would
        # otherwise carry the password in its words.
        return node.name
    if node.role in _TYPED_ROLES:
        return ""
    parts = [node.trailing] if node.trailing else []
    parts += [_words(kid) for kid in branch.children]
    return " ".join(part for part in parts if part)


# ------------------------------------------------------------------------- folding


def _fold(kids: list[_Branch], drafts: list[list[_Draft]], url: str) -> list[_Draft]:
    """Fold runs of 3 or more look-alike siblings into one group.

    Look-alike: same role, the same sequence of element kinds inside (a repeat counts once,
    so a quote with two tags and one with four still match), and the same first path
    segment on the first link. Siblings with nothing to show do not break a run."""
    present = _without_repeats(
        [(kid, found) for kid, found in zip(kids, drafts, strict=True) if found]
    )
    shapes = [_shape(kid, found, url) if kid is not None else None for kid, found in present]
    out: list[_Draft] = []
    index = 0
    while index < len(present):
        end = index + 1
        while end < len(present) and shapes[index] is not None and shapes[end] == shapes[index]:
            end += 1
        if end - index >= FOLD_MIN:
            out.append(_Fold(tuple(tuple(_flatten(found)) for _, found in present[index:end])))
            index = end
        else:
            out += present[index][1]
            index += 1
    return out


def _without_repeats(
    present: list[tuple[_Branch | None, list[_Draft]]],
) -> list[tuple[_Branch | None, list[_Draft]]]:
    """Siblings with a run that repeats word for word kept once, and a note for the rest.

    tinylaunch.com cloned a testimonial carousel about 20 times, and the clones filled the
    view. A run of up to REPEAT_PERIOD siblings counts when it holds REPEAT_MIN_LINES lines
    or more; smaller look-alikes (a row of stars, pager dots) fold as before."""
    signs = [_signature(found) for _, found in present]
    out: list[tuple[_Branch | None, list[_Draft]]] = []
    at = 0
    while at < len(present):
        period, times = _repetition(signs, at)
        unit = present[at : at + period]
        lines = sum(len(list(_flatten(found))) for _, found in unit)
        if times < 2 or lines < REPEAT_MIN_LINES:
            out.append(present[at])
            at += 1
            continue
        out.extend(unit)
        first_again = next(_flatten(present[at + period][1]))
        out.append((None, [_Repeat(first_again.order, lines, times - 1)]))
        at += period * times
    return out


def _repetition(signs: list[tuple[tuple[str, ...], ...]], at: int) -> tuple[int, int]:
    """The run starting at `at` that repeats most, as (siblings in it, times in a row)."""
    best = (1, 1)
    for period in range(1, min(REPEAT_PERIOD, (len(signs) - at) // 2) + 1):
        unit = signs[at : at + period]
        if not all(unit):
            continue
        times = 1
        while signs[at + times * period : at + (times + 1) * period] == unit:
            times += 1
        if times > 1 and period * times > best[0] * best[1]:
            best = (period, times)
    return best


def _signature(found: Sequence[_Draft]) -> tuple[tuple[str, ...], ...]:
    """What a sibling says, without its refs: two clones of one card have the same."""
    return tuple((item.kind, item.role, item.name, item.said) for item in _flatten(found))


def _shape(kid: _Branch, found: list[_Draft], url: str) -> tuple[str, tuple[str, ...], str] | None:
    items = list(_flatten(found))
    if len(items) > ROW_MAX_ITEMS:
        return None
    kinds: list[str] = []
    for item in items:
        if not kinds or kinds[-1] != item.kind:
            kinds.append(item.kind)
    link = next((item for item in items if item.node.href), None)
    return kid.node.role, tuple(kinds), _first_segment(link.node.href, url) if link else ""


def _first_segment(href: str | None, url: str) -> str:
    """`/tag/love/page/1/` -> `tag`. Relative links are resolved first: on a books page every
    `../mystery_3/index.html` is `/catalogue/...`, and its own first part differs per row."""
    parsed = urlparse(urljoin(url, href or ""))
    segments = [part for part in parsed.path.split("/") if part]
    return f"{parsed.netloc}/{segments[0] if segments else ''}"


def _flatten(found: Sequence[_Draft | Group]) -> Iterator[Item]:
    for draft in found:
        if isinstance(draft, Item):
            yield draft
        elif not isinstance(draft, _Repeat):
            for row in draft.rows:
                yield from row


def _name_groups(drafts: list[_Draft]) -> list[_Block]:
    """Give every fold its id, g1 first, in page order."""
    named: list[_Block] = []
    for draft in drafts:
        if isinstance(draft, Item | _Repeat):
            named.append(draft)
            continue
        number = sum(isinstance(block, Group) for block in named) + 1
        named.append(Group(f"g{number}", _noun(draft.rows), draft.rows))
    return named


def _noun(rows: tuple[tuple[Item, ...], ...]) -> str:
    kinds = {row[0].kind for row in rows}
    if any(len(row) > 1 for row in rows) or len(kinds) > 1:
        return "rows"
    kind = kinds.pop()
    return "lines" if kind == "text" else f"{kind}s"


def _first_order(block: _Block) -> int:
    return block.order if isinstance(block, Item | _Repeat) else block.rows[0][0].order


# ------------------------------------------------------------------------- rendering


def _block_lines(blocks: Sequence[_Block], *, expand: bool) -> list[_Line]:
    out: list[_Line] = []
    for block in blocks:
        if isinstance(block, Item):
            out.append(_Line(block.line, (block,)))
        elif isinstance(block, _Repeat):
            out.append(_Line(block.text))
        elif expand:
            out += _expanded(block, 0)
        else:
            out += _folded(block)
    return out


def _folded(group: Group) -> list[_Line]:
    total = len(group.rows)
    shown = group.rows[:FOLD_SHOWN]
    more = total - len(shown)
    if group.singles:
        cells = [row[0].short for row in shown]
        if more:
            cells.append(f"+{more} more: look {group.id}")
        return [_Line(f"{group.id} {total} {group.noun}: " + " · ".join(cells), _cells(shown))]
    head = f"{group.id} {total} rows, {len(shown)} shown:" if more else f"{group.id} {total} rows:"
    out = [_Line(head)]
    out += [_row_line(number, row) for number, row in enumerate(shown, start=1)]
    if more:
        out.append(_Line(f" +{more} more rows: look {group.id}"))
    return out


def _expanded(group: Group, first_row: int) -> list[_Line]:
    total = len(group.rows)
    head = f"{group.id} {total} {group.noun}"
    head += f", from r{first_row + 1}:" if first_row else ":"
    out = [_Line(head)]
    for number, row in enumerate(group.rows[first_row:], start=first_row + 1):
        out.append(_row_line(number, row))
    return out


def _row_line(number: int, row: tuple[Item, ...]) -> _Line:
    return _Line(f" r{number} " + " · ".join(item.line for item in row), row)


def _cells(rows: Sequence[tuple[Item, ...]]) -> tuple[Item, ...]:
    return tuple(item for row in rows for item in row)


def _cut(sequence: list[_Line], limit: int) -> tuple[list[_Line], list[_Line]]:
    """Cut at a line boundary once `limit` characters are used.

    The first line is always kept, so paging moves forward even under a tiny budget; under
    the default budget no single line comes near it (rows are at most ROW_MAX_ITEMS)."""
    used = 0
    for index, line in enumerate(sequence):
        used += len(line.text) + 1
        if used > limit and index:
            return sequence[:index], sequence[index:]
    return sequence, []


def _assemble(
    page: _Page,
    shown: list[_Line],
    rest: list[_Line],
    words: list[str],
    title: str,
    frames: Mapping[str, str],
) -> View:
    # Items are told apart by their place on the page, not their ref: a disabled control
    # with no ref is printed too (see `_disabled_control`).
    on_screen = [item for line in shown for item in line.items]
    seen = {item.order for item in on_screen}
    something_hidden = any(item.order not in seen for item in page.items)
    best = _best(page, words) if words and something_hidden else []
    listed_best = {item.order for item in best}
    pager = [
        item
        for item in page.items
        if item.control
        and item.ref
        and _is_pager(item)
        and item.order not in seen
        and item.order not in listed_best
    ]

    text = [f"page {_quoted(_clean(title))} {page.url}"]
    if best:
        joined = " · ".join(item.brief for item in best)
        text.append(f"best for {_quoted(' '.join(words))}: {joined}")
    text += [line.text for line in shown]
    if rest:
        text.append(_note(rest))
    pager_line, listed = _pager_line(pager)
    if pager_line:
        text.append(pager_line)

    printed = [*on_screen, *best, *listed]
    targets = {item.ref: _target(item, frames) for item in printed if item.ref}
    known = {
        branch.node.ref: _node_target(branch.node, frames)
        for branch in _walk(page.root)
        if branch.node.ref
    }
    return View("\n".join(text), targets, page.groups, len(rest), known)


def _note(rest: list[_Line]) -> str:
    following = next((line.items[0].ref for line in rest if line.items), "")
    where = f"look from {following}" if following else "look all"
    return f"+{len(rest)} more lines not shown: {where}, or look <words>"


def _pager_line(pager: list[Item]) -> tuple[str, list[Item]]:
    if not pager:
        return "", []
    listed: list[Item] = []
    text = "pager:"
    for item in pager:
        if len(text) + len(item.line) + 3 > PAGER_LIMIT:
            return f"{text} · +{len(pager) - len(listed)} more", listed
        text += (" · " if listed else " ") + item.line
        listed.append(item)
    return text, listed


def _target(item: Item, frames: Mapping[str, str]) -> Target:
    return _node_target(item.node, frames)


def _node_target(node: Node, frames: Mapping[str, str]) -> Target:
    return Target(node.ref, node, frames.get(node.frame_ref) if node.frame_ref else None)


def _is_pager(item: Item) -> bool:
    raw = _clean(item.words).lower()
    trimmed = raw.strip(_ARROWS + " ").rstrip(_TRAILING_DOTS).strip()
    if not trimmed:
        # Nothing but arrows is a pager ("›", "»"); nothing but dots is a "more actions" menu.
        return any(arrow in raw for arrow in _ARROWS)
    return bool(_PAGER.fullmatch(trimmed))


# ------------------------------------------------------------------------- focus


def _best(page: _Page, words: list[str]) -> list[Item]:
    """The lines that best match the words, best first, ties in page order.

    A word scores its rarity on THIS page: on a page of city names "cities" is everywhere
    and "lagos" is on two lines, so "lagos" decides. The lab added this weighting after
    plain counting missed Lagos (post-hoc, lab-results.md §7); it is measured again in
    Phase 2."""
    stems = list(dict.fromkeys(_stem(word) for word in words))
    own = {item.order: _tokens(item.words) for item in page.items}
    count = len(page.items)
    weight = {
        stem: math.log((count + 1) / (sum(stem in seen for seen in own.values()) + 1)) + IDF_FLOOR
        for stem in stems
    }
    heading = ""
    scored: list[tuple[float, int, Item]] = []
    for item in page.items:
        if item.kind == "heading":
            heading = item.words
        context = (_tokens(_href_words(item.node.href, page.url)), _tokens(heading))
        score = sum(OWN_WEIGHT * weight[stem] for stem in stems if stem in own[item.order])
        score += sum(weight[stem] for stem in stems for seen in context if stem in seen)
        if score > 0:
            scored.append((score + (CONTROL_BONUS if item.control else 0.0), item.order, item))
    scored.sort(key=lambda entry: (-entry[0], entry[1]))
    return [item for _, _, item in scored[:BEST_COUNT]]


def _passages(page: _Page, words: list[str]) -> list[str]:
    """`e1 says: …words around a match…`, for each element whose text is too long to print.

    market.lobehub.com served a 48k markdown guide as one element: its line was cut at 120
    characters, and `look <words>` could only point at that one line again."""
    if not words:
        return []
    found: list[str] = []
    for item in page.items:
        text = item.said or item.words
        if len(text) <= LONG_TEXT:
            continue
        lowered = text.lower()
        spans: list[tuple[int, int]] = []
        for word in words:
            for match in re.finditer(re.escape(word), lowered):
                start = max(match.start() - PASSAGE_SIDE, 0)
                end = min(match.end() + PASSAGE_SIDE, len(text))
                if spans and start <= spans[-1][1]:
                    spans[-1] = (spans[-1][0], max(end, spans[-1][1]))
                else:
                    spans.append((start, end))
        for start, end in sorted(spans)[:PASSAGES_SHOWN]:
            before = "…" if start else ""
            after = "…" if end < len(text) else ""
            found.append(f"{item.ref} says: {before}{text[start:end].strip()}{after}")
    return found[:PASSAGES_SHOWN]


def _href_words(href: str | None, url: str) -> str:
    """A link target as words: the path on this site, the host too when it is elsewhere."""
    if not href:
        return ""
    target = urlparse(urljoin(url, href))
    here = urlparse(url).netloc
    host = target.netloc if target.netloc != here else ""
    return " ".join((host, target.path, target.query, target.fragment))


def _stem(word: str) -> str:
    """Plural to singular, crudely, so "issues" finds "Issue" (the lab's rule)."""
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def _tokens(text: str) -> set[str]:
    return {_stem(word) for word in _WORD.findall(text.lower())}


# ------------------------------------------------------------------------- text


def _clean(text: str) -> str:
    """One line of text: runs of whitespace become one space, invisible characters go."""
    visible = text.translate(_INVISIBLE)
    if any(unicodedata.category(character) == _PRIVATE_USE for character in visible):
        visible = "".join(
            character for character in visible if unicodedata.category(character) != _PRIVATE_USE
        )
    return " ".join(visible.split())


def _cut_text(text: str, limit: int = TEXT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _quoted(text: str, limit: int = TEXT_LIMIT) -> str:
    """A name in double quotes, cut, with any quote inside escaped so the line still parses."""
    escaped = _cut_text(text, limit).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
