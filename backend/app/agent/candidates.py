"""T-23.2: cheap candidate pre-filter, so Jev is not called on every pair.

Signals, strongest first: an explicit reference (``#12``, an issue key like
``PROJ-7``, or the other item's URL), shared distinctive words, same author,
nearby in time. Only pairs with an explicit reference or enough shared words
qualify; author/time only break ties. Aryan's contradiction check (T-30.2) can
import ``find_candidates`` as is.
"""

import re
from dataclasses import dataclass, field

KEYWORD_MIN_LEN = 4
MIN_SHARED_KEYWORDS = 2
TIME_WINDOW_DAYS = 7
_WORD = re.compile(r"[a-z0-9_]{%d,}" % KEYWORD_MIN_LEN)
_ISSUE_KEY = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
_NUMBER_REF = re.compile(r"(?<![\w/])#(\d+)\b")
_STOP = frozenset(
    "this that with from have will would should could there their about which when what "
    "then than into also been were your more some just like over only make made".split()
)


@dataclass(frozen=True)
class Artifact:
    key: str  # "PullRequest:42"
    label: str
    id: int | str
    workspace_id: str
    title: str
    body: str
    url: str | None = None
    repo: str | None = None
    number: int | None = None
    author: str | None = None
    created_at: str | None = None  # ISO-8601
    analysis_hash: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.body}"


def _keywords(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


def explicit_references(a: Artifact, b: Artifact) -> list[str]:
    """Why a names b (or vice versa), as short human-readable strings."""
    found: list[str] = []
    for src, dst in ((a, b), (b, a)):
        if dst.number is not None and dst.repo == src.repo:
            if any(int(n) == dst.number for n in _NUMBER_REF.findall(src.text)):
                found.append(f"{src.title[:40]!r} mentions #{dst.number}")
        if dst.url and dst.url in src.text:
            found.append(f"text links to {dst.url}")
        keys = set(_ISSUE_KEY.findall(dst.title)) & set(_ISSUE_KEY.findall(src.text))
        found.extend(f"text mentions {k}" for k in sorted(keys))
    return found


def _day(iso: str | None) -> float | None:
    from datetime import datetime

    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() / 86400
    except (AttributeError, ValueError):
        return None


def score(a: Artifact, b: Artifact) -> float:
    refs = explicit_references(a, b)
    shared = len(_keywords(a.text) & _keywords(b.text))
    if not refs and shared < MIN_SHARED_KEYWORDS:
        return 0.0
    total = 10.0 * len(refs) + shared
    if a.author and a.author == b.author:
        total += 0.5
    da, db = _day(a.created_at), _day(b.created_at)
    if da is not None and db is not None and abs(da - db) <= TIME_WINDOW_DAYS:
        total += 0.5
    return total


def find_candidates(target: Artifact, pool: list[Artifact], limit: int) -> list[Artifact]:
    """Top ``limit`` qualifying artifacts from the *same workspace*, best first."""
    scored = [
        (score(target, other), other)
        for other in pool
        if other.key != target.key and other.workspace_id == target.workspace_id
    ]
    scored = [item for item in scored if item[0] > 0]
    scored.sort(key=lambda item: (-item[0], item[1].key))
    return [other for _, other in scored[:limit]]
