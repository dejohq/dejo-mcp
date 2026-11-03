# What Dejo can do, next to other browser tools

Dejo should be able to do everything the major browser automation tools can do, and then
remember it. This page lists every capability of those tools, taken from their own docs and
source code, and says for each one whether Dejo has it and how you reach it.

How to read the **Dejo** column:

- **yes**: Dejo does it. The next column says what to write.
- **partly**: Dejo does some of it. The next column says what is missing.
- **no**: Dejo cannot do it yet.
- **not in Dejo, on purpose**: Dejo will not do it. This is for solving captchas, hiding or
  faking the browser's fingerprint, getting round a site's own block on automated browsers,
  and (for agent tools) the model call itself: in Dejo your own agent does the thinking.
  When a site shows a captcha or blocks the browser, Dejo stops and hands over to you.

Almost everything in Dejo is a **step line** in the `steps` of `dejo_run`, such as
`click button "Save"` or `read css ".price" as price`. A few things are settings, given as
environment variables (`DEJO_...`) in your MCP config, or as options of the `dejo` command.

Every step a trail keeps is replayed later with zero model calls, and checked as it runs.
Where a step is not kept in a trail, the reply says so and why.

## Summary

| Tool | Capabilities listed | Dejo: yes | partly | no | not on purpose |
|---|---|---|---|---|---|
| [Playwright (the library)](#playwright-the-library) | 205 | 108 | 32 | 63 | 2 |
| [Playwright MCP](#playwright-mcp) | 126 | 50 | 36 | 40 | 0 |
| [Chrome DevTools MCP](#chrome-devtools-mcp) | 127 | 44 | 18 | 65 | 0 |
| [browser-use](#browser-use) | 119 | 56 | 25 | 24 | 14 |
| [Stagehand](#stagehand) | 112 | 55 | 25 | 14 | 18 |
| [Puppeteer and Selenium WebDriver](#puppeteer-and-selenium-webdriver) | 28 | 0 | 6 | 22 | 0 |

Counts are of the rows below. Some rows group a few small methods that do one job.

Before the November 2026 parity work, the "yes" counts were: Playwright 70, Playwright MCP
21, Chrome DevTools MCP 21, browser-use 29, Stagehand 36, Puppeteer and Selenium 0.

## Playwright (the library)

Source: <https://github.com/microsoft/playwright>. License: Apache License 2.0. Copyright line in the repo's NOTICE: "Copyright (c) Microsoft Corporation" (the LICENSE appendix also says "Portions Copyright (c) Microsoft Corporation. Portions Copyright 2017 Google Inc."; playwright-python's LICENSE has the same two lines).

### 1. Page: open, move, wait

| Capability (plain words for users) | Playwright API | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Open a web address | `page.goto` | yes | `go URL` (also the `url` argument of `dejo_run`) | https://playwright.dev/python/docs/api/class-page#page-goto |
| Go back / go forward in history | `page.go_back`, `page.go_forward` | yes | `back`, `forward` | https://playwright.dev/python/docs/api/class-page#page-go-back |
| Reload the page | `page.reload` | yes | `reload` | https://playwright.dev/python/docs/api/class-page#page-reload |
| Read the current address | `page.url` | yes | `read url as NAME`, `expect url "x"` | https://playwright.dev/python/docs/api/class-page#page-url |
| Read the page title | `page.title` | yes | `read title as NAME` | https://playwright.dev/python/docs/api/class-page#page-title |
| Get the whole page HTML | `page.content` | partly | `read html css "html" as page` (cut after 20,000 characters) | https://playwright.dev/python/docs/api/class-page#page-content |
| Put your own HTML into the page | `page.set_content` | no | — | https://playwright.dev/python/docs/api/class-page#page-set-content |
| Wait for a load stage (load, DOM ready, network quiet) | `page.wait_for_load_state` | partly | `wait idle` (network quiet only; no "load" or "domcontentloaded") | https://playwright.dev/python/docs/api/class-page#page-wait-for-load-state |
| Wait until the address changes to a pattern | `page.wait_for_url` | yes | `wait url:PART` (part of the address; no glob or regex) | https://playwright.dev/python/docs/api/class-page#page-wait-for-url |
| Wait a fixed number of seconds | `page.wait_for_timeout` | yes | `wait SECONDS` | https://playwright.dev/python/docs/api/class-page#page-wait-for-timeout |
| Wait for an element to show up or go away | `page.wait_for_selector`, `locator.wait_for` | yes | `wait T`, `wait element:CSS`, `wait gone:CSS`, `wait text:WORDS` (no "attached"/"detached" states) | https://playwright.dev/python/docs/api/class-locator#locator-wait-for |
| Wait until a JavaScript condition is true | `page.wait_for_function`, `locator.wait_for_function` | no | — | https://playwright.dev/python/docs/api/class-page#page-wait-for-function |
| Wait for any named event | `page.wait_for_event`, `page.expect_event` | no | — | https://playwright.dev/python/docs/api/class-page#page-wait-for-event |
| Change the default wait time for actions and page loads | `page.set_default_timeout`, `page.set_default_navigation_timeout` (also on the context) | partly | engine only: `Browser(timeout_ms=...)`; not from MCP, not per step | https://playwright.dev/python/docs/api/class-page#page-set-default-timeout |

### 2. Page: tabs, window and look of the page

| Capability (plain words for users) | Playwright API | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Open a new tab | `context.new_page` | yes | `tab new [URL]` | https://playwright.dev/python/docs/api/class-browsercontext#browser-context-new-page |
| List tabs and switch between them | `context.pages`, `page.bring_to_front` | yes | `tab N`, `tab latest`, `tab main`; `read tabs as tabs` lists them | https://playwright.dev/python/docs/api/class-page#page-bring-to-front |
| Catch a pop-up / new tab opened by a click | `page.expect_popup`, event `popup` | yes | `tab latest` after the click (it waits for a tab that is still opening) | https://playwright.dev/python/docs/api/class-page#page-wait-for-popup |
| Close a tab | `page.close` | yes | `tab close [N\|latest]` | https://playwright.dev/python/docs/api/class-page#page-close |
| Set or read the window (viewport) size | `page.set_viewport_size`, `page.viewport_size` | yes | `emulate viewport 390x844` (reading the size back only by `js`) | https://playwright.dev/python/docs/api/class-page#page-set-viewport-size |
| Pretend dark mode, print view, reduced motion, high contrast, forced colors | `page.emulate_media` | partly | `emulate color dark`, `emulate media print`, `emulate motion reduce`; no high contrast or forced colors | https://playwright.dev/python/docs/api/class-page#page-emulate-media |
| Save the page as a PDF file | `page.pdf` | yes | `pdf [as NAME]` (saved under `~/.dejo/captures`; headless only, as in Playwright) | https://playwright.dev/python/docs/api/class-page#page-pdf |
| Take a screenshot of the page | `page.screenshot` | partly | `screenshot`, `screenshot full`, `look image` (picture back to the agent); no clip area, masking of secret parts or JPEG | https://playwright.dev/python/docs/api/class-page#page-screenshot |
| Take a screenshot of one element | `locator.screenshot` | yes | `screenshot T [as NAME]` | https://playwright.dev/python/docs/api/class-locator#locator-screenshot |
| Accessibility tree of the page as text (what Dejo shows the agent) | `page.aria_snapshot`, `locator.aria_snapshot` | yes | `look`, `look WORDS`, `look from REF`, `look all`, `look raw` | https://playwright.dev/python/docs/api/class-page#page-aria-snapshot |
| Element boxes (x, y, width, height) in the snapshot | `aria_snapshot(boxes=True)` | no | — (`read box T` gives one element's box) | https://playwright.dev/python/docs/api/class-page#page-aria-snapshot |
| Live screen frames, video with action labels and chapter titles | `page.screencast` (`Screencast.start`, `show_actions`, `show_chapter`, `show_overlay`) | partly | `record video` ... `record stop` makes a plain video; no action labels, chapter titles or live frames | https://playwright.dev/python/docs/api/class-screencast |
| Let a person point at an element and get its locator | `page.pick_locator`, `page.cancel_pick_locator` | no | — | https://playwright.dev/python/docs/api/class-page#page-pick-locator |
| Pause and open the Playwright Inspector | `page.pause` | no | — | https://playwright.dev/python/docs/api/class-page#page-pause |
| Step through actions one by one (pause, next, run to) | `context.debugger` (`Debugger.request_pause`, `next`, `run_to`, `resume`) | no | — | https://playwright.dev/python/docs/api/class-debugger |

### 3. Page: JavaScript and page data

| Capability (plain words for users) | Playwright API | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Run JavaScript in the page and get the answer | `page.evaluate`, `locator.evaluate` | yes | `js CODE` (with or without a target; must be alone, not remembered) | https://playwright.dev/python/docs/api/class-page#page-evaluate |
| Run JavaScript over every matching element | `locator.evaluate_all`, `page.eval_on_selector_all` | no | only by `js` | https://playwright.dev/python/docs/api/class-locator#locator-evaluate-all |
| Keep a handle to a live JavaScript object | `page.evaluate_handle`, `JSHandle` | no | — | https://playwright.dev/python/docs/api/class-page#page-evaluate-handle |
| Run a script before every page loads (for example, set a flag or a fake API) | `page.add_init_script`, `context.add_init_script` | yes | `script "window.tour = false"` (not kept in a trail) | https://playwright.dev/python/docs/api/class-browsercontext#browser-context-add-init-script |
| Add a script or style tag to the page | `page.add_script_tag`, `page.add_style_tag` | no | only by `js` (or `script "..."` for pages that load after it) | https://playwright.dev/python/docs/api/class-page#page-add-script-tag |
| Let the page call a Python function | `page.expose_function`, `page.expose_binding` (also on the context) | no | — | https://playwright.dev/python/docs/api/class-page#page-expose-function |
| Read and write localStorage / sessionStorage | `page.local_storage`, `page.session_storage` (`WebStorage.get_item`, `set_item`, `items`, `remove_item`, `clear`) | partly | `read storage ["key"]`, `storage set KEY "VALUE"`, `storage clear [KEY]`; localStorage only, sessionStorage only by `js` | https://playwright.dev/python/docs/api/class-webstorage |
| Read console messages | `page.console_messages`, event `console`, `ConsoleMessage` | yes | `read console as log` (every message with its type; no arguments or source line) | https://playwright.dev/python/docs/api/class-page#page-console-messages |
| Clear the console list | `page.clear_console_messages` | no | — | https://playwright.dev/python/docs/api/class-page#page-clear-console-messages |
| Read JavaScript errors the page threw | `page.page_errors`, event `pageerror`, `WebError` | yes | `read console_errors` (page errors are kept there too) | https://playwright.dev/python/docs/api/class-page#page-page-errors |
| Wait for a certain console message | `page.expect_console_message` | no | — | https://playwright.dev/python/docs/api/class-page#page-wait-for-console-message |
| List and call tools a site offers through WebMCP | `page.webmcp`, `frame.webmcp` (`WebMCP.tools`, `call_tool`) | no | — | https://playwright.dev/python/docs/api/class-webmcp |
| Run code inside a web worker | `page.workers`, `Worker.evaluate`, event `worker` | partly | `read workers as w` lists the page's web workers. Missing: running code inside one | https://playwright.dev/python/docs/api/class-worker |
| Auto-close things that pop over the page (cookie banner, newsletter box) | `page.add_locator_handler`, `page.remove_locator_handler` | partly | `dismiss css "SEL"` (remembered per site; CSS only, always just clicks it, no step to remove it) | https://playwright.dev/python/docs/api/class-page#page-add-locator-handler |

### 4. Locator: finding elements

| Capability (plain words for users) | Playwright API | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Find by role and name (button "Save") | `get_by_role` | yes | `role "name"` | https://playwright.dev/python/docs/api/class-page#page-get-by-role |
| Find by visible text | `get_by_text` | yes | `text ".."` | https://playwright.dev/python/docs/api/class-page#page-get-by-text |
| Find by form label | `get_by_label` | yes | `label ".."` | https://playwright.dev/python/docs/api/class-page#page-get-by-label |
| Find by placeholder | `get_by_placeholder` | yes | `placeholder ".."` | https://playwright.dev/python/docs/api/class-page#page-get-by-placeholder |
| Find by image alt text | `get_by_alt_text` | yes | `alt ".."` | https://playwright.dev/python/docs/api/class-page#page-get-by-alt-text |
| Find by title attribute | `get_by_title` | yes | `title ".."` | https://playwright.dev/python/docs/api/class-page#page-get-by-title |
| Find by test id (data-testid and others) | `get_by_test_id`, `selectors.set_test_id_attribute` | yes | `testid ".."` (Dejo keeps the attribute name with the value, so data-qa, data-cy and so on work) | https://playwright.dev/python/docs/api/class-selectors#selectors-set-test-id-attribute |
| Find by CSS or other selector | `page.locator` | yes | `css ".."` (the text goes to `page.locator`, pierces open shadow DOM) | https://playwright.dev/python/docs/api/class-page#page-locator |
| Find by snapshot ref | `page.get_by_ref`, `aria-ref=` | yes | refs like `e12`, `f1e3` from `look` | https://playwright.dev/python/docs/api/class-page#page-get-by-ref |
| Pick first, last or Nth match | `locator.first`, `last`, `nth` | yes | `first`, `last`, `nth N` after the target | https://playwright.dev/python/docs/api/class-locator#locator-nth |
| Keep only matches that contain some text | `locator.filter(has_text=)` | yes | `has "text"` after the target | https://playwright.dev/python/docs/api/class-locator#locator-filter |
| Other filters: not containing text, containing / not containing another element, only visible | `locator.filter(has_not_text=, has=, has_not=, visible=)`, `locator.visible` | no | — | https://playwright.dev/python/docs/api/class-locator#locator-filter |
| Search inside another element (a row, a card) | `locator.locator`, `locator.get_by_*` | no | — (`look from REF` only narrows what you see) | https://playwright.dev/python/docs/api/class-locator#locator-locator |
| Match both / either of two locators | `locator.and_`, `locator.or_` | no | — | https://playwright.dev/python/docs/api/class-locator#locator-or |
| Same column in every row (relative inside each parent) | `locator.within` | no | — | https://playwright.dev/python/docs/api/class-locator#locator-within |
| Loop over every match one by one | `locator.all` | partly | `read all_text T`, `read count T` and `read fields '{...}' css "..."` cover every match; no action repeated on each match | https://playwright.dev/python/docs/api/class-locator#locator-all |
| Turn a fleeting ref into a lasting locator | `locator.normalize` | yes | automatic: Dejo stores a lasting locator for each learned step | https://playwright.dev/python/docs/api/class-locator#locator-normalize |
| Elements inside an iframe | `page.frame_locator`, `locator.content_frame`, `FrameLocator` (`locator`, `get_by_*`, `first`, `last`, `nth`, `owner`) | partly | refs reach inside iframes and stored locators keep the iframe; `wait in_frame:FRAME\|CSS`; no way to write "inside this iframe" in a hand-written target | https://playwright.dev/python/docs/api/class-framelocator |
| Register your own selector engine | `selectors.register` | no | — | https://playwright.dev/python/docs/api/class-selectors#selectors-register |

### 5. Locator: actions

| Capability (plain words for users) | Playwright API | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Click an element | `locator.click` | yes | `click T`, with `button=right\|middle`, `keys=Shift+Control`, `at=X,Y` at the end (no force click) | https://playwright.dev/python/docs/api/class-locator#locator-click |
| Double-click | `locator.dblclick` | yes | `double_click T` | https://playwright.dev/python/docs/api/class-locator#locator-dblclick |
| Hover | `locator.hover` | yes | `hover T` | https://playwright.dev/python/docs/api/class-locator#locator-hover |
| Tap (touch) | `locator.tap` | partly | `tap T` only when the engine starts with touch (`Browser(touch=True)`); not reachable from MCP, and `emulate device` does not turn it on | https://playwright.dev/python/docs/api/class-locator#locator-tap |
| Fill a field | `locator.fill` | yes | `fill T "text"` | https://playwright.dev/python/docs/api/class-locator#locator-fill |
| Type key by key | `locator.press_sequentially`, `locator.type` | yes | `type T "text" delay=100` | https://playwright.dev/python/docs/api/class-locator#locator-press-sequentially |
| Empty a field | `locator.clear` | yes | `clear T` | https://playwright.dev/python/docs/api/class-locator#locator-clear |
| Press a key or key chord | `locator.press` | yes | `press KEY [T]` (for example `press Control+A`) | https://playwright.dev/python/docs/api/class-locator#locator-press |
| Tick / untick a box or radio | `locator.check`, `uncheck`, `set_checked` | yes | `check T`, `uncheck T`, `set_checked T true\|false` | https://playwright.dev/python/docs/api/class-locator#locator-check |
| Choose in a dropdown | `locator.select_option` | yes | `select T "opt"` (value, `label:`, `index:`, several with commas; custom comboboxes too) | https://playwright.dev/python/docs/api/class-locator#locator-select-option |
| Attach files to a file field | `locator.set_input_files` | yes | `upload T "path[,path]"` (from disk only, not from memory bytes) | https://playwright.dev/python/docs/api/class-locator#locator-set-input-files |
| Drop files or data dragged in from outside | `locator.drop` | no | — | https://playwright.dev/python/docs/api/class-locator#locator-drop |
| Drag one element onto another | `locator.drag_to`, `page.drag_and_drop` | yes | `drag T to T`; exact spots with `mouse drag X Y to X2 Y2` | https://playwright.dev/python/docs/api/class-locator#locator-drag-to |
| Focus / unfocus | `locator.focus`, `locator.blur` | yes | `focus T`, `blur T` | https://playwright.dev/python/docs/api/class-locator#locator-focus |
| Select all the text in an element | `locator.select_text` | yes | `select_text T` | https://playwright.dev/python/docs/api/class-locator#locator-select-text |
| Fire a DOM event | `locator.dispatch_event` | partly | `dispatch_event T "event"` (no event data such as which key or which button) | https://playwright.dev/python/docs/api/class-locator#locator-dispatch-event |
| Scroll an element into view | `locator.scroll_into_view_if_needed` | yes | `scroll T` | https://playwright.dev/python/docs/api/class-locator#locator-scroll-into-view-if-needed |
| Highlight an element on screen | `locator.highlight`, `hide_highlight` | yes | `highlight T`, `hide_highlight` | https://playwright.dev/python/docs/api/class-locator#locator-highlight |
| Get an element's position and size | `locator.bounding_box` | yes | `read box T as box` (X Y WIDTH HEIGHT) | https://playwright.dev/python/docs/api/class-locator#locator-bounding-box |
| Give a locator a human name for reports | `locator.describe`, `locator.description` | no | — | https://playwright.dev/python/docs/api/class-locator#locator-describe |

### 6. Locator: reading values

| Capability (plain words for users) | Playwright API | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Read an element's text | `locator.inner_text`, `text_content` | yes | `read text T as NAME` | https://playwright.dev/python/docs/api/class-locator#locator-inner-text |
| Read the text of every match | `locator.all_inner_texts`, `all_text_contents` | yes | `read all_text T as NAME` | https://playwright.dev/python/docs/api/class-locator#locator-all-inner-texts |
| Read the whole visible text of the page | `page.inner_text("body")` | yes | `read page_text as NAME`, `read passage "words"` (one section) | https://playwright.dev/python/docs/api/class-page#page-inner-text |
| Read an element's inner HTML | `locator.inner_html` | yes | `read html T as markup` (outer HTML, cut after 20,000 characters) | https://playwright.dev/python/docs/api/class-locator#locator-inner-html |
| Read what is typed in a field | `locator.input_value` | yes | `read value T as NAME` | https://playwright.dev/python/docs/api/class-locator#locator-input-value |
| Read an attribute (href, src...) | `locator.get_attribute` | yes | `read attr NAME T as NAME` | https://playwright.dev/python/docs/api/class-locator#locator-get-attribute |
| Is it ticked? | `locator.is_checked` | yes | `read checked T as NAME` | https://playwright.dev/python/docs/api/class-locator#locator-is-checked |
| Is it visible / hidden? | `locator.is_visible`, `is_hidden` | yes | `read visible T as NAME` | https://playwright.dev/python/docs/api/class-locator#locator-is-visible |
| Is it enabled / disabled? | `locator.is_enabled`, `is_disabled` | yes | `read enabled T as NAME` | https://playwright.dev/python/docs/api/class-locator#locator-is-enabled |
| Can you type in it? | `locator.is_editable` | yes | `read editable T as NAME` | https://playwright.dev/python/docs/api/class-locator#locator-is-editable |
| How many match? | `locator.count` | yes | `read count T as NAME`, `expect count T N` | https://playwright.dev/python/docs/api/class-locator#locator-count |

### 7. Checks (assertions, `expect(...)`)

| Capability (plain words for users) | Playwright API | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| The address is right | `expect(page).to_have_url` | yes | `expect url "x"` | https://playwright.dev/python/docs/api/class-pageassertions#page-assertions-to-have-url |
| The title is right | `expect(page).to_have_title` | partly | `read title` only; no `expect title` | https://playwright.dev/python/docs/api/class-pageassertions#page-assertions-to-have-title |
| An element is visible / hidden | `to_be_visible`, `to_be_hidden` | yes | `expect see T`, `expect gone T`, `expect gone text "x"` | https://playwright.dev/python/docs/api/class-locatorassertions#locator-assertions-to-be-visible |
| Some text is on the page / in an element | `to_have_text`, `to_contain_text` | partly | `expect text "x"` (whole page only; not "this element has this text", no regex) | https://playwright.dev/python/docs/api/class-locatorassertions#locator-assertions-to-have-text |
| Number of matches | `to_have_count` | yes | `expect count T N` | https://playwright.dev/python/docs/api/class-locatorassertions#locator-assertions-to-have-count |
| A field holds a value | `to_have_value` | yes | `expect value T "x"` | https://playwright.dev/python/docs/api/class-locatorassertions#locator-assertions-to-have-value |
| A multi-select holds these values | `to_have_values` | no | — | https://playwright.dev/python/docs/api/class-locatorassertions#locator-assertions-to-have-values |
| Ticked / enabled / disabled / editable | `to_be_checked`, `to_be_enabled`, `to_be_disabled`, `to_be_editable` | partly | `read checked/enabled/editable` give the answer; no `expect` that stops the run | https://playwright.dev/python/docs/api/class-locatorassertions#locator-assertions-to-be-checked |
| Has focus / is on screen / is empty / is in the DOM | `to_be_focused`, `to_be_in_viewport`, `to_be_empty`, `to_be_attached` | no | — | https://playwright.dev/python/docs/api/class-locatorassertions#locator-assertions-to-be-in-viewport |
| Has an attribute, class, id, CSS value, JS property or role | `to_have_attribute`, `to_have_class`, `to_contain_class`, `to_have_id`, `to_have_css`, `to_have_js_property`, `to_have_role` | no | — | https://playwright.dev/python/docs/api/class-locatorassertions#locator-assertions-to-have-attribute |
| Has an accessible name, description or error message | `to_have_accessible_name`, `to_have_accessible_description`, `to_have_accessible_error_message` | no | — | https://playwright.dev/python/docs/api/class-locatorassertions#locator-assertions-to-have-accessible-name |
| Page part matches a saved accessibility snapshot | `to_match_aria_snapshot` | no | — | https://playwright.dev/python/docs/api/class-locatorassertions#locator-assertions-to-match-aria-snapshot |
| The opposite of any check ("not ...") | `not_to_*` | partly | only `expect gone T` and `expect gone text "x"` | https://playwright.dev/python/docs/api/class-locatorassertions#locator-assertions-not-to-have-text |
| Every step checks it really happened | (Playwright has no such rule) | yes | built in: every learned step has a postcondition | https://playwright.dev/python/docs/test-assertions |

### 8. Frames

| Capability (plain words for users) | Playwright API | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Act and read inside an iframe | `frame.*` (same actions as page), `frame_locator` | partly | refs like `f1e3` work for every action and read; no hand-written "in frame" target | https://playwright.dev/python/docs/api/class-frame |
| Find a frame by name or address | `page.frame(name=, url=)`, `page.frames`, `page.main_frame` | no | — | https://playwright.dev/python/docs/api/class-page#page-frame |
| Walk the frame tree (parent, children, its element) | `frame.parent_frame`, `child_frames`, `frame_element` | no | — | https://playwright.dev/python/docs/api/class-frame#frame-child-frames |
| Wait for something inside an iframe | `frame_locator(...).locator(...).wait_for` | yes | `wait in_frame:FRAME\|CSS` | https://playwright.dev/python/docs/api/class-framelocator#frame-locator-locator |
| Read a frame's address, title, HTML | `frame.url`, `frame.title`, `frame.content` | no | — | https://playwright.dev/python/docs/api/class-frame#frame-url |

### 9. Keyboard, mouse, touchscreen

| Capability (plain words for users) | Playwright API | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Press a key on whatever has focus | `keyboard.press` | yes | `press KEY` with no target | https://playwright.dev/python/docs/api/class-keyboard#keyboard-press |
| Type text into whatever has focus | `keyboard.type` | partly | `type T "text" delay=MS` needs a target; only single keys go to whatever has focus (`press KEY`) | https://playwright.dev/python/docs/api/class-keyboard#keyboard-type |
| Paste-like text input (one input event, no key presses) | `keyboard.insert_text` | no | — (`fill` is close but needs a target) | https://playwright.dev/python/docs/api/class-keyboard#keyboard-insert-text |
| Hold a key down and let it go (Shift held while clicking) | `keyboard.down`, `keyboard.up` | yes | `keydown Shift` ... `keyup Shift`, or `keys=Shift` at the end of a click | https://playwright.dev/python/docs/api/class-keyboard#keyboard-down |
| Click or double-click at x, y on the screen | `mouse.click`, `mouse.dblclick` | yes | `mouse click X Y`, `mouse dblclick X Y`, `mouse right X Y` | https://playwright.dev/python/docs/api/class-mouse#mouse-click |
| Move the mouse, press and release (draw, sliders, canvas, hand-made drag) | `mouse.move`, `mouse.down`, `mouse.up` | yes | `mouse move X Y`, `mouse down`, `mouse up`, `mouse drag X Y to X2 Y2` | https://playwright.dev/python/docs/api/class-mouse#mouse-move |
| Scroll with the mouse wheel | `mouse.wheel` | yes | `mouse wheel DX DY`, `scroll down\|up\|left\|right [PIXELS]`, `scroll T down 300` (inside one panel) | https://playwright.dev/python/docs/api/class-mouse#mouse-wheel |
| Tap at x, y on a touch screen | `touchscreen.tap` | partly | `tap T` taps an element, and only in touch mode (engine only); no tap at x, y | https://playwright.dev/python/docs/api/class-touchscreen#touchscreen-tap |

### 10. Dialogs, downloads, file choosers

| Capability (plain words for users) | Playwright API | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Say OK to alert / confirm / prompt / leave-page boxes | `dialog.accept`, event `dialog` | yes | automatic, or `dialog accept` before the step that opens the box; replay stops if the message changed | https://playwright.dev/python/docs/api/class-dialog#dialog-accept |
| Say Cancel to a dialog | `dialog.dismiss` | yes | `dialog dismiss` before the step that opens the box | https://playwright.dev/python/docs/api/class-dialog#dialog-dismiss |
| Type an answer into a prompt box | `dialog.accept(prompt_text)` | yes | `dialog accept "text"` | https://playwright.dev/python/docs/api/class-dialog#dialog-accept |
| Read the dialog's message, kind and default text | `dialog.message`, `type`, `default_value` | yes | `read dialog as msg`; also recorded in the reply | https://playwright.dev/python/docs/api/class-dialog#dialog-message |
| Save a download | `download.save_as`, `download.path`, event `download`, `expect_download` | partly | automatic, always to `~/.dejo/downloads`; no choice of folder or file name | https://playwright.dev/python/docs/api/class-download#download-save-as |
| Read a download's address, suggested name, error | `download.url`, `suggested_filename`, `failure` | partly | `read downloads as files` lists the saved paths, and a download counts as a postcondition. Missing: its address and a failure reason | https://playwright.dev/python/docs/api/class-download#download-suggested-filename |
| Cancel or delete a download | `download.cancel`, `download.delete` | no | — | https://playwright.dev/python/docs/api/class-download#download-cancel |
| Answer the operating system's file picker | `page.expect_file_chooser`, `file_chooser.set_files` | yes | `upload T "path"` catches it on its own | https://playwright.dev/python/docs/api/class-filechooser#file-chooser-set-files |

### 11. Network: requests, responses, routes

| Capability (plain words for users) | Playwright API | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| See the list of requests the page made | `page.requests`, events `request`, `requestfinished` | yes | `read requests ["words"] as calls` (METHOD STATUS URL) | https://playwright.dev/python/docs/api/class-page#page-requests |
| See requests that failed | event `requestfailed`, HTTP errors on `response` | yes | `read requests` (shows network failures too), `read failed_requests` (HTTP 400 and above) | https://playwright.dev/python/docs/api/class-page#page-event-request-failed |
| Read a request's method, headers and posted data | `request.method`, `headers`, `all_headers`, `post_data`, `post_data_json`, `resource_type` | partly | `read requests` gives the method; no headers, posted data or resource type | https://playwright.dev/python/docs/api/class-request#request-post-data-json |
| Read a response's status and headers | `response.status`, `ok`, `headers`, `header_value` | partly | `read requests` gives the status; no headers | https://playwright.dev/python/docs/api/class-response#response-status |
| Read a response's body or JSON (the data behind the page) | `response.body`, `text`, `json` | yes | `read response "/api/orders" as orders` (up to 20,000 characters) | https://playwright.dev/python/docs/api/class-response#response-json |
| Request timing, sizes, redirects, TLS and server address | `request.timing`, `sizes`, `redirected_from`, `response.security_details`, `server_addr` | no | — | https://playwright.dev/python/docs/api/class-request#request-timing |
| Wait for a certain request or response | `page.expect_request`, `expect_response`, `expect_request_finished` | yes | `wait request:WORDS`, `wait response:WORDS` | https://playwright.dev/python/docs/api/class-page#page-wait-for-response |
| Block requests (ads, images, trackers) | `page.route` / `context.route` + `route.abort` | yes | `block "**/*.png"`; `block off [PATTERN]` | https://playwright.dev/python/docs/api/class-route#route-abort |
| Answer a request with fake data (mock) | `route.fulfill` | partly | `mock "**/api/user" 200 '{"name": "Asha"}'`, `mock off` (status and body only, no headers of your own; not kept in a trail) | https://playwright.dev/python/docs/api/class-route#route-fulfill |
| Change a request on its way (headers, URL, body) | `route.continue_`, `route.fallback` | partly | `header set NAME "VALUE"` adds a header to every request; no change of one request's URL or body | https://playwright.dev/python/docs/api/class-route#route-continue |
| Fetch the real answer, change it, then hand it to the page | `route.fetch` + `route.fulfill` | no | — | https://playwright.dev/python/docs/api/class-route#route-fetch |
| Stop routing | `unroute`, `unroute_all` | yes | `block off [PATTERN]`, `mock off [PATTERN]` | https://playwright.dev/python/docs/api/class-page#page-unroute-all |
| Replay the network from a saved HAR file | `route_from_har` | no | — | https://playwright.dev/python/docs/api/class-browsercontext#browser-context-route-from-har |
| Record the network to a HAR file | `tracing.start_har`, `stop_har`, `record_har_path` option | no | — | https://playwright.dev/python/docs/api/class-tracing#tracing-start-har |
| Watch WebSocket messages | event `websocket`, `WebSocket` (`framesent`, `framereceived`), `expect_websocket` | no | — | https://playwright.dev/python/docs/api/class-websocket |
| Mock or change WebSocket messages | `route_web_socket`, `WebSocketRoute` | no | — | https://playwright.dev/python/docs/api/class-websocketroute |
| Call a web API directly with the browser's cookies | `page.request` / `context.request` (`APIRequestContext.get`, `post`, `fetch`...) | no | — | https://playwright.dev/python/docs/api/class-apirequestcontext |
| Send extra headers on every request | `set_extra_http_headers`, `extra_http_headers` option | yes | `header set NAME "VALUE"`, `header clear` | https://playwright.dev/python/docs/api/class-browsercontext#browser-context-set-extra-http-headers |
| Go offline | `context.set_offline`, `offline` option | yes | `emulate offline on`; `emulate offline off` | https://playwright.dev/python/docs/api/class-browsercontext#browser-context-set-offline |

### 12. Browser context (one browser session: cookies, storage, settings)

| Capability (plain words for users) | Playwright API | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Separate sessions side by side (two accounts) | `browser.new_context`, `launch_persistent_context` | yes | `dejo_profile(name)` and the `profile` argument of `dejo_run` | https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context |
| Stay signed in between runs | `launch_persistent_context(user_data_dir)` | yes | profiles keep cookies and storage; `dejo_login` opens a window to sign in by hand | https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context |
| Save and load the signed-in state as a file | `context.storage_state`, `set_storage_state`, `storage_state` option | yes | `state save NAME`, `state load NAME\|"/path/state.json"` (Playwright's storage-state format) | https://playwright.dev/python/docs/api/class-browsercontext#browser-context-storage-state |
| Read, add or clear cookies | `context.cookies`, `add_cookies`, `clear_cookies` | yes | `read cookies ["words"]`, `cookie set NAME "VALUE"`, `cookie clear [NAME]` | https://playwright.dev/python/docs/api/class-browsercontext#browser-context-cookies |
| Give a site permissions (camera, notifications, clipboard) | `grant_permissions`, `clear_permissions`, `permissions` option | yes | `allow notifications clipboard-read camera`, `allow off` | https://playwright.dev/python/docs/api/class-browsercontext#browser-context-grant-permissions |
| Pretend to be at a place on the map | `set_geolocation`, `geolocation` option | yes | `emulate geolocation 18.52,73.85` | https://playwright.dev/python/docs/api/class-browsercontext#browser-context-set-geolocation |
| Pretend to be a phone (size, touch, mobile mode, pixel ratio) | `playwright.devices`, `is_mobile`, `has_touch`, `device_scale_factor`, `screen` options | yes | `emulate device "iPhone 13"` (Playwright's device list; `tap` still needs touch mode) | https://playwright.dev/python/docs/emulation#devices |
| Choose the language | `locale` option | yes | `emulate locale de-DE`, or the `DEJO_LOCALE` setting | https://playwright.dev/python/docs/api/class-browser#browser-new-context-option-locale |
| Choose the time zone | `timezone_id` option | yes | `emulate timezone Asia/Tokyo` | https://playwright.dev/python/docs/api/class-browser#browser-new-context-option-timezone-id |
| Set your own user agent | `user_agent` option | partly | only the one that comes with `emulate device "..."`; you cannot write your own string | https://playwright.dev/python/docs/api/class-browser#browser-new-context-option-user-agent |
| Sign in to sites with HTTP basic auth | `http_credentials` option | partly | `header set Authorization "Basic ..."`; no username and password option | https://playwright.dev/python/docs/api/class-browser#browser-new-context-option-http-credentials |
| Use a client certificate | `client_certificates` option | no | — | https://playwright.dev/python/docs/api/class-browser#browser-new-context-option-client-certificates |
| Open sites with bad HTTPS certificates (local test servers) | `ignore_https_errors` option | yes | `DEJO_IGNORE_HTTPS_ERRORS=1` | https://playwright.dev/python/docs/api/class-browser#browser-new-context-option-ignore-https-errors |
| Turn JavaScript off | `java_script_enabled` option | no | — | https://playwright.dev/python/docs/api/class-browser#browser-new-context-option-java-script-enabled |
| Ignore the site's content security policy | `bypass_csp` option | no | — | https://playwright.dev/python/docs/api/class-browser#browser-new-context-option-bypass-csp |
| Short addresses relative to a base URL | `base_url` option | no | — | https://playwright.dev/python/docs/api/class-browser#browser-new-context-option-base-url |
| Block service workers | `service_workers` option, `context.service_workers` | no | — | https://playwright.dev/python/docs/api/class-browser#browser-new-context-option-service-workers |
| Accept downloads | `accept_downloads` option | yes | automatic | https://playwright.dev/python/docs/api/class-browser#browser-new-context-option-accept-downloads |
| Fake passkeys / WebAuthn sign-in | `context.credentials` (`Credentials.install`, `create`, `get`, `delete`) | no | — | https://playwright.dev/python/docs/api/class-credentials |
| Work with browser extensions (their background pages) | `context.background_pages`, `launch_persistent_context(args=...)` | no | — | https://playwright.dev/python/docs/api/class-browsercontext#browser-context-background-pages |

### 13. Browser and browser type (start, connect)

| Capability (plain words for users) | Playwright API | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Start Chromium | `chromium.launch` | yes | automatic | https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch |
| Start Firefox or WebKit (Safari engine) | `firefox.launch`, `webkit.launch` | no | — (Chromium only) | https://playwright.dev/python/docs/api/class-browsertype |
| Use real Chrome or Edge, or a browser at a given path | `channel`, `executable_path` options | partly | real Chrome if installed, else bundled Chromium; Edge or another Chromium only by starting it yourself and `DEJO_CDP_URL=...`; no path option | https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-option-channel |
| Show the window or run hidden | `headless` option | yes | `DEJO_HEADED=1` (or `dejo run --headed`); headless otherwise | https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-option-headless |
| Slow every action down to watch it | `slow_mo` option | no | — | https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-option-slow-mo |
| Go through a proxy server | `proxy` option | partly | `DEJO_PROXY=http://proxy:8080` (server only). Missing: bypass list, username and password | https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-option-proxy |
| Pass your own browser flags | `args`, `ignore_default_args`, `env` options | no | — | https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-option-args |
| Choose where downloads go | `downloads_path` option | partly | fixed: `~/.dejo/downloads` | https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-option-downloads-path |
| Attach to a Chrome that is already running (over CDP) | `chromium.connect_over_cdp` | yes | `DEJO_CDP_URL=http://127.0.0.1:9222` (or `dejo run --cdp URL`) | https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-cdp |
| Connect to a remote Playwright browser server | `browser_type.connect` | no | — | https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect |
| Share this browser so other clients can connect | `browser.bind`, `browser.unbind` | no | — | https://playwright.dev/python/docs/api/class-browser#browser-bind |
| Send raw Chrome DevTools commands | `context.new_cdp_session`, `browser.new_browser_cdp_session`, `CDPSession.send` | no | — | https://playwright.dev/python/docs/api/class-cdpsession#cdp-session-send |
| Chrome performance trace (for DevTools Performance panel) | `browser.start_tracing`, `stop_tracing` | yes | `record performance` ... `record stop` | https://playwright.dev/python/docs/api/class-browser#browser-start-tracing |
| Read the browser version | `browser.version` | no | — (`dejo doctor` on the command line checks the setup) | https://playwright.dev/python/docs/api/class-browser#browser-version |
| Hide that the browser is automated (stealth flags, fake fingerprint) | `args`, `ignore_default_args`, `add_init_script` used for stealth | not in Dejo, on purpose | Dejo only drops Chrome's "automation" flag and the "HeadlessChrome" word; no fingerprint hiding | https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-option-ignore-default-args |
| Solve a captcha or get round a bot wall | (none in Playwright; done by add-ons) | not in Dejo, on purpose | Dejo stops and hands over to the person | https://playwright.dev/python/docs/api/class-page |

### 14. Tracing, video, clock

| Capability (plain words for users) | Playwright API | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Record a trace (steps, screenshots, DOM, network) to open in Trace Viewer | `context.tracing.start`, `stop`, `start_chunk`, `stop_chunk` | yes | `record trace` ... `record stop`, or `DEJO_RECORD=trace` for every replay | https://playwright.dev/python/docs/api/class-tracing#tracing-start |
| Group steps under a name in the trace | `tracing.group`, `group_end` | no | — | https://playwright.dev/python/docs/api/class-tracing#tracing-group |
| Record a video of the run | `record_video_dir` option, `page.video`, `Video.save_as`, `path`, `delete` | yes | `record video` ... `record stop`, or `DEJO_RECORD=video` for every replay | https://playwright.dev/python/docs/api/class-video#video-save-as |
| Freeze the page's clock at a date | `clock.set_fixed_time` | yes | `set_time "2026-09-15"` | https://playwright.dev/python/docs/api/class-clock#clock-set-fixed-time |
| Set the clock but let it keep running | `clock.set_system_time` | no | — | https://playwright.dev/python/docs/api/class-clock#clock-set-system-time |
| Take control of timers (setTimeout, setInterval) | `clock.install` | no | — | https://playwright.dev/python/docs/api/class-clock#clock-install |
| Jump time forward (skip a 30-minute timeout) | `clock.fast_forward`, `clock.run_for` | no | — | https://playwright.dev/python/docs/api/class-clock#clock-fast-forward |
| Pause time at a moment, then resume | `clock.pause_at`, `clock.resume` | no | — | https://playwright.dev/python/docs/api/class-clock#clock-pause-at |

### 15. Events you can listen to

| Capability (plain words for users) | Playwright API | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| A dialog appeared | `page.on("dialog")` | yes | handled and recorded automatically | https://playwright.dev/python/docs/api/class-page#page-event-dialog |
| A download started | `page.on("download")` | yes | handled automatically | https://playwright.dev/python/docs/api/class-page#page-event-download |
| A file picker opened | `page.on("filechooser")` | yes | handled by `upload` | https://playwright.dev/python/docs/api/class-page#page-event-file-chooser |
| A pop-up or new tab opened | `page.on("popup")`, `context.on("page")` | yes | noticed and reported | https://playwright.dev/python/docs/api/class-page#page-event-popup |
| A console message | `page.on("console")`, `context.on("console")` | yes | `read console` (every message), `read console_errors` | https://playwright.dev/python/docs/api/class-page#page-event-console |
| An uncaught page error | `page.on("pageerror")`, `context.on("weberror")` | yes | via `read console_errors` | https://playwright.dev/python/docs/api/class-page#page-event-page-error |
| Requests and responses | `request`, `response`, `requestfinished`, `requestfailed` | yes | `read requests`, `read response "words"`, `wait request:WORDS`, `wait response:WORDS` | https://playwright.dev/python/docs/api/class-page#page-event-response |
| Page loaded / DOM ready | `page.on("load")`, `page.on("domcontentloaded")` | no | — | https://playwright.dev/python/docs/api/class-page#page-event-load |
| A frame was added, removed or moved to a new address | `frameattached`, `framedetached`, `framenavigated` | no | — | https://playwright.dev/python/docs/api/class-page#page-event-frame-navigated |
| The page crashed | `page.on("crash")` | no | — | https://playwright.dev/python/docs/api/class-page#page-event-crash |
| A tab was closed | `page.on("close")`, `context.on("close")` | no | — | https://playwright.dev/python/docs/api/class-page#page-event-close |
| A WebSocket opened | `page.on("websocket")` | no | — | https://playwright.dev/python/docs/api/class-page#page-event-web-socket |
| A worker or service worker started | `page.on("worker")`, `context.on("serviceworker")` | partly | `read workers` lists web workers. Missing: an event, and service workers | https://playwright.dev/python/docs/api/class-page#page-event-worker |
| The browser went away | `browser.on("disconnected")` | no | — | https://playwright.dev/python/docs/api/class-browser#browser-event-disconnected |

---

## Playwright MCP

Source: <https://github.com/microsoft/playwright-mcp>. License:** Apache License 2.0. Copyright line (LICENSE, line 189, and every source file header): `Copyright (c) Microsoft Corporation.` There is no NOTICE file.

### 1. Tools

#### 1a. Core tools (always on)

| Capability (plain words) | Playwright MCP tool / option (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Open a web address | `browser_navigate` (`url`) | yes | `go URL` (or the `url` argument of `dejo_run`) | [navigate.ts#L24](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/navigate.ts#L24) |
| Go back one page | `browser_navigate_back` (none) | yes | `back` | [navigate.ts#L45](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/navigate.ts#L45) |
| Go forward one page | `browser_navigate_forward` (none) (CLI only) | yes | `forward` | [navigate.ts#L63](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/navigate.ts#L63) |
| Reload the page | `browser_reload` (none) (CLI only) | yes | `reload` | [navigate.ts#L81](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/navigate.ts#L81) |
| See the page as a tree of elements with refs | `browser_snapshot` (`target`, `filename`, `depth`, `boxes`) | partly | `look`, `look from REF`, `look gN`, `look all`, `look raw`. Missing: depth limit, element boxes (x,y,w,h), save to a file | [snapshot.ts#L38](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/snapshot.ts#L38) |
| Search the page tree for words | `browser_find` (`text`, `regex`, `maxResults`, `filename`) | partly | `look WORDS`. Missing: regular expressions, a result limit, save to a file | [find.ts#L27](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/find.ts#L27) |
| Click an element | `browser_click` (`element`, `target`, `doubleClick`, `button` left/right/middle, `modifiers` Alt/Control/ControlOrMeta/Meta/Shift) | yes | `click T`, `double_click T`, with `button=right\|middle` or `keys=Shift+Control` at the end | [snapshot.ts#L67](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/snapshot.ts#L67) |
| Drag one element onto another | `browser_drag` (`startElement`, `startTarget`, `endElement`, `endTarget`) | yes | `drag T to T` | [snapshot.ts#L103](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/snapshot.ts#L103) |
| Move the mouse over an element | `browser_hover` (`element`, `target`) | yes | `hover T` | [snapshot.ts#L134](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/snapshot.ts#L134) |
| Choose option(s) in a dropdown | `browser_select_option` (`element`, `target`, `values[]`) | yes | `select T "a,b"` (by value, `label:`, `index:`; also custom comboboxes) | [snapshot.ts#L158](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/snapshot.ts#L158) |
| Tick a checkbox or radio | `browser_check` (`element`, `target`) (CLI only) | yes | `check T` / `set_checked T true` | [snapshot.ts#L196](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/snapshot.ts#L196) |
| Untick a checkbox | `browser_uncheck` (`element`, `target`) (CLI only) | yes | `uncheck T` / `set_checked T false` | [snapshot.ts#L214](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/snapshot.ts#L214) |
| Type text into a field (fast fill, or key by key, optional Enter after) | `browser_type` (`element`, `target`, `text`, `submit`, `slowly`) | yes | `fill T "text"` (fast), `type T "text"` (key by key), then `press Enter T` | [keyboard.ts#L87](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/keyboard.ts#L87) |
| Press one key or key chord | `browser_press_key` (`key`) | yes | `press KEY [T]` (chords like `Control+A` work) | [keyboard.ts#L26](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/keyboard.ts#L26) |
| Type text key by key on the page, with no element | `browser_press_sequentially` (`text`, `submit`) (CLI only) | partly | `type T "text"` needs an element. Missing: typing into whatever has focus | [keyboard.ts#L54](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/keyboard.ts#L54) |
| Hold a key down / let it go | `browser_keydown` (`key`), `browser_keyup` (`key`) (CLI only) | yes | `keydown KEY`, `keyup KEY` | [keyboard.ts#L127](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/keyboard.ts#L127), [#L147](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/keyboard.ts#L147) |
| Fill many form fields in one call | `browser_fill_form` (`fields[]`: `name`, `type` textbox/checkbox/radio/combobox/slider, `target`, `value`) | yes | one line per field (`fill`, `check`, `select`) in the same `dejo_run` call | [form.ts#L26](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/form.ts#L26) |
| Upload files into an open file picker, or cancel it | `browser_file_upload` (`paths[]`; leave out to cancel the picker) | partly | `upload T "a.pdf,b.pdf"` (file input or file chooser). Missing: cancel an open file picker | [files.ts#L26](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/files.ts#L26) |
| Drop files or data onto a drop zone (as if dragged in from outside) | `browser_drop` (`element`, `target`, `paths[]`, `data` {mime: value}) | no | — | [files.ts#L66](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/files.ts#L66) |
| Answer a pop-up (alert / confirm / prompt) | `browser_handle_dialog` (`accept`, `promptText`) | yes | `dialog accept`, `dialog accept "text"`, `dialog dismiss` (before the step that opens it); otherwise accepted on its own | [dialogs.ts#L24](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/dialogs.ts#L24) |
| Wait for time, for text to show, or for text to go | `browser_wait_for` (`time` max 30 s, `text`, `textGone`) | yes | `wait SECONDS`, `wait text:WORDS`, `wait "text:Saved\|Error"`, `wait gone:CSS`, `expect gone text "x"` | [wait.ts#L26](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/wait.ts#L26) |
| Run JavaScript in the page or on one element | `browser_evaluate` (`element`, `target`, `function`, `filename`) | partly | `js CODE` (page or element; must be alone; not remembered). Missing: save the result to a file | [evaluate.ts#L33](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/evaluate.ts#L33) |
| Run any Playwright code on the server (`page` object) | `browser_run_code_unsafe` (`code`, `filename`) | no | — (`js` runs inside the page, not Playwright code) | [runCode.ts#L40](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/runCode.ts#L40) |
| Take a screenshot | `browser_take_screenshot` (`element`, `target`, `type` png/jpeg/webp, `filename`, `fullPage`, `scale` css/device) | partly | `screenshot [T\|full] [as NAME]` saves a file; `look image` sends the picture to the agent. Missing: JPEG/WebP and scale choice | [screenshot.ts#L51](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/screenshot.ts#L51) |
| Read console messages | `browser_console_messages` (`level` error/warning/info/debug, `all`, `filename`) | yes | `read console as log` (every level), `read console_errors`. Missing only a level filter and saving to a file | [console.ts#L23](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/console.ts#L23) |
| Clear the console list | `browser_console_clear` (none) (CLI only) | no | — | [console.ts#L48](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/console.ts#L48) |
| List network requests | `browser_network_requests` (`static`, `filter` regex, `all`, `filename`) | yes | `read requests ["words"] as calls` (METHOD STATUS URL; words, not a regex) | [network.ts#L34](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/network.ts#L34) |
| Read one request in full (headers, body, response) | `browser_network_request` (`index`, `part` request-headers/request-body/response-headers/response-body, `filename`) | partly | `read response "words"` gives the response body. Missing: request and response headers, request body | [network.ts#L78](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/network.ts#L78) |
| Clear the request list | `browser_network_clear` (none) (CLI only) | no | — | [network.ts#L107](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/network.ts#L107) |
| Change light/dark mode, reduced motion, print media | `browser_emulate_media` (`colorScheme`, `reducedMotion`, `forcedColors`, `contrast`, `media` screen/print) | partly | `emulate color dark`, `emulate motion reduce`, `emulate media print`. Missing: forced colors, contrast | [emulation.ts#L25](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/emulation.ts#L25) |
| Change the window / viewport size | `browser_resize` (`width`, `height`) | yes | `emulate viewport 1024x768` | [common.ts#L45](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/common.ts#L45) |
| Close the browser | `browser_close` (none) | no | — (Dejo opens and closes the browser itself) | [common.ts#L25](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/common.ts#L25) |
| Tabs: list, open, close, switch; open a tab in a separate named login world | `browser_tabs` (`action` list/new/close/select, `index`, `url`, `isolatedContext`) | partly | `read tabs`, `tab new [URL]`, `tab close [N]`, `tab N\|latest\|main`. Missing: a tab in a separate cookie world (Dejo uses whole profiles: `dejo_profile`) | [tabs.ts#L25](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/tabs.ts#L25) |
| List tools a web page offers through WebMCP | `browser_webmcp_list` (none) (CLI only) | no | — | [webmcp.ts#L157](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/webmcp.ts#L157) |
| Call a tool a web page offers through WebMCP | `browser_webmcp_call` (`name`, `params`, `frame`) (CLI only) | no | — | [webmcp.ts#L181](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/webmcp.ts#L181) |

#### 1b. Opt-in tools (`--caps=...`)

| Capability (plain words) | Playwright MCP tool / option (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Show the final settings the server runs with | `browser_get_config` (none) — caps `config` | no | — | [config.ts#L24](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/config.ts#L24) |
| Go offline / back online | `browser_network_state_set` (`state` online/offline) — caps `network` | yes | `emulate offline on`, `emulate offline off` | [network.ts#L268](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/network.ts#L268) |
| Fake a server answer, or add/remove request headers | `browser_route` (`pattern`, `status`, `body`, `contentType`, `headers[]`, `removeHeaders`) — caps `network` | partly | `mock "PATTERN" STATUS "BODY"`, `header set NAME "VALUE"`. Missing: headers on the fake answer, removing a header | [route.ts#L28](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/route.ts#L28) |
| List the fake answers set up | `browser_route_list` (none) — caps `network` | no | — | [route.ts#L103](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/route.ts#L103) |
| Remove fake answers | `browser_unroute` (`pattern`) — caps `network` | yes | `mock off [PATTERN]` | [route.ts#L143](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/route.ts#L143) |
| List cookies | `browser_cookie_list` (`domain`, `path`) — caps `storage` | yes | `read cookies ["words"] as c` (an httpOnly cookie's value is hidden) | [cookies.ts#L25](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/cookies.ts#L25) |
| Read one cookie | `browser_cookie_get` (`name`) — caps `storage` | partly | `read cookies "NAME"`; an httpOnly cookie's value is hidden | [cookies.ts#L61](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/cookies.ts#L61) |
| Set a cookie | `browser_cookie_set` (`name`, `value`, `domain`, `path`, `expires`, `httpOnly`, `secure`, `sameSite`) — caps `storage` | partly | `cookie set NAME "VALUE"` for this page's site. Missing: domain, path, expiry, httpOnly, secure, sameSite | [cookies.ts#L87](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/cookies.ts#L87) |
| Delete one cookie | `browser_cookie_delete` (`name`, `domain`, `path`) — caps `storage` | yes | `cookie clear NAME` | [cookies.ts#L136](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/cookies.ts#L136) |
| Delete all cookies | `browser_cookie_clear` (none) — caps `storage` | yes | `cookie clear` | [cookies.ts#L160](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/cookies.ts#L160) |
| localStorage: list / get / set / delete / clear | `browser_localstorage_list` (none), `_get` (`key`), `_set` (`key`, `value`), `_delete` (`key`), `_clear` (none) — caps `storage` | yes | `read storage ["key"]`, `storage set KEY "VALUE"`, `storage clear [KEY]` | [webstorage.ts#L25](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/webstorage.ts#L25) (to #L110) |
| sessionStorage: list / get / set / delete / clear | `browser_sessionstorage_list` (none), `_get` (`key`), `_set` (`key`, `value`), `_delete` (`key`), `_clear` (none) — caps `storage` | partly | only through a lone `js` line. Missing: a real step | [webstorage.ts#L129](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/webstorage.ts#L129) (to #L214) |
| Save the sign-in state (cookies + localStorage) to a file | `browser_storage_state` (`filename`) — caps `storage` | yes | `state save NAME` (to `~/.dejo/states/NAME.json`) | [storage.ts#L25](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/storage.ts#L25) |
| Load a saved sign-in state from a file | `browser_set_storage_state` (`filename`) — caps `storage` | yes | `state load NAME\|"/path/state.json"` | [storage.ts#L48](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/storage.ts#L48) |
| Person draws notes on the page; agent gets picture + notes | `browser_annotate` (none) — caps `devtools` | no | — | [devtools.ts#L126](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/devtools.ts#L126) |
| Draw a box around an element | `browser_highlight` (`element`, `target`, `style` CSS) — caps `devtools` | partly | `highlight T`. Missing: own CSS style for the box | [devtools.ts#L83](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/devtools.ts#L83) |
| Remove the box | `browser_hide_highlight` (`element`, `target`) — caps `devtools` | yes | `hide_highlight` (removes all boxes) | [devtools.ts#L102](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/devtools.ts#L102) |
| Continue a paused test script (debugger step) | `browser_resume` (`step`, `location` file:line) — caps `devtools` | no | — | [devtools.ts#L31](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/devtools.ts#L31) |
| Record what the person does by hand, as code | `browser_start_recording` (none), `browser_stop_recording` (none) — caps `devtools` | no | — (`dejo_login` opens a window for the person, but nothing is recorded) | [recorder.ts#L25](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/recorder.ts#L25), [#L44](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/recorder.ts#L44) |
| Record a trace (actions, screenshots, DOM, network) for Trace Viewer | `browser_start_tracing` (none), `browser_stop_tracing` (none) — caps `devtools` | yes | `record trace` ... `record stop`, or `DEJO_RECORD=trace` | [tracing.ts#L28](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/tracing.ts#L28), [#L46](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/tracing.ts#L46) |
| Record a video of the browser | `browser_start_video` (`filename`, `size` {width,height}, `fps`, `cursor`), `browser_stop_video` (none) — caps `devtools` | partly | `record video` ... `record stop`, or `DEJO_RECORD=video`. Missing: size, fps and cursor options | [video.ts#L24](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/video.ts#L24), [#L50](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/video.ts#L50) |
| Put a title card into the video | `browser_video_chapter` (`title`, `description`, `duration`) — caps `devtools` | no | — | [video.ts#L78](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/video.ts#L78) |
| Show / hide labels for each action on screen (for videos) | `browser_video_show_actions` (`duration`, `position`, `cursor`, `style` {point, highlight, title}), `browser_video_hide_actions` (none) — caps `devtools` | no | — | [video.ts#L106](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/video.ts#L106), [#L138](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/video.ts#L138) |
| Click at x,y on the screen | `browser_mouse_click_xy` (`x`, `y`, `button`, `clickCount`, `delay`) — caps `vision` | yes | `mouse click X Y`, `mouse dblclick X Y`, `mouse right X Y` | [mouse.ts#L111](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/mouse.ts#L111) |
| Move the mouse to x,y | `browser_mouse_move_xy` (`x`, `y`) — caps `vision` | yes | `mouse move X Y` | [mouse.ts#L24](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/mouse.ts#L24) |
| Press / release a mouse button | `browser_mouse_down` (`button`), `browser_mouse_up` (`button`) — caps `vision` | partly | `mouse down`, `mouse up` (left button only) | [mouse.ts#L46](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/mouse.ts#L46), [#L69](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/mouse.ts#L69) |
| Drag from one x,y to another x,y | `browser_mouse_drag_xy` (`startX`, `startY`, `endX`, `endY`) — caps `vision` | yes | `mouse drag X Y to X2 Y2` | [mouse.ts#L147](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/mouse.ts#L147) |
| Turn the mouse wheel | `browser_mouse_wheel` (`deltaX`, `deltaY`) — caps `vision` | yes | `mouse wheel DX DY`, `scroll T down\|up\|left\|right [PIXELS]` | [mouse.ts#L91](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/mouse.ts#L91) |
| Save the page as a PDF | `browser_pdf_save` (`filename`) — caps `pdf` | yes | `pdf [as NAME]` | [pdf.ts#L30](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/pdf.ts#L30) |
| Make a stable locator for an element (for tests) | `browser_generate_locator` (`element`, `target`) — caps `testing` | partly | Dejo builds and stores its own locators for every learned step. Missing: a way to ask for one on request | [snapshot.ts#L178](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/snapshot.ts#L178) |
| Check an element with this role and name is shown | `browser_verify_element_visible` (`role`, `accessibleName`) — caps `testing` | yes | `expect see role "name"` | [verify.ts#L27](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/verify.ts#L27) |
| Check some text is shown | `browser_verify_text_visible` (`text`) — caps `testing` | yes | `expect text "x"` | [verify.ts#L54](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/verify.ts#L54) |
| Check a list holds these items | `browser_verify_list_visible` (`element`, `target`, `items[]`) — caps `testing` | partly | one `expect text` line per item, or `read all_text T`. Missing: one check that the items are inside that list | [verify.ts#L80](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/verify.ts#L80) |
| Check a field's value or a checkbox's state | `browser_verify_value` (`type`, `element`, `target`, `value`) — caps `testing` | partly | `expect value T "x"` for fields. Missing: an `expect` for checked/unchecked (only `read checked`) | [verify.ts#L112](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/verify.ts#L112) |

#### 1c. Automatic behaviour (no tool name)

| Capability (plain words) | Playwright MCP tool / option (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Fresh page tree sent back after each action | every action reply (`setIncludeSnapshot`) | yes | `dejo_run` shows the page after the steps | [response.ts#L316](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/response.ts#L316) |
| Target by ref, CSS, or a locator string (`getByRole(...)` in JS/Python/Java/C#) | `target` on every element tool | yes | refs `e12`/`f1e3`, `role "name"`, `text`, `label`, `placeholder`, `alt`, `title`, `testid`, `css`, plus `first`/`last`/`nth`/`has` | [tab.ts#L597](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/tab.ts#L597) |
| Elements inside iframes reachable | refs like `f1e3` | yes | refs reach inside iframes | [tab.ts#L601](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/tab.ts#L601) |
| Downloads saved automatically | `page.on('download')` → output dir | yes | saved to `~/.dejo/downloads`; counts as a postcondition | [tab.ts#L155](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/tab.ts#L155) |
| Dialog or file picker blocks other tools until handled ("modal state") | `page.on('dialog')`, `page.on('filechooser')` | yes | dialogs accepted unless `dialog dismiss` or `dialog accept "text"` came first, and recorded; file picker filled by `upload` | [tab.ts#L147](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/tab.ts#L147) |
| Wait for clicks' network work to settle | `waitForCompletion` (settle 500 ms, waits for started requests) | partly | `wait idle` step; Dejo's own postcondition checks. Missing: a setting for the settle time | [utils.ts#L20](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/utils.ts#L20) |
| Tools a web page registers (WebMCP) shown to the agent as extra MCP tools | dynamic tools | no | — | [browserBackend.ts#L78](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/backend/browserBackend.ts#L78) |

---

### 2. Configuration options

Every option is a command-line flag, an environment variable `PLAYWRIGHT_MCP_*`, and a key in the JSON `--config` file. Rows marked "(config file only)" have no flag.

Note: the older flags `--save-trace` and `--save-video` are **gone** from the current source. Tracing and video are now the `browser_start_tracing` / `browser_start_video` tools above.

| Capability (plain words) | Playwright MCP tool / option (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Show the browser window, or hide it | `--headless` (headed is default) | yes | `DEJO_HEADED=1` (or `dejo run --headed`); hidden otherwise | [program.ts#L56](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L56) |
| Pick the browser (Chrome, Edge, Firefox, WebKit) | `--browser <chrome\|firefox\|webkit\|msedge>`; `browser.browserName` | partly | Chromium only. Missing: any choice | [program.ts#L41](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L41) |
| Use a browser program at a given path | `--executable-path <path>` | no | — | [program.ts#L51](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L51) |
| Pretend to be a phone or tablet | `--device <name>` (e.g. "iPhone 15") | yes | `emulate device "iPhone 15"` (Playwright's device names; `tap` still needs touch mode) | [program.ts#L49](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L49) |
| Generic phone mode (Pixel 10 / iPhone 17) | `--mobile` | no | — | [program.ts#L50](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L50) |
| Set the page size | `--viewport-size <WxH>` (default 1280x720) | yes | `emulate viewport 1280x720` | [program.ts#L90](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L90) |
| Set the user agent text | `--user-agent <ua>` | partly | only the one that comes with `emulate device "..."`; no string of your own | [program.ts#L88](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L88) |
| Keep the profile (logins) in a chosen folder | `--user-data-dir <path>` | yes | `DEJO_PROFILE` (default profile folder), `DEJO_PROFILES_DIR`, `dejo_profile(name)` | [program.ts#L89](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L89) |
| Throw-away profile kept only in memory | `--isolated` | partly | `dejo_profile(name)` gives separate profiles. Missing: one that is never saved to disk | [program.ts#L63](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L63) |
| Start with cookies + localStorage from a file | `--storage-state <path>` | yes | `state load NAME\|"/path/state.json"` as the first step | [program.ts#L83](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L83) |
| Connect to a Chrome that is already running (DevTools protocol) | `--cdp-endpoint <url>`, `--cdp-header <h...>`, `--cdp-timeout <ms>` | partly | `DEJO_CDP_URL=http://127.0.0.1:9222` (or `dejo run --cdp URL`). Missing: extra headers and timeout for the connection | [program.ts#L43](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L43) (to #L45) |
| Connect to a remote Playwright server | `--endpoint <url>`; `browser.remoteEndpoint`; hidden `--remote-header` | no | — | [program.ts#L53](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L53) |
| Drive the person's own Chrome/Edge tabs through an extension | `--extension`, `--profile-dir-name <name>`, `--background`, `--no-tab-group` | no | — | [program.ts#L52](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L52), [#L66](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L66), [#L72](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L72) |
| Send traffic through a proxy | `--proxy-server <url>`, `--proxy-bypass <domains>` | partly | `DEJO_PROXY=http://proxy:8080`. Missing: a bypass list | [program.ts#L73](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L73) (to #L74) |
| Ignore bad HTTPS certificates | `--ignore-https-errors` | yes | `DEJO_IGNORE_HTTPS_ERRORS=1` | [program.ts#L59](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L59) |
| Give the site permissions (location, clipboard...) | `--grant-permissions <p...>` | yes | `allow clipboard-read notifications`, `emulate geolocation 18.52,73.85` (steps, not a start option) | [program.ts#L55](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L55) |
| Block service workers | `--block-service-workers` | no | — | [program.ts#L40](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L40) |
| Only allow requests to these sites | `--allowed-origins <o;o>`; `network.allowedOrigins` | no | — | [program.ts#L37](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L37) |
| Block requests to these sites | `--blocked-origins <o;o>`; `network.blockedOrigins` | yes | `block "https://ads.example.com/**"` (a step, kept in the trail) | [program.ts#L39](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L39) |
| Run a JavaScript file in every page before the page's own scripts | `--init-script <path...>` | partly | `script "JS"` takes the code, not a file; not kept in a trail | [program.ts#L62](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L62) |
| Run a setup file on the Playwright `page` object at start | `--init-page <path...>` | no | — | [program.ts#L61](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L61) |
| Any Playwright launch option (channel, args, slowMo...) | `browser.launchOptions` (config file only) | no | — | [config.d.ts#L60](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/config.d.ts#L60) |
| Any Playwright context option (locale, timezone, geolocation, colorScheme...) | `browser.contextOptions` (config file only) | partly | as steps: `emulate locale de-DE`, `emulate timezone Asia/Tokyo`, `emulate geolocation 18.52,73.85`, `emulate color dark`, `allow ...`, `header set ...`; `DEJO_IGNORE_HTTPS_ERRORS=1`. Missing: the rest, and no config file | [config.d.ts#L67](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/config.d.ts#L67) |
| How long one action may take | `--timeout-action <ms>` (default 5000) | partly | Python `Browser(timeout_ms=...)` only. Missing: from MCP | [program.ts#L85](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L85) |
| How long a page load may take | `--timeout-navigation <ms>` (default 60000) | partly | Python `Browser(timeout_ms=...)` only (one value for all). Missing: from MCP | [program.ts#L86](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L86) |
| How long to wait after an action for things to settle | `--timeout-settle <ms>` (default 500) | partly | `wait idle` step. Missing: a setting | [program.ts#L87](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L87) |
| How long a check waits | `timeouts.expect` (config file only) | no | — | [config.d.ts#L239](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/config.d.ts#L239) |
| Close the browser after idle time | `--idle-timeout <ms>`; `timeouts.idle` | no | — | [program.ts#L58](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L58) |
| Turn on extra tool groups | `--caps <vision,pdf,devtools,network,storage,testing,config>`; `capabilities`; hidden `--vision` | no | — (Dejo keeps 5 tools always; new verbs go into the step language, rule 8) | [program.ts#L42](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L42) |
| Which console levels to report | `--console-level <error\|warning\|info\|debug>`; `console.level` | yes | `read console` (every level) or `read console_errors` (errors and warnings) | [program.ts#L48](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L48) |
| Folder for screenshots, downloads, traces | `--output-dir <path>` | partly | fixed folders: `~/.dejo/downloads`, `~/.dejo/captures`, `~/.dejo/recordings`. Missing: a setting for the folder | [program.ts#L69](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L69) |
| Delete old output files above a size | `--output-max-size <bytes>` | no | — | [program.ts#L70](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L70) |
| Show file paths relative or absolute | `--file-paths <relative\|absolute>` | no | — | [program.ts#L54](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L54) |
| Keep file access inside the project folder | `--allow-unrestricted-file-access` (default: restricted) | no | — (Dejo has no such guard) | [program.ts#L38](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L38) |
| Do not ask the client for its workspace folders | `--ignore-roots` | no | — (Dejo does not use MCP roots) | [program.ts#L60](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L60) |
| Send images to the agent, or not | `--image-responses <allow\|omit\|only>` | partly | `look image` sends a picture only when asked. Missing: a setting | [program.ts#L64](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L64) |
| Send the page tree after actions, or not | `--snapshot-mode <full\|none>` | no | — | [program.ts#L82](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L82) |
| Add element boxes (x,y,w,h) to every page tree | `--snapshot-boxes` | no | — | [program.ts#L81](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L81) |
| Use another attribute for test ids | `--test-id-attribute <attr>` | no | — (`testid ".."` always uses `data-testid`) | [program.ts#L84](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L84) |
| Show matching Playwright code with every action | `--codegen <typescript\|python\|java\|csharp\|none>` | no | — | [program.ts#L46](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L46) |
| Keep passwords out of what the agent sees | `--secrets <dotenv file>`; `secrets` | partly | passwords come from `DEJO_SECRET_*` env vars or `~/.dejo/secrets.json` and are never stored. Missing: hiding any given text in all replies | [program.ts#L79](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L79) |
| Hide values of named URL parameters (tokens) in replies | `--redact-url-params <names>` | partly | Dejo hides one-time codes and sign-in-link tokens in views by itself. Missing: a user list of names | [program.ts#L75](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L75) |
| Save a log of the whole session | `--save-session` | partly | one plain line per step in `~/.dejo/logs/DATE.log` (on by default; `DEJO_LOG=off` stops it), and learned tasks in memory. Missing: the full replies and page trees in the log | [program.ts#L78](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L78) |
| Expose page WebMCP tools, or not | `--no-webmcp`; `webmcp` | no | — | [program.ts#L68](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L68) |
| Run as an HTTP server instead of stdio | `--port <port>`, `--host <host>` | no | — (Dejo is stdio only) | [program.ts#L71](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L71), [#L57](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L57) |
| Which host names may reach the HTTP server | `--allowed-hosts <hosts...>` | no | — (no HTTP server) | [program.ts#L36](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L36) |
| Share one browser between all HTTP clients | `--shared-browser-context` | no | — | [program.ts#L80](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L80) |
| Browser sandbox on / off | `--sandbox`, `--no-sandbox` | no | — | [program.ts#L65](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L65), [#L77](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L77) |
| Read all settings from a JSON file | `--config <path>` | no | — (Dejo reads `DEJO_*` environment variables) | [program.ts#L47](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/tools/mcp/program.ts#L47) |
| Install the browser | `npx @playwright/mcp install-browser` | partly | `dejo doctor` checks the browser and says how to fix it. Missing: installing it | [cli.js#L21](https://github.com/microsoft/playwright-mcp/blob/main/cli.js#L21) |

---

## Chrome DevTools MCP

Source: <https://github.com/ChromeDevTools/chrome-devtools-mcp>. License: Apache License 2.0. The LICENSE file has no filled-in copyright line (it ends with the template line "Copyright [yyyy] [name of copyright owner]"). Every source file carries "Copyright 2025 Google LLC" (newer files say "Copyright 2026 Google LLC"), with `SPDX-License-Identifier: Apache-2.0`.

### 1. Tools

#### Input automation (default on)

| Capability (plain words) | Chrome DevTools MCP tool / option (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Click an element | `click` (uid, dblClick, includeSnapshot) | yes | `click T` | [input.ts#L119](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/input.ts#L119) |
| Double-click an element | `click` (dblClick=true) | yes | `double_click T` | [input.ts#L119](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/input.ts#L119) |
| Click at x,y screen points (for vision models) | `click_at` (x, y, dblClick, includeSnapshot); needs `--experimentalVision` | yes | `mouse click X Y`, `mouse dblclick X Y` (find the spot with `look image`) | [input.ts#L180](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/input.ts#L180) |
| Move the mouse over an element | `hover` (uid, includeSnapshot) | yes | `hover T` | [input.ts#L216](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/input.ts#L216) |
| Put text in a box, pick a `<select>` option, or set a checkbox/radio | `fill` (uid, value; "true"/"false" for checkbox and toggle, "true" for radio) | yes | `fill T "text"`, `select T "opt"`, `set_checked T true\|false`, `check T` | [input.ts#L404](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/input.ts#L404) |
| Type key by key, then press a submit key | `type_text` (text, submitKey) | yes | `type T "text" delay=MS` then `press Enter` (Dejo needs a target) | [input.ts#L446](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/input.ts#L446) |
| Drag one element onto another | `drag` (from_uid, to_uid, includeSnapshot) | yes | `drag T to T` | [input.ts#L477](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/input.ts#L477) |
| Fill a whole form in one call | `fill_form` (elements: [{uid, value}], includeSnapshot) | yes | several `fill` / `select` / `set_checked` lines in one `dejo_run` call | [input.ts#L511](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/input.ts#L511) |
| Upload files (file input or file chooser) | `upload_file` (uid, filePaths[], includeSnapshot) | yes | `upload T "path,path"` | [input.ts#L567](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/input.ts#L567) |
| Press a key or key chord | `press_key` (key, e.g. "Control+Shift+R", includeSnapshot) | yes | `press KEY [T]` | [input.ts#L636](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/input.ts#L636) |
| Answer a dialog: accept, dismiss, or type a prompt answer | `handle_dialog` (action: accept\|dismiss, promptText) | yes | `dialog accept`, `dialog dismiss`, `dialog accept "text"` before the step that opens it; `read dialog` reads its words | [pages.ts#L399](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/pages.ts#L399) |

#### Navigation and tabs (default on)

| Capability (plain words) | Chrome DevTools MCP tool / option (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| List all open tabs (and extension service workers) | `list_pages` (none) | partly | `read tabs as tabs` (number, title, URL, which is in use). Missing: extension service workers | [pages.ts#L25](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/pages.ts#L25) |
| Switch to another tab | `select_page` (pageId, bringToFront) | yes | `tab N\|latest\|main` | [pages.ts#L44](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/pages.ts#L44) |
| Close a tab | `close_page` (pageId) | yes | `tab close [N\|latest]` | [pages.ts#L78](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/pages.ts#L78) |
| Open a new tab with a URL | `new_page` (url, background, timeout) | partly | `tab new [URL]`. Missing: open in background, per-call timeout | [pages.ts#L109](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/pages.ts#L109) |
| Open a tab in a separate, clean cookie jar | `new_page` (isolatedContext: name) | partly | `dejo_profile(name)` gives separate persistent profiles; no throwaway clean context in the same browser | [pages.ts#L109](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/pages.ts#L109) |
| Go to a URL | `navigate_page` (type=url, url, timeout) | yes | `go URL` (http(s) or a path only) | [pages.ts#L195](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/pages.ts#L195) |
| Go back / forward in history | `navigate_page` (type=back\|forward) | yes | `back`, `forward` | [pages.ts#L195](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/pages.ts#L195) |
| Reload the page | `navigate_page` (type=reload) | yes | `reload` | [pages.ts#L195](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/pages.ts#L195) |
| Hard reload, skipping the cache | `navigate_page` (ignoreCache) | no | — | [pages.ts#L195](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/pages.ts#L195) |
| Run a script before any page script on the next load | `navigate_page` (initScript) | yes | `script "JS"` then `go URL` (runs on every later load; not kept in a trail) | [pages.ts#L195](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/pages.ts#L195) |
| Choose accept or dismiss for "leave this page?" | `navigate_page` (handleBeforeUnload: accept\|dismiss) | yes | `dialog dismiss` or `dialog accept` before the step that leaves the page (`go`, `tab close`) | [pages.ts#L195](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/pages.ts#L195) |
| Set a wait limit for one navigation | `navigate_page` / `new_page` / `wait_for` (timeout ms) | no | — (engine only: `Browser(timeout_ms)`) | [pages.ts#L195](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/pages.ts#L195) |
| Wait until a text appears (any of several; only visible if asked) | `wait_for` (text[], timeout, visible) | partly | `wait text:WORDS`, `wait "text:Saved\|Error"`. Missing: its own timeout, visible-only switch | [snapshot.ts#L54](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/snapshot.ts#L54) |
| Read the Chrome tab id (hidden, for interop) | `get_tab_id` (none); needs hidden `--experimentalInteropTools` | no | — | [pages.ts#L453](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/pages.ts#L453) |

#### Emulation (default on)

`emulate` takes all of the settings below in one call. Each call replaces all earlier settings except `extraHttpHeaders`.

| Capability (plain words) | Chrome DevTools MCP tool / option (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Slow network or offline | `emulate` (networkConditions: Offline\|Slow 3G\|Fast 3G\|Slow 4G\|Fast 4G) | yes | `emulate network slow3g\|fast3g\|slow4g\|fast4g\|offline`, `emulate offline on` | [emulation.ts#L56](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/emulation.ts#L56) |
| Slow CPU | `emulate` (cpuThrottlingRate 1–20) | yes | `emulate cpu 4` (1 to 20) | [emulation.ts#L56](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/emulation.ts#L56) |
| Fake location | `emulate` (geolocation "lat,long") | yes | `emulate geolocation 18.52,73.85` | [emulation.ts#L56](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/emulation.ts#L56) |
| Change the user agent | `emulate` (userAgent) | partly | only the one that comes with `emulate device "..."`; no string of your own | [emulation.ts#L56](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/emulation.ts#L56) |
| Dark or light mode | `emulate` (colorScheme: dark\|light\|auto) | yes | `emulate color dark\|light` (`emulate color off` for auto) | [emulation.ts#L56](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/emulation.ts#L56) |
| Forced colors (Windows high contrast) | `emulate` (forcedColors: active\|none\|auto) | no | — | [emulation.ts#L56](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/emulation.ts#L56) |
| More or less contrast | `emulate` (prefersContrast: more\|less\|custom\|no-preference\|auto) | no | — | [emulation.ts#L56](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/emulation.ts#L56) |
| Reduced motion | `emulate` (prefersReducedMotion: reduce\|no-preference\|auto) | yes | `emulate motion reduce` | [emulation.ts#L56](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/emulation.ts#L56) |
| Phone or tablet screen (size, pixel ratio, mobile, touch, landscape) | `emulate` (viewport "WxHxDPR[,mobile][,touch][,landscape]") | partly | `emulate device "iPhone 13"` (named devices, landscape ones too), `emulate viewport 390x844`. Missing: your own mix of pixel ratio, mobile and touch | [emulation.ts#L56](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/emulation.ts#L56) |
| Add HTTP headers to every request (e.g. Authorization) | `emulate` (extraHttpHeaders JSON) | yes | `header set Authorization "Bearer ..."`, `header clear` | [emulation.ts#L56](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/emulation.ts#L56) |
| Resize the window | `resize_page` (width, height) | yes | `emulate viewport 1024x768` | [pages.ts#L357](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/pages.ts#L357) |

#### Performance (default on)

| Capability (plain words) | Chrome DevTools MCP tool / option (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Record a performance trace (optionally reload, cold cache, stop by itself after 5 s, save raw trace) | `performance_start_trace` (reload=true, autoStop=true, ignoreCache, filePath .json / .json.gz) | partly | `record performance`, then `reload`, then `record stop` saves a .json for the DevTools Performance panel. Missing: cold cache, stop by itself | [performance.ts#L35](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/performance.ts#L35) |
| Stop the trace and get a summary (LCP, INP, CLS, insight list, real-user CrUX data) | `performance_stop_trace` (filePath) | partly | `record stop`, and `read metrics as speed` (first byte, FCP, LCP, CLS, load, requests, KB). Missing: INP, the insight list, CrUX data | [performance.ts#L152](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/performance.ts#L152) |
| Explain one performance insight in detail | `performance_analyze_insight` (insightSetId, insightName) | no | — | [performance.ts#L185](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/performance.ts#L185) |

#### Network (default on)

| Capability (plain words) | Chrome DevTools MCP tool / option (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| List every request the page made (filter by type, page through, keep last 3 navigations) | `list_network_requests` (pageSize, pageIdx, resourceTypes[], includePreservedRequests) | partly | `read requests ["words"] as calls` (METHOD STATUS URL). Missing: type filter, paging, earlier navigations | [network.ts#L41](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/network.ts#L41) |
| See one request in full: headers, request body, response body, failure, redirects | `get_network_request` (reqid, requestFilePath, responseFilePath) | partly | `read response "words"` (response body), `read requests` (status or failure). Missing: headers, request body, redirects | [network.ts#L99](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/network.ts#L99) |

#### Debugging (default on)

| Capability (plain words) | Chrome DevTools MCP tool / option (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Run JavaScript in the page, with page elements as arguments | `evaluate_script` (function, args[] uids, format: function\|script, waitForStableDom) | yes | `js CODE` (on the page, or on one element; alone on its line; not remembered) | [script.ts#L32](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/script.ts#L32) |
| Load the script from a file, or save its result to a file | `evaluate_script` (sourcePath, filePath) | no | — | [script.ts#L32](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/script.ts#L32) |
| Run JavaScript inside a service worker | `evaluate_script` (serviceWorkerId) | no | — | [script.ts#L32](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/script.ts#L32) |
| Choose how dialogs opened by the script are answered | `evaluate_script` (dialogAction: accept\|dismiss\|prompt text) | yes | `dialog dismiss` or `dialog accept "text"` in the call before the `js` line (a `js` line must be alone) | [script.ts#L32](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/script.ts#L32) |
| List console messages (all types, Chrome "issues", stack traces, filter, pages, history) | `list_console_messages` (types[], pageSize, pageIdx, includePreservedMessages, includeStackTraces, serviceWorkerId) | partly | `read console as log` (every type), `read console_errors`. Missing: Chrome issues, stack traces, earlier navigations | [console.ts#L45](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/console.ts#L45) |
| Open one console message in detail (arguments, stack) | `get_console_message` (msgid) | no | — | [console.ts#L113](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/console.ts#L113) |
| See which CSS rules style an element (cascade, overridden rules, source lines) | `get_css_styles` (uid, pageIdx, pageSize) | no | — (`js` can read computed style, not the matched rules) | [css.ts#L13](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/css.ts#L13) |
| Lighthouse audit: accessibility, SEO, best practices, agent-readiness | `lighthouse_audit` (device: desktop\|mobile, mode: navigation\|snapshot, outputDirPath) | no | — | [lighthouse.ts#L171](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/lighthouse.ts#L171) |
| Start a video recording of the page | `screencast_start` (filePath .mp4 or .webm) | yes | `record video` (.webm, every tab), or `DEJO_RECORD=video` for every replay | [screencast.ts#L75](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/screencast.ts#L75) |
| Stop the video recording | `screencast_stop` (none) | yes | `record stop` | [screencast.ts#L173](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/screencast.ts#L173) |
| Screenshot of the page or one element (viewport or full page, png/jpeg/webp, quality, to file or straight to the model) | `take_screenshot` (uid, fullPage, format, quality, filePath) | partly | `screenshot [T\|full] [as NAME]` (PNG file), `look image` (picture straight to the model). Missing: jpeg/webp, quality | [screenshot.ts#L155](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/screenshot.ts#L155) |
| Text view of the page with element ids (from the accessibility tree) | `take_snapshot` (verbose, filePath) | yes | `look`, `look WORDS`, `look all`, `look raw` (no save-to-file) | [snapshot.ts#L17](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/snapshot.ts#L17) |

#### DevTools comments (hidden, "internal WIP", needs hidden `--devtoolsComments`)

| Capability (plain words) | Chrome DevTools MCP tool / option (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Open a DevTools window for the page | `open_devtools` (none) | no | — | [comments.ts#L21](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/comments.ts#L21) |
| Read comments a person left in DevTools (waits for one) | `get_devtools_comments` (timeout ≤ 30000 ms) | no | — | [comments.ts#L49](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/comments.ts#L49) |
| Reply to and close a DevTools comment | `resolve_devtools_comment` (threadId, replyText) | no | — | [comments.ts#L121](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/comments.ts#L121) |
| Show an element or request in a DevTools panel | `reveal_in_devtools` (panelName, uid, reqid) | no | — | [comments.ts#L187](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/comments.ts#L187) |

#### Memory / heap snapshots (`take_heapsnapshot` is on by default; the others need `--memoryDebugging`)

| Capability (plain words) | Chrome DevTools MCP tool / option (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Save a JavaScript heap snapshot to a file | `take_heapsnapshot` (filePath) | no | — | [memory.ts#L57](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/memory.ts#L57) |
| Heap summary (native contexts and sizes) | `get_heapsnapshot_summary` (filePath, maxNameLength) | no | — | [memory.ts#L90](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/memory.ts#L90) |
| Heap statistics and object counts by class | `get_heapsnapshot_details` (filePath, filterName, objectId, maxNameLength, pageIdx, pageSize) | no | — | [memory.ts#L136](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/memory.ts#L136) |
| All objects of one class | `get_heapsnapshot_class_nodes` (filePath, id, filterName, objectId, maxNameLength, pageIdx, pageSize) | no | — | [memory.ts#L183](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/memory.ts#L183) |
| What holds one object | `get_heapsnapshot_retainers` (filePath, nodeId, maxNameLength, pageIdx, pageSize) | no | — | [memory.ts#L232](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/memory.ts#L232) |
| Free a loaded heap snapshot | `close_heapsnapshot` (filePath) | no | — | [memory.ts#L269](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/memory.ts#L269) |
| Why an object is not garbage collected | `get_heapsnapshot_retaining_paths` (filePath, nodeId, maxDepth, maxNodes, maxSiblings, maxNameLength) | no | — | [memory.ts#L302](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/memory.ts#L302) |
| What one object points to | `get_heapsnapshot_edges` (filePath, nodeId, excludePrimitives, retainedSize, sortBy, maxNameLength, pageIdx, pageSize) | no | — | [memory.ts#L350](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/memory.ts#L350) |
| Dominator chain of an object | `get_heapsnapshot_dominators` (filePath, nodeId, maxNameLength) | no | — | [memory.ts#L406](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/memory.ts#L406) |
| Compare two heap snapshots (find leaks) | `compare_heapsnapshots` (baseFilePath, currentFilePath, classIndex, maxNameLength, pageIdx, pageSize) | no | — | [memory.ts#L441](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/memory.ts#L441) |
| Duplicate strings in memory | `get_heapsnapshot_duplicate_strings` (filePath, maxNameLength, pageIdx, pageSize) | no | — | [memory.ts#L499](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/memory.ts#L499) |
| Details of one object (size, type, detached DOM) | `get_heapsnapshot_object_details` (filePath, nodeId, maxNameLength) | no | — | [memory.ts#L534](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/memory.ts#L534) |
| Search objects by class, property, type, size, detached | `query_heapsnapshot_objects` (filePath, className, propertyName, nodeType, retainedSize, selfSize, isDetached, sortBy, maxNameLength, pageIdx, pageSize) | no | — | [memory.ts#L567](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/memory.ts#L567) |
| Find closures that keep dead variables alive | `analyze_heapsnapshot_contexts` (filePath, retainedSize, scopeInfoNodeId, maxNameLength, pageIdx, pageSize) | no | — | [memory.ts#L641](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/memory.ts#L641) |

#### Extensions (off by default, `--categoryExtensions`)

| Capability (plain words) | Chrome DevTools MCP tool / option (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Install an unpacked Chrome extension | `install_extension` (path) | no | — | [extensions.ts#L13](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/extensions.ts#L13) |
| Uninstall an extension | `uninstall_extension` (id) | no | — | [extensions.ts#L37](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/extensions.ts#L37) |
| List installed extensions | `list_extensions` (none) | no | — | [extensions.ts#L57](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/extensions.ts#L57) |
| Reload an extension | `reload_extension` (id) | no | — | [extensions.ts#L74](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/extensions.ts#L74) |
| Click an extension's toolbar action | `trigger_extension_action` (id) | no | — | [extensions.ts#L98](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/extensions.ts#L98) |

#### Third-party developer tools and WebMCP (off by default)

| Capability (plain words) | Chrome DevTools MCP tool / option (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| List debug tools the page itself offers | `list_3p_developer_tools` (none); `--categoryExperimentalThirdParty` | no | — | [thirdPartyDeveloper.ts#L48](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/thirdPartyDeveloper.ts#L48) |
| Call a debug tool the page offers | `execute_3p_developer_tool` (toolName, params JSON) | no | — | [thirdPartyDeveloper.ts#L72](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/thirdPartyDeveloper.ts#L72) |
| List WebMCP tools the page offers | `list_webmcp_tools` (none); `--categoryExperimentalWebmcp`, Chrome 150+ | no | — | [webmcp.ts#L13](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/webmcp.ts#L13) |
| Call a WebMCP tool the page offers | `execute_webmcp_tool` (toolName, input JSON) | no | — | [webmcp.ts#L29](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/webmcp.ts#L29) |

#### Progressive Web Apps (off by default, `--categoryPwa`, launched browser only)

| Capability (plain words) | Chrome DevTools MCP tool / option (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Install a web app | `install_pwa` (manifestId, installUrlOrBundleUrl, displayMode: standalone\|browser) | no | — | [pwa.ts#L32](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/pwa.ts#L32) |
| Uninstall a web app | `uninstall_pwa` (manifestId) | no | — | [pwa.ts#L82](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/pwa.ts#L82) |
| Launch an installed web app | `launch_pwa` (manifestId, url) | no | — | [pwa.ts#L107](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/pwa.ts#L107) |
| Read app badge and file handlers | `get_os_app_state` (manifestId) | no | — | [pwa.ts#L139](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/pwa.ts#L139) |

#### WebAuthn (off by default, `--categoryWebauthn`)

| Capability (plain words) | Chrome DevTools MCP tool / option (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Fake passkey / security key for testing sign-in | `configure_webauthn` (enabled, protocol: ctap2\|u2f, transport, hasResidentKey, hasUserVerification, isUserVerified) | no | — | [webauthn.ts#L13](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/webauthn.ts#L13) |

#### Slim mode tools (only with `--slim`, which replaces all the tools above)

| Capability (plain words) | Chrome DevTools MCP tool / option (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Load a URL | `navigate` (url) | yes | `go URL` | [slim/tools.ts#L61](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/slim/tools.ts#L61) |
| Run a JavaScript snippet | `evaluate` (script) | yes | `js CODE` | [slim/tools.ts#L110](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/slim/tools.ts#L110) |
| Take a PNG screenshot | `screenshot` (filePath) | yes | `screenshot [as NAME]` | [slim/tools.ts#L14](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/tools/slim/tools.ts#L14) |

### 2. Server options

Options are command-line flags, or keys in a JSON config file. Dejo has no flags for its MCP server. Its settings are `DEJO_*` environment variables read through `home.setting()` (for example `DEJO_PROFILE`, `DEJO_PROFILES_DIR`, `DEJO_LOCALE`, `DEJO_DB`).

| Capability (plain words) | Chrome DevTools MCP tool / option (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Turn whole tool groups on or off | `--categoryInput`, `--categoryNavigation`, `--categoryEmulation`, `--categoryPerformance`, `--categoryNetwork`, `--categoryDebugging`, `--categoryMemory` (default on); `--categoryExtensions`, `--categoryExperimentalThirdParty`, `--categoryExperimentalWebmcp`, `--categoryPwa`, `--categoryWebauthn` (default off) | no | — (always the same 5 tools) | [category-options.ts](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/category-options.ts) |
| Small tool set only | `--slim` | yes | Dejo is always small: 5 tools, one browsing tool (`dejo_run`) | [mcp-options.ts#L257](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/mcp-options.ts#L257) |
| Attach to the Chrome the person already has open (Chrome 144+) | `--autoConnect` (with `--channel`) | partly | `DEJO_CDP_URL=http://127.0.0.1:9222` once Chrome was started with `--remote-debugging-port=9222`. Missing: attaching with no restart | [browser-options.ts#L27](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/browser-options.ts#L27) |
| Connect to a running Chrome by its debug URL | `--browserUrl` / `-u` (e.g. http://127.0.0.1:9222) | yes | `DEJO_CDP_URL=http://127.0.0.1:9222` (or `dejo run --cdp URL`) | [browser-options.ts#L33](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/browser-options.ts#L33) |
| Connect to a running Chrome by WebSocket | `--wsEndpoint` / `-w` | yes | `DEJO_CDP_URL=ws://...` (passed to Playwright's `connect_over_cdp`) | [browser-options.ts#L50](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/browser-options.ts#L50) |
| Send auth headers on that WebSocket | `--wsHeaders` (JSON) | no | — | [browser-options.ts#L75](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/browser-options.ts#L75) |
| Run with no window (headless) | `--headless` (default false) | yes | headless by default; `DEJO_HEADED=1` shows the window | [browser-options.ts#L107](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/browser-options.ts#L107) |
| Use a chosen Chrome program | `--executablePath` / `-e` | no | — (Playwright's own Chromium) | [browser-options.ts#L112](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/browser-options.ts#L112) |
| Throwaway profile, deleted at the end | `--isolated` | partly | `dejo_profile(name)` gives separate profiles, but they are kept, never thrown away | [browser-options.ts#L117](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/browser-options.ts#L117) |
| Choose the profile folder | `--userDataDir` | partly | `DEJO_PROFILES_DIR` sets the folder for Dejo's own profiles; cannot point at the person's normal Chrome profile | [browser-options.ts#L123](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/browser-options.ts#L123) |
| Use Chrome Canary / Dev / Beta | `--channel` (stable\|beta\|dev\|canary) | no | — | [browser-options.ts#L128](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/browser-options.ts#L128) |
| Go through a proxy | `--proxyServer` | yes | `DEJO_PROXY=http://proxy:8080` | [browser-options.ts#L135](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/browser-options.ts#L135) |
| Extra Chrome command-line flags | `--chromeArg` (array) | no | — | [browser-options.ts#L139](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/browser-options.ts#L139) |
| Drop some default Chrome flags | `--ignoreDefaultChromeArg` (array) | no | — | [browser-options.ts#L145](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/browser-options.ts#L145) |
| Starting window size | `--viewport` (e.g. 1280x720) | yes | `emulate viewport 1280x720` (a step, not a start option) | [puppeteer-options.ts#L33](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/puppeteer-options.ts#L33) |
| Allow self-signed / expired HTTPS certificates | `--acceptInsecureCerts` | yes | `DEJO_IGNORE_HTTPS_ERRORS=1` | [puppeteer-options.ts#L60](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/puppeteer-options.ts#L60) |
| Block some URLs | `--blockedUrlPattern` (URL patterns) | yes | `block "**/ads/**"`, `block off [PATTERN]` (steps, kept in the trail) | [puppeteer-options.ts#L65](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/puppeteer-options.ts#L65) |
| Allow only some URLs (Chrome 149+) | `--allowedUrlPattern` (URL patterns) | no | — | [puppeteer-options.ts#L79](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/puppeteer-options.ts#L79) |
| Default screenshot format, quality and maximum size | `--screenshotFormat` (png\|jpeg\|webp), `--screenshotQuality`, `--screenshotMaxWidth`, `--screenshotMaxHeight` | no | — (always PNG, full size) | [tool-options.ts#L28](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/tool-options.ts#L28) |
| Write debug logs to a file | `--logFile` | partly | the step log `~/.dejo/logs/DATE.log` (on by default; `DEJO_LOG=off`). Missing: a debug log, choice of file | [mcp-options.ts#L79](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/mcp-options.ts#L79) |
| Route each call to a page by id (for several agents at once) | `--pageIdRouting` (default true) | no | — (`tab N` inside one run) | [mcp-options.ts#L84](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/mcp-options.ts#L84) |
| Let the input tools drive the DevTools window itself | `--experimentalDevtools` | no | — | [mcp-options.ts#L99](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/mcp-options.ts#L99) |
| Turn on coordinate tools (`click_at`) | `--experimentalVision` | yes | always on: `mouse click X Y` and the other `mouse` steps | [mcp-options.ts#L105](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/mcp-options.ts#L105) |
| Turn on heap analysis tools | `--memoryDebugging` / `--experimentalMemory` | no | — | [mcp-options.ts#L112](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/mcp-options.ts#L112) |
| Structured (JSON) tool results | `--experimentalStructuredContent`; hidden `--experimentalDataFormat` (default\|toon\|gcf) | no | — (text results) | [mcp-options.ts#L119](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/mcp-options.ts#L119) |
| Treat webviews and background pages as pages | `--experimentalIncludeAllPages` | no | — | [mcp-options.ts#L142](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/mcp-options.ts#L142) |
| Old ffmpeg video recorder, its path, frames per second | `--experimentalScreencast`, `--experimentalFfmpegPath`, `--screencastFps` | no | — (`record video` makes a .webm; no fps choice) | [mcp-options.ts#L156](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/mcp-options.ts#L156) |
| Fetch real-user speed data (CrUX) for traced URLs | `--performanceCrux` (default true; sends URLs to Google) | no | — | [mcp-options.ts#L187](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/mcp-options.ts#L187) |
| Turn off usage statistics | `--usageStatistics` (default true; also off with `CI` or `CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS`) | yes | nothing to turn off: no usage-statistics code found in Dejo | [mcp-options.ts#L194](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/mcp-options.ts#L194) |
| Turn off agent-written JavaScript | `--javascriptEvaluation=false` (disables evaluate tools, `initScript`, javascript:/data: URLs) | no | — (`js` cannot be switched off; `go` already refuses javascript: and data:) | [mcp-options.ts#L200](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/mcp-options.ts#L200) |
| Refuse file: URLs | `--fileNavigations=false` | yes | always on: `go` takes only http(s) or a path | [mcp-options.ts#L207](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/mcp-options.ts#L207) |
| Use source maps for stack traces | `--sourceMaps` (default true) | no | — | [mcp-options.ts#L214](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/mcp-options.ts#L214) |
| How many past navigations keep console and network data | `--maxNavigationSaved` (1–25, default 3) | no | — | [mcp-options.ts#L221](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/mcp-options.ts#L221) |
| Hide secret headers (Cookie, Authorization) in network output | `--redactNetworkHeaders` | no | — (`read requests` shows no headers to hide) | [mcp-options.ts#L271](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/mcp-options.ts#L271) |
| Limit which folders file tools may read or write | `--filesystemRoot` / `--workspace` (default: OS temp folder), `--allowUnrestrictedPaths` | no | — (`upload` takes any path) | [mcp-options.ts#L278](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/mcp-options.ts#L278) |
| Settings in a JSON config file | `--config` (also found by itself in `~/.config/cd4a/config.json`) | partly | `DEJO_*` environment variables; no config file | [mcp-options.ts#L299](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/mcp-options.ts#L299) |
| Apply config changes without restart | `--watchConfig` | no | — | [mcp-options.ts#L309](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/mcp-options.ts#L309) |
| Hidden switches for unfinished tools | `--devtoolsComments`, `--experimentalInteropTools` (both hidden) | no | — | [mcp-options.ts#L91](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/config/mcp-options.ts#L91) |
| Same tools from a terminal (CLI + agent skill) | `chrome-devtools` CLI (`docs/cli.md`) | partly | `dejo run / sites / show / map / forget / share / borrow / commons / export / doctor`; no CLI for single browsing steps | [docs/cli.md](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/docs/cli.md) |

## browser-use

Source: <https://github.com/browser-use/browser-use>. License: MIT. Copyright line from LICENSE: `Copyright (c) 2024 Gregor Zunic`.

### 1. Actions the browser-use agent can take (default action list, `browser_use/tools/service.py`)

| Capability (plain words) | browser-use name (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Search the web | `search`(query, engine = duckduckgo / google / bing) | yes | No own verb; the agent writes the search address: `go https://duckduckgo.com/?q=your+words` | [service.py#L458](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L458) |
| Open a web address | `navigate`(url, new_tab) | yes | `go URL`; in a new tab: `tab new URL` | [service.py#L502](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L502) |
| Go back | `go_back`() | yes | `back` (Dejo also has `forward`, `reload`) | [service.py#L583](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L583) |
| Wait some seconds | `wait`(seconds, at most 30) | yes | `wait SECONDS` (also `wait T`, `wait text:WORDS`, `wait url:PART`, `wait idle`) | [service.py#L597](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L597) |
| Click an element by its number | `click`(index) | yes | `click e12`, or `click role "name"` / `text ".."` / `css ".."` | [service.py#L2128](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L2128) |
| Click at an x,y point on the screen | `click`(coordinate_x, coordinate_y) | yes | `mouse click X Y` (find the spot with `look image`) | [service.py#L656](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L656) |
| Move to a tab that a click opened | inside `click` (switches to the new tab by itself) | partly | Dejo names the new tab but never switches by itself; the agent writes `tab latest` (it waits for a tab still opening) | [service.py#L629](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L629) |
| Type into a field, clearing it first | `input`(index, text, clear=True) | yes | `fill T "text"`; clear only: `clear T` | [service.py#L774](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L774) |
| Type, adding to what is already there | `input`(index, text, clear=False) | yes | `press End T` then `type T "text"` (key by key) | [views.py#L83](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/views.py#L83) |
| Upload a file | `upload_file`(index, path); only paths the user allowed in `available_file_paths` | yes | `upload T "path[,path]"` (file input or file chooser). Dejo has no allow-list of paths | [service.py#L860](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L860) |
| Switch to another tab | `switch`(tab_id, 4 characters) | yes | `tab N`, `tab latest`, `tab main` | [service.py#L1004](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L1004) |
| Close a tab | `close`(tab_id) | yes | `tab close [N\|latest]` | [service.py#L1038](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L1038) |
| Pull data out of the page (a model reads the page; optional JSON schema) | `extract`(query, extract_links, extract_images, start_from_char, output_schema, already_collected) | partly | No model, the agent names the fields: `read fields '{"name": "h3", "price": ".price", "link": "a@href"}' css "article" as items` (a list of records), `read table T as rows`. Missing: a typed schema, image lists, paging through long text, skipping items already collected | [service.py#L1067](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L1067) |
| Find words on the page, like grep (no model) | `search_page`(pattern, regex, case_sensitive, context_chars, css_scope, max_results) | partly | `read passage "words" [T] as x`, `look words`, `expect text "words"`. Missing: regex, case switch, every match with text around it | [service.py#L1307](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L1307) |
| List elements by CSS selector, with their attributes (no model) | `find_elements`(selector, attributes, max_results, include_text) | yes | `read fields '{"text": ".", "link": "@href", "id": "@id"}' css "a" as links` (no result limit), `read count css ".."` | [service.py#L1344](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L1344) |
| Scroll the page up or down | `scroll`(down, pages: 0.5 to 10) | yes | `scroll down`, `scroll up`, `scroll top`, `scroll bottom`, `scroll PIXELS` | [service.py#L1379](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L1379) |
| Scroll inside one element (a long list, a dropdown) | `scroll`(index, down, pages) | yes | `scroll T down [PIXELS]` (also `up`, `left`, `right`) | [service.py#L1379](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L1379) |
| Press keys and shortcuts | `send_keys`(keys, e.g. Escape, Control+o) | yes | `press Enter`, `press Control+A T` | [service.py#L1484](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L1484) |
| Scroll until some text is visible | `find_text`(text) | yes | `scroll text "words"` | [service.py#L1503](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L1503) |
| Take a screenshot | `screenshot`(file_name); with no name the picture goes to the model | yes | `screenshot [T\|full] [as NAME]` saves a file; `look image` sends the picture to the model | [service.py#L1524](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L1524) |
| Save the page as a PDF | `save_as_pdf`(file_name, print_background, landscape, scale, paper_format, display_header_footer, header_template, footer_template) | partly | `pdf [as NAME]`. Missing: background, landscape, scale, paper size, header and footer options | [service.py#L1564](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L1564) |
| See the choices in a dropdown | `dropdown_options`(index) | yes | `look` prints a native select's options on its line (a long list is cut to "+N more"; `look India` finds one); a custom listbox's options get their own refs | [service.py#L1679](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L1679) |
| Choose a dropdown option | `select_dropdown`(index, text) | yes | `select T "opt"` (by value, `label:`, `index:`, several with commas; custom comboboxes too) | [service.py#L1707](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L1707) |
| Write a file | `write_file`(file_name, content, append, trailing_newline, leading_newline) | not in Dejo, on purpose | The user's own agent does this with its own file tools | [service.py#L1754](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L1754) |
| Change text inside a file | `replace_file`(file_name, old_str, new_str) | not in Dejo, on purpose | The user's own agent does this | [service.py#L1787](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L1787) |
| Read a file | `read_file`(file_name) | not in Dejo, on purpose | The user's own agent does this | [service.py#L1795](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L1795) |
| Run JavaScript in the page | `evaluate`(code) | yes | `js CODE` (must be alone in its call; not remembered) | [service.py#L1833](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L1833) |
| Finish the task and report | `done`(text, success, files_to_display) | not in Dejo, on purpose | The user's own agent does this. (`done=true` on `dejo_run` only saves a task that reads nothing) | [service.py#L2049](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L2049) |
| Finish with typed (structured) output | `done`(data matching `output_model_schema`) | not in Dejo, on purpose | The user's own agent does this | [service.py#L2012](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L2012) |

#### Extra actions in the "Browser Use toolset for Claude" driver (`browser_use/integrations/anthropic/browser_use.py`)

This driver runs Claude's own browser toolset (the README says "31 browser actions") on a browser-use
browser. Only the actions not already in the table above are listed.

| Capability (plain words) | browser-use name (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Right click / middle click | `right_click`, `middle_click`(target: ref or x,y) | yes | `click T button=right\|middle`, `mouse right X Y` | [browser_use.py#L674](https://github.com/browser-use/browser-use/blob/main/browser_use/integrations/anthropic/browser_use.py#L674) |
| Double click / triple click | `double_click`, `triple_click`(target) | partly | `double_click T`. Missing: triple click (`select_text T` selects an element's text, which is the usual reason for it) | [browser_use.py#L680](https://github.com/browser-use/browser-use/blob/main/browser_use/integrations/anthropic/browser_use.py#L680) |
| Hover / move the mouse | `hover`, `mouse_move`(target: ref or x,y) | yes | `hover T`, `mouse move X Y` | [browser_use.py#L686](https://github.com/browser-use/browser-use/blob/main/browser_use/integrations/anthropic/browser_use.py#L686) |
| Hold the mouse button down, let it go | `left_mouse_down`, `left_mouse_up`(target) | yes | `mouse move X Y`, `mouse down`, `mouse up` | [browser_use.py#L694](https://github.com/browser-use/browser-use/blob/main/browser_use/integrations/anthropic/browser_use.py#L694) |
| Drag from one point to another | `left_click_drag`(from_, target, as x,y) | yes | `mouse drag X Y to X2 Y2`, `drag T to T` | [browser_use.py#L710](https://github.com/browser-use/browser-use/blob/main/browser_use/integrations/anthropic/browser_use.py#L710) |
| Scroll at a point, also left and right | `scroll`(target, scroll_direction up/down/left/right, scroll_amount) | yes | `scroll T down\|up\|left\|right [PIXELS]`, `scroll left\|right`, `mouse wheel DX DY` (after `mouse move X Y`) | [browser_use.py#L731](https://github.com/browser-use/browser-use/blob/main/browser_use/integrations/anthropic/browser_use.py#L731) |
| Hold a key down for some time | `hold_key`(text, duration) | yes | `keydown KEY`, `wait SECONDS`, `keyup KEY` | [browser_use.py#L758](https://github.com/browser-use/browser-use/blob/main/browser_use/integrations/anthropic/browser_use.py#L758) |
| Zoom into part of a screenshot | `zoom`(region x0,y0,x1,y1) | no | — | [browser_use.py#L662](https://github.com/browser-use/browser-use/blob/main/browser_use/integrations/anthropic/browser_use.py#L662) |
| Fill a form field by ref (text, select, checkbox) | `form_input`(ref, value) | yes | `fill T "text"`, `select T "opt"`, `set_checked T true` | [browser_use.py#L791](https://github.com/browser-use/browser-use/blob/main/browser_use/integrations/anthropic/browser_use.py#L791) |
| Read all text of the page | `get_page_text`() | yes | `read page_text as text` | [browser_use.py#L1050](https://github.com/browser-use/browser-use/blob/main/browser_use/integrations/anthropic/browser_use.py#L1050) |
| Read the browser console | `read_console`() | yes | `read console as log` (every message), `read console_errors` | [browser_use.py#L1086](https://github.com/browser-use/browser-use/blob/main/browser_use/integrations/anthropic/browser_use.py#L1086) |
| Read the network log | `read_network`() | yes | `read requests as calls` (METHOD STATUS URL), `read response "words"` (a body) | [browser_use.py#L1093](https://github.com/browser-use/browser-use/blob/main/browser_use/integrations/anthropic/browser_use.py#L1093) |
| List open tabs | `list_tabs`() | yes | `read tabs as tabs` | [browser_use.py#L1129](https://github.com/browser-use/browser-use/blob/main/browser_use/integrations/anthropic/browser_use.py#L1129) |

### 2. MCP tools

browser-use has two MCP servers. `browser-use --mcp` runs `browser_use/mcp/server.py` (16 tools).
`browser-use --cli-mcp` runs `browser_use/mcp/cli_mcp.py` (2 tools). Dejo has one server with 5 tools;
almost everything below is a step line inside `dejo_run`.

| Capability (plain words) | browser-use name (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Open a web address | `browser_navigate`(url, new_tab) | yes | `dejo_run` with `go URL` or `tab new URL` | [server.py#L221](https://github.com/browser-use/browser-use/blob/main/browser_use/mcp/server.py#L221) |
| Click by number or by x,y | `browser_click`(index, or coordinate_x + coordinate_y, new_tab) | yes | `click T`, `mouse click X Y`; `click T keys=Control` opens a link in a new tab | [server.py#L233](https://github.com/browser-use/browser-use/blob/main/browser_use/mcp/server.py#L233) |
| Type into a field | `browser_type`(index, text) | yes | `fill T "text"` | [server.py#L259](https://github.com/browser-use/browser-use/blob/main/browser_use/mcp/server.py#L259) |
| See the page and its clickable elements | `browser_get_state`(include_screenshot) | yes | `look`, `look words`, `look all`, `look from REF` (one line per element with refs); `look image` adds the screenshot | [server.py#L277](https://github.com/browser-use/browser-use/blob/main/browser_use/mcp/server.py#L277) |
| Pull content out with a model | `browser_extract_content`(query, extract_links); calls browser-use's own model, needs an API key | not in Dejo, on purpose | The user's own agent does this: it reads `read page_text` / `look` and picks the facts | [server.py#L292](https://github.com/browser-use/browser-use/blob/main/browser_use/mcp/server.py#L292) |
| Get the raw HTML (page or one CSS selector) | `browser_get_html`(selector) | partly | `read html css "sel" as html`; the page: `read html css "html"`. Missing: anything past 20,000 characters | [server.py#L308](https://github.com/browser-use/browser-use/blob/main/browser_use/mcp/server.py#L308) |
| Screenshot returned as an image | `browser_screenshot`(full_page) | yes | `look image` (the screen); `screenshot full` saves the whole page as a file | [server.py#L322](https://github.com/browser-use/browser-use/blob/main/browser_use/mcp/server.py#L322) |
| Scroll the page | `browser_scroll`(direction up/down) | yes | `scroll down`, `scroll up` | [server.py#L337](https://github.com/browser-use/browser-use/blob/main/browser_use/mcp/server.py#L337) |
| Go back | `browser_go_back`() | yes | `back` | [server.py#L352](https://github.com/browser-use/browser-use/blob/main/browser_use/mcp/server.py#L352) |
| List open tabs | `browser_list_tabs`() | yes | `read tabs as tabs` | [server.py#L358](https://github.com/browser-use/browser-use/blob/main/browser_use/mcp/server.py#L358) |
| Switch tab | `browser_switch_tab`(tab_id) | yes | `tab N`, `tab latest`, `tab main` | [server.py#L364](https://github.com/browser-use/browser-use/blob/main/browser_use/mcp/server.py#L364) |
| Close a tab | `browser_close_tab`(tab_id) | yes | `tab close [N\|latest]` | [server.py#L375](https://github.com/browser-use/browser-use/blob/main/browser_use/mcp/server.py#L375) |
| Hand the task to browser-use's own AI agent | `retry_with_browser_use_agent`(task, max_steps, model, allowed_domains, use_vision) | not in Dejo, on purpose | The user's own agent is the brain; Dejo never runs a model | [server.py#L392](https://github.com/browser-use/browser-use/blob/main/browser_use/mcp/server.py#L392) |
| List live browser sessions | `browser_list_sessions`() | partly | `dejo_profile()` lists the signed-in profiles. Missing: live sessions with last-activity time | [server.py#L431](https://github.com/browser-use/browser-use/blob/main/browser_use/mcp/server.py#L431) |
| Close one browser session | `browser_close_session`(session_id) | no | — (the browser closes when the server stops) | [server.py#L437](https://github.com/browser-use/browser-use/blob/main/browser_use/mcp/server.py#L437) |
| Close every browser session | `browser_close_all`() | no | — | [server.py#L451](https://github.com/browser-use/browser-use/blob/main/browser_use/mcp/server.py#L451) |
| Run Python with browser helpers (`new_tab`, `click_at_xy`, `js`, `cdp`, ...) | `browser_exec`(code) — cli-mcp server | partly | `js CODE` runs JavaScript in the page; `mouse click X Y`, `tab new URL` are steps. Missing: Python, raw Chrome DevTools (CDP) calls | [cli_mcp.py#L48](https://github.com/browser-use/browser-use/blob/main/browser_use/mcp/cli_mcp.py#L48) |
| Screenshot as an image, with a size limit | `browser_screenshot`(full, max_dim) — cli-mcp server | partly | `look image`. Missing: a size limit | [cli_mcp.py#L65](https://github.com/browser-use/browser-use/blob/main/browser_use/mcp/cli_mcp.py#L65) |

### 3. Browser options a user can set (`BrowserProfile`, `browser_use/browser/profile.py`)

In Dejo, the MCP server is set only by environment variables (`DEJO_AGENT`, `DEJO_PROFILE`,
`DEJO_PROFILES_DIR`, `DEJO_DB`, `DEJO_LOCALE`). The Python engine's `Browser(headless, touch,
permissions, geolocation, timeout_ms)` cannot be reached from MCP.

| Capability (plain words) | browser-use name (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Hidden or visible browser window | `headless` (env `BROWSER_USE_HEADLESS`) | yes | `DEJO_HEADED=1` shows it (or `dejo run --headed`); hidden otherwise | [profile.py#L430](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L430) |
| Connect to a Chrome that is already running (CDP) | `cdp_url` | yes | `DEJO_CDP_URL=http://127.0.0.1:9222` (or `dejo run --cdp URL`) | [profile.py#L609](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L609) |
| Use a hosted (cloud) browser | `use_cloud`, `cloud_browser_params` | partly | `DEJO_CDP_URL=wss://...` drives a cloud browser you started. Missing: starting one for you | [profile.py#L611](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L611) |
| Folder that keeps the browser's data (stay signed in) | `user_data_dir` | yes | `DEJO_PROFILE` (default profile folder), `DEJO_PROFILES_DIR`, `dejo_profile(name)` | [profile.py#L557](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L557) |
| Pick one Chrome profile inside that folder ("Profile 1") | `profile_directory` | no | — | [profile.py#L714](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L714) |
| Load / save cookies and storage from a JSON file | `storage_state` (auto-saved every 30 s) | yes | `state save NAME`, `state load NAME\|"/path/state.json"` (no auto-save; profiles keep sign-ins anyway) | [profile.py#L522](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L522) |
| Choose which browser program | `executable_path`, `channel` | partly | Dejo uses real Chrome when installed, else the bundled Chromium. Missing: the user cannot choose | [profile.py#L425](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L425) |
| Extra / removed Chrome command-line flags | `args`, `ignore_default_args` | no | — | [profile.py#L434](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L434) |
| Environment variables for the browser | `env` | no | — | [profile.py#L421](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L421) |
| Chromium sandbox on/off (for Docker) | `chromium_sandbox` | no | — | [profile.py#L447](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L447) |
| Open DevTools with each page | `devtools` | no | — | [profile.py#L450](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L450) |
| Extra headers when connecting to a remote browser | `headers` | no | — | [profile.py#L400](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L400) |
| Set the user agent | `user_agent` | partly | only the one that comes with `emulate device "..."`; no string of your own | [profile.py#L373](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L373) |
| Page size | `viewport`, `screen`, `no_viewport` | yes | `emulate viewport 1280x800` | [profile.py#L375](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L375) |
| Window size and place on screen | `window_size`, `window_position` | no | — | [profile.py#L665](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L665) |
| Pixel density (retina) | `device_scale_factor` | partly | `emulate device "iPhone 13"` brings that device's density. Missing: a number of your own | [profile.py#L377](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L377) |
| Grant browser permissions (clipboard, notifications, ...) | `permissions` | yes | `allow clipboard-read notifications`, `allow off` | [profile.py#L363](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L363) |
| Allow downloads and choose the folder | `accept_downloads`, `downloads_path` | partly | always saved to `~/.dejo/downloads` and count as a check; `read downloads` lists them. Missing: choosing the folder | [profile.py#L455](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L455) |
| Download a PDF instead of showing it | `auto_download_pdfs` | no | — | [profile.py#L712](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L712) |
| Send traffic through a proxy | `proxy`(server, bypass, username, password) | partly | `DEJO_PROXY=http://proxy:8080` (server only). Missing: bypass list, username and password | [profile.py#L644](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L644) |
| Only allow some websites | `allowed_domains` | no | — | [profile.py#L628](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L628) |
| Block some websites | `prohibited_domains` | yes | `block "https://ads.example.com/**"` (a step, kept in the trail) | [profile.py#L632](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L632) |
| Block bare IP addresses (and localhost) | `block_ip_addresses` | no | — | [profile.py#L636](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L636) |
| Turn off browser security (CORS etc.) | `disable_security` | no | — | [profile.py#L626](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L626) |
| Same drawing on every machine | `deterministic_rendering` | no | — | [profile.py#L627](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L627) |
| Keep the browser open after the run | `keep_alive` | partly | The MCP server keeps one browser open between calls until it stops. Missing: a setting | [profile.py#L640](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L640) |
| Built-in extensions: ad blocker, cookie-banner remover, URL cleaner | `enable_default_extensions` | partly | `dismiss css "SEL"` closes a cookie banner (remembered per site); `block "PATTERN"` stops ads you name. Missing: a ready ad-block list, URL cleaning | [profile.py#L648](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L648) |
| Leave cookie banners alone on some sites | `cookie_whitelist_domains` | yes | Dejo only dismisses a banner on a site where the agent added `dismiss`; every other site is left alone | [profile.py#L660](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L660) |
| Solve captchas | `captcha_solver` | not in Dejo, on purpose | Dejo stops and hands the captcha to the person | [profile.py#L652](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L652) |
| Show the agent's log inside the browser window | `demo_mode` | no | — | [profile.py#L656](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L656) |
| Draw numbered boxes on clickable elements | `highlight_elements`, `dom_highlight_elements`, `filter_highlight_ids` | partly | `highlight T` and `hide_highlight` for one element when asked. Missing: boxes on every element | [profile.py#L697](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L697) |
| Colour and time of the click flash | `interaction_highlight_color`, `interaction_highlight_duration` | no | — | [profile.py#L705](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L705) |
| Work inside iframes from other sites | `cross_origin_iframes`, `max_iframes`, `max_iframe_depth` | yes | Refs reach inside iframes (`f1e3`); saved steps keep the iframe. The limits are not settable | [profile.py#L675](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L675) |
| How long to wait for a page to settle | `minimum_wait_page_load_time`, `wait_for_network_idle_page_load_time` | partly | `wait idle`, `wait T`, `wait SECONDS` per step. Missing: one global setting | [profile.py#L691](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L691) |
| Pause between every action | `wait_between_actions` | no | — (only `wait SECONDS` as its own step) | [profile.py#L694](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L694) |
| Hide elements that are covered by others | `paint_order_filtering` | no | — | [profile.py#L704](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L704) |
| Record a video of the session | `record_video_dir`, `record_video_size`, `record_video_framerate` | partly | `record video` ... `record stop`, or `DEJO_RECORD=video`. Missing: size and frame rate | [profile.py#L723](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L723) |
| Record all network traffic (HAR file) | `record_har_path`, `record_har_content`, `record_har_mode` | no | — | [profile.py#L383](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L383) |
| Save a Playwright trace | `traces_dir` | yes | `record trace` ... `record stop`, or `DEJO_RECORD=trace` | [profile.py#L460](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L460) |

Not in browser-use at all: geolocation (the field is commented out, [profile.py#L378](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L378)),
time zone, locale, device presets, colour scheme, offline mode. Dejo's engine has geolocation and touch, and
reads the locale from `DEJO_LOCALE`, so in these Dejo is a little ahead, though not from MCP.

### 4. Other features

| Capability (plain words) | browser-use name (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| The model looks at screenshots (vision) | `Agent(use_vision=True/False/'auto', vision_detail_level, llm_screenshot_size)` | yes | `look image` puts a picture of the screen in the reply when the agent asks; text first (`look`) otherwise | [agent/service.py#L170](https://github.com/browser-use/browser-use/blob/main/browser_use/agent/service.py#L170) |
| Keep passwords away from the model | `Agent(sensitive_data={name: value} or {domain: {name: value}})`; the model writes `<secret>name</secret>` and the real value is put in just before typing | partly | A password field's value is never saved; replay takes it from `DEJO_SECRET_...` or `~/.dejo/secrets.json`; `share` never sends typed values; `dejo_login` lets the person sign in by hand. Missing: a placeholder in step lines, so the agent sees the password the first time; only `type=password` fields count as secret | [registry/service.py#L442](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/registry/service.py#L442) |
| Save a run and replay it later | `save_history`, `load_and_rerun`(history_file), `rerun_history`(max_retries, skip_failures, delay_between_actions, ai_step_llm, wait_for_elements) | yes | This is Dejo's core: `dejo_run(site, task)` replays with zero model calls, each step has a check, only the step that moved is re-learned. (browser-use's replay still calls a model for `extract` steps and the summary, and has no per-step check) | [agent/service.py#L3128](https://github.com/browser-use/browser-use/blob/main/browser_use/agent/service.py#L3128) |
| Replay with new values (variables) | `load_and_rerun`(variables={'email': ...}) | no | — (a remembered task types the values it learned; for new values the agent sends the steps again) | [agent/service.py#L3906](https://github.com/browser-use/browser-use/blob/main/browser_use/agent/service.py#L3906) |
| Run fixed actions with no model | `Agent(initial_actions=[...])` | yes | Every step line in `steps` runs with no model | [agent/service.py#L153](https://github.com/browser-use/browser-use/blob/main/browser_use/agent/service.py#L153) |
| Add your own actions, or remove built-in ones | `@tools.action(...)`, `Tools(exclude_actions=[...])` | no | — (verbs are fixed in `actions.ACTIONS` and `reads.READS`; `js CODE` covers one-off needs) | [tools/service.py#L2102](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py#L2102) |
| Ready-made hosted "skills" | `Agent(skill_ids=[...])` via the Browser Use API | partly | Agents share learned tasks on one machine: `dejo_manage do=share/borrow`, `dejo_memory what=commons`. Missing: a hosted catalog | [skills/service.py](https://github.com/browser-use/browser-use/blob/main/browser_use/skills/service.py) |
| Typed result for the whole task | `Agent(output_model_schema=..., extraction_schema=...)` | not in Dejo, on purpose | The user's own agent does this | [agent/service.py#L168](https://github.com/browser-use/browser-use/blob/main/browser_use/agent/service.py#L168) |
| The agent loop: model, planning, judge, loop check, retries, fallback model, thinking, flash mode, memory compaction, cost | `Agent(llm, enable_planning, use_judge, loop_detection_enabled, max_failures, fallback_llm, use_thinking, flash_mode, message_compaction, max_actions_per_step, step_timeout, calculate_cost, extend_system_message, ...)` | not in Dejo, on purpose | The user's own agent does this; Dejo has no model | [agent/service.py#L137](https://github.com/browser-use/browser-use/blob/main/browser_use/agent/service.py#L137) |
| Save the model conversation | `Agent(save_conversation_path)` | not in Dejo, on purpose | The user's own agent does this | [agent/service.py#L171](https://github.com/browser-use/browser-use/blob/main/browser_use/agent/service.py#L171) |
| Make a GIF of the run | `Agent(generate_gif)` | no | — | [agent/service.py#L176](https://github.com/browser-use/browser-use/blob/main/browser_use/agent/service.py#L176) |
| Callbacks on each step, at the end, or to stop | `register_new_step_callback`, `register_done_callback`, `register_should_stop_callback` | partly | The engine sends typed events (`events.py`) to Python callers. Missing: anything through MCP | [agent/service.py#L155](https://github.com/browser-use/browser-use/blob/main/browser_use/agent/service.py#L155) |
| Pop-up dialogs handled by themselves | `PopupsWatchdog`: accept alert / confirm / beforeunload, cancel prompt | yes | Accepted by themselves and recorded; `dialog dismiss` cancels the next one, `dialog accept "text"` answers a prompt; replay stops if the message changed | [popups_watchdog.py](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/watchdogs/popups_watchdog.py) |
| Read emails for one-time codes (Gmail) | Gmail action `get_recent_emails`(keyword) | no | — (`dejo_login` lets the person type the code by hand) | [gmail/actions.py#L47](https://github.com/browser-use/browser-use/blob/main/browser_use/integrations/gmail/actions.py#L47) |
| Stealth browsers, captcha solving, home-network proxies (cloud) | Browser Use Cloud (README) | not in Dejo, on purpose | Dejo never gets round a site's bot block; it hands over to the person | [README.md](https://github.com/browser-use/browser-use/blob/main/README.md) |
| Hide that the browser is automated | default drops `--enable-automation` ("we mask the automation fingerprint") | not in Dejo, on purpose | Dejo only removes the "HeadlessChrome" word from its user agent, so it is honest | [profile.py#L437](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/profile.py#L437) |
| Command line that runs Python against a lasting browser | `browser-use <<'PY' ... PY` with `new_tab`, `goto_url`, `page_info`, `click_at_xy`, `type_text`, `fill_input`, `press_key`, `scroll`, `js`, `cdp`, `wait_for_load`, `wait_for_element`, `list_tabs`, `switch_tab`, `close_tab` | partly | `dejo` CLI: `run` (replay), `login`, `sites`, `show`, `map`, `forget`, `share`, `borrow`, `commons`, `doctor`, `export`. Missing: writing new steps from the shell (they go through MCP `dejo_run`) | [cli.py#L241](https://github.com/browser-use/browser-use/blob/main/browser_use/cli.py#L241) |
| Health check | `browser-use doctor` (also `--doctor`) | yes | `dejo doctor` | [cli.py#L193](https://github.com/browser-use/browser-use/blob/main/browser_use/cli.py#L193) |
| Its agent uses other MCP servers | `browser_use/mcp/client.py` | not in Dejo, on purpose | The user's own agent connects to other MCP servers | [mcp/client.py](https://github.com/browser-use/browser-use/blob/main/browser_use/mcp/client.py) |
| Runs as Claude's own browser toolset | `integrations/anthropic` driver ("31 browser actions") | partly | Dejo is one MCP server that Claude and every other agent use. Missing: the Claude toolset's action names and x,y actions | [anthropic/browser_use.py](https://github.com/browser-use/browser-use/blob/main/browser_use/integrations/anthropic/browser_use.py) |

## Stagehand

Source: <https://github.com/browserbase/stagehand>. License: MIT. The copyright line in `LICENSE` is: `Copyright (c) 2024 Browserbase Inc.`

### 1. Core methods: act, observe, extract, agent

| Capability (plain words) | Stagehand name (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Do one action from an English sentence; the model picks the element | `stagehand.act(instruction, { model, timeout, page })` | not in Dejo, on purpose | The agent writes the step itself: `click button "Log in"` | [stagehand.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/stagehand.ts) |
| Replay a planned action with no model call | `stagehand.act(action)` where `action = { selector, method, arguments, description }` | yes | A learned task replays its whole trail with zero model calls; one step by ref: `click e12` | [act docs](https://docs.stagehand.dev/v4/basics/act) |
| Fix a step when its saved selector stops working (self-heal) | `selfHeal: true` on `Stagehand.create()` (off by default; asks the model again, retries once) | yes | Replay stops at the step that moved; the agent re-learns only that step. Dejo itself calls no model | [actService.ts](https://github.com/browserbase/stagehand/blob/main/packages/extension/services/actService.ts) |
| Keep secret values out of the instruction (`%name%` placeholders) | `variables` on `act()` / `observe()` (`{ name: value }` or `{ value, description }`) | partly | Passwords never go into memory: read at run time from `DEJO_SECRET_<SITE>_<FIELD>` or `~/.dejo/secrets.json`. No general named variables in step lines | [schemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/protocol/schemas.ts) |
| Find elements from an English question; get back selectors to use later | `stagehand.observe(instruction?)` returns `[{ selector, description, method, arguments }]` | not in Dejo, on purpose | Model-free: `look` or `look WORDS` lists elements with refs (`e12`); the agent picks one | [stagehand.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/stagehand.ts) |
| Limit act / observe / extract to one part of the page | `options.locator` | partly | `look from REF`, `look gN`; every read takes a target T | [schemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/protocol/schemas.ts) |
| Hide parts of the page (nav, ads, cookie banner) from the view | `options.ignoreLocators` | no | — (`dismiss css "SEL"` clicks banners away, but `look` cannot skip a region) | [schemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/protocol/schemas.ts) |
| Pull typed data with a model and a schema | `stagehand.extract(instruction, zodSchema \| PydanticModel, { locator, ignoreLocators, screenshot, timeout, model, cache })` | not in Dejo, on purpose | Model-free instead: `read fields '{"name": "h3", "price": ".price"}' css "article" as items` (see section 4) | [extractService.ts](https://github.com/browserbase/stagehand/blob/main/packages/extension/services/extractService.ts) |
| Get many named fields, or a list of rows, back as one JSON object (model-free) | what `extract` with `z.object` / `z.array` gives | yes | `read fields '{"name": "h3", "price": ".price", "link": "a@href"}' css "article" as items` (one object per row), `read table T as rows` | [extract docs](https://docs.stagehand.dev/v4/basics/extract) |
| Free-text answer about the page | `extract(instruction)` with no schema returns `{ extraction: string }` | not in Dejo, on purpose | `read page_text as body`, then the agent reads it | [schemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/protocol/schemas.ts) |
| Get the real URL of links | `z.url()` fields in `extract` (model picks an element ID, Stagehand swaps in the URL) | yes | `read attr href T as link` | [extractService.ts](https://github.com/browserbase/stagehand/blob/main/packages/extension/services/extractService.ts) |
| Send a screenshot to the model during extract | `extract` `options.screenshot` | not in Dejo, on purpose | `look image` sends a picture to the agent's own model | [schemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/protocol/schemas.ts) |
| Pick the model (per instance or per call), Model Gateway, or your own LLM callback | `model: { modelName, apiKey, headers }`, `model: { generate }`, `options.model` | not in Dejo, on purpose | — The user's agent is the model; Dejo needs no API key | [clientSchemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/clientSchemas.ts) |
| Extra system prompt for the model | `systemPrompt` on `Stagehand.create()` | not in Dejo, on purpose | — (`note "fact"` keeps site knowledge for the agent to read) | [schemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/protocol/schemas.ts) |
| Token and timing numbers per call | `stagehand.metrics()`, `result.metadata.usage` | not in Dejo, on purpose | — Dejo spends no tokens | [stagehand.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/stagehand.ts) |
| Cache results so a repeat call skips the model | `cache: true \| { threshold }` on create, `options.cache` per call (server-side, Browserbase only, on by default) | yes | Every learned task is saved as a trail and replayed with zero model calls, on the user's own machine | [caching docs](https://docs.stagehand.dev/v4/best-practices/caching) |
| See if a call came from the cache, and why it missed | `metadata.cache = { status: HIT \| MISS \| DISABLED, count, threshold, missReason, tokensSaved }` | yes | `dejo_run` says whether it replayed or is learning, and names the step that moved | [schemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/protocol/schemas.ts) |
| Local action cache in a folder (v3) | `enableCaching`, `cacheDir` (v3; removed in v4) | yes | Trails live in `~/.dejo` (SQLite); `dejo_memory`, `dejo_manage do=forget` | [v3 to v4 guide](https://docs.stagehand.dev/v4/migrations/v3) |
| Built-in agent loop that plans and runs many steps (v3) | `stagehand.agent({ mode: "cua", tools, systemPrompt }).execute({ instruction, maxSteps })` (v3; removed in v4) | not in Dejo, on purpose | — The user's own agent is the loop | [v3 to v4 guide](https://docs.stagehand.dev/v4/migrations/v3) |
| Run many browser commands in one round trip | `stagehand.experimentalBatch(callback, input, { timeout, page })` | yes | Many step lines in one `dejo_run` `steps` argument | [batch.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/batch.ts) |
| Call tools that the web page itself publishes (WebMCP) | `page.tools()`, `tool.invoke({ input })`, `invocation.result()`, `page.onToolsAdded()` / `onToolsRemoved()` | no | — | [webmcp.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/webmcp.ts) |
| Web search with no browser | `browserbase.search({ apiKey, query, numResults })` | no | — | [factories.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/browser/factories.ts) |
| Fetch a URL as raw / markdown / JSON with no browser | `browserbase.fetch({ apiKey, url, format, proxies, schema, allowRedirects })` | no | — (`go URL` then `read page_text as body` uses the browser) | [clientSchemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/clientSchemas.ts) |

### 2. Page and context API (no model)

| Capability (plain words) | Stagehand name (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Open a URL | `page.goto(url, { waitUntil, timeout })` | yes | `go URL` (add `wait idle` when needed) | [page.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/page.ts) |
| Read the HTTP answer of a page load (status, headers, body, JSON, TLS, server address) | `goto()` / `reload()` return `Response`: `allHeaders()`, `headerValue()`, `body()`, `text()`, `json()`, `securityDetails()`, `serverAddr()` | partly | `read requests "words"` (status), `read response "words"` (body or JSON). Missing: headers, TLS, server address | [response.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/response.ts) |
| Reload | `page.reload({ ignoreCache, waitUntil, timeout })` | yes | `reload` (no ignore-cache choice) | [page.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/page.ts) |
| Back and forward | `page.goBack()`, `page.goForward()` | yes | `back`, `forward` | [page.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/page.ts) |
| Click at a screen point, any button, N clicks | `page.click(x, y, { button, clickCount })` | yes | `mouse click X Y`, `mouse dblclick X Y`, `mouse right X Y` (no middle button at a point) | [page.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/page.ts) |
| Move the mouse to a screen point | `page.hover(x, y)` | yes | `mouse move X Y` | [page.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/page.ts) |
| Mouse wheel at a point, up/down and sideways | `page.scroll(x, y, deltaX, deltaY)` | yes | `mouse move X Y` then `mouse wheel DX DY` | [page.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/page.ts) |
| Drag between points, with steps, delay and a path | `page.dragAndDrop(fromX, fromY, toX, toY, { button, steps, delay, route })` | partly | `mouse drag X Y to X2 Y2`, `drag T to T`. Missing: steps, delay, a path | [page.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/page.ts) |
| Type into whatever has focus, with a delay per key | `page.type(text, { delay })` | partly | `type T "text" delay=100` (needs a target) | [page.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/page.ts) |
| Type with fake typing mistakes to look human | `page.type(text, { withMistakes })` | not in Dejo, on purpose | — (looking human is a way to hide automation) | [page.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/page.ts) |
| Press a key | `page.keyPress(key, { delay })` | yes | `press KEY [T]`, chords like `press Control+A` | [page.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/page.ts) |
| Run JavaScript and get the result | `page.evaluate(fnOrString, arg)` | yes | `js CODE` (must be alone; not remembered) | [page.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/page.ts) |
| Run a script before every page loads | `page.addInitScript(script, arg)`, `context.addInitScript(script, arg)` | yes | `script "window.tour = false"` (not kept in a trail) | [browserContext.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/browserContext.ts) |
| Answer alert / confirm dialogs | none (docs say: stub `window.confirm` with `addInitScript`) | yes | Accepted on their own, or `dialog dismiss` / `dialog accept "text"` first; message recorded; replay stops if it changed | [Playwright migration](https://docs.stagehand.dev/v4/migrations/playwright) |
| Watch console messages | `page.on("console", listener)` | yes | `read console as log` (every message), `read console_errors` | [page.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/page.ts) |
| Send extra HTTP headers | `page.setExtraHTTPHeaders(h)`, `context.setExtraHTTPHeaders(h)` | yes | `header set NAME "VALUE"`, `header clear` | [page.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/page.ts) |
| Change the window size | `page.setViewportSize(w, h, { deviceScaleFactor })` | yes | `emulate viewport 1024x768` (pixel ratio only through `emulate device "..."`) | [page.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/page.ts) |
| Wait for a load state | `page.waitForLoadState("load" \| "domcontentloaded" \| "networkidle", timeout)` | partly | `wait idle` (network idle only) | [page.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/page.ts) |
| Wait a fixed time | `page.waitForTimeout(ms)` | yes | `wait SECONDS` | [page.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/page.ts) |
| Wait until a JavaScript test is true | `page.waitForFunction(fn, arg, { polling, timeout })` | no | — | [page.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/page.ts) |
| Wait for an element to show up or go away | `page.waitForSelector(sel, { state: attached\|detached\|visible\|hidden, timeout, pierceShadow })` | yes | `wait T`, `wait element:CSS`, `wait gone:CSS`, `wait text:WORDS`, `wait url:PART` | [page.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/page.ts) |
| Take a screenshot | `page.screenshot({ fullPage, clip, mask, maskColor, type, quality, animations, caret, style, omitBackground, scale, path })` | partly | `screenshot [T\|full] [as NAME]`, `look image`. No clip, mask, JPEG or quality | [schemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/protocol/schemas.ts) |
| Save the page as a PDF | `page.pdf({ landscape, printBackground, scale, margin, pageRanges, headerTemplate, ... })` | partly | `pdf [as NAME]`. No landscape, margins, page ranges or header and footer | [page.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/page.ts) |
| Text view of the page for an agent (accessibility tree), iframes included | `page.snapshot({ includeIframes, timeout })` returns `formattedTree`, `xpathMap`, `urlMap` | yes | `look`, `look all`, `look raw`; refs like `f1e3` reach inside iframes | [page.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/page.ts) |
| Page URL and title | `page.url()`, `page.title()` | yes | `read url as u`, `read title as t` | [page.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/page.ts) |
| Close a tab | `page.close()` | yes | `tab close [N\|latest]` | [page.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/page.ts) |
| Find an element by CSS | `page.locator("css")` | yes | `css ".."` | [locator docs](https://docs.stagehand.dev/v4/reference/locator) |
| Find an element by XPath, even a deep XPath through iframes | `page.locator("/html/body/iframe[2]//div")` | no | — | [locator docs](https://docs.stagehand.dev/v4/reference/locator) |
| Reach elements inside iframes | `page.locator("iframe#checkout >> button.submit")` (v3: `page.deepLocator()`) | yes | Refs like `f1e3`; saved steps keep the iframe selector; `wait in_frame:FRAME` | [locator docs](https://docs.stagehand.dev/v4/reference/locator) |
| Reach elements inside open shadow DOM | `page.locator(sel)` pierces shadow roots | yes | `css ".."` pierces open shadow DOM | [locator docs](https://docs.stagehand.dev/v4/reference/locator) |
| Reach elements inside closed shadow DOM | `page.locator(sel)` (needs an http/https page) | no | — | [locator docs](https://docs.stagehand.dev/v4/reference/locator) |
| Pick the first or Nth match | `locator.first()`, `locator.nth(i)` | yes | `first`, `last`, `nth N`, `has "text"` after a target | [locator.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/locator.ts) |
| Click an element with right or middle button, or N times | `locator.click({ button, clickCount, timeout })` | partly | `click T`, `double_click T`. No right or middle click | [locator.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/locator.ts) |
| Hover an element | `locator.hover()` | yes | `hover T` | [locator.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/locator.ts) |
| Fill a field | `locator.fill(value)` | yes | `fill T "text"` | [locator.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/locator.ts) |
| Type key by key, with a delay | `locator.type(text, { delay })` | partly | `type T "text"` (no delay) | [locator.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/locator.ts) |
| Choose from a dropdown | `locator.selectOption(values)` | yes | `select T "opt"` (value, `label:`, `index:`, several with commas; custom comboboxes too) | [locator.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/locator.ts) |
| Upload files (paths or bytes in memory, up to 50 MiB each) | `locator.setInputFiles(files)` | yes | `upload T "path[,path]"` (paths only) | [locator.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/locator.ts) |
| Scroll inside an element to a percent | `locator.scrollTo(percent)` | partly | `scroll T down [PIXELS]` (by pixels, not by percent) | [locator.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/locator.ts) |
| Get the centre point of an element | `locator.centroid()` | yes | `read box T as box` (X Y WIDTH HEIGHT; the centre is X + WIDTH/2, Y + HEIGHT/2) | [locator.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/locator.ts) |
| Highlight an element | `locator.highlight({ durationMs, borderColor, contentColor })` | yes | `highlight T`, `hide_highlight` (no time or colour choice) | [locator.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/locator.ts) |
| Fire a DOM click event without a real mouse click | `locator.sendClickEvent({ bubbles, cancelable, composed, detail })` | yes | `dispatch_event T "click"` | [locator.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/locator.ts) |
| Read count, checked, value, visible | `locator.count()`, `isChecked()`, `inputValue()`, `isVisible()` | yes | `read count T as n`, `read checked T as c`, `read value T as v`, `read visible T as s` | [locator.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/locator.ts) |
| Read the visible text of an element | `locator.innerText()` | yes | `read text T as name` | [locator.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/locator.ts) |
| Read all text of an element, hidden text too | `locator.textContent()` | partly | `read text T` gives visible text only; hidden text only inside `read html T` | [locator.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/locator.ts) |
| Read the HTML inside an element | `locator.innerHtml()` | yes | `read html T as markup` (outer HTML, cut after 20,000 characters) | [locator.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/locator.ts) |
| A time limit on each call | `timeout` on every locator call (default 20 s), on `goto`, `act`, `observe`, `extract` | no | — (engine `Browser(timeout_ms)` exists but not from MCP) | [schemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/protocol/schemas.ts) |
| List the open tabs | `context.pages()` | yes | `read tabs as tabs` | [browserContext.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/browserContext.ts) |
| Open a new tab | `context.newPage(url?)` | yes | `tab new [URL]` | [browserContext.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/browserContext.ts) |
| Get or set the active tab | `context.activePage()`, `context.setActivePage(page)`; `options.page` on act/observe/extract | yes | `tab N`, `tab latest`, `tab main` | [browserContext.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/browserContext.ts) |
| Allow or block whole domains | `context.setDomainPolicy({ allowedDomains, blockedDomains })`, `getDomainPolicy()` | partly | `block "https://tracker.example/**"` blocks. Missing: an allow-only list, reading the policy back | [browserContext.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/browserContext.ts) |
| Read cookies | `context.cookies(urls?)` | yes | `read cookies ["words"] as c` (an httpOnly cookie's value is hidden) | [browserContext.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/browserContext.ts) |
| Add cookies | `context.addCookies([{ name, value, url \| domain, path, expires, httpOnly, secure, sameSite }])` | partly | `cookie set NAME "VALUE"` for this page's site; `state load NAME` adds whole cookies from a file. Missing: domain, path, expiry, flags in a step | [browserContext.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/browserContext.ts) |
| Clear cookies, all or by name / domain / path | `context.clearCookies({ name, domain, path })` (string or RegExp) | partly | `cookie clear`, `cookie clear NAME`. Missing: by domain or path, RegExp | [browserContext.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/browserContext.ts) |
| Read or write clipboard text | `context.clipboard.readText()`, `writeText(text)`, `clear()` | no | — | [browserClipboard.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/browserClipboard.ts) |
| Copy, cut, paste in the page | `context.clipboard.copy()`, `cut()`, `paste({ shortcut })` | partly | `press Control+C`, `press Control+X`, `press Control+V` | [browserClipboard.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/browserClipboard.ts) |

### 3. Options (browser launch and `Stagehand.create`)

| Capability (plain words) | Stagehand name (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Start a local Chrome | `localBrowser.launch(options)` (v3: `env: "LOCAL"`, `localBrowserLaunchOptions`) | yes | Starts by itself on the first `dejo_run` | [factories.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/browser/factories.ts) |
| Hidden or visible window | `headless` | yes | `DEJO_HEADED=1` (or `dejo run --headed`); hidden otherwise | [clientSchemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/clientSchemas.ts) |
| Window size and pixel ratio | `viewport: { width, height }`, `deviceScaleFactor` | partly | `emulate viewport 1280x720`; pixel ratio only through `emulate device "..."` | [clientSchemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/clientSchemas.ts) |
| Touch screen | `hasTouch` | partly | `tap T` needs touch mode, which is engine only (`Browser(touch=True)`); `emulate device` turns on touch events but not `tap` | [clientSchemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/clientSchemas.ts) |
| Browser language | `locale` | yes | `emulate locale de-DE`, or `DEJO_LOCALE` | [clientSchemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/clientSchemas.ts) |
| Keep a signed-in profile on disk | `userDataDir`, `preserveUserDataDir` (cloud: `browserSettings.context: { id, persist }`) | yes | Profiles under `~/.dejo`: `dejo_profile(name)`, `dejo_login` | [clientSchemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/clientSchemas.ts) |
| Downloads | `acceptDownloads`, `downloadsPath` (no download event) | partly | Saved by itself to `~/.dejo/downloads`, counted as a postcondition, listed by `read downloads`; folder cannot be chosen | [clientSchemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/clientSchemas.ts) |
| Go through a proxy server (for example a company proxy) | `proxy: { server, bypass, username, password }` | partly | `DEJO_PROXY=http://proxy:8080` (server only). Missing: bypass, username and password | [clientSchemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/clientSchemas.ts) |
| Ignore HTTPS certificate errors | `ignoreHTTPSErrors` | yes | `DEJO_IGNORE_HTTPS_ERRORS=1` | [clientSchemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/clientSchemas.ts) |
| Own Chrome program and command-line flags | `executablePath`, `args`, `ignoreDefaultArgs`, `chromiumSandbox`, `port`, `devtools` | no | — | [clientSchemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/clientSchemas.ts) |
| Keep the browser running after the script ends, reconnect later | `keepAlive` | no | — (profiles keep the sign-in, not the open browser) | [clientSchemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/clientSchemas.ts) |
| Attach to a Chrome that is already running (CDP URL) | `localBrowser.connect({ cdpUrl, headers })` (v3: `localBrowserLaunchOptions.cdpUrl`) | yes | `DEJO_CDP_URL=http://127.0.0.1:9222` (or `dejo run --cdp URL`; no extra headers) | [factories.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/browser/factories.ts) |
| Run in a cloud browser | `browserbase.launch({ apiKey, region, timeout, keepAlive, userMetadata, browserSettings })`, `browserbase.connect({ sessionId })` (v3: `env: "BROWSERBASE"`) | partly | `DEJO_CDP_URL=wss://...` drives a cloud browser you started. Missing: starting or reconnecting a Browserbase session | [factories.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/browser/factories.ts) |
| Stealth: hide automation, fake fingerprint, fake OS, "verified" identity | `browserSettings.advancedStealth`, `verified`, `fingerprint`, `os` | not in Dejo, on purpose | Honest user agent; at a bot wall Dejo stops and hands over to the person | [schemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/protocol/schemas.ts) |
| Solve captchas | `browserSettings.solveCaptchas`, `captchaImageSelector`, `captchaInputSelector` | not in Dejo, on purpose | Dejo stops and hands over to the person | [schemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/protocol/schemas.ts) |
| Residential or country proxies to get past blocks | `proxies: true \| [{ type: "browserbase", geolocation }, { type: "external", server }]` | not in Dejo, on purpose | — | [schemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/protocol/schemas.ts) |
| Block ads | `browserSettings.blockAds` | partly | `block "PATTERN"` for each ad address you name. Missing: a ready ad list | [schemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/protocol/schemas.ts) |
| Record the session (video-like replay) and its logs | `browserSettings.recordSession`, `logSession` | yes | `record video`, `record trace` ... `record stop`, or `DEJO_RECORD=video,trace`; step log in `~/.dejo/logs/DATE.log` | [schemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/protocol/schemas.ts) |
| Wait for the page to stop changing before each step | `domSettleTimeoutMs` | partly | `wait idle`, `wait T`; no general setting | [schemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/protocol/schemas.ts) |
| Logs: level, format, callback | `logging: { level, format: "pretty" \| "json", onLog }` (v3: `verbose`, `logger`) | partly | plain step log `~/.dejo/logs/DATE.log` (`DEJO_LOG=off` stops it); typed events (`events.py`) for Python callers. No level or JSON option | [clientSchemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/sdk-ts/src/clientSchemas.ts) |
| Send traces to an OpenTelemetry collector | `telemetry: { traces: { endpoint, headers } }` | no | — | [schemas.ts](https://github.com/browserbase/stagehand/blob/main/packages/protocol/schemas.ts) |

### 4. MCP server tools

Repo: [browserbase/mcp-server-browserbase](https://github.com/browserbase/mcp-server-browserbase) v3.0.0,
Apache-2.0 ("Portions Copyright 2025 Browserbase, Inc"). **The repo is archived**; it keeps the same
6 tools as the hosted server at `https://mcp.browserbase.com/mcp`. It runs only on Browserbase (cloud),
uses Stagehand 3.x, and needs a model (default `google/gemini-2.5-flash-lite`).

| Capability (plain words) | Stagehand name (parameters) | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Start or reuse a browser session | `start` (no input) | yes | Browser starts by itself on the first `dejo_run`; `dejo_profile(name)` picks who is signed in | [session.ts](https://github.com/browserbase/mcp-server-browserbase/blob/main/src/tools/session.ts) |
| Close the session | `end` (no input) | partly | Browser closes when the MCP server stops; there is no close tool | [session.ts](https://github.com/browserbase/mcp-server-browserbase/blob/main/src/tools/session.ts) |
| Open a URL | `navigate { url }` | yes | `dejo_run(url=...)` or step `go URL` | [navigate.ts](https://github.com/browserbase/mcp-server-browserbase/blob/main/src/tools/navigate.ts) |
| Do an action from an English sentence | `act { action }` | not in Dejo, on purpose | The agent writes step lines in `dejo_run` `steps`: `click button "Log in"` | [act.ts](https://github.com/browserbase/mcp-server-browserbase/blob/main/src/tools/act.ts) |
| Find elements from an English question | `observe { instruction }` | not in Dejo, on purpose | `look WORDS` | [observe.ts](https://github.com/browserbase/mcp-server-browserbase/blob/main/src/tools/observe.ts) |
| Pull data from the page with a model | `extract { instruction? }` (no schema in the MCP tool) | not in Dejo, on purpose | `read text T as name`, `read page_text as body` | [extract.ts](https://github.com/browserbase/mcp-server-browserbase/blob/main/src/tools/extract.ts) |
| Server flags for stealth and block-dodging proxies | `--verified` (old name `--advancedStealth`), `--proxies` | not in Dejo, on purpose | — | [program.ts](https://github.com/browserbase/mcp-server-browserbase/blob/main/src/program.ts) |
| Server flags to keep a signed-in profile | `--contextId`, `--persist` | yes | `dejo_profile(name)`, `dejo_login` | [program.ts](https://github.com/browserbase/mcp-server-browserbase/blob/main/src/program.ts) |
| Server flags for window size | `--browserWidth`, `--browserHeight` (default 1024 x 768) | yes | `emulate viewport 1024x768` (a step, not a server flag) | [program.ts](https://github.com/browserbase/mcp-server-browserbase/blob/main/src/program.ts) |
| Server flags for the model | `--modelName`, `--modelApiKey` | not in Dejo, on purpose | — Dejo needs no API key | [program.ts](https://github.com/browserbase/mcp-server-browserbase/blob/main/src/program.ts) |
| Keep the cloud browser alive | `--keepAlive` | no | — | [program.ts](https://github.com/browserbase/mcp-server-browserbase/blob/main/src/program.ts) |
| Serve over HTTP (hosted or `--port` / `--host`) as well as stdio | SHTTP transport, `--port`, `--host` | no | — (stdio only) | [program.ts](https://github.com/browserbase/mcp-server-browserbase/blob/main/src/program.ts) |

Side note: the same Stagehand repo also has the `browse` CLI ([packages/cli](https://github.com/browserbase/stagehand/tree/main/packages/cli), v0.11.3):
an agent-facing command-line tool with about 30 commands (`browse snapshot`, `click @0-12`, `tab close`,
`viewport`, `network on`, `mouse drag`, `--cdp <url>`), and `browse skills add <domain>/<task>` that
pulls site know-how from the browse.sh catalog. That catalog is the nearest thing to Dejo's commons
(`dejo_manage do=share|borrow`), but a skill there is instructions for the agent, not a replayable,
checked trail.

## Puppeteer and Selenium WebDriver

Source: <https://pptr.dev/api>. 

### 2. Tables

These tables list only things that Playwright, Playwright MCP, Chrome DevTools MCP, browser-use and
Stagehand do **not** offer, or that Puppeteer or Selenium do in a different way that a user would care
about. Items already covered by those tools are in the "Checked and left out" list under each table.

Dejo column: **yes** = a step line or option does it today. **partly** = only some of it, or only with a
workaround. **no** = not possible today.

#### Puppeteer

| Capability (plain words) | API | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Wait until the network is quiet using your own rules: how long it must stay quiet, and how many requests may stay open (useful for sites that keep polling and are never fully quiet). Playwright has one fixed rule only. | `page.waitForNetworkIdle({idleTime, concurrency})` | partly | `wait idle` (fixed rule, no settings) | [pptr.dev](https://pptr.dev/api/puppeteer.page.waitfornetworkidle) |
| Read the size and edges of an element: content box, padding, border and margin (Playwright gives only the outer box). | `ElementHandle.boxModel()` | partly | `read box T as box` gives the outer box (X Y WIDTH HEIGHT). Missing: padding, border and margin, only by `js` | [pptr.dev](https://pptr.dev/api/puppeteer.elementhandle.boxmodel) |
| Page health numbers: number of DOM nodes, event listeners, layouts, JS heap size, script time. | `page.metrics()` | no | — (`read metrics` gives load times and bytes, not these) | [pptr.dev](https://pptr.dev/api/puppeteer.page.metrics) |
| Turn the browser cache off for one page, so every file is fetched fresh. (Chrome DevTools MCP only uses this inside its own performance trace.) | `page.setCacheEnabled(false)` | no | — | [pptr.dev](https://pptr.dev/api/puppeteer.page.setcacheenabled) |
| Turn JavaScript off and on again while the page is open (Playwright can only set it when the browser context is created). | `page.setJavaScriptEnabled(bool)` | no | — | [pptr.dev](https://pptr.dev/api/puppeteer.page.setjavascriptenabled) |
| Slow the network with your own numbers: download speed, upload speed, delay (Chrome DevTools MCP has only fixed presets like "Slow 3G"). | `page.emulateNetworkConditions({download, upload, latency, offline})` | partly | `emulate network slow3g\|fast3g\|slow4g\|fast4g\|offline`: presets only. Missing: your own speeds and delay | [pptr.dev](https://pptr.dev/api/puppeteer.page.emulatenetworkconditions) |
| Pretend the user is away or the screen is locked (for sites using the Idle Detection API, for example chat "away" status). | `page.emulateIdleState({isUserActive, isScreenUnlocked})` | no | — | [pptr.dev](https://pptr.dev/api/puppeteer.page.emulateidlestate) |
| See the page as a person with colour blindness or blurred sight sees it (accessibility check). | `page.emulateVisionDeficiency('deuteranopia' \| 'blurredVision' \| ...)` | no | — | [pptr.dev](https://pptr.dev/api/puppeteer.page.emulatevisiondeficiency) |
| Make the page believe its tab has focus even when it is in the background (some pages pause or hide things when not focused). | `page.emulateFocusedPage(true)` | no | — | [pptr.dev](https://pptr.dev/api/puppeteer.page.emulatefocusedpage) |
| Set a permission to "denied" or "ask", not only "allowed" (Playwright can only grant). Useful to test "camera blocked" or "location refused" paths. | `browserContext.setPermission(origin, {permission, state})` | no | — (`allow camera` can only grant; `allow off` takes every grant back) | [pptr.dev](https://pptr.dev/api/puppeteer.browsercontext.setpermission) |
| Move, resize, minimize, maximize or full-screen the real browser window. | `browser.setWindowBounds(windowId, {left, top, width, height, windowState})`, `browser.getWindowBounds` | no | — (`emulate viewport 1280x720` changes the page size, not the window) | [pptr.dev](https://pptr.dev/api/puppeteer.browser.setwindowbounds) |
| Add or remove fake extra screens (multi-monitor tests), headless only. | `browser.addScreen()`, `browser.screens()`, `browser.removeScreen()` | no | — | [pptr.dev](https://pptr.dev/api/puppeteer.browser.addscreen) |
| Touch gestures with a finger that goes down, moves and lifts: swipe, long press, pull to refresh (Playwright only has a single tap). | `ElementHandle.touchStart/touchMove/touchEnd`, `page.touchscreen.touchStart/touchMove` | no | — (`tap T` exists, but it needs touch mode, which MCP cannot turn on) | [pptr.dev](https://pptr.dev/api/puppeteer.touchscreen.touchstart) |
| Test the browser's own autofill on a credit card or address form. | `ElementHandle.autofill({creditCard} \| {address})` | no | — | [pptr.dev](https://pptr.dev/api/puppeteer.elementhandle.autofill) |
| Fake a Bluetooth adapter and Bluetooth devices, for Web Bluetooth pages. | `page.bluetooth.emulateAdapter()`, `simulatePreconnectedPeripheral()` | no | — | [pptr.dev](https://pptr.dev/api/puppeteer.bluetoothemulation) |
| Answer the browser's own "choose a device" box (Bluetooth) and pick a device. | `page.waitForDevicePrompt()`, `DeviceRequestPrompt.select()` | no | — | [pptr.dev](https://pptr.dev/api/puppeteer.page.waitfordeviceprompt) |
| Drive the normal, released Firefox (not a patched build like Playwright's) through WebDriver BiDi. | `puppeteer.launch({browser: 'firefox'})` | no | — (Chromium only) | [pptr.dev](https://pptr.dev/webdriver-bidi) |

**Checked and left out (another tool already has it):** `page.coverage` (Playwright `page.coverage`);
`page.accessibility.snapshot` and `ElementHandle.queryAXTree` (Playwright `ariaSnapshot` and
`ariaSnapshotJSON`, `getByRole`; Dejo has `look raw` and `role "name"`); `page.setBypassCSP` (Playwright
`bypassCSP`); `page.emulateCPUThrottling` (Chrome DevTools MCP `emulate cpuThrottlingRate`);
`page.screencast` / `page.record` (Playwright video and screencast, Chrome DevTools MCP
`screencast_start`); `page.tracing` (Chrome DevTools MCP performance trace, Playwright tracing);
`page.setRequestInterception` (Playwright `route`); `browser.waitForTarget` (Playwright `waitForPage`,
`waitForPopup`, `waitForWorker`); `page.queryObjects` and `captureHeapSnapshot` (Chrome DevTools MCP heap
snapshot tools); `HTTPRequest` details such as `initiator`, `redirectChain`, `timing` (Playwright
`Request`/`Response`, Chrome DevTools MCP `get_network_request`); `::-p-xpath`, `::-p-text`, `::-p-aria`,
`>>>` (Playwright `xpath=`, `getByText`, `getByRole`, shadow-piercing CSS; `Page.$x` no longer exists in
Puppeteer); `page.setOfflineMode` (Playwright `setOffline`); `page.authenticate` (Playwright
`httpCredentials`); `page.setExtraHTTPHeaders` (Playwright, Chrome DevTools MCP); `createBrowserContext`
with proxy (Playwright `newContext({proxy})`); `page.createPDFStream` / `pdf` (Playwright `page.pdf`);
`setBypassServiceWorker` (Playwright `serviceWorkers: 'block'`); extensions, PWA, WebMCP
(Chrome DevTools MCP, Playwright `webmcp`); `Browser.restrictNetwork` (Playwright MCP blocked/allowed
origins).

#### Selenium WebDriver (Python)

| Capability (plain words) | API | Dejo | How in Dejo | Source |
|---|---|---|---|---|
| Find an element by where it sits next to another one: above, below, left of, right of, near, or straight in line. | `locate_with(By.TAG_NAME, "input").below(...)`, `.near(el, distance)`, `.straight_above(...)` | partly | `click css "input:below(label:text('Email'))"`: Playwright layout CSS, which Playwright marks as deprecated; no "straight" forms. Checked: the step parses and the selector works in Chromium. | [selenium.dev](https://www.selenium.dev/documentation/webdriver/elements/locators/), [relative_locator.py](https://github.com/SeleniumHQ/selenium/blob/trunk/py/selenium/webdriver/support/relative_locator.py) |
| Get files that were downloaded on a remote Grid machine back to your own machine. | `get_downloadable_files()`, `download_file(name, dir)`, `delete_downloadable_files()` | partly | Downloads are saved to `~/.dejo/downloads` and listed by `read downloads`; no Selenium Grid, so no remote fetch | [webdriver.py](https://github.com/SeleniumHQ/selenium/blob/trunk/py/selenium/webdriver/remote/webdriver.py) |
| Drive the real browsers each company ships: real Safari (Playwright's WebKit is not Safari), Edge, normal Firefox, Chrome. | `webdriver.Safari()`, `webdriver.Edge()`, `webdriver.Firefox()`, `webdriver.Chrome()` | no | — (Chromium only: real Chrome when installed, or an Edge you started, through `DEJO_CDP_URL=...`) | [selenium.dev](https://www.selenium.dev/documentation/webdriver/browsers/safari/), [safari/webdriver.py](https://github.com/SeleniumHQ/selenium/blob/trunk/py/selenium/webdriver/safari/webdriver.py) |
| Run old Internet Explorer-only pages inside Edge's IE mode (old company and government sites). | `webdriver.Ie(options)` with `options.attach_to_edge_chrome = True` | no | — | [selenium.dev](https://www.selenium.dev/documentation/webdriver/browsers/internet_explorer/), [ie/options.py](https://github.com/SeleniumHQ/selenium/blob/trunk/py/selenium/webdriver/ie/options.py) |
| Run the browser on another machine or on a Selenium Grid (many machines, many browser and OS mixes, cloud test vendors). | `webdriver.Remote(command_executor=URL, options=...)` | partly | `DEJO_CDP_URL=http://other-machine:9222` drives a Chrome on another machine or a cloud browser. Missing: Selenium Grid, other browsers and systems | [selenium.dev](https://www.selenium.dev/documentation/webdriver/drivers/remote_webdriver/), [Grid](https://www.selenium.dev/documentation/grid/) |
| Pen (stylus) input with pressure, tilt and twist, for drawing and signature pads. | `ActionChains(driver, devices=[PointerInput(POINTER_PEN, "pen")])`, `pointer_down(pressure=, tilt_x=, tilt_y=, twist=)` | no | — | [selenium.dev](https://www.selenium.dev/documentation/webdriver/actions_api/pen/), [pointer_actions.py](https://github.com/SeleniumHQ/selenium/blob/trunk/py/selenium/webdriver/common/actions/pointer_actions.py) |
| Several fingers at once (pinch to zoom, two-finger swipe), each finger moved on its own. | `ActionBuilder.add_pointer_input("touch", name)` (one per finger), then `perform()` | no | — | [action_builder.py](https://github.com/SeleniumHQ/selenium/blob/trunk/py/selenium/webdriver/common/actions/action_builder.py) |
| Minimize, maximize, full-screen, or move the browser window to a screen position. | `minimize_window()`, `maximize_window()`, `fullscreen_window()`, `set_window_rect(x, y, w, h)`, `set_window_position()` | no | — (only the page size: `emulate viewport 1280x720`) | [selenium.dev](https://www.selenium.dev/documentation/webdriver/interactions/windows/) |
| Set a permission to "denied" or "prompt", not only "granted". | Chrome: `driver.set_permissions("clipboard-read", "denied")`; BiDi: `driver.permissions.set_permission(...)` | no | — (`allow ...` can only grant; `allow off` takes every grant back) | [chromium/webdriver.py](https://github.com/SeleniumHQ/selenium/blob/trunk/py/selenium/webdriver/chromium/webdriver.py) |
| Handle the browser's "Sign in with ..." account chooser (FedCM): read the accounts, pick one, accept or close it. | `driver.fedcm.account_list`, `driver.fedcm.select_account(0)`, `driver.fedcm.accept()`, `driver.fedcm.dismiss()`, `driver.fedcm_dialog()` | no | — (a person can click it by hand in the `dejo_login` window, but no step can) | [fedcm.py](https://github.com/SeleniumHQ/selenium/blob/trunk/py/selenium/webdriver/remote/fedcm.py), [dialog.py](https://github.com/SeleniumHQ/selenium/blob/trunk/py/selenium/webdriver/common/fedcm/dialog.py) |
| Cast a tab or the desktop to a Chromecast-type receiver, and stop it. | `get_sinks()`, `set_sink_to_use()`, `start_tab_mirroring()`, `start_desktop_mirroring()`, `stop_casting()` | no | — | [chromium/webdriver.py](https://github.com/SeleniumHQ/selenium/blob/trunk/py/selenium/webdriver/chromium/webdriver.py) |

**Checked and left out (another tool already has it):** the common `ActionChains` moves
(`move_by_offset`, `click_and_hold`, `context_click`, `key_down`/`key_up`, `pause`) and
`scroll_by_amount` / `scroll_from_origin` (Playwright `mouse` and `keyboard`: move, down, up, wheel;
Chrome DevTools MCP `click_at`). Dejo itself still has no right-click, no mouse by coordinates and no
scroll of one element by an amount. Also left out: `switch_to.frame/alert/window` (Playwright frames,
pages, `dialog.accept(promptText)` / `dismiss`); `print_page` (Playwright `page.pdf`);
`get_screenshot_as_*` and Firefox `get_full_page_screenshot` (Playwright `fullPage`); cookies (Playwright);
virtual authenticator / WebAuthn (Playwright `context.credentials` since v1.61, Chrome DevTools MCP
`configure_webauthn`); BiDi log and network events, request handlers, auth handlers, extra headers
(Playwright); `execute_async_script` (Playwright `evaluate` waits for promises); `Select`
(Playwright `selectOption`); `implicitly_wait`, `set_page_load_timeout` (Playwright auto-wait and
timeouts); `execute_cdp_cmd` (Playwright `newCDPSession`); Chrome `set_network_conditions` (Chrome
DevTools MCP `emulate`); `get_log` (Playwright console messages); BiDi emulation of geolocation,
timezone, locale, user agent, screen orientation, scripting (Playwright context options, Chrome DevTools
MCP `emulate`); BiDi `locate_nodes` (Playwright `getByText` / `getByRole`); `driver.request`
(Playwright `APIRequestContext`).
