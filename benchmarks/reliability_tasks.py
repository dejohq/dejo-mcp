"""The reliability benchmark's tasks: fixed Dejo programs on real public websites.

Every program was written by hand after looking at the page, the way a person writes a
Playwright script: name the element by its role and the words on it, as the page shows them.
Nothing here is generated while the benchmark runs, and nothing sends a form, signs up,
posts, buys or logs in. A search box is typed into; a filter, a tab or a link is clicked.

R01-R25 are the 25 tasks of `real_tasks.py` (T01-T25), with the same checked answers.
R26-R50 cover what those miss: iframes, shadow DOM, custom dropdowns, date pickers, hover
menus, infinite scroll, a second tab, a search box with suggestions, tables and long pages.
R51-R61 cover what other browser tools can do that Dejo learned to: dialogs, right clicks,
whole tables and many fields as JSON, closing a tab, a page's own API answers, another
language or a phone, cookies and PDFs. They run on test services and practice sites.
Where a site exists to practise test automation, it is used, because nobody minds being
automated there and its pages stay the same for years.

An accepted answer that starts with `re:` is a regular expression, for answers that move
with the calendar (a date picked "next month").
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    id: str
    site: str
    covers: str
    """What the task exercises, in a few words."""
    steps: str
    """A program in the `dejo_run` step language. It starts with `go` and ends with a read."""
    answers: tuple[str, ...]


def _steps(*lines: str) -> str:
    return "\n".join(lines) + "\n"


TASKS: list[Task] = [
    # ------------------------------------------------------------------ from real_tasks.py
    Task(
        "R01",
        "scrapethissite.com",
        "search box, table row",
        _steps(
            "go https://www.scrapethissite.com/pages/",
            'click link "Hockey Teams: Forms, Searching and Pagination"',
            'fill textbox "Search for Teams:" "Mighty Ducks"',
            'click button "Search"',
            "read css \"tr.team:has(td.year:text-is('1997')) td.ga\" as answer",
        ),
        ("261",),
    ),
    Task(
        "R02",
        "scrapethissite.com",
        "pagination link",
        _steps(
            "go https://www.scrapethissite.com/pages/forms/",
            'click link "5" first',
            'read css "tr.team td.name" first as answer',
        ),
        ("Edmonton Oilers",),
    ),
    Task(
        "R03",
        "packages.debian.org",
        "two forms with the same labels, native select",
        _steps(
            "go https://www.debian.org/distrib/packages",
            'fill textbox "Keyword:" first "moon-buggy"',
            'select combobox "Distribution:" first "oldstable"',
            'click button "Search" nth 2',
            'click link "bookworm (oldstable)"',
            'read heading "Package: moon-buggy" as answer',
        ),
        ("1:1.0.51-13", "1.0.51-13"),
    ),
    Task(
        "R04",
        "packages.debian.org",
        "native select, table row",
        _steps(
            "go https://www.debian.org/distrib/packages",
            'fill textbox "Keyword:" first "pacman4console"',
            'click button "Search" nth 2',
            'click link "trixie (stable)"',
            'read row has "armhf" as answer',
        ),
        ("74.0 kB", "74.0 kb", "74.0", "74 kB"),
    ),
    Task(
        "R05",
        "rfc-editor.org",
        "search box, result list",
        _steps(
            "go https://www.rfc-editor.org/",
            'fill searchbox "Find an RFC" "Computing-Aware Traffic Steering"',
            'click button "Submit search"',
            'read link "RFC" has "10053" as answer',
        ),
        ("RFC 10053", "10053", "RFC10053"),
    ),
    Task(
        "R06",
        "rfc-editor.org",
        "checkbox filters",
        _steps(
            "go https://www.rfc-editor.org/search/",
            'fill searchbox "Search RFCs" "DNSSEC Delegation Signer"',
            'click button "Submit search"',
            'check checkbox "Best Current Practice"',
            'read heading "Delegation Signer (DS) Automation" as answer',
        ),
        ("BCP 246", "246", "BCP246"),
    ),
    Task(
        "R07",
        "talbothistory.pastperfectonline.com",
        "search box, record page",
        _steps(
            "go https://talbothistory.pastperfectonline.com/",
            'click link "Keyword Search"',
            'fill textbox "What are you looking for?" "1979.003.000018"',
            'click button "Search"',
            'click link "1979.003.000018 - decoy"',
            "read css \"tr:has(h3:text-is('Date'))\" as answer",
        ),
        ("1880-1890", "1880–1890", "1880 to 1890"),
    ),
    Task(
        "R08",
        "talbothistory.pastperfectonline.com",
        "search, open one result among many",
        _steps(
            "go https://talbothistory.pastperfectonline.com/",
            'click link "Keyword Search"',
            'fill textbox "What are you looking for?" "\\"Emma Giles\\""',
            'click button "Search"',
            'click link "Magazine"',
            "read css \"tr:has(h3:text-is('Description'))\" as answer",
        ),
        ("Del-Mar-Va Heartland", "Del-Mar-Va Heartland magazine"),
    ),
    Task(
        "R09",
        "catalog.ccv.edu",
        "catalog filter",
        _steps(
            "go https://catalog.ccv.edu/",
            'click link "Course Descriptions"',
            'select combobox "Prefix" "MEC"',
            'click button "Filter"',
            'click link "MEC 2350 - Green Production"',
            'read text "Credits" as answer',
        ),
        ("1", "1 credit", "Credits: 1"),
    ),
    Task(
        "R10",
        "catalog.ccv.edu",
        "catalog pagination",
        _steps(
            "go https://catalog.ccv.edu/",
            'click link "Course Descriptions"',
            'click link "3" first',
            'read css "td.width a" last as answer',
        ),
        ("MAT 1230 - College Algebra", "MAT 1230", "College Algebra"),
    ),
    Task(
        "R11",
        "doververmont.com",
        "drop-down site menu",
        _steps(
            "go https://www.doververmont.com/",
            'click button "Town Services Departments & Resources"',
            'click link "Highway and Transfer Station"',
            'read text "Road Foreman" first as answer',
        ),
        ("Brian Moore",),
    ),
    Task(
        "R12",
        "doververmont.com",
        "long link name in a news carousel",
        _steps(
            "go https://www.doververmont.com/",
            'click link "2026 Transfer Station Rates & Fees" first',
            'read text "Mattress" first as answer',
        ),
        ("$55 each", "$55", "$55.00"),
    ),
    Task(
        "R13",
        "ctan.org",
        "search box with no label",
        _steps(
            "go https://ctan.org/",
            'fill css "input[name=phrase]" "knittingpattern"',
            "press Enter",
            'click link "Package knittingpattern"',
            'read row has "Version" as answer',
        ),
        ("2009-11-13",),
    ),
    Task(
        "R14",
        "practicesoftwaretesting.com",
        "checkbox filter in an Angular shop",
        _steps(
            "go https://practicesoftwaretesting.com/",
            'check checkbox "Sander"',
            'wait link "Belt Sander"',
            'read link "Belt Sander" as answer',
        ),
        ("$73.59", "73.59"),
    ),
    Task(
        "R15",
        "practicesoftwaretesting.com",
        "search, product page",
        _steps(
            "go https://practicesoftwaretesting.com/",
            'fill textbox "Search" "Swiss Woodcarving Chisels"',
            'click button "Search"',
            'click link "Swiss Woodcarving Chisels"',
            'read row has "Weight" as answer',
        ),
        ("550g", "550 g"),
    ),
    Task(
        "R16",
        "demowebshop.tricentis.com",
        "category, price filter",
        _steps(
            "go https://demowebshop.tricentis.com/",
            'click link "Books" first',
            'click link "Over 50.00"',
            'read css ".product-title a" as answer',
        ),
        ("Science",),
    ),
    Task(
        "R17",
        "demowebshop.tricentis.com",
        "category, second page",
        _steps(
            "go https://demowebshop.tricentis.com/",
            'click link "Apparel & Shoes" first',
            'click link "Next"',
            "read css \".product-item:has-text('Wool Hat') .actual-price\" as answer",
        ),
        ("30.00", "$30.00"),
    ),
    Task(
        "R18",
        "collection.internationalfolkart.org",
        "museum search, object page",
        _steps(
            "go http://collection.internationalfolkart.org/",
            'fill textbox "Keyword Search" last "Arjuna Sasrabahu"',
            "press Enter",
            'click link "Arjuna Sasrabahu" first',
            'read css ".invnoField" as answer',
        ),
        ("FA.2007.40.25",),
    ),
    Task(
        "R19",
        "collection.internationalfolkart.org",
        "collection, facet filter",
        _steps(
            "go http://collection.internationalfolkart.org/",
            'click link "100 Aspects of the Moon" last',
            'click link "View All Works" first',
            'click text "Classification(s)"',
            'click link "Prints"',
            'read css ".title" first as answer',
        ),
        ("One Hundred Aspects of the Moon: Moon of the Lonely House", "Moon of the Lonely House"),
    ),
    Task(
        "R20",
        "gutenberg.org",
        "search box, book page table",
        _steps(
            "go https://www.gutenberg.org/",
            'fill textbox "Search books" "Realmah"',
            'click button "Go!"',
            'click link "Realmah"',
            'read row has "Release Date" as answer',
        ),
        ("Oct 20, 2026", "20 Oct 2026", "October 20, 2026", "20 October 2026", "2026-10-20"),
    ),
    Task(
        "R21",
        "pub.dev",
        "search, package tabs",
        _steps(
            "go https://pub.dev/",
            'fill searchbox "Search" "mustache_recase"',
            "press Enter",
            'click link "mustache_recase" first',
            'click button "Changelog"',
            "read css \"h2:text-is('2.0.1') + *\" as answer",
        ),
        ("Removed Generator+ dep",),
    ),
    Task(
        "R22",
        "pub.dev",
        "search, versions table",
        _steps(
            "go https://pub.dev/",
            'fill searchbox "Search" "mustache_recase"',
            "press Enter",
            'click link "mustache_recase" first',
            'click button "Versions"',
            "read css \"tr[data-version='2.0.3'] td.sdk\" as answer",
        ),
        ("2.0",),
    ),
    Task(
        "R23",
        "tcatbus.com",
        "site menu, long page",
        _steps(
            "go https://tcatbus.com/",
            'click link "Rider Resources"',
            'click link "Park & Ride Lots" first',
            'read paragraph has "Danby" as answer',
        ),
        ("Dotson Park",),
    ),
    Task(
        "R24",
        "tcatbus.com",
        "site menu, fares table",
        _steps(
            "go https://tcatbus.com/",
            'click link "Fares"',
            'read row has "Weekly" as answer',
        ),
        ("$17.50", "17.50"),
    ),
    Task(
        "R25",
        "hackage.haskell.org",
        "category list, package page",
        _steps(
            "go https://hackage.haskell.org/",
            'click link "Packages by category"',
            'click link "Chess Engine"',
            "click css \"h3:has(a[name='cat:Chess Engine']) + ul a\" first",
            'read row has "Author" as answer',
        ),
        ("Alberto Perez",),
    ),
    # ------------------------------------------------------------------ what those miss
    Task(
        "R26",
        "the-internet.herokuapp.com",
        "iframe: text in a rich text editor",
        _steps(
            "go https://the-internet.herokuapp.com/iframe",
            'read css "#tinymce p" as answer',
        ),
        ("Your content goes here.",),
    ),
    Task(
        "R27",
        "the-internet.herokuapp.com",
        "iframe: frames inside frames",
        _steps(
            "go https://the-internet.herokuapp.com/nested_frames",
            'read css "#content" as answer',
        ),
        ("MIDDLE",),
    ),
    Task(
        "R28",
        "jqueryui.com",
        "iframe: tabs widget",
        _steps(
            "go https://jqueryui.com/tabs/",
            'click tab "Proin dolor"',
            'read tabpanel "Proin dolor" as answer',
        ),
        ("Morbi tincidunt",),
    ),
    Task(
        "R29",
        "shop.polymer-project.org",
        "shadow DOM: a web-component shop",
        _steps(
            "go https://shop.polymer-project.org/",
            'click link "Men\'s Outerwear" first',
            'click link "Men\'s Tech Shell Full-Zip"',
            'read css ".price" first as answer',
        ),
        ("$50.20",),
    ),
    Task(
        "R30",
        "mdn.github.io",
        "shadow DOM: text inside a custom element",
        _steps(
            "go https://mdn.github.io/web-components-examples/popup-info-box-web-component/",
            'read css "popup-info .info" as answer',
        ),
        ("last 3 or 4 numbers on the back of your card",),
    ),
    Task(
        "R31",
        "jqueryui.com",
        "custom dropdown inside an iframe",
        _steps(
            "go https://jqueryui.com/selectmenu/",
            'click css "#speed-button"',
            'click option "Fast" first',
            'read css "#speed-button" as answer',
        ),
        ("Fast",),
    ),
    Task(
        "R32",
        "demoqa.com",
        "custom dropdown: react-select",
        _steps(
            "go https://demoqa.com/select-menu",
            'click css "#selectOne"',
            'click text "Prof."',
            'read css "#selectOne" as answer',
        ),
        ("Prof.",),
    ),
    Task(
        "R33",
        "jqueryui.com",
        "date picker inside an iframe",
        _steps(
            "go https://jqueryui.com/datepicker/",
            'click css "#datepicker"',
            'click title "Next"',
            'click link "15"',
            'read value css "#datepicker" as answer',
        ),
        (r"re:^\d\d/15/\d{4}$",),
    ),
    Task(
        "R34",
        "demoqa.com",
        "date picker: react-datepicker",
        _steps(
            "go https://demoqa.com/date-picker",
            'click css "#datePickerMonthYearInput"',
            'select css ".react-datepicker__month-select" "May"',
            'select css ".react-datepicker__year-select" "2020"',
            'click css ".react-datepicker__day--015:not(.react-datepicker__day--outside-month)"',
            'read value css "#datePickerMonthYearInput" as answer',
        ),
        ("05/15/2020",),
    ),
    Task(
        "R35",
        "the-internet.herokuapp.com",
        "hover: caption shown on hover",
        _steps(
            "go https://the-internet.herokuapp.com/hovers",
            'hover css ".figure" nth 2',
            'read css ".figure h5" nth 2 as answer',
        ),
        ("name: user2",),
    ),
    Task(
        "R36",
        "the-internet.herokuapp.com",
        "hover menu: a link under a menu that opens on hover",
        _steps(
            "go https://the-internet.herokuapp.com/jqueryui/menu",
            'hover link "Enabled"',
            'click link "Back to JQuery UI"',
            'read heading "JQuery UI" as answer',
        ),
        ("JQuery UI",),
    ),
    Task(
        "R37",
        "webdriveruniversity.com",
        "hover menu: buttons that open a list",
        _steps(
            "go https://webdriveruniversity.com/Actions/index.html",
            'hover button "Hover Over Me Second!"',
            'read link "Link 1" as answer',
        ),
        ("Link 1",),
    ),
    Task(
        "R38",
        "quotes.toscrape.com",
        "infinite scroll",
        _steps(
            "go https://quotes.toscrape.com/scroll",
            "scroll bottom",
            'wait css ".quote:nth-of-type(11)"',
            'read css ".quote .author" nth 11 as answer',
        ),
        ("Marilyn Monroe",),
    ),
    Task(
        "R39",
        "the-internet.herokuapp.com",
        "a second tab",
        _steps(
            "go https://the-internet.herokuapp.com/windows",
            'click link "Click Here"',
            "tab latest",
            'read heading "New Window" as answer',
        ),
        ("New Window",),
    ),
    Task(
        "R40",
        "webdriveruniversity.com",
        "a second tab from a long link",
        _steps(
            "go https://webdriveruniversity.com/",
            'click link "DATA TABLE"',
            "tab latest",
            'read row has "Jemma" as answer',
        ),
        ("94",),
    ),
    Task(
        "R41",
        "en.wikipedia.org",
        "search box with suggestions",
        _steps(
            "go https://en.wikipedia.org/wiki/Main_Page",
            'type searchbox "Search Wikipedia" "Ada Lovel"',
            'click option "Ada Lovelace" first',
            'read heading "Ada Lovelace" first as answer',
        ),
        ("Ada Lovelace",),
    ),
    Task(
        "R42",
        "jqueryui.com",
        "search suggestions inside an iframe",
        _steps(
            "go https://jqueryui.com/autocomplete/",
            'type textbox "Tags:" "Jav"',
            'click text "JavaScript"',
            'read value textbox "Tags:" as answer',
        ),
        ("JavaScript",),
    ),
    Task(
        "R43",
        "webdriveruniversity.com",
        "suggestions list",
        _steps(
            "go https://webdriveruniversity.com/Autocomplete-TextField/autocomplete-textfield.html",
            'type textbox "Food Item" "Chi"',
            'click text "Chips"',
            'read value textbox "Food Item" as answer',
        ),
        ("Chips",),
    ),
    Task(
        "R44",
        "the-internet.herokuapp.com",
        "table: sort by a column header",
        _steps(
            "go https://the-internet.herokuapp.com/tables",
            'click columnheader "Due" first',
            'click columnheader "Due" first',
            'read css "#table1 tbody tr td" first as answer',
        ),
        ("Doe",),
    ),
    Task(
        "R45",
        "webscraper.io",
        "table: one cell by its row",
        _steps(
            "go https://webscraper.io/test-sites/tables",
            'read row has "Larry" as answer',
        ),
        ("@twitter",),
    ),
    Task(
        "R46",
        "en.wikipedia.org",
        "long page: an infobox row",
        _steps(
            "go https://en.wikipedia.org/wiki/Python_(programming_language)",
            'read row has "Designed by" as answer',
        ),
        ("Guido van Rossum",),
    ),
    Task(
        "R47",
        "www.rfc-editor.org",
        "long text page: a section deep down",
        _steps(
            "go https://www.rfc-editor.org/rfc/rfc9110.html",
            'click link "418 (Unused)" first',
            'read heading "418 (Unused)" as answer',
        ),
        ("418 (Unused)",),
    ),
    Task(
        "R48",
        "the-internet.herokuapp.com",
        "content that appears after a click",
        _steps(
            "go https://the-internet.herokuapp.com/dynamic_loading/2",
            'click button "Start"',
            'wait heading "Hello World!"',
            'read css "#finish" as answer',
        ),
        ("Hello World!",),
    ),
    Task(
        "R49",
        "books.toscrape.com",
        "category link with spaces around its name",
        _steps(
            "go https://books.toscrape.com/",
            'click link "Travel"',
            'read css "article.product_pod p.price_color" first as answer',
        ),
        ("£45.17",),
    ),
    Task(
        "R50",
        "quotes.toscrape.com",
        "a page drawn by JavaScript, then the next page",
        _steps(
            "go https://quotes.toscrape.com/js/",
            'click link "Next"',
            'read css ".quote .author" first as answer',
        ),
        ("Marilyn Monroe",),
    ),
    # ------------------------------------------------- what other browser tools can do too
    Task(
        "R51",
        "the-internet.herokuapp.com",
        "cancel a prompt box",
        _steps(
            "go https://the-internet.herokuapp.com/javascript_alerts",
            "dialog dismiss",
            'click button "Click for JS Prompt"',
            'read css "#result" as answer',
        ),
        ("You entered: null",),
    ),
    Task(
        "R52",
        "the-internet.herokuapp.com",
        "type an answer into a prompt box",
        _steps(
            "go https://the-internet.herokuapp.com/javascript_alerts",
            'dialog accept "Dejo"',
            'click button "Click for JS Prompt"',
            'read css "#result" as answer',
        ),
        ("You entered: Dejo",),
    ),
    Task(
        "R53",
        "the-internet.herokuapp.com",
        "right click, and read the alert it opens",
        _steps(
            "go https://the-internet.herokuapp.com/context_menu",
            'click css "#hot-spot" button=right',
            "read dialog as answer",
        ),
        ("You selected a context menu",),
    ),
    Task(
        "R54",
        "the-internet.herokuapp.com",
        "a whole table as JSON",
        _steps(
            "go https://the-internet.herokuapp.com/tables",
            'read table css "#table1" as answer',
        ),
        ('re:"Last Name": "Smith".*"Email": "jsmith@gmail.com"',),
    ),
    Task(
        "R55",
        "the-internet.herokuapp.com",
        "a new window, then closing it",
        _steps(
            "go https://the-internet.herokuapp.com/windows",
            'click link "Click Here"',
            "tab latest",
            'read css "h3" as opened',
            "tab close",
            'read css "h3" as answer',
        ),
        ("Opening a new window",),
    ),
    Task(
        "R56",
        "books.toscrape.com",
        "many fields of every card at once",
        _steps(
            "go https://books.toscrape.com/",
            'read fields \'{"title": "h3 a@title", "price": ".price_color"}\' '
            'css "article.product_pod" as answer',
        ),
        ('re:"title": "A Light in the Attic", "price": "£51.77"',),
    ),
    Task(
        "R57",
        "quotes.toscrape.com",
        "the JSON a page draws itself from",
        _steps(
            "go https://quotes.toscrape.com/scroll",
            "wait response:/api/quotes",
            'read response "/api/quotes" as answer',
        ),
        ('re:"has_next": ?true',),
    ),
    Task(
        "R58",
        "httpbin.org",
        "another language, as the site is told it",
        _steps(
            "go https://httpbin.org/",
            "emulate locale de-DE",
            "go https://httpbin.org/headers",
            'read css "pre" as answer',
        ),
        ('re:"Accept-Language": "de-DE',),
    ),
    Task(
        "R59",
        "httpbin.org",
        "a phone, as the site is told it",
        _steps(
            "go https://httpbin.org/",
            'emulate device "iPhone 13"',
            "go https://httpbin.org/user-agent",
            'read css "pre" as answer',
        ),
        ("re:iPhone",),
    ),
    Task(
        "R60",
        "httpbin.org",
        "a cookie the site set",
        _steps(
            "go https://httpbin.org/cookies/set?flavour=ginger",
            'read cookies "flavour" as answer',
        ),
        ("flavour=ginger (httpbin.org)",),
    ),
    Task(
        "R61",
        "example.com",
        "the page as a PDF",
        _steps(
            "go https://example.com/",
            "read pdf as answer",
        ),
        (r"re:\.pdf$",),
    ),
]
