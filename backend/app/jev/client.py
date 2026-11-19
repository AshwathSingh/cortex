"""T-23.1: the one shared Jev AI (TypeSafe System One) client.

Jev is a decision model: it answers typed questions about a ``state`` with
calibrated probabilities and never writes free text. This client sends Noul
questions ("is this true?", answered 0-1) to ``POST /v1/systemone``; Choice and
Score can be added next to ``ask_nouls`` by whoever needs them, reusing the
retry and logging here.

Rules the callers rely on:

* A failed call raises. It is never turned into an answer, so "the API was
  down" cannot be mistaken for "no relationship".
* Transient failures (timeouts, transport errors, 429, 5xx) are retried with
  exponential backoff and jitter; 429 honours ``Retry-After``. 401/403 and other
  4xx are not retried.
* One call covers one workspace: ``item_workspace_ids`` must all match
  ``workspace_id`` or nothing is sent.
* Logs carry status, attempt and workspace only: never the key, the state or a
  question.
"""

import logging
import random
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

MAX_BACKOFF_SECONDS = 30.0


class JevError(Exception):
    """A call failed for good (or ran out of retries)."""


class JevTransientError(JevError):
    """A retryable failure that persisted through every retry."""


class JevAuthError(JevError):
    """The API key was rejected. Retrying cannot help."""


class WorkspaceMismatch(JevError):
    """Items from more than one workspace were about to share a call."""


@dataclass(frozen=True)
class JevResult:
    model: str  # the versioned id that answered, for ``model_version`` provenance
    nouls: dict[str, float]
    input_tokens: int = 0


class JevClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.typesafe.ai",
        model: str = "jev-1.14.0",
        timeout_ms: int = 20_000,
        max_retries: int = 3,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._key = api_key
        self._url = base_url.rstrip("/") + "/v1/systemone"
        self._model = model
        self._max_retries = max_retries
        self._sleep = sleep
        self._http = http or httpx.Client(timeout=timeout_ms / 1000)

    def close(self) -> None:
        self._http.close()

    def ask_nouls(
        self,
        *,
        workspace_id: str,
        item_workspace_ids: Iterable[str],
        state: dict,
        questions: dict[str, str],
    ) -> JevResult:
        """Ask several yes/no questions about one state in a single request."""
        if any(str(w) != str(workspace_id) for w in item_workspace_ids):
            raise WorkspaceMismatch("refusing to send items from several workspaces")
        body = {
            "model": self._model,
            "state": state,
            "questions": {
                name: {"type": "noul", "instructions": text}
                for name, text in questions.items()
            },
        }
        response = self._post_with_retry(body, workspace_id)
        return _parse(response, set(questions))

    def _post_with_retry(self, body: dict, workspace_id: str) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._key}"}
        last = "unknown"
        for attempt in range(self._max_retries + 1):
            retry_after: float | None = None
            try:
                response = self._http.post(self._url, json=body, headers=headers)
            except httpx.HTTPError as error:
                last = type(error).__name__
            else:
                status = response.status_code
                if status == 200:
                    return response
                if status in (401, 403):
                    raise JevAuthError(f"Jev rejected the API key ({status})")
                if status != 429 and status < 500:
                    raise JevError(f"Jev returned HTTP {status}")
                last = f"HTTP {status}"
                retry_after = _retry_after(response)
            if attempt == self._max_retries:
                break
            delay = retry_after if retry_after is not None else min(
                MAX_BACKOFF_SECONDS, 0.5 * 2**attempt
            ) * random.uniform(0.5, 1.5)
            logger.warning(
                "jev call failed (%s); retry %d/%d in %.1fs workspace=%s",
                last, attempt + 1, self._max_retries, delay, workspace_id,
            )
            self._sleep(delay)
        raise JevTransientError(f"Jev unavailable after retries ({last})")


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return min(MAX_BACKOFF_SECONDS, max(0.0, float(response.headers["retry-after"])))
    except (KeyError, ValueError):
        return None


def _parse(response: httpx.Response, expected: set[str]) -> JevResult:
    try:
        data = response.json()
        answers = data["answers"]
        nouls = {
            name: float(answers[name]["noul"])
            for name in expected
            if answers[name]["type"] == "noul"
        }
        usage = data.get("usage") or {}
        model = str(data["model"])
    except (ValueError, KeyError, TypeError) as error:
        raise JevError("Jev returned an unexpected response shape") from error
    if set(nouls) != expected or any(not 0.0 <= p <= 1.0 for p in nouls.values()):
        raise JevError("Jev returned missing or out-of-range answers")
    return JevResult(model=model, nouls=nouls, input_tokens=int(usage.get("input_tokens", 0)))
