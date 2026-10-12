from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Iterable, Iterator


@dataclass(frozen=True)
class ProviderCapabilities:
    endpoint: str
    model: str
    context_limit: int
    output_limit: int
    streaming: bool = True
    usage_reporting: bool = True
    token_count_mode: str = "estimated"
    structured_output: bool = False


@dataclass(frozen=True)
class ProviderFailure:
    code: str
    message: str


@dataclass
class ProviderResult:
    text: str = ""
    usage: dict = field(default_factory=dict)
    finish_reason: str = "stop"
    failure: ProviderFailure | None = None


class ProviderAdapter:
    def capabilities_for(self, profile: dict) -> ProviderCapabilities:
        raise NotImplementedError

    def generate_text(self, request: dict) -> Iterator[str | ProviderResult | ProviderFailure]:
        raise NotImplementedError

    def generate_structured(self, request: dict, schema: dict) -> ProviderResult | ProviderFailure:
        raise NotImplementedError("Structured output is not supported by this adapter")


class FakeProvider(ProviderAdapter):
    """Deterministic provider used only by tests and local development."""

    def __init__(self, outputs: Iterable[str | ProviderFailure], *, capabilities: ProviderCapabilities | None = None):
        self.outputs = list(outputs)
        self.calls: list[dict] = []
        self.capabilities = capabilities or ProviderCapabilities("fake://local", "synthetic-fixture", 12000, 4000)

    def capabilities_for(self, profile: dict) -> ProviderCapabilities:
        return self.capabilities

    def generate_text(self, request: dict) -> Iterator[str | ProviderResult | ProviderFailure]:
        self.calls.append(request)
        output = self.outputs.pop(0) if self.outputs else ""
        if isinstance(output, ProviderFailure):
            yield output
            return
        words = output.split(" ")
        for index, word in enumerate(words):
            yield word + (" " if index < len(words) - 1 else "")
        yield ProviderResult(text=output, usage={"input_tokens": request.get("estimated_input_tokens", 0), "output_tokens": len(words), "total_tokens": request.get("estimated_input_tokens", 0) + len(words)}, finish_reason="stop")

    def generate_structured(self, request: dict, schema: dict) -> ProviderResult | ProviderFailure:
        output = self.outputs.pop(0) if self.outputs else ProviderFailure("MODEL_REFUSED", "No deterministic structured fixture")
        if isinstance(output, ProviderFailure):
            return output
        try:
            json_text = output if isinstance(output, str) else str(output)
            return ProviderResult(text=json_text, usage={"input_tokens": request.get("estimated_input_tokens", 0), "output_tokens": len(json_text.split())}, finish_reason="stop")
        except Exception:
            return ProviderFailure("SCHEMA_INVALID", "Malformed structured fixture")
