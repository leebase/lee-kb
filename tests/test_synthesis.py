"""Focused tests for the injected, source-bounded Responses provider."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from lee_kb.answer_contracts import Claim, Confidence, SynthesisProvider
from lee_kb.contracts import (
    ChunkId,
    Citation,
    KnowledgeItemId,
    SourceLocator,
    compute_content_hash,
)
from lee_kb.synthesis import (
    OpenAIResponsesSynthesisProvider,
    SynthesisProviderError,
)


@dataclass
class FakeResponses:
    response: object
    error: Exception | None = None
    calls: list[dict[str, object]] | None = None

    def __post_init__(self) -> None:
        self.calls = []

    def create(self, **kwargs: object) -> object:
        assert self.calls is not None
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


@dataclass
class FakeClient:
    response: object
    error: Exception | None = None

    def __post_init__(self) -> None:
        self.responses = FakeResponses(self.response, self.error)


def make_claim(name: str, text: str) -> Claim:
    item_id = KnowledgeItemId("local_files", name)
    chunk_id = ChunkId(item_id, 0, compute_content_hash(f"{name}:{text}"))
    return Claim(
        text=text,
        citations=(
            Citation(
                item_id=item_id,
                chunk_id=chunk_id,
                source_locator=SourceLocator(
                    "local_files", f"file:///private/{name}.md", name
                ),
                title=name,
            ),
        ),
        confidence=Confidence.DIRECTLY_EVIDENCED,
    )


def test_provider_sends_only_ordered_claims_and_preserves_markers() -> None:
    client = FakeClient({"output_text": "[1] First fact. [2] Second fact."})
    provider = OpenAIResponsesSynthesisProvider(client, model="approved-model")
    claims = (
        make_claim("first", "First fact."),
        make_claim("second", "Second fact."),
    )

    assert isinstance(provider, SynthesisProvider)
    assert provider.narrate(claims) == "[1] First fact. [2] Second fact."
    call = client.responses.calls[0]
    assert call["model"] == "approved-model"
    instructions = str(call["instructions"])
    prompt = str(call["input"])
    assert "Use only the supplied claim text" in instructions
    assert prompt.index("First fact.") < prompt.index("Second fact.")
    assert "file:///private/" not in prompt
    assert "local_files" not in prompt
    assert "first" not in prompt
    assert "second" not in prompt


def test_provider_extracts_raw_responses_output_items() -> None:
    client = FakeClient(
        {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "[1] Grounded fact."}],
                }
            ]
        }
    )
    provider = OpenAIResponsesSynthesisProvider(client, model="approved-model")

    assert provider.narrate((make_claim("fact", "Grounded fact."),)) == (
        "[1] Grounded fact."
    )


@pytest.mark.parametrize(
    "output",
    [
        "[2] Wrong order. [1] First.",
        "[1] Missing second marker.",
        "[1] First. [2] Second. [3] Invented.",
        "UNABLE_TO_GROUND",
    ],
)
def test_provider_rejects_unbounded_or_unattributed_output(output: str) -> None:
    provider = OpenAIResponsesSynthesisProvider(
        FakeClient({"output_text": output}), model="approved-model"
    )

    with pytest.raises(SynthesisProviderError, match="ground|marker"):
        provider.narrate(
            (
                make_claim("first", "First."),
                make_claim("second", "Second."),
            )
        )


def test_provider_failure_does_not_expose_client_error_or_claim_text() -> None:
    provider = OpenAIResponsesSynthesisProvider(
        FakeClient(
            {},
            error=RuntimeError("secret provider diagnostic with claim text"),
        ),
        model="approved-model",
    )

    with pytest.raises(SynthesisProviderError) as raised:
        provider.narrate((make_claim("secret", "Claim text."),))

    assert str(raised.value) == "synthesis provider request failed"
    assert "secret provider diagnostic" not in str(raised.value)
    assert "Claim text" not in str(raised.value)


def test_provider_rejects_empty_claims_before_client_call() -> None:
    client = FakeClient({"output_text": "[1] Should not be used."})
    provider = OpenAIResponsesSynthesisProvider(client, model="approved-model")

    with pytest.raises(SynthesisProviderError, match="at least one claim"):
        provider.narrate(())

    assert client.responses.calls == []
