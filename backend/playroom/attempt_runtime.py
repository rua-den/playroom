from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

from .provider import ProviderFailure


@dataclass
class AttemptHandle:
    key: str
    provider: object | None
    request: dict
    cancel_event: threading.Event
    queue: queue.Queue
    done: threading.Event
    release: callable

    def cancel(self) -> None:
        self.cancel_event.set()
        provider = self.provider
        if provider is not None:
            try:
                provider.cancel(self.request)
            except Exception:
                pass


class PhysicalAttemptRegistry:
    """Application-owned physical slot and cancellation registry."""

    def __init__(self, limit: int = 2):
        self._slots = threading.BoundedSemaphore(limit)
        self._handles: dict[str, AttemptHandle] = {}
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._shutdown = threading.Event()

    def _start(self, key: str, provider, request: dict, timeout: float, invoke, provider_factory=None) -> AttemptHandle:
        cancel_event = request.setdefault("cancel_event", threading.Event())
        values: queue.Queue = queue.Queue()
        done = threading.Event()
        deadline = time.monotonic() + timeout
        slot_held = False

        def release():
            nonlocal slot_held
            with self._lock:
                self._handles.pop(key, None)
                if slot_held:
                    slot_held = False
                    self._slots.release()
                self._condition.notify_all()

        handle = AttemptHandle(key, provider, request, cancel_event, values, done, release)
        with self._condition:
            self._handles[key] = handle
            self._condition.notify_all()

        def worker():
            nonlocal slot_held
            try:
                while not self._shutdown.is_set() and not cancel_event.is_set():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return
                    if self._slots.acquire(timeout=min(0.05, remaining)):
                        with self._lock:
                            slot_held = True
                        break
                else:
                    return
                if cancel_event.is_set() or time.monotonic() >= deadline:
                    return
                selected = provider_factory(handle) if provider_factory is not None else provider
                if isinstance(selected, ProviderFailure):
                    values.put(selected)
                    return
                handle.provider = selected
                if cancel_event.is_set() or time.monotonic() >= deadline:
                    handle.cancel()
                    return
                result = invoke(selected)
                if isinstance(result, (str, bytes, ProviderFailure)):
                    values.put(result)
                else:
                    try:
                        iterator = iter(result)
                    except TypeError:
                        values.put(result)
                    else:
                        for item in iterator:
                            values.put(item)
            except Exception:
                values.put(ProviderFailure("PROVIDER_ERROR", "Provider execution failed"))
            finally:
                done.set()
                release()

        threading.Thread(target=worker, name=f"playroom-attempt-{key}", daemon=True).start()
        return handle

    def structured(self, key: str, provider, request: dict, schema: dict, timeout: float, *, provider_factory=None):
        handle = self._start(key, provider, request, timeout, lambda selected: selected.generate_structured(request, schema), provider_factory=provider_factory)
        deadline = time.monotonic() + timeout
        while True:
            if handle.cancel_event.is_set():
                handle.cancel()
                raise TimeoutError("cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                handle.cancel()
                raise TimeoutError("timeout")
            try:
                return handle.queue.get(timeout=min(0.05, remaining))
            except queue.Empty:
                if handle.done.is_set():
                    if handle.cancel_event.is_set():
                        raise TimeoutError("cancelled")
                    if time.monotonic() >= deadline:
                        raise TimeoutError("timeout")
                    return ProviderFailure("MISSING_TERMINAL", "Provider did not return a terminal result")

    def stream(self, key: str, provider, request: dict, timeout: float, *, provider_factory=None):
        handle = self._start(key, provider, request, timeout, lambda selected: selected.generate_text(request), provider_factory=provider_factory)
        deadline = time.monotonic() + timeout
        while True:
            if handle.cancel_event.is_set():
                handle.cancel()
                raise TimeoutError("cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                handle.cancel()
                raise TimeoutError("timeout")
            try:
                yield handle.queue.get(timeout=min(0.05, remaining))
            except queue.Empty:
                if handle.done.is_set() and handle.queue.empty():
                    if handle.cancel_event.is_set():
                        raise TimeoutError("cancelled")
                    if time.monotonic() >= deadline:
                        raise TimeoutError("timeout")
                    return

    def cancel(self, job_id: str) -> None:
        with self._lock:
            handles = [handle for key, handle in self._handles.items() if key.startswith(f"{job_id}:")]
        for handle in handles:
            handle.cancel()

    def cancel_all(self) -> None:
        with self._lock:
            handles = list(self._handles.values())
        for handle in handles:
            handle.cancel()

    def shutdown(self) -> None:
        self._shutdown.set()
        self.cancel_all()

    def wait_registered(self, key: str, timeout: float = 1.0) -> bool:
        deadline = time.monotonic() + timeout
        with self._condition:
            while key not in self._handles:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def active(self) -> int:
        with self._lock:
            return len(self._handles)
