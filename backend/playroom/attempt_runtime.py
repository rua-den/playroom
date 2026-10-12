from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

from .provider import ProviderFailure


@dataclass
class AttemptHandle:
    key: str
    provider: object
    request: dict
    cancel_event: threading.Event
    queue: queue.Queue
    done: threading.Event
    release: callable

    def cancel(self) -> None:
        self.cancel_event.set()
        try:
            self.provider.cancel(self.request)
        except Exception:
            pass


class PhysicalAttemptRegistry:
    """Application-owned physical slot and cancellation registry."""

    def __init__(self, limit: int = 2):
        self._slots = threading.BoundedSemaphore(limit)
        self._handles: dict[str, AttemptHandle] = {}
        self._lock = threading.RLock()
        self._shutdown = threading.Event()

    def _start(self, key: str, provider, request: dict, invoke) -> AttemptHandle:
        while not self._shutdown.is_set():
            if self._slots.acquire(timeout=0.05):
                break
        else:
            raise RuntimeError("Attempt registry is shutting down")
        cancel_event = request.setdefault("cancel_event", threading.Event())
        values: queue.Queue = queue.Queue()
        done = threading.Event()

        def release():
            with self._lock:
                self._handles.pop(key, None)
            self._slots.release()

        handle = AttemptHandle(key, provider, request, cancel_event, values, done, release)
        with self._lock:
            self._handles[key] = handle

        def worker():
            try:
                result = invoke()
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
            except Exception as exc:
                values.put(ProviderFailure("PROVIDER_ERROR", "Provider execution failed"))
            finally:
                done.set()
                release()

        threading.Thread(target=worker, name=f"playroom-attempt-{key}", daemon=True).start()
        return handle

    def structured(self, key: str, provider, request: dict, schema: dict, timeout: float):
        handle = self._start(key, provider, request, lambda: provider.generate_structured(request, schema))
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
                    return ProviderFailure("MISSING_TERMINAL", "Provider did not return a terminal result")

    def stream(self, key: str, provider, request: dict, timeout: float):
        handle = self._start(key, provider, request, lambda: provider.generate_text(request))
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

    def active(self) -> int:
        with self._lock:
            return len(self._handles)
