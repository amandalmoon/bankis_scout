import base64
import json

import pytest

from bankis_scout.cloud_delivery import publish_receipt, restore


def test_previous_evidence_restore_and_invalid_snapshot(tmp_path):
    state = tmp_path / "data/cloud_state"
    state.mkdir(parents=True)
    (state / "previous.json").write_text('{"observations": []}')
    stamp = "20261009T080000000000"
    (state / "previous_id").write_text(stamp)
    restore(tmp_path)
    assert (tmp_path / "reports/published/CURRENT").read_text() == stamp
    assert (tmp_path / "reports/runs" / stamp / "intelligence.json").exists()
    (state / "previous_id").write_text("../../private")
    with pytest.raises(ValueError):
        restore(tmp_path)


def test_running_or_failed_receipt_cannot_reuse_old_artifact(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "amandalmoon/bankis_scout")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    monkeypatch.setenv("GITHUB_TOKEN", "fake-secret")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    bodies = []
    class Response:
        status_code = 200
        def json(self):
            return {"sha": "oldsha"}
    class Session:
        headers = {}
        def get(self, *args, **kwargs):
            return Response()
        def put(self, endpoint, **kwargs):
            bodies.append(json.loads(base64.b64decode(kwargs["json"]["content"])))
            return Response()
    monkeypatch.setattr("bankis_scout.cloud_delivery.requests.Session", Session)
    for status in ("RUNNING", "FAILED"):
        publish_receipt(tmp_path, status)
    assert all(row["artifact_id"] is None for row in bodies)
    assert "fake-secret" not in json.dumps(bodies)
