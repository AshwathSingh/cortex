"""T-28.1: the rules that flag stale, contradictory and thinly-supported items.

Pure functions over a list of ``GraphItem``, with ``now`` passed in. Nothing here
touches Neo4j -- ``app.pruning.graph`` does the reading -- so every rule is
testable against a handful of hand-built items, which is the only way thresholds
and edge cases get checked honestly.

Why these three rules
---------------------
US-28 asks for information that is "out of date, contradicted elsewhere, or
thinly supported". Over GitHub-derived data that is:

``STALE``
    An item that is still open and has not been touched in months. The graph is
    asserting live work that nobody is doing.

``CONTRADICTED``
    Two items in one repository whose titles are the same once case, punctuation
    and word order are ignored, where one is resolved and the other is not. The
    workspace is saying the same thing is both done and not done.

``THIN``
    An item with no description worth reading, or with no author recorded, so
    there is nothing to judge it by and nobody to ask.

Each rule had to be computable from what is actually in the graph *and* able to
fire on real data. A rule that never fires is dead code dressed up as a feature,
which is why there is no "merged but still open" check here: GitHub closes merged
pull requests, so the inconsistency it would look for cannot arrive.

Deliberately not learned, not scored by a model: a flag the reader cannot argue
with is a flag they cannot act on, so every one carries the evidence that
produced it (AC4) and nothing else decides the outcome.
"""

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

#: An open item untouched for longer than this is worth a look. Three months is
#: a quarter: long enough that "we were busy" has stopped being the explanation.
STALE_AFTER = timedelta(days=90)
#: Past these, the same staleness is reported harder rather than as a new flag.
STALE_SERIOUS = timedelta(days=180)
#: A year of silence on something still marked open.
STALE_CRITICAL = timedelta(days=365)

#: Below this, a description is not evidence of anything. Deliberately short: a
#: couple of sentences is a real description, and anything stricter would flag
#: half of every repository and teach the reader to ignore the page.
MIN_BODY_CHARS = 40

#: Titles shorter than this (in words) are not compared for duplicates. A
#: one-word title like "Bug" matches every other "Bug" and means nothing.
MIN_TITLE_WORDS = 2

#: Conventional-commit and status prefixes, stripped before comparing titles so
#: "[WIP] fix login" and "fix: Login" are recognised as the same thing.
_TITLE_PREFIX = re.compile(
    r"^\s*(?:\[[^\]]*\]\s*|\((?:[^)]*)\)\s*|"
    r"(?:wip|fix|fixes|bug|bugfix|feat|feature|chore|docs|refactor|test|hotfix)"
    r"\s*[:\-/]\s*)+",
    re.IGNORECASE,
)
_WORD = re.compile(r"[a-z0-9]+")

#: Filler words dropped before comparing titles, so "Fix the login, redirect!"
#: and "fix login redirect" are recognised as the same subject.
#:
#: Articles, prepositions and conjunctions only. Action verbs are deliberately
#: kept, even though dropping "fix" and "add" would catch a few more rewordings:
#: without them "Add rate limiting" and "Remove rate limiting" would collapse to
#: the same subject, and flagging two opposite items as duplicates is a worse
#: mistake than missing one real one.
_FILLER = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
        "in", "into", "is", "it", "its", "of", "on", "or", "that", "the",
        "their", "this", "to", "was", "were", "when", "with",
    }
)


class FlagRule(str, Enum):
    STALE = "STALE"
    CONTRADICTED = "CONTRADICTED"
    THIN = "THIN"


class Severity(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


#: What each rule is called on screen. Held here rather than in the frontend so
#: the wording cannot drift from the rule that produced it.
RULE_LABELS: dict[FlagRule, str] = {
    FlagRule.STALE: "Out of date",
    FlagRule.CONTRADICTED: "Contradicted",
    FlagRule.THIN: "Thinly supported",
}

_SEVERITY_ORDER = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}


@dataclass(frozen=True)
class GraphItem:
    """One pull request or issue, as the rules need it.

    A flat, already-parsed shape rather than the raw node: the rules should not
    each have to cope with a missing property or an unparseable date.
    """

    key: str
    type: str
    title: str
    repo: str | None
    number: int | None
    url: str | None
    state: str | None
    body: str
    created_at: datetime | None
    updated_at: datetime | None
    closed_at: datetime | None
    merged_at: datetime | None
    author_login: str | None

    @property
    def is_open(self) -> bool:
        # Anything not explicitly closed counts as open: a null state is not a
        # reason to stop reporting on an item.
        return (self.state or "open").lower() != "closed"

    @property
    def is_merged(self) -> bool:
        return self.merged_at is not None

    @property
    def is_resolved(self) -> bool:
        return not self.is_open


@dataclass(frozen=True)
class Evidence:
    """One fact that contributed to a flag (AC4)."""

    label: str
    detail: str


@dataclass(frozen=True)
class FlagTarget:
    key: str
    type: str
    title: str
    url: str | None = None


@dataclass(frozen=True)
class Flag:
    id: str
    rule: FlagRule
    label: str
    severity: Severity
    #: One sentence naming what is wrong, for the list (AC2).
    summary: str
    targets: tuple[FlagTarget, ...]
    evidence: tuple[Evidence, ...] = field(default_factory=tuple)


def _flag_id(rule: FlagRule, keys: tuple[str, ...]) -> str:
    """A stable id for the same finding about the same items.

    Flags are recomputed on every read rather than stored, so the id has to come
    from the finding itself: without that, a reader could not keep a flag open in
    one tab and refresh in another, and nothing could ever reference one.
    """
    digest = hashlib.sha256(
        "|".join([rule.value, *sorted(keys)]).encode("utf-8")
    ).hexdigest()
    return digest[:16]


def _target(item: GraphItem) -> FlagTarget:
    return FlagTarget(key=item.key, type=item.type, title=item.title, url=item.url)


def _item_name(item: GraphItem) -> str:
    """How an item is referred to in a sentence."""
    return item.title or f"{item.type} {item.key}"


def _age_words(span: timedelta) -> str:
    days = max(0, span.days)
    if days >= 365:
        years = days // 365
        return f"{years} year{'s' if years != 1 else ''}"
    if days >= 60:
        months = days // 30
        return f"{months} months"
    return f"{days} day{'s' if days != 1 else ''}"


def _on(moment: datetime | None) -> str:
    return moment.date().isoformat() if moment else "an unknown date"


# --- out of date ------------------------------------------------------------


def _stale_flag(item: GraphItem, now: datetime) -> Flag | None:
    if not item.is_open:
        return None
    touched = item.updated_at or item.created_at
    if touched is None:
        return None
    idle = now - touched
    if idle < STALE_AFTER:
        return None

    severity = (
        Severity.HIGH
        if idle >= STALE_CRITICAL
        else Severity.MEDIUM
        if idle >= STALE_SERIOUS
        else Severity.LOW
    )
    words = _age_words(idle)
    evidence = [
        Evidence("Last activity", f"{_on(touched)}, {words} ago"),
        Evidence("State", item.state or "open"),
    ]
    if item.created_at is not None:
        evidence.append(Evidence("Opened", _on(item.created_at)))
    if item.author_login:
        evidence.append(Evidence("Author", item.author_login))

    return Flag(
        id=_flag_id(FlagRule.STALE, (item.key,)),
        rule=FlagRule.STALE,
        label=RULE_LABELS[FlagRule.STALE],
        severity=severity,
        summary=(
            f"{_item_name(item)} is still open but nothing has touched it "
            f"for {words}."
        ),
        targets=(_target(item),),
        evidence=tuple(evidence),
    )


# --- contradicted -----------------------------------------------------------


def _title_signature(title: str) -> str | None:
    """A title reduced to what it is *about*, or None if it says too little.

    Case, punctuation, status prefixes and word order are all dropped, so
    "[WIP] Fix the login redirect" and "fix: login redirect fix" collapse to the
    same signature. Sorting the words is what catches a reworded duplicate,
    which is the common case -- somebody reopened the same work under a tidier
    name and nobody closed the first one.
    """
    stripped = _TITLE_PREFIX.sub("", title or "")
    words = [word for word in _WORD.findall(stripped.lower()) if word not in _FILLER]
    if len(words) < MIN_TITLE_WORDS:
        return None
    return " ".join(sorted(set(words)))


def _contradiction_flag(resolved: GraphItem, unresolved: GraphItem) -> Flag:
    keys = (resolved.key, unresolved.key)
    # One of them actually shipped, so the open one is the more likely leftover.
    severity = Severity.HIGH if resolved.is_merged else Severity.MEDIUM
    closed_word = "merged" if resolved.is_merged else "closed"
    return Flag(
        id=_flag_id(FlagRule.CONTRADICTED, keys),
        rule=FlagRule.CONTRADICTED,
        label=RULE_LABELS[FlagRule.CONTRADICTED],
        severity=severity,
        summary=(
            f"{_item_name(resolved)} is {closed_word}, but "
            f"{_item_name(unresolved)} describes the same thing and is still open."
        ),
        targets=(_target(resolved), _target(unresolved)),
        evidence=(
            Evidence(
                "Same subject",
                "Both titles are identical once case, punctuation and word "
                "order are ignored",
            ),
            # Labelled by role rather than by title: the two items usually have
            # near-identical titles, which is the whole point, so titled labels
            # would read as the same thing said twice.
            Evidence(
                "Resolved",
                f"{_item_name(resolved)} was {closed_word} on "
                f"{_on(resolved.closed_at or resolved.merged_at)}",
            ),
            Evidence(
                "Still open",
                f"{_item_name(unresolved)}, last touched "
                f"{_on(unresolved.updated_at)}",
            ),
            Evidence("Repository", resolved.repo or "unknown"),
        ),
    )


def _contradiction_flags(items: list[GraphItem]) -> list[Flag]:
    """Pair up same-subject items in one repository that disagree about being done.

    Grouped by (repo, signature) so this stays linear: comparing every item with
    every other would be a quarter of a million comparisons on a workspace at
    the node ceiling, for a result no better than an exact signature match.
    """
    groups: dict[tuple[str | None, str], list[GraphItem]] = defaultdict(list)
    for item in items:
        signature = _title_signature(item.title)
        if signature is None:
            continue
        groups[(item.repo, signature)].append(item)

    flags: list[Flag] = []
    for group in groups.values():
        if len(group) < 2:
            continue
        resolved = [item for item in group if item.is_resolved]
        unresolved = [item for item in group if item.is_open]
        if not resolved or not unresolved:
            # Two open duplicates, or two closed ones, are not a contradiction:
            # nothing is claiming different things about the same subject.
            continue
        # The most recently resolved against the oldest still open: that is the
        # pair where "this was finished, so why is that still here" bites.
        newest = max(
            resolved, key=lambda item: item.closed_at or item.merged_at or datetime.min.replace(tzinfo=timezone.utc)
        )
        for item in unresolved:
            flags.append(_contradiction_flag(newest, item))
    return flags


# --- thinly supported -------------------------------------------------------


def _thin_flag(item: GraphItem) -> Flag | None:
    # Only what the graph is currently asserting. A pull request somebody
    # abandoned two years ago with no description is not a gap in the project's
    # knowledge, it is just closed.
    if not (item.is_open or item.is_merged):
        return None

    undocumented = len(item.body.strip()) < MIN_BODY_CHARS
    unattributed = not item.author_login
    if not (undocumented or unattributed):
        return None

    evidence = []
    if undocumented:
        evidence.append(
            Evidence(
                "Description",
                "empty" if not item.body.strip() else f"{len(item.body.strip())} characters",
            )
        )
    if unattributed:
        evidence.append(
            Evidence("Author", "no author is recorded in the graph")
        )
    evidence.append(Evidence("State", item.state or "open"))

    if undocumented and unattributed:
        severity = Severity.HIGH
        problem = "has no description and no recorded author"
    elif unattributed:
        # Worse than a missing description: there is nobody to ask.
        severity = Severity.MEDIUM
        problem = "has no recorded author, so there is nobody to ask about it"
    else:
        severity = Severity.LOW
        problem = "has little or no description to judge it by"

    return Flag(
        id=_flag_id(FlagRule.THIN, (item.key,)),
        rule=FlagRule.THIN,
        label=RULE_LABELS[FlagRule.THIN],
        severity=severity,
        summary=f"{_item_name(item)} {problem}.",
        targets=(_target(item),),
        evidence=tuple(evidence),
    )


# --- the task ---------------------------------------------------------------


def detect_flags(items: list[GraphItem], *, now: datetime | None = None) -> list[Flag]:
    """Run every rule and return the flags, most serious first.

    Ordered by severity, then rule, then id. The id is in the sort so two runs
    over unchanged data produce the same list in the same order -- a review queue
    that reshuffles on reload is one nobody can work through.
    """
    moment = now or datetime.now(timezone.utc)

    flags: list[Flag] = []
    for item in items:
        stale = _stale_flag(item, moment)
        if stale:
            flags.append(stale)
        thin = _thin_flag(item)
        if thin:
            flags.append(thin)
    flags.extend(_contradiction_flags(items))

    flags.sort(key=lambda flag: (_SEVERITY_ORDER[flag.severity], flag.rule.value, flag.id))
    return flags
