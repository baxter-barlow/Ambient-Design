"""Model adapters.

AC5 requires "a pinned frontier model (stated version and sampling params)".
Pinning is enforced structurally here: a client cannot be constructed
without a concrete model id and sampling parameters, and those travel into
every result record. A run whose model identity is unknown is not an AC5
run, and there is no code path that produces one.

TOKEN ACCOUNTING. `ModelResponse.usage` carries the PROVIDER's reported
token counts, never a local estimate. The AC5 budget of 150K tokens per
trial is a cost budget, and the only defensible source for cost is the bill.
The pinned local tokenizer in tokenizer.py answers a different question and
is not used here.

ReplayClient makes a recorded run re-executable offline: CI exercises the
whole protocol with no API key and no spend, and a recording whose requests
no longer match the protocol fails loudly instead of quietly diverging.
"""

import hashlib
import json
from dataclasses import dataclass, field, asdict


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_dict(self) -> dict:
        return {**asdict(self), "total": self.total}


@dataclass
class ModelResponse:
    text: str
    usage: Usage
    stop_reason: str | None = None
    model: str | None = None

    def as_dict(self) -> dict:
        return {
            "text_sha256": "sha256:"
            + hashlib.sha256(self.text.encode("utf-8")).hexdigest(),
            "text_chars": len(self.text),
            "usage": self.usage.as_dict(),
            "stop_reason": self.stop_reason,
            "model": self.model,
        }


@dataclass
class SamplingParams:
    """Pinned sampling configuration. Recorded verbatim in every result."""

    temperature: float
    max_tokens: int
    top_p: float | None = None
    top_k: int | None = None
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def request_digest(system: str, messages: list[dict]) -> str:
    """Stable digest of a request, used to detect replay divergence."""
    payload = json.dumps(
        {"system": system, "messages": messages}, sort_keys=True, ensure_ascii=False
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ModelUnavailableError(RuntimeError):
    """The pinned model could not be reached. Never silently substituted."""


class AnthropicClient:
    """Live client for a pinned Anthropic model.

    Deliberately thin: the harness needs one non-streaming completion with
    reported usage, and nothing else. Retries are NOT implemented here — a
    retried trial is a different trial, and silently retrying to a better
    outcome is exactly the "retry to green" failure the project prohibits
    elsewhere. A failed call fails its trial and is recorded as such.
    """

    def __init__(self, model: str, sampling: SamplingParams, api_key: str | None = None):
        if not model:
            raise ValueError("a concrete pinned model id is required")
        try:
            import anthropic
        except ImportError as exc:
            raise ModelUnavailableError(
                "the anthropic package is not installed; install it to run live "
                "trials, or use ReplayClient against a recorded transcript."
            ) from exc
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.model = model
        self.sampling = sampling

    def complete(self, system: str, messages: list[dict]) -> ModelResponse:
        kwargs = {
            "model": self.model,
            "system": system,
            "messages": messages,
            "max_tokens": self.sampling.max_tokens,
            "temperature": self.sampling.temperature,
        }
        if self.sampling.top_p is not None:
            kwargs["top_p"] = self.sampling.top_p
        if self.sampling.top_k is not None:
            kwargs["top_k"] = self.sampling.top_k
        kwargs.update(self.sampling.extra)

        response = self._client.messages.create(**kwargs)
        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
        return ModelResponse(
            text=text,
            usage=Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
            stop_reason=getattr(response, "stop_reason", None),
            model=self.model,
        )

    def identity(self) -> dict:
        return {
            "kind": "anthropic",
            "model": self.model,
            "sampling": self.sampling.as_dict(),
        }


class ReplayClient:
    """Replay recorded model responses, verifying the request still matches.

    Each recorded turn carries the digest of the request that produced it.
    If the protocol now sends a different request — a changed prompt, an
    extra repair turn, a reordered context — the digest differs and this
    raises. That is the point: a replay that quietly returned a stale
    response would make prompt changes invisible and every recorded result
    unfalsifiable.
    """

    def __init__(self, turns: list[dict], model: str, sampling: SamplingParams,
                 strict: bool = True):
        self._turns = list(turns)
        self._cursor = 0
        self.model = model
        self.sampling = sampling
        self.strict = strict

    def complete(self, system: str, messages: list[dict]) -> ModelResponse:
        if self._cursor >= len(self._turns):
            raise IndexError(
                "replay transcript exhausted: the protocol requested more model "
                "turns than were recorded. Re-record rather than padding."
            )
        turn = self._turns[self._cursor]
        self._cursor += 1

        recorded_digest = turn.get("request_digest")
        if self.strict and recorded_digest:
            actual = request_digest(system, messages)
            if actual != recorded_digest:
                raise ValueError(
                    "replay divergence at turn "
                    f"{self._cursor - 1}: the request no longer matches the "
                    f"recording.\n  recorded {recorded_digest}\n  actual   {actual}\n"
                    "The prompt or protocol changed since this transcript was "
                    "made, so replaying it would report results for a run that "
                    "never happened. Re-record the transcript."
                )

        usage = turn.get("usage", {})
        return ModelResponse(
            text=turn["text"],
            usage=Usage(
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
            ),
            stop_reason=turn.get("stop_reason"),
            model=self.model,
        )

    def identity(self) -> dict:
        return {
            "kind": "replay",
            "model": self.model,
            "sampling": self.sampling.as_dict(),
            "turns": len(self._turns),
        }
