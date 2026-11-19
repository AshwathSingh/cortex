"""US-23 unit tests: routing, dedup, Jev client, the agent run, and the review API.

No Neo4j and no network: the agent runs against an in-memory store and
``FakeJev``; the Jev client runs against ``httpx.MockTransport``.
"""

import logging

import httpx
import pytest

from app.agent import relationships as rel
from app.agent.candidates import Artifact, find_candidates
from app.agent.service import ConnectionAgent, content_hash
from app.jev import JevAuthError, JevClient, JevError, JevTransientError, WorkspaceMismatch
from app.jev.testing import FakeJev

WS = "ccccccc0-0000-4000-8000-00000000c0de"
OTHER_WS = "ccccccc0-0000-4000-8000-00000000c0df"


def art(n, title, body="", *, ws=WS, label="Issue", repo="o/r", number=None, **kw):
    return Artifact(key=f"{label}:{n}", label=label, id=n, workspace_id=ws, title=title,
                    body=body, repo=repo, number=number if number is not None else n, **kw)


# --- routing / schema (T-23.3) ------------------------------------------------

@pytest.mark.parametrize("p,expected", [
    (1.0, "active"), (0.7, "active"), (0.6999, "pending_review"),
    (0.4, "pending_review"), (0.3999, "discard"), (0.0, "discard"),
])
def test_three_way_routing_including_boundaries(p, expected):
    assert rel.route(p, 0.7, 0.4) == expected


def test_floor_zero_sends_everything_below_threshold_to_review():
    assert rel.route(0.0, 0.7, 0.0) == "pending_review"


def test_dedup_key_is_direction_insensitive_unless_directional():
    assert rel.dedup_key(WS, "Issue:1", "Issue:2", "RELATED_TO") == rel.dedup_key(WS, "Issue:2", "Issue:1", "RELATED_TO")
    assert rel.dedup_key(WS, "Issue:1", "Issue:2", "IMPLEMENTS") != rel.dedup_key(WS, "Issue:2", "Issue:1", "IMPLEMENTS")
    assert rel.dedup_key(WS, "Issue:1", "Issue:2", "IMPLEMENTS").startswith(WS)


def test_best_verdict_picks_highest_and_direction():
    v = rel.best_verdict({"IMPLEMENTS:ab": 0.2, "IMPLEMENTS:ba": 0.9, "RELATED_TO:ab": 0.5})
    assert (v.relationship_type, v.a_is_source, v.confidence) == ("IMPLEMENTS", False, 0.9)


def test_specific_type_beats_a_vaguer_one_within_the_margin():
    live = {"IMPLEMENTS:ab": 0.95, "REFERENCES:ab": 0.96, "RELATED_TO:ab": 0.98, "DEPENDS_ON:ab": 0.44}
    assert rel.best_verdict(live).relationship_type == "IMPLEMENTS"
    assert rel.best_verdict({"IMPLEMENTS:ab": 0.5, "RELATED_TO:ab": 0.9}).relationship_type == "RELATED_TO"


def test_every_question_is_asked_for_every_type():
    q = rel.build_questions()
    assert {"IMPLEMENTS:ab", "IMPLEMENTS:ba", "RELATED_TO:ab"} <= set(q) and "RELATED_TO:ba" not in q


@pytest.mark.parametrize("existing,routed,action", [
    (None, "active", "create"), (None, "pending_review", "create"), (None, "discard", "skip"),
    ("rejected", "active", "skip"),                      # never re-suggest
    ("active", "active", "update"), ("active", "pending_review", "skip"),  # never downgrade
    ("pending_review", "active", "promote"), ("pending_review", "pending_review", "update"),
])
def test_upsert_decision_table(existing, routed, action):
    assert rel.decide_upsert(existing, routed) == action


# --- candidates (T-23.2) -------------------------------------------------------

def test_candidates_need_a_signal_stay_in_workspace_and_are_capped():
    target = art(1, "Fix login", "Closes #2 and relates to PROJ-7")
    pool = [
        art(2, "Login bug"), art(3, "Unrelated lunch plans"),
        art(4, "Login bug", ws=OTHER_WS), art(5, "PROJ-7: login", number=99),
    ]
    found = [c.key for c in find_candidates(target, pool, limit=10)]
    assert found == ["Issue:2", "Issue:5"] or set(found) == {"Issue:2", "Issue:5"}
    assert "Issue:3" not in found and "Issue:4" not in found
    assert len(find_candidates(target, pool, limit=1)) == 1


# --- Jev client (T-23.1 / T-23.6) ----------------------------------------------

def jev(handler, retries=2, sleeps=None):
    return JevClient("sk-secret-key", max_retries=retries,
                     http=httpx.Client(transport=httpx.MockTransport(handler)),
                     sleep=(sleeps.append if sleeps is not None else lambda s: None))


OK = {"model": "jev-1.14.0", "answers": {"q": {"type": "noul", "noul": 0.8}}, "usage": {"input_tokens": 5}}


def ask(client, **over):
    args = dict(workspace_id=WS, item_workspace_ids=[WS], state={"a": "x"}, questions={"q": "?"})
    return client.ask_nouls(**{**args, **over})


def test_client_parses_answers_and_sends_bearer_key():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json=OK)

    result = ask(jev(handler))
    assert result.nouls == {"q": 0.8} and result.model == "jev-1.14.0"
    assert seen["auth"] == "Bearer sk-secret-key"


def test_client_retries_5xx_and_honours_retry_after_on_429():
    replies = iter([httpx.Response(429, headers={"retry-after": "2"}), httpx.Response(503),
                    httpx.Response(200, json=OK)])
    sleeps: list[float] = []
    assert ask(jev(lambda r: next(replies), retries=3, sleeps=sleeps)).nouls == {"q": 0.8}
    assert sleeps[0] == 2.0 and len(sleeps) == 2


def test_client_gives_up_after_max_retries_and_never_returns_a_fake_answer():
    calls = []
    client = jev(lambda r: calls.append(1) or httpx.Response(500), retries=2)
    with pytest.raises(JevTransientError):
        ask(client)
    assert len(calls) == 3


def test_client_timeout_is_transient():
    def boom(request):
        raise httpx.ReadTimeout("slow")
    with pytest.raises(JevTransientError):
        ask(jev(boom, retries=1))


def test_auth_failure_is_not_retried():
    calls = []
    with pytest.raises(JevAuthError):
        ask(jev(lambda r: calls.append(1) or httpx.Response(401)))
    assert len(calls) == 1


@pytest.mark.parametrize("payload", [{"nope": 1}, {**OK, "answers": {"q": {"type": "noul", "noul": 1.5}}},
                                     {**OK, "answers": {}}])
def test_malformed_or_out_of_range_response_is_an_error(payload):
    with pytest.raises(JevError):
        ask(jev(lambda r: httpx.Response(200, json=payload)))


def test_mixed_workspaces_are_refused_before_any_request():
    calls = []
    with pytest.raises(WorkspaceMismatch):
        ask(jev(lambda r: calls.append(1) or httpx.Response(200, json=OK)),
            item_workspace_ids=[WS, OTHER_WS])
    assert calls == []


def test_logs_never_contain_the_key_or_content(caplog):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(JevError):
        ask(jev(lambda r: httpx.Response(500), retries=1), state={"a": "PRIVATE BODY"})
    assert "sk-secret-key" not in caplog.text and "PRIVATE BODY" not in caplog.text


# --- the agent run (T-23.2 - T-23.4, T-23.6) -----------------------------------

class MemStore:
    """Stands in for Neo4jStore *and* the mutation layer's persistence."""

    def __init__(self, artifacts):
        self.artifacts = {a.key: a for a in artifacts}
        self.edges: dict[str, dict] = {}     # dedup -> edge
        self.status: dict[str, str] = {}
        self.hashes: dict[str, str] = {}
        self.blocked: set[frozenset] = set()

    def fetch_artifacts(self, ws):
        return [a if a.key not in self.hashes else
                Artifact(**{**a.__dict__, "analysis_hash": self.hashes[a.key]})
                for a in self.artifacts.values() if a.workspace_id == ws]

    def pair_blocked(self, ws, a, b):
        return frozenset((a, b)) in self.blocked

    def existing_edge_for_pair(self, ws, a, b):
        pair = frozenset((a, b))
        for e in self.edges.values():
            if frozenset((e["source"], e["target"])) == pair:
                return (e["id"], e["status"], e["type"])
        return None


@pytest.fixture
def mem(monkeypatch):
    from app.agent import service

    def build(artifacts, answer, **kw):
        store, fake = MemStore(artifacts), FakeJev(answer)

        def create(driver, ws, *, source_key, target_key, relationship_type, dedup, status,
                   confidence, evidence, model_version, explicit_refs):
            store.edges[dedup] = dict(id=f"e{len(store.edges)}", status=status, confidence=confidence,
                                      source=source_key, target=target_key, type=relationship_type,
                                      evidence=evidence, model=model_version)
            return store.edges[dedup]["id"]

        def update(driver, ws, *, edge_id, confidence, evidence, model_version, explicit_refs, promote):
            e = next(e for e in store.edges.values() if e["id"] == edge_id)
            assert e["status"] != "rejected"
            e.update(confidence=confidence, evidence=evidence)
            if promote:
                e["status"] = "active"

        def retype(driver, ws, *, old_edge_id, source_key, target_key, relationship_type, dedup,
                  status, confidence, evidence, model_version, explicit_refs):
            old_dedup = next(k for k, e in store.edges.items() if e["id"] == old_edge_id)
            if store.edges[old_dedup]["status"] == "rejected":
                return None
            del store.edges[old_dedup]
            new_id = f"e{len(store.edges)}"
            store.edges[dedup] = dict(id=new_id, status=status, confidence=confidence,
                                      source=source_key, target=target_key, type=relationship_type,
                                      evidence=evidence, model=model_version)
            return new_id

        def status(driver, ws, key, st, *, content_hash=None, error=None):
            store.status[key] = st
            if st == "done":
                store.hashes[key] = content_hash

        monkeypatch.setattr(service.mutations, "create_agent_edge", create)
        monkeypatch.setattr(service.mutations, "retype_agent_edge", retype)
        monkeypatch.setattr(service.mutations, "update_agent_edge", update)
        monkeypatch.setattr(service.mutations, "set_analysis_status", status)
        agent = ConnectionAgent(store, fake, None, threshold=0.7, review_floor=0.4,
                                max_candidates=kw.get("max_candidates", 10))
        return store, fake, agent
    return build


PAIR = [art(1, "Fix login crash", "Closes #2 login crash fix"),
        art(2, "Login crash on submit", "users see a crash on login submit")]


def says(p, key="IMPLEMENTS:ab"):
    return lambda state, questions: {key: p}


def test_high_confidence_becomes_an_active_edge_with_provenance(mem):
    store, fake, agent = mem(PAIR, says(0.9))
    summary = agent.run(WS)
    (edge,) = store.edges.values()
    assert (edge["status"], edge["type"], edge["source"], edge["target"]) == ("active", "IMPLEMENTS", "Issue:1", "Issue:2")
    assert edge["model"] == "jev-test" and "90%" in edge["evidence"] and edge["confidence"] == 0.9
    assert summary.created == 1 and store.status == {"Issue:1": "done", "Issue:2": "done"}
    assert len(fake.calls) == 1, "a pair is analysed once, not from both sides"


def test_mid_confidence_is_pending_review_and_low_is_discarded(mem):
    store, _, agent = mem(PAIR, says(0.5))
    agent.run(WS)
    assert [e["status"] for e in store.edges.values()] == ["pending_review"]
    store, _, agent = mem(PAIR, says(0.39))
    agent.run(WS)
    assert store.edges == {}


def test_rerun_with_unchanged_content_makes_no_calls_and_no_duplicates(mem):
    store, fake, agent = mem(PAIR, says(0.9))
    agent.run(WS)
    agent.run(WS)
    assert len(fake.calls) == 1 and len(store.edges) == 1


def test_changed_content_reanalyses_and_updates_in_place(mem):
    store, fake, agent = mem(PAIR, says(0.9))
    agent.run(WS)
    store.artifacts["Issue:1"] = art(1, "Fix login crash", "Closes #2, edited text")
    fake.answer = says(0.95)
    agent.run(WS)
    (edge,) = store.edges.values()
    assert edge["confidence"] == 0.95 and len(fake.calls) == 2


def test_pending_edge_is_promoted_when_reanalysis_clears_the_threshold(mem):
    store, fake, agent = mem(PAIR, says(0.5))
    agent.run(WS)
    store.artifacts["Issue:1"] = art(1, "Fix login crash", "Closes #2 edited")
    fake.answer = says(0.8)
    agent.run(WS)
    assert [e["status"] for e in store.edges.values()] == ["active"]


def test_reanalysis_with_a_different_type_retypes_in_place_not_a_duplicate(mem):
    """Regression: looking the pair's edge up by a dedup_key that embeds the
    *old* type meant a changed verdict never found it, so re-analysis added a
    second edge beside the stale one instead of replacing it."""
    store, fake, agent = mem(PAIR, says(0.9, key="IMPLEMENTS:ab"))
    agent.run(WS)
    (edge,) = store.edges.values()
    assert edge["type"] == "IMPLEMENTS" and edge["status"] == "active"

    store.artifacts["Issue:1"] = art(1, "Fix login crash", "Closes #2, edited text")
    fake.answer = lambda state, questions: {"RELATED_TO:ab": 0.9}
    agent.run(WS)

    assert len(store.edges) == 1, "a type change must retype the one edge, not add a second"
    (edge,) = store.edges.values()
    assert edge["type"] == "RELATED_TO" and edge["status"] == "active"


def test_type_change_never_downgrades_an_already_active_edge(mem):
    """The "never downgrade an active edge" rule must still hold once the
    lookup is by pair instead of by the old exact dedup key: a type change
    that now scores mid-confidence leaves the active edge exactly as it was,
    with no second edge added for the new, lower-scoring type."""
    store, fake, agent = mem(PAIR, says(0.9, key="IMPLEMENTS:ab"))
    agent.run(WS)
    store.artifacts["Issue:1"] = art(1, "Fix login crash", "Closes #2, edited text")
    fake.answer = lambda state, questions: {"RELATED_TO:ab": 0.5}
    agent.run(WS)
    assert len(store.edges) == 1
    (edge,) = store.edges.values()
    assert edge["type"] == "IMPLEMENTS" and edge["status"] == "active"


def test_type_change_promotes_a_pending_edge_in_place(mem):
    """A pending-review edge whose re-analysis now predicts a different,
    high-confidence type is promoted in place under the new type -- not left
    as a stale pending edge beside a second, active one."""
    store, fake, agent = mem(PAIR, lambda state, questions: {"RELATED_TO:ab": 0.5})
    agent.run(WS)
    store.artifacts["Issue:1"] = art(1, "Fix login crash", "Closes #2, edited text")
    fake.answer = says(0.9, key="IMPLEMENTS:ab")
    agent.run(WS)
    assert len(store.edges) == 1
    (edge,) = store.edges.values()
    assert edge["type"] == "IMPLEMENTS" and edge["status"] == "active"


def test_rejected_or_manual_pairs_are_skipped_without_calling_jev(mem):
    store, fake, agent = mem(PAIR, says(0.99))
    store.blocked.add(frozenset(("Issue:1", "Issue:2")))
    agent.run(WS)
    assert fake.calls == [] and store.edges == {}


def test_rejected_edge_is_never_touched_even_at_high_confidence(mem):
    store, fake, agent = mem(PAIR, says(0.9))
    agent.run(WS)
    next(iter(store.edges.values()))["status"] = "rejected"
    store.hashes.clear()
    agent.run(WS)
    assert next(iter(store.edges.values()))["status"] == "rejected" and len(store.edges) == 1


def test_jev_failure_marks_the_artifact_failed_and_does_not_raise(mem):
    store, fake, agent = mem(PAIR, says(0.9))
    fake.fail_with = JevTransientError("down")
    summary = agent.run(WS)          # ingestion would never see an exception
    assert summary.failed >= 1 and "failed" in store.status.values() and store.edges == {}
    fake.fail_with = None
    agent.run(WS)                     # retry: failed artifacts never recorded a hash
    assert len(store.edges) == 1


def test_artifacts_from_other_workspaces_are_never_linked(mem):
    foreign = art(2, "Login crash on submit", "users see a crash on login submit", ws=OTHER_WS)
    store, fake, agent = mem([PAIR[0], foreign], says(0.99))
    agent.run(WS)
    assert fake.calls == [] and store.edges == {}


def test_content_hash_ignores_unrelated_fields():
    assert content_hash(art(1, "t", "b")) == content_hash(art(9, "t", "b", repo="x"))


# --- Neo4jStore.fetch_artifacts pagination (T-23.6) ----------------------------

class _FakeSession:
    """Hands out ``pages`` one per call; the caller stops once a page is short."""

    def __init__(self, pages):
        self._pages = pages
        self._calls = 0
        self.skips: list[int] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute_read(self, fn):
        return fn(self)

    def run(self, query, **kwargs):
        self.skips.append(kwargs["skip"])
        page = self._pages[self._calls] if self._calls < len(self._pages) else []
        self._calls += 1
        return page


class _FakeDriver:
    def __init__(self, pages):
        self._session = _FakeSession(pages)

    def session(self):
        return self._session


def _row(n):
    return {"labels": ["Issue"], "props": {"id": n}, "author": None}


def test_fetch_artifacts_pages_past_a_single_round_trip(monkeypatch):
    """Regression: a hard ``LIMIT`` on the artifact query meant anything past
    the first page was never fetched, so it was never a candidate and never
    analysed. ``fetch_artifacts`` must keep paging until a short page says
    the workspace is exhausted, however many round trips that takes."""
    from app.agent import store as store_module

    monkeypatch.setattr(store_module, "ARTIFACT_PAGE_SIZE", 2)
    driver = _FakeDriver([[_row(1), _row(2)], [_row(3), _row(4)], [_row(5)]])

    result = store_module.Neo4jStore(driver).fetch_artifacts(WS)

    assert [a.id for a in result] == [1, 2, 3, 4, 5]
    assert driver._session.skips == [0, 2, 4]


def test_fetch_artifacts_stops_at_the_first_short_page(monkeypatch):
    from app.agent import store as store_module

    monkeypatch.setattr(store_module, "ARTIFACT_PAGE_SIZE", 5)
    driver = _FakeDriver([[_row(1), _row(2)]])

    result = store_module.Neo4jStore(driver).fetch_artifacts(WS)

    assert [a.id for a in result] == [1, 2]
    assert driver._session.skips == [0]
