from __future__ import annotations

import os
from contextlib import contextmanager
from functools import wraps
from typing import Any


class _NoopObservation:
    def update(self, **kwargs: Any) -> None:
        return None


class _NoopClient:
    @contextmanager
    def start_as_current_observation(self, **kwargs: Any):
        yield _NoopObservation()

    def update_current_span(self, **kwargs: Any) -> None:
        return None

    def update_current_generation(self, **kwargs: Any) -> None:
        return None

try:
    from langfuse import get_client, observe, propagate_attributes

    LANGFUSE_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - chỉ dùng khi chưa cài requirements
    LANGFUSE_SDK_AVAILABLE = False

    def observe(*args: Any, **kwargs: Any):
        def decorator(func):
            return func

        return decorator

    _DummyClient = _NoopClient

    def get_client():
        return _DummyClient()

    @contextmanager
    def propagate_attributes(**kwargs: Any):
        yield


def get_langfuse_client():
    return get_client() if tracing_enabled() else _NoopClient()


def instrumented_observe(*args: Any, **kwargs: Any):
    if tracing_enabled():
        return observe(*args, **kwargs)

    def decorator(func):
        @wraps(func)
        def call_without_tracing(*func_args, **func_kwargs):
            return func(*func_args, **func_kwargs)

        return call_without_tracing

    return decorator


@contextmanager
def instrumented_propagate_attributes(**kwargs: Any):
    if tracing_enabled():
        with propagate_attributes(**kwargs):
            yield
        return
    yield


def tracing_enabled() -> bool:
    return LANGFUSE_SDK_AVAILABLE and bool(
        os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")
    )
