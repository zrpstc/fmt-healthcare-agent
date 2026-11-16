from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
import app.consumer_api as consumer_api
from wgs_fmt_platform.infrastructure.database import (
    AuthSession,
    ConsumerGlossaryReview,
    ConsumerShareLink,
    SessionLocal,
    User,
    hash_password,
)


SAMPLE = "CONSUMER_API_TEST"


def _fake_report() -> dict:
    return {
        "schema_version": "consumer-report/1",
        "sample": {
            "sample_id": SAMPLE,
            "alias": "样本 TEST",
            "report_date": "2026-11-16",
            "generated_at": "2026-11-16T00:00:00Z",
            "source_report_sha256": "a" * 64,
            "builder_version": "consumer-web-builder-v1",
        },
        "summary": {"headline": "测试", "headline_source": "rule", "status_cards": [], "key_findings": []},
        "sections": [],
        "actions": [],
        "retest": None,
        "red_flags": [],
        "glossary": [],
        "references": [],
        "omissions": [],
        "methods": [],
        "downloads": [],
    }


def _user_with_token(role: str) -> tuple[str, str]:
    username = f"consumer-test-{secrets.token_hex(6)}"
    with SessionLocal() as session:
        user = User(
            username=username,
            email=f"{username}@example.test",
            password_hash=hash_password("consumer-test-password"),
            display_name=username,
            role=role,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        token = secrets.token_urlsafe(32)
        session.add(AuthSession(
            user_id=user.id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(days=1),
        ))
        session.commit()
    return token, user.id


def _make_link(token: str, *, expires_at: datetime, revoked_at: datetime | None = None) -> str:
    with SessionLocal() as session:
        link = ConsumerShareLink(
            sample_id=SAMPLE,
            token_sha256=hashlib.sha256(token.encode()).hexdigest(),
            created_by="test",
            expires_at=expires_at,
            revoked_at=revoked_at,
        )
        session.add(link)
        session.commit()
        session.refresh(link)
        return link.id


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(consumer_api, "_report_for", lambda sample_id, refresh=False, allow_pending=None: _fake_report())
    monkeypatch.setattr(consumer_api, "_public_report", lambda sample_id, refresh=False: _fake_report())
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def cleanup():
    yield
    with SessionLocal() as session:
        session.query(ConsumerShareLink).filter(ConsumerShareLink.sample_id == SAMPLE).delete()
        session.commit()


def test_viewer_cannot_create_share(client):
    token, _ = _user_with_token("viewer")
    response = client.post(
        f"/api/reports/{SAMPLE}/consumer/share",
        json={"expires_days": 30},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_researcher_can_create_and_list_share(client):
    token, _ = _user_with_token("researcher")
    created = client.post(
        f"/api/reports/{SAMPLE}/consumer/share",
        json={"expires_days": 30},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["token"]
    assert body["url"].startswith("/share/")
    listed = client.get(
        f"/api/reports/{SAMPLE}/consumer/shares",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listed.status_code == 200
    assert listed.json()["shares"]


def test_public_share_json_has_no_real_sample_id_or_server_path(client):
    share_token = secrets.token_urlsafe(32)
    _make_link(share_token, expires_at=datetime.now(UTC) + timedelta(days=1))
    response = client.get(f"/api/share/{share_token}")
    assert response.status_code == 200
    assert response.headers.get("X-Robots-Tag") == "noindex"
    payload = response.text
    assert SAMPLE not in payload
    assert "127.0.0.1" not in payload
    assert "storageB" not in payload
    assert response.json()["sample"]["sample_id"] == "样本 TEST"


def test_expired_token_is_rejected(client):
    token = secrets.token_urlsafe(32)
    _make_link(token, expires_at=datetime.now(UTC) - timedelta(minutes=1))
    response = client.get(f"/api/share/{token}")
    assert response.status_code == 404


def test_revoked_token_is_rejected(client):
    token = secrets.token_urlsafe(32)
    _make_link(token, expires_at=datetime.now(UTC) + timedelta(days=1), revoked_at=datetime.now(UTC))
    response = client.get(f"/api/share/{token}")
    assert response.status_code == 404


def test_wrong_token_is_rejected(client):
    response = client.get("/api/share/not-a-real-token")
    assert response.status_code == 404


def test_glossary_review_queue_and_approval(client):
    researcher, _ = _user_with_token("researcher")
    queue = client.get("/api/consumer/glossary/review", headers={"Authorization": f"Bearer {researcher}"})
    assert queue.status_code == 200
    entries = queue.json()["entries"]
    assert entries
    entry = entries[0]
    response = client.post(
        f"/api/consumer/glossary/review/{entry['term_id']}",
        json={"field": entry["field"], "status": "approved", "text": "审核后的解释。"},
        headers={"Authorization": f"Bearer {researcher}"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    with SessionLocal() as session:
        session.query(ConsumerGlossaryReview).filter(ConsumerGlossaryReview.term_id == entry["term_id"]).delete()
        session.commit()


def test_revoke_link(client):
    researcher, _ = _user_with_token("researcher")
    token = secrets.token_urlsafe(32)
    link_id = _make_link(token, expires_at=datetime.now(UTC) + timedelta(days=1))
    response = client.delete(
        f"/api/reports/{SAMPLE}/consumer/shares/{link_id}",
        headers={"Authorization": f"Bearer {researcher}"},
    )
    assert response.status_code == 200
    assert client.get(f"/api/share/{token}").status_code == 404
