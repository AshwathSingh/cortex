"""T-28.3: the Pruning Agent's rules, item by item.

Pure functions over hand-built items with an injected ``now``, which is the only
way the thresholds get checked honestly -- a rule tested through a database and a
real clock can only be tested for "it fired at all".

What a flag has to deliver, per US-28:

* AC1 -- out-of-date, contradicted and thinly-supported items all get flagged
* AC2 -- a flag names its items, says what is wrong, and how serious it is
* AC4 -- a flag carries the evidence that produced it
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.pruning.detect import (
    MIN_BODY_CHARS,
    STALE_AFTER,
    FlagRule,
    GraphItem,
    Severity,
    detect_flags,
)

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
BODY = "x" * (MIN_BODY_CHARS + 10)


def item(
    key: str = "Issue:1",
    *,
    type: str = "Issue",
    title: str = "Login redirect is broken",
    repo: str | None = "cortex/app",
    state: str | None = "open",
    body: str = BODY,
    updated_days_ago: int = 1,
    created_days_ago: int | None = None,
    closed_days_ago: int | None = None,
    merged_days_ago: int | None = None,
    author_login: str | None = "ashwath",
    url: str | None = "https://github.com/cortex/app/issues/1",
    number: int | None = 1,
) -> GraphItem:
    def ago(days: int | None) -> datetime | None:
        return None if days is None else NOW - timedelta(days=days)

    return GraphItem(
        key=key,
        type=type,
        title=title,
        repo=repo,
        number=number,
        url=url,
        state=state,
        body=body,
        created_at=ago(created_days_ago if created_days_ago is not None else updated_days_ago),
        updated_at=ago(updated_days_ago),
        closed_at=ago(closed_days_ago),
        merged_at=ago(merged_days_ago),
        author_login=author_login,
    )


def flags(items, now=NOW):
    return detect_flags(items, now=now)


def by_rule(items, rule: FlagRule, now=NOW):
    return [flag for flag in flags(items, now) if flag.rule is rule]


# --- out of date ------------------------------------------------------------


def test_a_fresh_open_item_is_not_flagged():
    assert by_rule([item(updated_days_ago=3)], FlagRule.STALE) == []


def test_an_item_untouched_for_months_is_flagged():
    (flag,) = by_rule([item(updated_days_ago=120)], FlagRule.STALE)

    assert flag.severity is Severity.LOW
    assert "still open" in flag.summary
    assert "4 months" in flag.summary
    assert [target.key for target in flag.targets] == ["Issue:1"]


def test_staleness_is_reported_harder_as_it_gets_worse():
    def severity(days: int) -> Severity:
        (flag,) = by_rule([item(updated_days_ago=days)], FlagRule.STALE)
        return flag.severity

    assert severity(100) is Severity.LOW
    assert severity(200) is Severity.MEDIUM
    assert severity(400) is Severity.HIGH


def test_the_threshold_is_not_crossed_a_day_early():
    just_inside = STALE_AFTER.days - 1
    assert by_rule([item(updated_days_ago=just_inside)], FlagRule.STALE) == []
    assert len(by_rule([item(updated_days_ago=STALE_AFTER.days)], FlagRule.STALE)) == 1


def test_a_closed_item_is_never_stale():
    """Nobody needs telling that finished work has stopped moving."""
    old_and_closed = item(updated_days_ago=800, state="closed", closed_days_ago=800)

    assert by_rule([old_and_closed], FlagRule.STALE) == []


def test_an_item_with_no_state_is_treated_as_open():
    """A missing property is not a reason to stop reporting on something."""
    assert len(by_rule([item(state=None, updated_days_ago=200)], FlagRule.STALE)) == 1


def test_an_item_with_no_timestamps_is_not_guessed_at():
    nothing_known = GraphItem(
        key="Issue:9", type="Issue", title="Mystery", repo="cortex/app", number=9,
        url=None, state="open", body=BODY, created_at=None, updated_at=None,
        closed_at=None, merged_at=None, author_login="ashwath",
    )

    assert by_rule([nothing_known], FlagRule.STALE) == []


def test_staleness_falls_back_to_when_it_was_opened():
    never_updated = GraphItem(
        key="Issue:9", type="Issue", title="Opened and forgotten", repo="cortex/app",
        number=9, url=None, state="open", body=BODY,
        created_at=NOW - timedelta(days=300), updated_at=None,
        closed_at=None, merged_at=None, author_login="ashwath",
    )

    (flag,) = by_rule([never_updated], FlagRule.STALE)
    assert flag.severity is Severity.MEDIUM


def test_a_stale_flag_shows_what_made_it_fire():
    """AC4."""
    (flag,) = by_rule([item(updated_days_ago=200, created_days_ago=400)], FlagRule.STALE)

    evidence = {e.label: e.detail for e in flag.evidence}
    assert "2026-04-19" in evidence["Last activity"]
    assert evidence["State"] == "open"
    assert evidence["Opened"] == "2025-10-01"
    assert evidence["Author"] == "ashwath"


# --- contradicted -----------------------------------------------------------


def test_a_closed_item_and_an_open_duplicate_contradict_each_other():
    """AC1: the workspace says the same thing is both done and not done."""
    done = item("PullRequest:10", type="PullRequest", title="Fix login redirect",
                state="closed", closed_days_ago=5, merged_days_ago=5)
    still_open = item("Issue:1", title="login redirect fix")

    (flag,) = by_rule([done, still_open], FlagRule.CONTRADICTED)

    assert flag.severity is Severity.HIGH  # one of them actually shipped
    assert {target.key for target in flag.targets} == {"PullRequest:10", "Issue:1"}
    assert "merged" in flag.summary
    assert "still open" in flag.summary


def test_a_closed_but_unmerged_duplicate_is_less_serious():
    abandoned = item("PullRequest:10", type="PullRequest", title="Fix login redirect",
                     state="closed", closed_days_ago=5)
    still_open = item("Issue:1", title="Fix login redirect")

    (flag,) = by_rule([abandoned, still_open], FlagRule.CONTRADICTED)

    assert flag.severity is Severity.MEDIUM


@pytest.mark.parametrize(
    "other_title",
    [
        "fix login redirect",             # case
        "Fix the login, redirect!",       # punctuation and a filler word
        "[WIP] login redirect fix",       # status prefix
        "FIX LOGIN REDIRECT",             # shouting
        "redirect login fix",             # word order
    ],
)
def test_a_reworded_duplicate_is_still_recognised(other_title):
    """Somebody reopened the same work under a tidier name and nobody closed the
    first one -- which is the common case, so the comparison has to survive it."""
    done = item("PullRequest:10", type="PullRequest", title="Fix login redirect",
                state="closed", closed_days_ago=5)
    reopened = item("Issue:1", title=other_title)

    assert len(by_rule([done, reopened], FlagRule.CONTRADICTED)) == 1


def test_two_open_duplicates_are_not_a_contradiction():
    """Nothing is claiming different things; they are just two open items."""
    a = item("Issue:1", title="Fix login redirect")
    b = item("Issue:2", title="Fix login redirect")

    assert by_rule([a, b], FlagRule.CONTRADICTED) == []


def test_two_closed_duplicates_are_not_a_contradiction():
    a = item("Issue:1", title="Fix login", state="closed", closed_days_ago=3)
    b = item("Issue:2", title="Fix login", state="closed", closed_days_ago=2)

    assert by_rule([a, b], FlagRule.CONTRADICTED) == []


def test_duplicates_in_different_repositories_do_not_contradict():
    """Two projects are allowed to have a 'Fix login' each."""
    done = item("Issue:1", repo="cortex/app", title="Fix login", state="closed",
                closed_days_ago=3)
    open_elsewhere = item("Issue:2", repo="cortex/docs", title="Fix login")

    assert by_rule([done, open_elsewhere], FlagRule.CONTRADICTED) == []


def test_opposite_items_are_not_treated_as_duplicates():
    """Action verbs are kept in the signature on purpose. Dropping them would
    catch a few more rewordings and collapse these two into one subject."""
    added = item("Issue:1", title="Add rate limiting", state="closed",
                 closed_days_ago=3)
    removed = item("Issue:2", title="Remove rate limiting")

    assert by_rule([added, removed], FlagRule.CONTRADICTED) == []


def test_a_one_word_title_is_not_compared():
    """"Bug" matches every other "Bug" and means nothing."""
    done = item("Issue:1", title="Bug", state="closed", closed_days_ago=3)
    still_open = item("Issue:2", title="Bug")

    assert by_rule([done, still_open], FlagRule.CONTRADICTED) == []


def test_every_open_duplicate_is_paired_with_the_resolved_one():
    done = item("PullRequest:10", type="PullRequest", title="Fix login redirect",
                state="closed", merged_days_ago=1, closed_days_ago=1)
    first = item("Issue:1", title="Fix login redirect")
    second = item("Issue:2", title="fix login redirect")

    found = by_rule([done, first, second], FlagRule.CONTRADICTED)

    assert len(found) == 2
    assert {flag.targets[1].key for flag in found} == {"Issue:1", "Issue:2"}


def test_the_most_recently_resolved_duplicate_is_the_one_cited():
    old = item("Issue:1", title="Fix login", state="closed", closed_days_ago=300)
    recent = item("Issue:2", title="Fix login", state="closed", closed_days_ago=2)
    still_open = item("Issue:3", title="Fix login")

    (flag,) = by_rule([old, recent, still_open], FlagRule.CONTRADICTED)

    assert flag.targets[0].key == "Issue:2"


def test_a_contradiction_flag_shows_both_sides():
    """AC4."""
    done = item("PullRequest:10", type="PullRequest", title="Fix login redirect",
                state="closed", closed_days_ago=5, merged_days_ago=5)
    still_open = item("Issue:1", title="Fix login redirect", updated_days_ago=30)

    (flag,) = by_rule([done, still_open], FlagRule.CONTRADICTED)

    evidence = {e.label: e.detail for e in flag.evidence}
    assert "word order" in evidence["Same subject"]
    assert evidence["Repository"] == "cortex/app"
    assert "merged on 2026-10-31" in evidence["Resolved"]
    assert "last touched 2026-10-06" in evidence["Still open"]


# --- thinly supported -------------------------------------------------------


def test_an_item_with_no_description_is_flagged():
    (flag,) = by_rule([item(body="")], FlagRule.THIN)

    assert flag.severity is Severity.LOW
    assert "little or no description" in flag.summary


def test_a_short_description_counts_as_none():
    assert len(by_rule([item(body="see above")], FlagRule.THIN)) == 1
    assert by_rule([item(body="y" * MIN_BODY_CHARS)], FlagRule.THIN) == []


def test_whitespace_is_not_a_description():
    assert len(by_rule([item(body="   \n\t  ")], FlagRule.THIN)) == 1


def test_an_item_with_no_author_is_worse_than_one_with_no_description():
    """There is nobody to ask."""
    (flag,) = by_rule([item(author_login=None)], FlagRule.THIN)

    assert flag.severity is Severity.MEDIUM
    assert "nobody to ask" in flag.summary


def test_an_item_with_neither_is_the_most_serious():
    (flag,) = by_rule([item(body="", author_login=None)], FlagRule.THIN)

    assert flag.severity is Severity.HIGH
    assert "no description and no recorded author" in flag.summary


def test_a_well_described_item_with_an_author_is_not_flagged():
    assert by_rule([item()], FlagRule.THIN) == []


def test_an_abandoned_closed_item_is_not_an_evidence_gap():
    """It is not a hole in the project's knowledge, it is just closed."""
    abandoned = item(state="closed", closed_days_ago=400, body="", author_login=None)

    assert by_rule([abandoned], FlagRule.THIN) == []


def test_a_merged_pull_request_is_still_held_to_it():
    """Merged work is load-bearing: the graph is asserting it shipped."""
    merged = item("PullRequest:10", type="PullRequest", state="closed",
                  merged_days_ago=10, closed_days_ago=10, body="")

    assert len(by_rule([merged], FlagRule.THIN)) == 1


def test_a_thin_flag_shows_what_was_missing():
    """AC4."""
    (flag,) = by_rule([item(body="", author_login=None)], FlagRule.THIN)

    evidence = {e.label: e.detail for e in flag.evidence}
    assert evidence["Description"] == "empty"
    assert evidence["Author"] == "no author is recorded in the graph"


# --- the run as a whole -----------------------------------------------------


def test_an_empty_workspace_has_nothing_to_review():
    assert flags([]) == []


def test_one_item_can_raise_more_than_one_flag():
    """Stale and undocumented are two separate problems with two separate fixes."""
    neglected = item(updated_days_ago=400, body="")

    assert {flag.rule for flag in flags([neglected])} == {FlagRule.STALE, FlagRule.THIN}


def test_the_most_serious_flags_come_first():
    """AC2: severity is part of the answer, so it decides the order."""
    found = flags([
        item("Issue:1", body="", updated_days_ago=1),                    # LOW
        item("Issue:2", body="", author_login=None, updated_days_ago=1), # HIGH
        item("Issue:3", author_login=None, updated_days_ago=1),          # MEDIUM
    ])

    assert [flag.severity for flag in found] == [
        Severity.HIGH,
        Severity.MEDIUM,
        Severity.LOW,
    ]


def test_two_runs_over_unchanged_data_agree_exactly():
    """A review queue that reshuffles on reload is one nobody can work through."""
    items = [
        item("Issue:1", body="", updated_days_ago=200),
        item("Issue:2", title="Fix login", state="closed", closed_days_ago=3),
        item("Issue:3", title="fix login"),
    ]

    first = flags(items)
    second = flags(list(reversed(items)))

    assert [flag.id for flag in first] == [flag.id for flag in second]


def test_a_flags_id_identifies_the_finding_not_the_run():
    """Nothing is stored, so the id has to come from the finding itself."""
    one = flags([item(updated_days_ago=200)])[0]
    later = flags([item(updated_days_ago=260)], now=NOW + timedelta(days=60))[0]

    assert one.id == later.id


def test_different_findings_about_one_item_have_different_ids():
    found = flags([item(updated_days_ago=400, body="")])

    assert len({flag.id for flag in found}) == 2


def test_every_flag_carries_a_label_a_summary_and_its_evidence():
    """AC2 and AC4, for every rule rather than one at a time."""
    found = flags([
        item("Issue:1", body="", updated_days_ago=400),
        item("Issue:2", title="Fix login", state="closed", closed_days_ago=3),
        item("Issue:3", title="fix login"),
    ])

    assert {flag.rule for flag in found} == set(FlagRule)
    for flag in found:
        assert flag.label and flag.summary.endswith(".")
        assert flag.targets and flag.evidence
