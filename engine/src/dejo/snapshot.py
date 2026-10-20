"""The page, as Playwright's own accessibility snapshot sees it.

This replaces about sixty lines of hand-written JavaScript that walked the DOM looking for
a fixed list of tags. That collector could only see what it was told to look for, and it
could not see:

- anything inside a shadow DOM
- anything inside an iframe
- a `div` with a click handler pretending to be a button, which is most of the modern web

On a page containing all three plus a late-loading link, the old collector found **one**
element. This finds seven, and can act on every one of them.

Two things make it work. `aria_snapshot(mode="ai")` returns a `ref` for every node, and
`aria-ref=<ref>` is a selector that resolves it again — through shadow roots and across
frame boundaries. A ref is good for one snapshot only and must never reach memory; what
gets stored is the durable descriptors in `describe.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .models import Locator, link_target

# Roles worth offering to a caller. Everything else on a page is layout.
INTERACTIVE_ROLES = frozenset(
    {
        "button",
        "link",
        "textbox",
        "searchbox",
        "combobox",
        "listbox",
        "option",
        "checkbox",
        "radio",
        "switch",
        "slider",
        "spinbutton",
        "menuitem",
        "menuitemcheckbox",
        "menuitemradio",
        "tab",
        "treeitem",
        "img",
    }
)

# Tags whose accessible name does not come from text inside them: a form field is named by
# a `<label>` beside it, and an image by its alt attribute. Searching the page for that text
# would find the label, or nothing at all.
_NAMED_FROM_ELSEWHERE = {"input", "select", "textarea", "img"}

# Roles that hold something a person typed or chose.
_FIELD_ROLES = frozenset({"textbox", "searchbox", "combobox", "spinbutton", "slider"})

# What a filled field reports instead of its contents.
#
# Playwright's snapshot prints the contents of every field in plain text, passwords
# included: `textbox "Password" [ref=e3]: hunter2`. Dejo must never carry that, so the
# fact that a field has something in it is kept and the something itself is thrown away.
# A caller that genuinely needs the text asks for it with `read(value)`, which is a
# deliberate act rather than a side effect of looking at the page.
FILLED = "(filled)"

# One line of the snapshot: `- button "Save" [ref=e4] [cursor=pointer]: some text`
_LINE = re.compile(
    r"""
    ^(?P<indent>\s*)-\s
    (?P<role>[a-zA-Z][\w-]*)
    (?:\s+"(?P<name>(?:[^"\\]|\\.)*)")?
    (?P<attrs>(?:\s+\[[^\]]*\])*)
    (?::\s*(?P<text>.*))?
    $
    """,
    re.VERBOSE,
)
_ATTR = re.compile(r"\[([^\]]*)\]")

# Playwright's own ref: `e4`, or `f3e4` when it has numbered the document `f3`. The number
# says nothing reliable about WHICH frame: after any navigation Playwright prefixes the main
# page's refs too (`f3e2` for a plain button), so frames are found by nesting instead.
_PLAYWRIGHT_REF = re.compile(r"^(?P<doc>f\d+)?e(?P<number>\d+)$")

# The escapes a YAML double-quoted scalar can hold that change the character. Anything else
# after a backslash stands for itself, which covers `\"` and `\\`.
_YAML_ESCAPES = {"n": "\n", "t": "\t"}

# What a ref looks like: `e4`, or `f1e2` inside a frame. Anything else a caller passes is
# a CSS selector, because that is what people reach for when an element has no ref.
_LOOKS_LIKE_REF = re.compile(r"^f?\d*e\d+$")


@dataclass
class Element:
    """One control on the page, with every way we know to find it again.

    Fields above the line come from the snapshot and are always present. Fields below it
    are the durable descriptors, filled in by `describe` only for elements actually acted
    on — reading them for every element on every look would cost a round trip per element
    and most of them are never touched.
    """

    ref: str
    """The ref a caller sees and passes back: `e16` on the main page, `f1e3` in the first
    iframe. Dejo's own, so it reads the same whatever Playwright has numbered the document."""
    role: str
    name: str
    aria_ref: str = ""
    """Playwright's ref for the same node, which is what `aria-ref=` resolves. Empty for an
    element that did not come from a snapshot."""
    selector: str = ""
    """How to find this element, when it did not come from a snapshot.

    A snapshot element is found by its `ref`. One named by a CSS selector — because it has
    no role and so is not offered as a control — is found by that selector instead. Plain
    `div`s holding the numbers are the normal case on a dashboard."""

    found_by: Locator | None = None
    """The stored locator this element was named with, when it came from MEMORY.

    An element from a snapshot has a `ref`; one the caller described has a `selector`. This
    is the third case: a control named the way the map remembers it, `role=button|Sign in`,
    resolved by the same code replay uses. Without it the map could only ever be a hint —
    the caller would know the button was there and still have to read the whole page to get
    a ref before pressing it."""

    href: str | None = None
    clickable: bool = False
    frame: str | None = None
    """CSS selector for the iframe this element lives in, if it is inside one.

    A stored locator that does not name its frame cannot be resolved later: `page.locator`
    does not look inside iframes, so the selector would simply find nothing."""

    nth: int = 0
    """Which of the look-alikes this is, among elements with the same role and name."""
    twins: int = 1
    """How many elements share this role and name. More than one means a bare role locator
    is ambiguous and needs `nth` pinned to it."""

    # --- filled in by `describe`, only for elements acted on -------------------
    tag: str = ""
    css: str = ""
    type: str | None = None
    test_id: str | None = None
    label: str | None = None
    placeholder: str | None = None
    title: str | None = None
    alt: str | None = None
    fallback_css: str = ""
    """A second, positional path to the same element, worked out from the page.

    Only used when the caller named the element with their own selector. Theirs is anchored
    to meaning — `:has-text("Visitors")` survives tiles being reordered — so it goes first,
    and this one is the spare for the day the class names change."""

    value: str | None = None
    """What the field holds — but only ever `"(filled)"` until `describe` has run.

    A page can arrive with fields already filled, and an AI that cannot see that will ask
    the user for something already on screen. Knowing a field is *not empty* is enough for
    that, and it is all the snapshot is allowed to say: Playwright prints field contents in
    plain text, passwords included. `describe` reads the real value later, where the
    password check happens in the page and a password box still reports `"(filled)"`."""

    def locators(self) -> list[Locator]:
        """Every way we know to find this element again, most durable first.

        The order is a claim about what survives a redesign. A test id is written for
        machines and almost never touched. A link target usually outlives its label, and a
        label usually outlives a CSS id, which is the first thing a rewrite throws away.

        Replay reorders these by measured confidence once they have a track record, so the
        order here only decides what gets tried on the very first replay.
        """
        found: list[Locator] = []

        if self.test_id:
            found.append(Locator("test_id", self.test_id))
        if self.href:
            found.append(Locator("structural", f"href={link_target(self.href)}"))
        if self.label:
            found.append(self._pin(Locator("label", self.label)))
        if self.name:
            found.append(self._pin(Locator("role", f"{self.role}|{self.name}")))
        if self.placeholder:
            found.append(self._pin(Locator("placeholder", self.placeholder)))
        if self.alt:
            found.append(self._pin(Locator("alt", self.alt)))
        if self.title:
            found.append(self._pin(Locator("title", self.title)))
        if self.name and self._text_is_its_own:
            found.append(self._pin(Locator("text", self.name)))
        if self.css:
            found.append(Locator("css", self.css))
        if self.fallback_css and self.fallback_css != self.css:
            found.append(Locator("css", self.fallback_css))

        for locator in found:
            locator.frame = self.frame
        return found

    @property
    def _text_is_its_own(self) -> bool:
        """Is this element's name the text inside it, rather than text pointing at it?

        A form field takes its name from a `<label>` that sits beside it, so searching the
        page for that text finds the label, not the field. Filling a label does nothing.
        Links and buttons contain their own words, so for them a text locator is sound.
        """
        return self.tag not in _NAMED_FROM_ELSEWHERE

    def _pin(self, locator: Locator) -> Locator:
        """Add a position to a locator that would otherwise be ambiguous.

        Three buttons all called "Edit" would each store the same locator, and every replay
        would press the first one. Pinning the index is what makes row three actually row
        three. Left alone when the element is unique, because an index is one more thing
        that can go stale.
        """
        if self.twins > 1:
            locator.nth = self.nth
        return locator

    def to_dict(self) -> dict[str, str | None]:
        described: dict[str, str | None] = {
            "ref": self.ref,
            "role": self.role,
            "name": self.name,
        }
        for key, extra in (
            ("href", self.href),
            ("frame", self.frame),
            ("value", self.value),
            # Below here only appears once `describe` has read the page. A candidate handed
            # to whoever repairs a step is always described, because they have to write
            # down something more lasting than a ref.
            ("css", self.css),
            ("tag", self.tag),
            ("test_id", self.test_id),
            ("label", self.label),
            ("placeholder", self.placeholder),
        ):
            if extra:
                described[key] = extra
        if self.twins > 1:
            described["nth"] = str(self.nth)
        return described


@dataclass
class Snapshot:
    """One look at the page."""

    url: str
    title: str
    elements: list[Element] = field(default_factory=list)
    text: str = ""

    def by_ref(self, ref: str) -> Element | None:
        for element in self.elements:
            if element.ref == ref:
                return element
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "elements": [element.to_dict() for element in self.elements],
            "text": self.text,
        }


@dataclass
class Node:
    """One line of the snapshot that carries a ref, before anything is decided about it."""

    aria_ref: str
    role: str
    name: str
    trailing: str
    flags: str
    frame_ref: str
    """Playwright's ref of the iframe this node sits under, or "" on the main page."""
    frame_index: int
    """Which iframe that is, counted by Dejo in document order from 1. 0 on the main page."""
    href: str | None = None


def nodes(snapshot: str) -> list[Node]:
    """Every node in the snapshot that has a ref, with the iframe it sits in.

    The iframe comes from NESTING: a node belongs to the nearest `iframe` line above it with
    a smaller indent. Playwright's `f<N>` numbers cannot be used for this: after a page has
    navigated, Playwright prefixes the main page's refs as well, so `f3e2` was a plain button
    while the iframe on the same page was `f4`, and every element inside a frame lost its
    frame. Only nesting says the same thing on every visit.
    """
    found: list[Node] = []
    frames: list[tuple[int, str, int]] = []  # (indent, iframe ref, index), innermost last
    counted = 0

    for line in snapshot.splitlines():
        stripped = line.strip()

        # `- /url: /invoices/9` is a property of the line above it, not a node of its own.
        # Checked before the main pattern, which only matches lines that start with a role.
        if stripped.startswith("- /url:"):
            if found:
                found[-1].href = _unquote(stripped[len("- /url:") :].strip())
            continue

        match = _LINE.match(_unwrapped(line.rstrip()))
        if match is None:
            continue
        indent = len(match.group("indent"))
        while frames and frames[-1][0] >= indent:
            frames.pop()

        attrs = _attributes(match.group("attrs") or "")
        ref = attrs.get("ref")
        if not ref:
            continue

        role = match.group("role")
        frame_ref, frame_index = (frames[-1][1], frames[-1][2]) if frames else ("", 0)
        found.append(
            Node(
                aria_ref=ref,
                role=role,
                name=_unescape(match.group("name") or ""),
                trailing=_plain((match.group("text") or "").strip()),
                flags=attrs.get("_flags", ""),
                frame_ref=frame_ref,
                frame_index=frame_index,
            )
        )
        if role == "iframe":
            counted += 1
            frames.append((indent, ref, counted))

    return found


def parse(snapshot: str, *, frames: dict[str, str] | None = None) -> list[Element]:
    """Turn Playwright's snapshot into the controls a caller can act on.

    `frames` maps an iframe's Playwright ref to a CSS selector for that iframe, so an
    element inside it can record where it lives. Without that a stored locator would be
    unresolvable: `page.locator` does not look inside iframes.
    """
    frames = frames or {}
    every = nodes(snapshot)
    main = _document_of(every[0].aria_ref) if every else ""
    found: list[Element] = []

    for node in every:
        # With a quoted name, the trailing text is the field's contents. Without one, it is
        # the element's name — which is how a `div role="combobox"` gets called anything at
        # all.
        name = node.name or node.trailing
        filled = bool(node.name and node.trailing and node.role in _FIELD_ROLES)

        element = Element(
            ref=_dejo_ref(node, main),
            role=node.role,
            name=name[:80],
            aria_ref=node.aria_ref,
            href=node.href,
            clickable="cursor=pointer" in node.flags,
            frame=frames.get(node.frame_ref) if node.frame_ref else None,
            value=FILLED if filled else None,
        )
        if _worth_offering(element):
            found.append(element)

    _count_twins(found)
    return found


def is_ref(handle: str) -> bool:
    """Is this one of our refs, or a CSS selector somebody typed?"""
    return bool(_LOOKS_LIKE_REF.match(handle.strip()))


def iframe_refs(snapshot: str) -> list[str]:
    """Playwright's refs of the iframes on this page, so each can be given a selector."""
    return [node.aria_ref for node in nodes(snapshot) if node.role == "iframe"]


def _document_of(aria_ref: str) -> str:
    """The `f<N>` Playwright has put in front of a ref, or "" for none."""
    match = _PLAYWRIGHT_REF.match(aria_ref)
    return (match.group("doc") or "") if match else ""


def _dejo_ref(node: Node, main: str) -> str:
    """The ref a caller sees: `e<n>` on the main page, `f<k>e<n>` in the k-th iframe.

    The main page's prefix is the one on the snapshot's first line, which is always the main
    document. A ref that does not have Playwright's shape is passed through unchanged rather
    than guessed at."""
    match = _PLAYWRIGHT_REF.match(node.aria_ref)
    if match is None:
        return node.aria_ref
    number = match.group("number")
    if node.frame_index:
        return f"f{node.frame_index}e{number}"
    if (match.group("doc") or "") == main:
        return f"e{number}"
    return node.aria_ref


def _worth_offering(element: Element) -> bool:
    """Is this something a caller could act on, or is it layout?

    `cursor=pointer` is the important half. A `div` with a click handler has no interactive
    role at all — it is the shape most modern component libraries produce, and the old
    collector was blind to every one of them. Playwright reports the cursor, and a pointer
    cursor is the site itself saying "this is clickable".
    """
    if element.role in INTERACTIVE_ROLES:
        return True
    return element.clickable and bool(element.name)


def _count_twins(elements: list[Element]) -> None:
    """Tell the look-alikes apart.

    Three buttons all called "Edit" would each store the same locator, and every replay
    would press the first one.
    """
    seen: dict[tuple[str, str], int] = {}
    for element in elements:
        key = (element.role, element.name)
        seen[key] = seen.get(key, 0) + 1

    counted: dict[tuple[str, str], int] = {}
    for element in elements:
        key = (element.role, element.name)
        element.twins = seen[key]
        element.nth = counted.get(key, 0)
        counted[key] = element.nth + 1


def _attributes(raw: str) -> dict[str, str]:
    """Pull `[ref=e4]` and `[cursor=pointer]` out of one line.

    Flags without a value — `[active]`, `[disabled]` — are collected into `_flags` rather
    than being dropped, because `cursor=pointer` arrives in that form.
    """
    found: dict[str, str] = {}
    flags: list[str] = []
    for chunk in _ATTR.findall(raw):
        key, sep, value = chunk.partition("=")
        if sep and key.strip() == "ref":
            found["ref"] = value.strip()
        else:
            flags.append(chunk.strip())
    found["_flags"] = " ".join(flags)
    return found


def _unwrapped(line: str) -> str:
    """Take Playwright's YAML quoting off a snapshot line.

    A line whose text contains `": "` is written as a quoted YAML scalar, because unquoted it
    would read as a mapping: `- 'link "Fix: login bug" [ref=e6]':`. The line pattern expects
    the role first, so every such element was silently skipped: 47 controls on one GitHub
    page, most topic titles on a Discourse forum, the titles of half the books on a shop
    page. A single-quoted scalar escapes `'` as `''`; a double-quoted one uses backslashes.
    What follows the closing quote (nothing, `:`, or `: text`) is kept as it was.
    """
    head = len(line) - len(line.lstrip())
    body = line[head:]
    if not body.startswith("- ") or body[2:3] not in ("'", '"'):
        return line
    quote = body[2]
    inner, end = _scalar(body, 3, quote)
    if end < 0:
        return line
    return f"{line[:head]}- {inner}{body[end:]}"


def _scalar(text: str, start: int, quote: str) -> tuple[str, int]:
    """Read one YAML quoted scalar that opens just before `start`. Returns its value and the
    index just past the closing quote, or -1 when it never closes."""
    out: list[str] = []
    at = start
    while at < len(text):
        char = text[at]
        if quote == "'" and char == "'":
            if text[at + 1 : at + 2] == "'":
                out.append("'")
                at += 2
                continue
            return "".join(out), at + 1
        if quote == '"' and char == "\\" and at + 1 < len(text):
            out.append(_YAML_ESCAPES.get(text[at + 1], text[at + 1]))
            at += 2
            continue
        if quote == '"' and char == '"':
            return "".join(out), at + 1
        out.append(char)
        at += 1
    return "", -1


def _plain(text: str) -> str:
    """A node's trailing text without YAML quoting, which it gets for the same reason a
    whole line does: `- paragraph: "Total: 1,240"`."""
    if len(text) >= 2 and text[0] in "\"'" and text[-1] == text[0]:
        inner, end = _scalar(text, 1, text[0])
        if end == len(text):
            return inner
    return text


def _unquote(url: str) -> str:
    """Playwright wraps a url in quotes when it contains anything awkward.

    Found on GitHub: `- /url: "#start-of-content"`. Keeping the quotes made `href_path`
    return `"` , so every `structural` locator on the page was silently useless — and
    structural is the second most durable kind we have.
    """
    if len(url) >= 2 and url[0] == url[-1] and url[0] in "\"'":
        return url[1:-1]
    return url


def _unescape(name: str) -> str:
    return name.replace('\\"', '"').replace("\\\\", "\\")
