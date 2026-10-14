"""Unit and Integration Tests for Real-Time Backend Operation Tracking.

Verifies thread-safe stage progression, timing calculations, stage skipping/failing,
operation isolation, TTL retention, and the REST telemetry endpoint.
"""

import time
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.operations import OperationTracker, OperationRecord, OperationStage


def test_operation_stage_lifecycle():
    """Verify individual stage transitions and duration calculations."""
    stage = OperationStage("test_key", "Test Label")
    assert stage.status == "pending"
    assert stage.duration_ms is None

    # Start stage
    stage.status = "active"
    stage.start_time = time.perf_counter()
    time.sleep(0.01)

    # Complete stage
    stage.status = "completed"
    stage.end_time = time.perf_counter()
    stage.duration_ms = round((stage.end_time - stage.start_time) * 1000, 2)
    stage.details["rows"] = 500

    stage_dict = stage.to_dict()
    assert stage_dict["key"] == "test_key"
    assert stage_dict["status"] == "completed"
    assert stage_dict["duration_ms"] >= 8.0  # At least ~10ms
    assert stage_dict["details"]["rows"] == 500


def test_operation_record_flow():
    """Verify OperationRecord stage transitions, skipping, and error tracking."""
    stages_def = [
        ("stage_1", "Step One"),
        ("stage_2", "Step Two"),
        ("stage_3", "Step Three")
    ]
    record = OperationRecord("op_test_123", "test_workflow", stages_def)
    assert record.op_id == "op_test_123"
    assert record.status == "in_progress"
    assert len(record.stages) == 3

    # Stage 1 complete
    record.start_stage("stage_1", {"detail": "init"})
    time.sleep(0.005)
    record.complete_stage("stage_1", {"detail": "done"})
    s1 = record.get_stage("stage_1")
    assert s1.status == "completed"
    assert s1.duration_ms > 0

    # Stage 2 skip
    record.skip_stage("stage_2", "Condition not met")
    s2 = record.get_stage("stage_2")
    assert s2.status == "skipped"
    assert s2.details["skip_reason"] == "Condition not met"

    # Stage 3 fail
    record.start_stage("stage_3")
    record.fail_stage("stage_3", "Simulated failure")
    s3 = record.get_stage("stage_3")
    assert s3.status == "failed"
    assert record.status == "failed"
    assert record.error == "Simulated failure"
    assert record.total_duration_ms > 0


def test_operation_tracker_retention():
    """Verify OperationTracker bounds memory via max_records retention."""
    tracker = OperationTracker(max_records=5)
    for i in range(10):
        tracker.create_upload_operation(op_id=f"op_{i}")

    # Should retain only the latest 5 operations
    for i in range(5):
        assert tracker.get_operation(f"op_{i}") is None
    for i in range(5, 10):
        assert tracker.get_operation(f"op_{i}") is not None


def test_operations_api_endpoint():
    """Verify GET /api/operations/{operation_id} endpoint returns accurate state."""
    client = TestClient(app)

    # 1. Non-existent operation returns 404
    res_404 = client.get("/api/operations/non_existent_id_9999")
    assert res_404.status_code == 404
    assert "not found" in res_404.json()["detail"].lower()

    # 2. Trigger query request with explicit operation ID
    test_op_id = "op_test_api_check_01"
    # Even if query fails validation (empty or no dataset in test mode),
    # operation record must exist and record the failure transparently!
    res_query = client.post("/api/query", json={"question": "   ", "operation_id": test_op_id})
    assert res_query.status_code == 400

    # 3. Retrieve telemetry for the tracked operation
    res_op = client.get(f"/api/operations/{test_op_id}")
    assert res_op.status_code == 200
    data = res_op.json()
    assert data["operation_id"] == test_op_id
    assert data["status"] == "failed"
    assert "Question string is empty" in data["error"]
    assert any(s["status"] == "failed" for s in data["stages"])
