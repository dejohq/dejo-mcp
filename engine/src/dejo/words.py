"""Words that never tell two tasks, or two lines of a page, apart."""

from __future__ import annotations

# Words too common to tell two tasks apart. "the invoice" and "the subscription" share
# "the" and nothing that matters. Pronouns and helper verbs are here for the same reason:
# "tell me its price" and "tell me its rating" share "its", and nothing that says which job.
#
# Shared by task matching in store.py and the page view's "best for" block, which drops the
# same words from a task before ranking lines: one list, so the two never disagree. In the
# view a word counts more the rarer it is on the page, so a stray function word is worse
# than useless: on Wikipedia's city table "its" sat on 6 of 2,284 lines and outranked
# "lagos", the word the task was about.
#
# "about" is deliberately NOT here: "open the About page" names a real link on most sites.
COMMON_WORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "do",
        "does",
        "for",
        "from",
        "get",
        "had",
        "has",
        "have",
        "her",
        "his",
        "how",
        "i",
        "in",
        "into",
        "is",
        "it",
        "its",
        "many",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "please",
        "show",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "with",
        "you",
        "your",
    ]
)
