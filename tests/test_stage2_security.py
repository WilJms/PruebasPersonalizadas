from __future__ import annotations

from fastapi.testclient import TestClient

from comprehension_verification.web.app import create_app
from comprehension_verification.web.rate_limit import FixedWindowRateLimiter
from comprehension_verification.web.settings import Settings


def test_rate_limiter_is_bounded_and_reports_retry_delay(monkeypatch) -> None:
    clock = iter((0.0, 0.1, 0.2, 61.0))
    monkeypatch.setattr(
        "comprehension_verification.web.rate_limit.monotonic",
        lambda: next(clock),
    )
    limiter = FixedWindowRateLimiter(window_seconds=60, max_keys=2)

    assert limiter.consume("tenant:user", limit=2) == (True, 0)
    assert limiter.consume("tenant:user", limit=2) == (True, 0)
    allowed, retry_after = limiter.consume("tenant:user", limit=2)
    assert allowed is False
    assert 59 <= retry_after <= 60
    assert limiter.consume("tenant:user", limit=2) == (True, 0)


def test_private_api_rate_limit_fails_closed_without_logging_payload() -> None:
    settings = Settings(
        environment="test",
        database_url="sqlite+pysqlite://",
        session_secret="stage2-rate-limit-test-secret-long-enough",
        api_mutation_rate_limit_per_minute=10,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        responses = [
            client.post(
                "/api/v1/session/login",
                json={"email": "teacher@example.test"},
            )
            for _ in range(12)
        ]

    assert all(response.status_code == 200 for response in responses[:11])
    limited = responses[-1]
    assert limited.status_code == 429
    assert limited.json()["code"] == "RATE_LIMITED"
    assert limited.json()["retryable"] is True
    assert int(limited.headers["Retry-After"]) >= 1
    assert limited.headers["Content-Security-Policy"].startswith("default-src")
