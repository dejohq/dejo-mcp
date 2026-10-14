"""Waiting for a frame means waiting for what is IN it.

Found on Google's file picker: `wait_for element:<the iframe>` passed while the frame was
still empty, and the very next click inside it had nothing to hit. An iframe is on screen
long before its own page is, and a picker fills itself in later still. These tests pin both
halves: a frame counts as arrived once its page has content, and `in_frame:` waits for one
particular thing inside it.
"""

from __future__ import annotations

import pytest

from dejo import actions, waits
from dejo.browser import Browser

# The frame is on screen at once and empty. Its page arrives 400ms later; the button the
# trail wants arrives 400ms after that — the shape of a real file picker.
FILLS_LATE = """
<!doctype html>
<title>picker</title>
<iframe id="picker" style="width:320px;height:200px;border:0"></iframe>
<script>
  const inside = () => document.getElementById('picker').contentDocument;
  setTimeout(() => { inside().body.innerHTML = '<p id="ready">Choose a file</p>'; }, 400);
  setTimeout(() => {
    inside().body.insertAdjacentHTML('beforeend', '<button id="upload">Upload</button>');
  }, 800);
</script>
"""


def wait(browser: Browser, value: str) -> None:
    actions.perform("wait_for", page=browser.page, target=None, value=value)


def inside(browser: Browser):
    return browser.page.frame_locator("#picker")


def test_waiting_for_a_frame_waits_for_its_page(browser: Browser) -> None:
    browser.page.set_content(FILLS_LATE)

    wait(browser, "element:#picker")

    assert inside(browser).locator("#ready").count() == 1, "the wait passed on an empty frame"


def test_in_frame_waits_for_the_thing_inside(browser: Browser) -> None:
    browser.page.set_content(FILLS_LATE)

    wait(browser, "in_frame:#picker|#upload")

    inside(browser).locator("#upload").click()  # there now, and clickable


def test_an_ordinary_element_is_not_slowed_down(browser: Browser) -> None:
    """Only a frame gets the second wait. A plain element returns as it always did."""
    browser.page.set_content('<p id="here">here</p>')

    wait(browser, "element:#here")


class TestTheShapeIsChecked:
    @pytest.mark.parametrize("value", ["in_frame:#picker", "in_frame:|#upload", "in_frame:#a|"])
    def test_both_halves_are_needed(self, value: str) -> None:
        with pytest.raises(waits.WaitNeedsMore) as refused:
            waits.parse(value)
        assert "in_frame:<the iframe>|<what is inside it>" in str(refused.value)

    def test_the_kind_is_listed_for_the_caller(self) -> None:
        assert "in_frame" in waits.catalogue()


def test_something_that_never_arrives_says_so(browser: Browser) -> None:
    browser.page.set_content(FILLS_LATE)

    with pytest.raises(waits.WaitedTooLong) as raised:
        waits.wait_for("in_frame:#picker|#never", page=browser.page, timeout_ms=300)

    assert "in_frame" in str(raised.value)
