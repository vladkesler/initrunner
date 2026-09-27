"""Tests for the Jev client: SDK responses become dataclasses, SDK errors become JevError."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("typesafe_sdk")

import httpx2
from typesafe_sdk import RetryPolicy, TypeSafeClient

from initrunner.jev import client
from initrunner.jev.client import JevError

_BODY = {
    "model": "jev-1.13.0",
    "answers": {
        "yes": {"type": "noul", "noul": 0.91},
        "pick": {
            "type": "choice",
            "choice": "a",
            "confidence": 0.8,
            "probabilities": {"a": 0.9, "b": 0.1},
        },
        "level": {
            "type": "score",
            "score": 1.2,
            "confidence": 0.7,
            "probabilities": {"0": 0.1, "1": 0.6, "2": 0.3},
            "legend": {"0": "low", "1": "mid", "2": "high"},
        },
    },
    "usage": {"input_tokens": 12, "output_tokens": 3},
}


def _install(monkeypatch, handler) -> list[dict]:
    """Point the shared client at a mock transport; return the captured requests."""
    seen: list[dict] = []

    def _capture(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return handler(request)

    fake = TypeSafeClient(
        api_key="ts_test",
        transport=httpx2.MockTransport(_capture),
        retry=RetryPolicy(max_retries=0),
    )
    monkeypatch.setattr(client, "_client", fake)
    return seen


class TestAsk:
    def test_answers_become_plain_dataclasses(self, monkeypatch):
        seen = _install(
            monkeypatch,
            lambda _r: httpx2.Response(200, json=_BODY, headers={"x-typesafe-request-id": "req_1"}),
        )
        judgment = client.ask({"task": "x"}, {"yes": {"type": "noul", "instructions": "?"}})

        assert judgment.nouls == {"yes": 0.91}
        assert judgment.choices["pick"].choice == "a"
        assert judgment.choices["pick"].probabilities == {"a": 0.9, "b": 0.1}
        assert judgment.scores["level"].probabilities == {0: 0.1, 1: 0.6, 2: 0.3}
        assert judgment.model == "jev-1.13.0"
        assert judgment.request_id == "req_1"
        assert judgment.input_tokens == 12
        assert seen[0]["state"] == {"task": "x"}

    def test_to_dict_keeps_raw_answers(self, monkeypatch):
        _install(monkeypatch, lambda _r: httpx2.Response(200, json=_BODY))
        data = client.ask("x", {"yes": {"type": "noul", "instructions": "?"}}).to_dict()
        assert data["nouls"] == {"yes": 0.91}
        assert data["scores"]["level"]["probabilities"] == {0: 0.1, 1: 0.6, 2: 0.3}
        assert data["model"] == "jev-1.13.0"

    def test_http_error_maps_to_jev_error_with_status(self, monkeypatch):
        _install(
            monkeypatch,
            lambda _r: httpx2.Response(
                401, json={"error": "bad key"}, headers={"x-typesafe-request-id": "req_9"}
            ),
        )
        with pytest.raises(JevError) as exc:
            client.ask("x", {"yes": {"type": "noul", "instructions": "?"}})
        assert exc.value.status == 401
        assert exc.value.request_id == "req_9"

    def test_timeout_does_not_leak_as_timeout_error(self, monkeypatch):
        def _timeout(request):
            raise httpx2.ReadTimeout("slow", request=request)

        _install(monkeypatch, _timeout)
        with pytest.raises(JevError) as exc:
            client.ask("x", {"yes": {"type": "noul", "instructions": "?"}})
        # The executor treats TimeoutError as a failed model call; Jev must not look like one.
        assert not isinstance(exc.value, TimeoutError)
        assert isinstance(exc.value.__cause__, TimeoutError)

    def test_connection_error_maps_to_jev_error(self, monkeypatch):
        def _refused(request):
            raise httpx2.ConnectError("refused", request=request)

        _install(monkeypatch, _refused)
        with pytest.raises(JevError):
            client.ask("x", {"yes": {"type": "noul", "instructions": "?"}})


class TestConfiguration:
    def test_missing_key_raises_jev_error(self):
        # The autouse fixture makes api_key() return None.
        with pytest.raises(JevError, match="TYPESAFE_API_KEY"):
            client.ask("x", {"yes": {"type": "noul", "instructions": "?"}})

    def test_not_configured_without_key(self):
        assert client.is_configured() is False

    def test_configured_with_key_and_extra(self, monkeypatch):
        monkeypatch.setattr(client, "api_key", lambda: "ts_test")
        assert client.is_configured() is True

    def test_not_configured_without_extra(self, monkeypatch):
        monkeypatch.setattr(client, "api_key", lambda: "ts_test")
        monkeypatch.setattr("initrunner._compat.is_extra_installed", lambda extra: False)
        assert client.is_configured() is False

    def test_model_defaults_to_pinned_version(self, monkeypatch):
        monkeypatch.delenv("TYPESAFE_DEFAULT_MODEL", raising=False)
        assert client.model() == "jev-1.13.0"

    def test_model_env_override(self, monkeypatch):
        monkeypatch.setenv("TYPESAFE_DEFAULT_MODEL", "~typesafe/jev-latest")
        assert client.model() == "~typesafe/jev-latest"

    def test_key_is_passed_explicitly_to_the_sdk(self, monkeypatch):
        """A key that only lives in the vault must still reach the SDK."""
        import typesafe_sdk

        captured: dict = {}

        class _Recorder:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def close(self):
                pass

        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        monkeypatch.setattr(client, "api_key", lambda: "ts_from_vault")
        monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", _Recorder)
        client._get_client()
        assert captured["api_key"] == "ts_from_vault"
        assert captured["model"] == client.model()

    def test_reset_drops_the_shared_client(self, monkeypatch):
        monkeypatch.setattr(client, "api_key", lambda: "ts_test")
        first = client._get_client()
        client.reset()
        assert client._get_client() is not first
