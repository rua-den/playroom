from __future__ import annotations

import codecs
import json
import threading
from dataclasses import dataclass, field
from typing import Iterable, Iterator

import httpx2 as httpx
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError


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
    supported_parameters: tuple[str, ...] = ()
    output_parameter: str = "max_tokens"
    provider_tag: str | None = None


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

    def cancel(self, request: dict) -> None:
        """Best-effort physical cancellation hook for worker shutdown."""
        event = request.get("cancel_event") if isinstance(request, dict) else None
        if event is not None and hasattr(event, "set"):
            event.set()


class FakeProvider(ProviderAdapter):
    """Deterministic provider for tests and explicit local fixtures only."""

    def __init__(self, outputs: Iterable[str | ProviderFailure | dict], *, capabilities: ProviderCapabilities | None = None):
        self.outputs = list(outputs)
        self.calls: list[dict] = []
        self.stage_counts: dict[str, int] = {}
        self.capabilities = capabilities or ProviderCapabilities("fake://local", "synthetic-fixture", 12000, 4000)

    def capabilities_for(self, profile: dict) -> ProviderCapabilities:
        return self.capabilities

    def generate_text(self, request: dict) -> Iterator[str | ProviderResult | ProviderFailure]:
        self.calls.append({key: value for key, value in request.items() if key != "cancel_event"})
        stage = str(request.get("stage", "narration"))
        self.stage_counts[stage] = self.stage_counts.get(stage, 0) + 1
        output = self.outputs.pop(0) if self.outputs else ""
        if isinstance(output, ProviderFailure):
            yield output
            return
        if isinstance(output, dict):
            if output.get("cancelled"):
                yield ProviderFailure("CANCELLED", "Generation was cancelled")
                return
            for event in output.get("events", []):
                if isinstance(event, ProviderFailure):
                    yield event
                    return
                if isinstance(event, str):
                    yield event
            reason = output.get("finish_reason")
            if reason != "stop":
                yield ProviderFailure("OUTPUT_TRUNCATED" if reason == "length" else "MISSING_TERMINAL" if reason is None else "MODEL_REFUSED", "Fake provider did not complete normally")
                return
            text = "".join(event for event in output.get("events", []) if isinstance(event, str))
            yield ProviderResult(text=text, usage=output.get("usage", {"status": "unknown"}), finish_reason="stop")
            return
        words = str(output).split(" ")
        for index, word in enumerate(words):
            yield word + (" " if index < len(words) - 1 else "")
        yield ProviderResult(text=str(output), usage={"input_tokens": request.get("estimated_input_tokens", 0), "output_tokens": len(words), "total_tokens": request.get("estimated_input_tokens", 0) + len(words)}, finish_reason="stop")

    def generate_structured(self, request: dict, schema: dict) -> ProviderResult | ProviderFailure:
        self.calls.append({key: value for key, value in request.items() if key != "cancel_event"})
        stage = str(request.get("stage", "context"))
        self.stage_counts[stage] = self.stage_counts.get(stage, 0) + 1
        output = self.outputs.pop(0) if self.outputs else ProviderFailure("MODEL_REFUSED", "No deterministic structured fixture")
        if isinstance(output, ProviderFailure):
            return output
        if isinstance(output, dict):
            if output.get("cancelled"):
                return ProviderFailure("CANCELLED", "Generation was cancelled")
            text = str(output.get("text", ""))
        else:
            text = str(output)
        try:
            value = json.loads(text)
            Draft202012Validator(schema).validate(value)
        except (ValueError, TypeError, SchemaValidationError):
            return ProviderFailure("SCHEMA_INVALID", "Provider returned data outside the requested schema")
        return ProviderResult(text=text, usage={"status": "unknown"}, finish_reason="stop")


class OpenRouterAdapter(ProviderAdapter):
    """Pinned OpenRouter adapter with provider fallback, tools and healing disabled."""

    def __init__(self, api_key: str, endpoint: str, *, profile: dict | None = None, http_client: httpx.Client | None = None):
        if not api_key or not endpoint.startswith("https://"):
            raise ValueError("OpenRouter requires HTTPS and a key")
        if not profile or not profile.get("id") or not profile.get("version") or not profile.get("profile_hash") or not profile.get("provider_tag"):
            raise ValueError("OpenRouter adapter requires an immutable verified profile")
        if profile and profile.get("endpoint") and profile["endpoint"] != endpoint:
            raise ValueError("OpenRouter endpoint does not match the verified profile")
        self._key, self.endpoint, self.profile = api_key, endpoint, dict(profile or {})
        self.client = http_client or httpx.Client(timeout=300)
        self._active_response = None
        self._response_lock = threading.Lock()

    def cancel(self, request: dict) -> None:
        super().cancel(request)
        with self._response_lock:
            response = self._active_response
        if response is not None:
            try:
                response.close()
            except Exception:
                pass

    def capabilities_for(self, profile: dict) -> ProviderCapabilities:
        return ProviderCapabilities(self.endpoint, profile["model"], int(profile["context_limit"]), int(profile["output_limit"]), structured_output=bool(profile.get("structured_output")), supported_parameters=tuple(profile.get("supported_parameters", ())), output_parameter=profile.get("output_parameter", "max_tokens"), provider_tag=profile.get("provider_tag"))

    def _payload(self, request: dict, schema: dict | None = None) -> dict:
        pinned = self.profile
        model = pinned.get("model")
        if not model:
            raise ValueError("OpenRouter adapter requires a verified pinned model")
        if request.get("model") and request["model"] != model:
            raise ValueError("Requested model does not match the verified profile")
        supported = set(pinned.get("supported_parameters", ()))
        output_parameter = pinned.get("output_parameter") or ("max_completion_tokens" if "max_completion_tokens" in supported else "max_tokens")
        if output_parameter not in supported:
            raise ValueError("Verified profile does not support its output allowance parameter")
        if schema is not None and not (pinned.get("native_structured_output") is True and pinned.get("structured_schema_parameter") in supported and pinned.get("structured_output") is True):
            raise ValueError("Verified endpoint does not support structured output")
        if any(key in request for key in ("reasoning", "reasoning_effort")) and not any(key in supported for key in ("reasoning", "reasoning_effort")):
            raise ValueError("Verified endpoint does not support reasoning parameters")
        if any(key in request for key in ("tools", "plugins", "transforms", "models", "model_fallbacks")):
            raise ValueError("Unsupported provider fallback or tool options")
        requested_output = request.get("reserved_completion_tokens", request.get("reserved_output_tokens"))
        try:
            requested_output = int(requested_output)
        except (TypeError, ValueError) as exc:
            raise ValueError("A reserved output allowance is required") from exc
        if requested_output <= 0 or requested_output > int(pinned["output_limit"]):
            raise ValueError("Reserved output allowance exceeds the verified endpoint limit")
        provider = {"allow_fallbacks": False, "require_parameters": True}
        if pinned.get("provider_tag"):
            provider["only"] = [pinned["provider_tag"]]
        payload = {"model": model, "messages": request.get("messages", []), "stream": True, "stream_options": {"include_usage": True}, output_parameter: requested_output, "provider": provider}
        if schema is not None:
            payload["response_format"] = {"type": "json_schema", "json_schema": {"name": request.get("schema_name", "selection_plan"), "strict": True, "schema": schema}}
        return payload

    def generate_text(self, request: dict) -> Iterator[str | ProviderResult | ProviderFailure]:
        try:
            payload = self._payload(request)
        except ValueError as exc:
            yield ProviderFailure("CONFIG_INVALID", str(exc))
            return
        yield from self._stream(payload, request=request)

    def generate_structured(self, request: dict, schema: dict) -> ProviderResult | ProviderFailure:
        try:
            events = list(self._stream(self._payload(request, schema), request=request))
        except ValueError as exc:
            return ProviderFailure("CONFIG_INVALID", str(exc))
        failure = next((item for item in events if isinstance(item, ProviderFailure)), None)
        if failure:
            return failure
        result = next((item for item in reversed(events) if isinstance(item, ProviderResult)), None)
        if result is None:
            return ProviderFailure("OUTPUT_TRUNCATED", "Missing terminal provider frame")
        try:
            value = json.loads(result.text)
            Draft202012Validator(schema).validate(value)
        except (ValueError, TypeError, SchemaValidationError):
            return ProviderFailure("SCHEMA_INVALID", "Provider returned data outside the requested schema")
        return result

    def _stream(self, payload: dict, *, request: dict | None = None) -> Iterator[str | ProviderResult | ProviderFailure]:
        text_parts: list[str] = []
        usage = None
        finish_reason = None
        done = False
        failed = False
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        pending = ""
        data_lines: list[str] = []

        def parse_event(lines: list[str]):
            nonlocal usage, finish_reason, done, failed
            if not lines:
                return None
            value = "\n".join(lines).strip()
            if value == "[DONE]":
                done = True
                return None
            try:
                frame = json.loads(value)
            except (ValueError, TypeError):
                failed = True
                return ProviderFailure("PROVIDER_ERROR", "Malformed provider frame")
            return process_frame(frame)

        def process_frame(frame):
            nonlocal usage, finish_reason, done, failed
            error = frame.get("error")
            if error:
                code = str(error.get("code", "")).casefold() if isinstance(error, dict) else ""
                normalized = "QUOTA_EXHAUSTED" if code in {"402", "429", "quota"} else "MODEL_UNAVAILABLE" if code in {"404", "503", "model_not_found"} else "PROVIDER_ERROR"
                failed = True
                return ProviderFailure(normalized, "OpenRouter provider returned an error")
            if frame.get("usage") is not None:
                usage = frame["usage"]
            choice = (frame.get("choices") or [{}])[0]
            delta = choice.get("delta") or {}
            refusal = delta.get("refusal") or choice.get("refusal")
            if refusal:
                failed = True
                return ProviderFailure("MODEL_REFUSED", "OpenRouter refused the request")
            if choice.get("finish_reason") is not None:
                finish_reason = choice.get("finish_reason")
            if delta.get("content"):
                text_parts.append(str(delta["content"]))
                return str(delta["content"])
            return None

        try:
            with self.client.stream("POST", self.endpoint, headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}, json=payload) as response:
                with self._response_lock:
                    self._active_response = response
                if response.status_code >= 400:
                    code = "QUOTA_EXHAUSTED" if response.status_code in {402, 429} else "MODEL_UNAVAILABLE" if response.status_code in {404, 503} else "PROVIDER_ERROR"
                    yield ProviderFailure(code, "OpenRouter request failed")
                    return
                for chunk in response.iter_bytes():
                    if request and request.get("cancel_event") is not None and request["cancel_event"].is_set():
                        return
                    pending += decoder.decode(chunk, final=False)
                    while "\n" in pending:
                        line, pending = pending.split("\n", 1)
                        line = line.rstrip("\r")
                        if line == "":
                            event = parse_event(data_lines)
                            data_lines = []
                            if isinstance(event, ProviderFailure):
                                yield event
                                return
                            if isinstance(event, str):
                                yield event
                        elif line.startswith(":"):
                            continue
                        elif line.startswith("data:"):
                            data_lines.append(line[5:].lstrip())
                pending += decoder.decode(b"", final=True)
                if pending:
                    data_lines.append(pending[5:].lstrip() if pending.startswith("data:") else pending)
                if data_lines:
                    event = parse_event(data_lines)
                    if isinstance(event, ProviderFailure):
                        yield event
                        return
                    if isinstance(event, str):
                        yield event
        except UnicodeDecodeError:
            yield ProviderFailure("PROVIDER_ERROR", "Provider stream encoding was invalid")
            return
        except httpx.TimeoutException:
            yield ProviderFailure("PROVIDER_TIMEOUT", "Provider request timed out")
            return
        except httpx.HTTPError:
            yield ProviderFailure("MODEL_UNAVAILABLE", "OpenRouter provider could not be reached")
            return
        finally:
            with self._response_lock:
                self._active_response = None
        if failed:
            return
        if finish_reason == "length":
            yield ProviderFailure("OUTPUT_TRUNCATED", "Provider output reached its limit")
        elif finish_reason == "refusal":
            yield ProviderFailure("MODEL_REFUSED", "OpenRouter refused the request")
        elif finish_reason != "stop" or not done:
            yield ProviderFailure("MISSING_TERMINAL", "Provider stream did not provide a normal terminal frame")
        else:
            yield ProviderResult("".join(text_parts), usage if usage is not None else {"status": "unknown"}, "stop")


def default_provider_factory(*, owner_id: str, stage: str, profile: dict, credential: str, http_client=None) -> ProviderAdapter:
    """Construct the pinned adapter for one immutable role dispatch."""
    if profile.get("provider") != "openrouter":
        raise ValueError("No production adapter is registered for this provider")
    if not credential:
        raise ValueError("Pinned provider credential is unavailable")
    return OpenRouterAdapter(credential, profile["endpoint"], profile=profile, http_client=http_client)
