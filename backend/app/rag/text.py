"""Small text utilities shared by the offline embedder, evidence checks, and demo answers.

Deliberately simple and dependency-free: lowercase words, common English stop words
removed, and a light suffix-stripping "stemmer" so that refund/refunds/refunded match.
"""

import re

_WORD = re.compile(r"[a-z0-9]+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")

STOPWORDS = frozenset(
    """
    a about above after again against all also am an and any are as at be because been
    before being below between both but by can could did do does doing done down during
    each either few for from further get got had has have having he her here hers him his
    how i if in into is it its itself just let me might more most must my no nor not now
    of off on once only or other our ours out over own per please same shall she should
    so some such than thank thanks that the their theirs them then there these they this
    those through to too under until up upon us very via was we were what when where which
    while who whom whose why will with within without would yes yet you your yours
    hi hello hey tell know want need like ok okay
    """.split()
)


def stem(word: str) -> str:
    """Strip common English suffixes. Crude, but consistent for queries and documents."""
    if len(word) <= 3 or word.isdigit():
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("es") and word[:-2].endswith(("s", "x", "z", "ch", "sh")):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    for suffix in ("ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            base = word[: -len(suffix)]
            # shipped -> shipp -> ship, but keep billing -> bill
            if base[-1] == base[-2] and base[-1] not in "lsz":
                base = base[:-1]
            return base
    return word


def terms(text: str) -> list[str]:
    """Content words of ``text``: lowercased, stop words removed, stemmed."""
    return [stem(w) for w in _WORD.findall(text.lower()) if w not in STOPWORDS and len(w) > 1]


def term_matches(term: str, vocabulary: set[str]) -> bool:
    """True if ``term`` or a word sharing its first five letters is in ``vocabulary``.

    The prefix rule absorbs stemming misses such as charge/charged.
    """
    if term in vocabulary:
        return True
    if len(term) < 5:
        return False
    prefix = term[:5]
    return any(word.startswith(prefix) for word in vocabulary)


def coverage(question: str, passages: list[str]) -> float:
    """Share of the question's distinct content words found in the passages (0..1)."""
    question_terms = set(terms(question))
    if not question_terms:
        return 0.0
    vocabulary = {t for passage in passages for t in terms(passage)}
    found = sum(1 for t in question_terms if term_matches(t, vocabulary))
    return found / len(question_terms)


def split_sentences(text: str) -> list[str]:
    """Split prose into sentences; list items and lines are kept as separate units."""
    sentences: list[str] = []
    for line in text.splitlines():
        line = line.strip().lstrip("-*•").strip()
        if line:
            sentences.extend(part.strip() for part in _SENTENCE_END.split(line) if part.strip())
    return sentences
