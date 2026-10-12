from __future__ import annotations

from dataclasses import dataclass, field
import json
import httpx2 as httpx
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


class OpenRouterAdapter(ProviderAdapter):
    """Pinned OpenRouter chat adapter with provider fallback and tools disabled."""
    def __init__(self, api_key: str, endpoint: str, *, http_client: httpx.Client | None = None):
        if not api_key or not endpoint.startswith("https://"):
            raise ValueError("OpenRouter requires HTTPS and a key")
        self._key, self.endpoint = api_key, endpoint
        self.client = http_client or httpx.Client(timeout=300)

    def capabilities_for(self, profile: dict) -> ProviderCapabilities:
        return ProviderCapabilities(self.endpoint, profile["model"], int(profile["context_limit"]), int(profile["output_limit"]), structured_output=bool(profile.get("structured_output")))

    def _payload(self, request: dict, schema: dict | None = None) -> dict:
        payload = {"model": request["model"], "messages": request.get("messages", []), "stream": True, "stream_options": {"include_usage": True}, "provider": {"allow_fallbacks": False, "require_parameters": True}}
        if schema is not None: payload["response_format"] = {"type": "json_schema", "json_schema": {"name": "selection_plan", "strict": True, "schema": schema}}
        if any(key in request for key in ("tools", "plugins", "transforms", "models")): raise ValueError("Unsupported provider fallback or tool options")
        return payload

    def generate_text(self, request: dict) -> Iterator[str | ProviderResult | ProviderFailure]:
        yield from self._stream(self._payload(request))

    def generate_structured(self, request: dict, schema: dict) -> ProviderResult | ProviderFailure:
        events = list(self._stream(self._payload(request, schema)))
        failure = next((item for item in events if isinstance(item, ProviderFailure)), None)
        if failure: return failure
        result = next((item for item in reversed(events) if isinstance(item, ProviderResult)), None)
        if result is None: return ProviderFailure("OUTPUT_TRUNCATED", "Missing terminal provider frame")
        try: json.loads(result.text)
        except (TypeError, ValueError): return ProviderFailure("SCHEMA_INVALID", "Provider returned invalid JSON")
        return result

    def _stream(self, payload: dict) -> Iterator[str | ProviderResult | ProviderFailure]:
        try: response = self.client.post(self.endpoint, headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}, json=payload)
        except httpx.TimeoutException:
            yield ProviderFailure("PROVIDER_TIMEOUT", "Provider request timed out"); return
        if response.status_code >= 400:
            code = "QUOTA_EXHAUSTED" if response.status_code in {402, 429} else "MODEL_UNAVAILABLE" if response.status_code in {404, 503} else "PROVIDER_ERROR"
            yield ProviderFailure(code, "OpenRouter request failed"); return
        text, usage, terminal, pending = [], None, False, ""
        for chunk in response.iter_bytes():
            pending += chunk.decode("utf-8", errors="strict")
            while "\n" in pending:
                line, pending = pending.split("\n", 1); line = line.rstrip("\r")
                if not line.startswith("data:"): continue
                value = line[5:].strip()
                if value == "[DONE]": terminal = True; continue
                try: frame = json.loads(value)
                except ValueError:
                    yield ProviderFailure("PROVIDER_ERROR", "Malformed provider frame"); return
                if frame.get("error"):
                    yield ProviderFailure("MODEL_REFUSED", "Provider refused the request"); return
                if frame.get("usage"): usage = frame["usage"]
                choice = (frame.get("choices") or [{}])[0]
                delta = (choice.get("delta") or {}).get("content")
                if delta: text.append(delta); yield delta
                if choice.get("finish_reason") == "stop": terminal = True
        if not terminal: yield ProviderFailure("OUTPUT_TRUNCATED", "Provider stream had no terminal success")
        else: yield ProviderResult("".join(text), usage or {"status": "unknown"}, "stop")
