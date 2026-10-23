"""The real-world bench, v1: 25 tasks on 14 lesser-known public sites.

Every answer was read off the live page in a real browser on 21 Oct 2026, BEFORE any tool was
run on it, and each final page was opened a second time to confirm it. The walk to each
answer, why a model cannot know it, and why it should not move are written down beside each
task in the private research notes (dejo-plans/research/real-bench/TASKS.md).

The famous sites of the 20 Oct bench (GitHub, toscrape) were the wrong test: a model knows
their layout, and sometimes their answers. These are sites it has to actually walk.

Tasks most likely to drift, to be re-checked before a run weeks later: T11 (a staff name),
T19 (one record's classification), T25 (a category that holds one package), T14/T15 (demo
seed data), T03 (Debian's "oldstable" moves at the next major release).
"""

from __future__ import annotations

# (id, domain, start url, what is asked, accepted answers)
REAL = [
    (
        "T01",
        "scrapethissite.com",
        "https://www.scrapethissite.com/pages/",
        "find the hockey team stats for the Mighty Ducks of Anaheim and tell me how many goals "
        "against they had in the 1997 season",
        ("261",),
    ),
    (
        "T02",
        "scrapethissite.com",
        "https://www.scrapethissite.com/pages/forms/",
        "go to page 5 of the hockey team table and tell me the name of the first team listed "
        "on that page",
        ("Edmonton Oilers",),
    ),
    (
        "T03",
        "packages.debian.org",
        "https://www.debian.org/distrib/packages",
        "search the Debian package directory for the package named moon-buggy in the oldstable "
        "distribution and tell me its version number",
        ("1:1.0.51-13", "1.0.51-13"),
    ),
    (
        "T04",
        "packages.debian.org",
        "https://www.debian.org/distrib/packages",
        "look up the Debian package pacman4console in the stable release (trixie) and tell me "
        "its installed size on the armhf architecture",
        ("74.0 kB", "74.0 kb", "74.0", "74 kB"),
    ),
    (
        "T05",
        "rfc-editor.org",
        "https://www.rfc-editor.org/",
        "search the RFC Editor for the framework document for Computing-Aware Traffic Steering "
        "(CATS) and tell me its RFC number",
        ("RFC 10053", "10053", "RFC10053"),
    ),
    (
        "T06",
        "rfc-editor.org",
        "https://www.rfc-editor.org/",
        "list only the Best Current Practice RFCs published in July 2026 and tell me the BCP "
        "number of the one about DNSSEC Delegation Signer (DS) automation",
        ("BCP 246", "246", "BCP246"),
    ),
    (
        "T07",
        "talbothistory.pastperfectonline.com",
        "https://talbothistory.pastperfectonline.com/",
        "search the online collection for the decoy with catalog number 1979.003.000018 and "
        "tell me the date given for it",
        ("1880-1890", "1880–1890", "1880 to 1890"),
    ),
    (
        "T08",
        "talbothistory.pastperfectonline.com",
        "https://talbothistory.pastperfectonline.com/",
        'search the collection for records about the steamboat "Emma Giles", open the magazine '
        "record among the results and tell me the name of the magazine",
        ("Del-Mar-Va Heartland", "Del-Mar-Va Heartland magazine"),
    ),
    (
        "T09",
        "catalog.ccv.edu",
        "https://catalog.ccv.edu/",
        "in the 2026-2027 course list, show only the MEC courses, open MEC 2350 Green "
        "Production and tell me how many credits it is worth",
        ("1", "1 credit", "Credits: 1"),
    ),
    (
        "T10",
        "catalog.ccv.edu",
        "https://catalog.ccv.edu/",
        "open the full course list in the 2026-2027 catalog, go to page 3 and tell me the last "
        "course listed on that page",
        ("MAT 1230 - College Algebra", "MAT 1230", "College Algebra", "MAT 1230 College Algebra"),
    ),
    (
        "T11",
        "doververmont.com",
        "https://www.doververmont.com/",
        "find out who the Road Foreman is in the Town of Dover's highway department",
        ("Brian Moore",),
    ),
    (
        "T12",
        "doververmont.com",
        "https://www.doververmont.com/",
        "find out how much the Dover transfer station charges to drop off a mattress or box spring",
        ("$55 each", "$55", "55", "$55.00"),
    ),
    (
        "T13",
        "ctan.org",
        "https://ctan.org/",
        "search CTAN for the LaTeX class for writing knitting patterns (the package is called "
        "knittingpattern) and tell me its version",
        ("2009-11-13",),
    ),
    (
        "T14",
        "practicesoftwaretesting.com",
        "https://practicesoftwaretesting.com/",
        "filter the shop to the Sander category and tell me the price of the Belt Sander",
        ("$73.59", "73.59"),
    ),
    (
        "T15",
        "practicesoftwaretesting.com",
        "https://practicesoftwaretesting.com/",
        "search the shop for the Swiss Woodcarving Chisels and tell me their weight from the "
        "product specifications",
        ("550g", "550 g"),
    ),
    (
        "T16",
        "demowebshop.tricentis.com",
        "https://demowebshop.tricentis.com/",
        "open the Books section, filter to books priced over 50.00 and tell me the name of the "
        "book that is left",
        ("Science",),
    ),
    (
        "T17",
        "demowebshop.tricentis.com",
        "https://demowebshop.tricentis.com/",
        "open Apparel & Shoes, go to the second page of products and tell me the price of the "
        "Wool Hat listed there",
        ("30.00", "$30.00", "30"),
    ),
    (
        "T18",
        "collection.internationalfolkart.org",
        "http://collection.internationalfolkart.org/",
        'search the museum\'s online collection for the shadow puppet "Arjuna Sasrabahu" and '
        "tell me its object number",
        ("FA.2007.40.25",),
    ),
    (
        "T19",
        "collection.internationalfolkart.org",
        "http://collection.internationalfolkart.org/",
        'open the "100 Aspects of the Moon" collection, view all its works, narrow the results '
        'to the classification "Prints" and tell me the title of the work that remains',
        ("One Hundred Aspects of the Moon: Moon of the Lonely House", "Moon of the Lonely House"),
    ),
    (
        "T20",
        "gutenberg.org",
        "https://www.gutenberg.org/",
        'search Project Gutenberg for the book "Realmah" by Arthur Helps and tell me its '
        "release date on the site",
        ("Oct 20, 2026", "20 Oct 2026", "October 20, 2026", "20 October 2026", "2026-10-20"),
    ),
    (
        "T21",
        "pub.dev",
        "https://pub.dev/",
        "find the Dart package mustache_recase, open its Changelog tab and tell me what changed "
        "in version 2.0.1",
        ("Removed Generator+ dep", "Removed Generator+ dep."),
    ),
    (
        "T22",
        "pub.dev",
        "https://pub.dev/",
        "find the Dart package mustache_recase, open its Versions tab and tell me the minimum "
        "Dart SDK listed for version 2.0.3",
        ("2.0",),
    ),
    (
        "T23",
        "tcatbus.com",
        "https://tcatbus.com/",
        "find where TCAT's park and ride lot in Danby is located",
        ("Dotson Park, across from Danby Town Hall", "Dotson Park"),
    ),
    (
        "T24",
        "tcatbus.com",
        "https://tcatbus.com/",
        "find out how much a weekly TCAT bus pass costs",
        ("$17.50", "17.50"),
    ),
    (
        "T25",
        "hackage.haskell.org",
        "https://hackage.haskell.org/",
        "browse Hackage's packages by category, open the Chess Engine category, open the "
        "package listed there and tell me its author",
        ("Alberto Perez",),
    ),
]
