"""Real-Time Backend Operation Tracking & Observability.

Provides thread-safe stage-by-stage telemetry for CSV upload and natural
language query workflows. Exposes operation state via REST API for honest,
backend-driven frontend progress display.
"""

import time
import uuid
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional


class OperationStage:
    """Individual stage within an operation workflow."""

    def __init__(self, key: str, label: str):
        self.key = key
        self.label = label
        self.status = "pending"  # pending, active, completed, skipped, failed
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.duration_ms: Optional[float] = None
        self.details: Dict[str, Any] = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "details": self.details
        }


class OperationRecord:
    """Complete workflow record containing pre-registered stages and metrics."""

    def __init__(self, op_id: str, op_type: str, stages_def: List[tuple]):
        self.op_id = op_id
        self.op_type = op_type
        self.status = "in_progress"  # in_progress, completed, failed
        self.created_at = datetime.utcnow().isoformat() + "Z"
        self.start_perf = time.perf_counter()
        self.end_perf: Optional[float] = None
        self.total_duration_ms: Optional[float] = None
        self.error: Optional[str] = None
        self.stages: List[OperationStage] = [
            OperationStage(key, label) for key, label in stages_def
        ]
        self.metadata: Dict[str, Any] = {}

    def get_stage(self, stage_key: str) -> Optional[OperationStage]:
        for s in self.stages:
            if s.key == stage_key:
                return s
        return None

    def start_stage(self, stage_key: str, details: Optional[Dict[str, Any]] = None):
        stage = self.get_stage(stage_key)
        if stage:
            stage.status = "active"
            stage.start_time = time.perf_counter()
            if details:
                stage.details.update(details)

    def complete_stage(self, stage_key: str, details: Optional[Dict[str, Any]] = None):
        stage = self.get_stage(stage_key)
        if stage:
            stage.status = "completed"
            stage.end_time = time.perf_counter()
            if stage.start_time is not None:
                stage.duration_ms = round((stage.end_time - stage.start_time) * 1000, 2)
            else:
                stage.duration_ms = 0.0
            if details:
                stage.details.update(details)

    def skip_stage(self, stage_key: str, reason: str = "Not needed"):
        stage = self.get_stage(stage_key)
        if stage:
            stage.status = "skipped"
            stage.duration_ms = 0.0
            stage.details["skip_reason"] = reason

    def fail_stage(self, stage_key: str, error_message: str):
        stage = self.get_stage(stage_key)
        if stage:
            stage.status = "failed"
            stage.end_time = time.perf_counter()
            if stage.start_time is not None:
                stage.duration_ms = round((stage.end_time - stage.start_time) * 1000, 2)
            stage.details["error"] = error_message
        self.status = "failed"
        self.error = error_message
        self.end_perf = time.perf_counter()
        self.total_duration_ms = round((self.end_perf - self.start_perf) * 1000, 2)

    def finish(self, metadata: Optional[Dict[str, Any]] = None):
        self.status = "completed"
        self.end_perf = time.perf_counter()
        self.total_duration_ms = round((self.end_perf - self.start_perf) * 1000, 2)
        if metadata:
            self.metadata.update(metadata)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation_id": self.op_id,
            "operation_type": self.op_type,
            "status": self.status,
            "created_at": self.created_at,
            "total_duration_ms": self.total_duration_ms or round((time.perf_counter() - self.start_perf) * 1000, 2),
            "error": self.error,
            "stages": [s.to_dict() for s in self.stages],
            "metadata": self.metadata
        }


class OperationTracker:
    """Thread-safe store of operations with TTL cleanup."""

    # Stage definitions for workflows
    UPLOAD_STAGES = [
        ("receive_validate", "File Validation & Limits Check"),
        ("parse_csv", "CSV Parsing & Encoding Detection"),
        ("normalize_headers", "Header Normalization & Unique Mapping"),
        ("profile_data", "Data Profiling & Missing Values"),
        ("stage_sqlite", "SQLite Staging & Row Verification"),
        ("verify_swap", "Atomic Table Swap & Metadata Save")
    ]

    RELATIONAL_UPLOAD_STAGES = [
        ("receive_validate", "Batch Files Validation & Limits Check"),
        ("parse_csvs", "Multi-CSV Parsing & Encoding Detection"),
        ("normalize_schemas", "Schema Normalization & Identifier Check"),
        ("stage_tables", "SQLite Multi-Table Staging"),
        ("validate_keys", "Primary Key & Foreign Key Discovery"),
        ("build_indexes", "Relational Index Creation & Query Optimization"),
        ("activate_workspace", "Workspace Activation & Relationship Registration")
    ]

    QUERY_STAGES = [
        ("validate_request", "Question Validation & Dataset Check"),
        ("reflect_schema", "Schema Reflection & Prompt Construction"),
        ("gemini_sql", "Gemini SQL Synthesis"),
        ("safety_check", "Read-Only Security Safeguards Check"),
        ("execute_query", "SQLite Read-Only Execution"),
        ("self_heal", "SQL Self-Healing (Bounded Repair)"),
        ("gemini_summary", "Executive Business Summary Synthesis"),
        ("serialize_response", "Result Formatting & Delivery")
    ]

    def __init__(self, max_records: int = 100):
        self._lock = threading.Lock()
        self._operations: Dict[str, OperationRecord] = {}
        self._max_records = max_records

    def create_upload_operation(self, op_id: Optional[str] = None) -> OperationRecord:
        op_id = op_id or f"op_upload_{uuid.uuid4().hex[:8]}"
        with self._lock:
            self._prune_old()
            record = OperationRecord(op_id, "upload", self.UPLOAD_STAGES)
            self._operations[op_id] = record
            return record

    def create_relational_upload_operation(self, op_id: Optional[str] = None) -> OperationRecord:
        op_id = op_id or f"op_relupload_{uuid.uuid4().hex[:8]}"
        with self._lock:
            self._prune_old()
            record = OperationRecord(op_id, "relational_upload", self.RELATIONAL_UPLOAD_STAGES)
            self._operations[op_id] = record
            return record

    def create_query_operation(self, op_id: Optional[str] = None) -> OperationRecord:
        op_id = op_id or f"op_query_{uuid.uuid4().hex[:8]}"
        with self._lock:
            self._prune_old()
            record = OperationRecord(op_id, "query", self.QUERY_STAGES)
            self._operations[op_id] = record
            return record

    def get_operation(self, op_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            record = self._operations.get(op_id)
            return record.to_dict() if record else None

    def get_record(self, op_id: str) -> Optional[OperationRecord]:
        with self._lock:
            return self._operations.get(op_id)

    def _prune_old(self):
        """Keep memory bounded to max_records."""
        while len(self._operations) >= self._max_records:
            oldest_key = next(iter(self._operations))
            self._operations.pop(oldest_key, None)


# Global tracker instance
operation_tracker = OperationTracker()
