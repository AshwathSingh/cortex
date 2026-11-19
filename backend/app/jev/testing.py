"""An in-memory stand-in for ``JevClient`` so tests never call the real API."""

from collections.abc import Callable, Iterable

from app.jev.client import JevError, JevResult, WorkspaceMismatch


class FakeJev:
    """``answer(state, questions) -> {question_name: probability}``; unlisted names get 0."""

    def __init__(self, answer: Callable[[dict, dict], dict[str, float]] | None = None,
                 model: str = "jev-test"):
        self.answer = answer or (lambda state, questions: {})
        self.model = model
        self.calls: list[dict] = []
        self.fail_with: JevError | None = None

    def ask_nouls(self, *, workspace_id: str, item_workspace_ids: Iterable[str],
                  state: dict, questions: dict[str, str]) -> JevResult:
        if any(str(w) != str(workspace_id) for w in item_workspace_ids):
            raise WorkspaceMismatch("refusing to send items from several workspaces")
        self.calls.append({"workspace_id": workspace_id, "state": state, "questions": questions})
        if self.fail_with:
            raise self.fail_with
        given = self.answer(state, questions)
        return JevResult(self.model, {name: given.get(name, 0.0) for name in questions})
