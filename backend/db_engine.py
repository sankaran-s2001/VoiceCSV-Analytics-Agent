"""SQLite Database Engine for VoiceCSV Analytics Agent.

Handles CSV parsing, header normalization, safe staging replacement,
schema reflection, and read-only query execution with strict authorization.
"""

import io
import re
import time
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Sequence
import pandas as pd

from backend.config import settings

# Thread lock to prevent race conditions during upload / table replacement
_db_write_lock = threading.Lock()


def normalize_column_name(name: str) -> str:
    """Normalize a single column name into a SQLite-safe identifier.
    
    Rules:
    1. Trim whitespace.
    2. Convert to lowercase.
    3. Replace whitespace and hyphens with underscores.
    4. Remove any non-alphanumeric characters except underscores.
    5. Prefix with 'col_' if it starts with a digit or is empty.
    """
    if not isinstance(name, str):
        name = str(name) if name is not None else "col"
    
    cleaned = name.strip().lower()
    # Replace spaces, hyphens, slashes, and periods with underscores
    cleaned = re.sub(r'[\s\-\/\.]+', '_', cleaned)
    # Remove all characters that are not alphanumeric or underscore
    cleaned = re.sub(r'[^a-z0-9_]', '', cleaned)
    # Collapse multiple consecutive underscores
    cleaned = re.sub(r'_+', '_', cleaned).strip('_')
    
    if not cleaned:
        cleaned = "col"
    elif cleaned[0].isdigit():
        cleaned = f"col_{cleaned}"
        
    return cleaned


def normalize_column_list_with_mapping(columns: List[str]) -> Tuple[List[str], Dict[str, str]]:
    """Normalize headers and return both the unique list and a mapping dict {original: normalized}."""
    normalized = []
    mapping = {}
    seen: Dict[str, int] = {}
    
    for idx, col in enumerate(columns):
        raw_str = str(col).strip() if col is not None else ""
        if not raw_str:
            base = f"col_{idx + 1}"
        else:
            base = normalize_column_name(raw_str)
            if not base:
                base = f"col_{idx + 1}"
            
        if base not in seen:
            seen[base] = 1
            unique_name = base
        else:
            seen[base] += 1
            unique_name = f"{base}_{seen[base]}"
            while unique_name in seen:
                seen[base] += 1
                unique_name = f"{base}_{seen[base]}"
            seen[unique_name] = 1
            
        normalized.append(unique_name)
        mapping[str(col)] = unique_name
        
    return normalized, mapping


def normalize_column_list(columns: List[str]) -> List[str]:
    """Normalize a list of headers ensuring uniqueness without overwriting columns."""
    norm_cols, _ = normalize_column_list_with_mapping(columns)
    return norm_cols


class DatabaseEngine:
    """Manages SQLite ingestion, schema discovery, and safe read-only queries."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.resolved_db_path
        self._init_db()

    def _get_write_connection(self) -> sqlite3.Connection:
        """Get a read-write connection with WAL journal mode for ingestion."""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _init_db(self):
        """Ensure metadata table exists."""
        with _db_write_lock:
            with self._get_write_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS _dataset_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                """)
                conn.commit()

    def get_metadata(self) -> Dict[str, Any]:
        """Fetch saved dataset metadata."""
        try:
            with self._get_write_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT key, value FROM _dataset_metadata")
                rows = cursor.fetchall()
                meta = {}
                for k, v in rows:
                    try:
                        meta[k] = json.loads(v)
                    except (json.JSONDecodeError, TypeError):
                        meta[k] = v
                return meta
        except Exception:
            return {}

    def set_metadata(self, key: str, value: Any):
        """Store dataset metadata value."""
        with _db_write_lock:
            with self._get_write_connection() as conn:
                val_str = json.dumps(value) if not isinstance(value, str) else value
                conn.execute(
                    "INSERT OR REPLACE INTO _dataset_metadata (key, value) VALUES (?, ?)",
                    (key, val_str)
                )
                conn.commit()

    def has_active_dataset(self) -> bool:
        """Check if uploaded_data table exists and has rows."""
        try:
            with self._get_write_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='uploaded_data'"
                )
                if not cursor.fetchone():
                    return False
                cursor.execute("SELECT COUNT(*) FROM uploaded_data")
                row = cursor.fetchone()
                return (row[0] > 0) if row else False
        except Exception:
            return False

    def ingest_csv(
        self,
        file_content: Any,
        original_filename: str = "uploaded_data.csv",
        op_record: Optional[Any] = None,
        filename: Optional[str] = None
    ) -> Dict[str, Any]:
        if filename:
            original_filename = filename
        """Parse CSV bytes, normalize headers, and safely replace uploaded_data.
        
        Guarantees atomicity:
        - Parses and validates CSV in memory / pandas.
        - Loads into _staging_uploaded_data table first.
        - Verifies rows were inserted.
        - Only on success drops old uploaded_data and renames staging.
        - If any error occurs, staging is cleaned up and old table is kept untouched.
        """
        if isinstance(file_content, (str, Path)) and Path(file_content).is_file():
            file_content = Path(file_content).read_bytes()
        elif isinstance(file_content, str):
            file_content = file_content.encode("utf-8")

        if not file_content or not file_content.strip():
            if op_record:
                op_record.fail_stage("receive_validate", "Uploaded file content is empty.")
            raise ValueError("The uploaded CSV is empty (contains no data).")

        if op_record:
            op_record.complete_stage("receive_validate", {"filename": original_filename, "size_bytes": len(file_content)})
            op_record.start_stage("parse_csv")

        # Try multiple encodings with leading zero preservation on sample
        encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']
        df = None
        last_error = None
        detected_enc = 'utf-8'
        
        for enc in encodings:
            try:
                # 1. Sample check to detect string identifier columns with leading zeros (e.g. 00125)
                sample_df = pd.read_csv(io.BytesIO(file_content), nrows=50, encoding=enc, dtype=str)
                dtypes = {}
                for col in sample_df.columns:
                    s = sample_df[col].dropna()
                    if s.str.match(r'^0\d+$').any():
                        dtypes[col] = str

                # 2. Full read with preserved dtypes
                df = pd.read_csv(
                    io.BytesIO(file_content),
                    encoding=enc,
                    dtype=dtypes if dtypes else None,
                    low_memory=False
                )
                detected_enc = enc
                break
            except Exception as e:
                last_error = e

        if df is None:
            if op_record:
                op_record.fail_stage("parse_csv", f"Could not parse CSV: {last_error}")
            raise ValueError(f"Could not parse CSV file. Error: {last_error}")

        if df.empty:
            if op_record:
                op_record.fail_stage("parse_csv", "The uploaded CSV contains no data rows.")
            raise ValueError("The uploaded CSV is empty (contains no data rows).")

        if len(df.columns) == 0:
            if op_record:
                op_record.fail_stage("parse_csv", "The uploaded CSV has no columns.")
            raise ValueError("The uploaded CSV has no columns.")

        if op_record:
            op_record.complete_stage("parse_csv", {
                "detected_encoding": detected_enc,
                "raw_rows": len(df),
                "raw_columns": len(df.columns)
            })
            op_record.start_stage("normalize_headers")

        # Normalize column names and build traceable mapping
        raw_cols = [str(c) for c in df.columns]
        norm_cols, header_mapping = normalize_column_list_with_mapping(raw_cols)
        df.columns = norm_cols

        if op_record:
            op_record.complete_stage("normalize_headers", {
                "column_count": len(norm_cols),
                "sample_mapping": dict(list(header_mapping.items())[:6])
            })
            op_record.start_stage("profile_data")

        # Clean NaN and inf values to Python None for SQLite NULL
        df = df.replace([float('inf'), float('-inf')], None)
        df = df.where(pd.notnull(df), None)

        total_rows = len(df)
        total_cols = len(norm_cols)

        # Count missing values per column for data quality
        quality_info = {}
        for col in norm_cols:
            null_count = int(df[col].isnull().sum())
            quality_info[col] = {
                "null_count": null_count,
                "null_percentage": round((null_count / total_rows) * 100, 2) if total_rows > 0 else 0
            }

        if op_record:
            op_record.complete_stage("profile_data", {
                "columns_profiled": total_cols,
                "null_columns_count": sum(1 for q in quality_info.values() if q["null_count"] > 0)
            })
            op_record.start_stage("stage_sqlite")

        # Safe atomic staging replacement
        with _db_write_lock:
            conn = self._get_write_connection()
            try:
                # 1. Clean up any existing staging table
                conn.execute("DROP TABLE IF EXISTS _staging_uploaded_data")
                conn.commit()

                # 2. Write to staging table using pandas to_sql
                df.to_sql(
                    name="_staging_uploaded_data",
                    con=conn,
                    if_exists="replace",
                    index=False,
                    chunksize=5000
                )

                # 3. Verify staging table row count
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM _staging_uploaded_data")
                staged_count = cur.fetchone()[0]
                if staged_count != total_rows:
                    raise RuntimeError(
                        f"Staging verification failed: expected {total_rows} rows, got {staged_count}"
                    )

                if op_record:
                    op_record.complete_stage("stage_sqlite", {"staged_rows": staged_count})
                    op_record.start_stage("verify_swap")

                # 4. Atomic table swap
                conn.execute("DROP TABLE IF EXISTS uploaded_data")
                conn.execute("ALTER TABLE _staging_uploaded_data RENAME TO uploaded_data")
                
                # 5. Save metadata
                upload_time = datetime.utcnow().isoformat() + "Z"
                meta_payload = {
                    "filename": original_filename,
                    "table_name": "uploaded_data",
                    "row_count": total_rows,
                    "column_count": total_cols,
                    "columns": norm_cols,
                    "header_mapping": header_mapping,
                    "upload_time": upload_time,
                    "quality": quality_info
                }
                conn.execute(
                    "INSERT OR REPLACE INTO _dataset_metadata (key, value) VALUES ('dataset', ?)",
                    (json.dumps(meta_payload),)
                )
                conn.commit()

                if op_record:
                    op_record.complete_stage("verify_swap", {"active_table": "uploaded_data"})
                    op_record.finish({
                        "filename": original_filename,
                        "row_count": total_rows,
                        "column_count": total_cols
                    })

            except Exception as e:
                conn.rollback()
                try:
                    conn.execute("DROP TABLE IF EXISTS _staging_uploaded_data")
                    conn.commit()
                except Exception:
                    pass
                if op_record:
                    op_record.fail_stage("verify_swap", f"Database swap failed: {e}")
                raise RuntimeError(f"Database loading failed: {e}") from e
            finally:
                conn.close()

        # Build preview of first 5 rows
        preview = self.get_preview_rows(limit=5)
        schema_info = self.get_schema_info()

        return {
            "status": "success",
            "filename": original_filename,
            "table_name": "uploaded_data",
            "row_count": total_rows,
            "column_count": total_cols,
            "columns": schema_info.get("columns", []),
            "header_mapping": header_mapping,
            "preview": preview,
            "quality": quality_info,
            "message": f"Successfully loaded {total_rows:,} rows across {total_cols} columns into uploaded_data."
        }

    def get_schema_info(self) -> Dict[str, Any]:
        """Inspect actual SQLite table schema using PRAGMA table_info."""
        if not self.has_active_dataset():
            return {
                "is_loaded": False,
                "message": "No active dataset loaded in database."
            }

        with self._get_write_connection() as conn:
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(uploaded_data)")
            col_rows = cur.fetchall()
            
            cur.execute("SELECT COUNT(*) FROM uploaded_data")
            total_rows = cur.fetchone()[0]

            meta = self.get_metadata().get("dataset", {})
            quality_map = meta.get("quality", {})
            filename = meta.get("filename", "uploaded_dataset.csv")

            columns_desc = []
            for col in col_rows:
                # cid, name, type, notnull, dflt_value, pk
                c_name = col[1]
                c_type = col[2] or "TEXT"
                q = quality_map.get(c_name, {})
                columns_desc.append({
                    "name": c_name,
                    "type": c_type.upper(),
                    "null_count": q.get("null_count", 0),
                    "null_percentage": q.get("null_percentage", 0.0)
                })

        preview = self.get_preview_rows(limit=5)

        # Build concise schema prompt context for Gemini
        schema_lines = [f"Table: uploaded_data (Total Rows: {total_rows:,})", "Columns:"]
        for c in columns_desc:
            schema_lines.append(f"  - {c['name']} ({c['type']})")

        sample_lines = ["Sample records (first 3 rows):"]
        for row in preview[:3]:
            sample_lines.append(f"  {json.dumps(row)}")

        schema_context = "\n".join(schema_lines) + "\n\n" + "\n".join(sample_lines)

        return {
            "is_loaded": True,
            "filename": filename,
            "table_name": "uploaded_data",
            "row_count": total_rows,
            "column_count": len(columns_desc),
            "columns": columns_desc,
            "header_mapping": meta.get("header_mapping", {}),
            "quality": quality_map,
            "preview": preview,
            "schema_context": schema_context
        }

    def get_preview_rows(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Fetch sample rows safely for UI display."""
        if not self.has_active_dataset():
            return []

        with self._get_write_connection() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(f"SELECT * FROM uploaded_data LIMIT {int(limit)}")
            rows = cur.fetchall()
            return [dict(r) for r in rows]

    def execute_query_readonly(
        self,
        sql: str,
        params: Sequence[Any] = (),
        max_rows: Optional[int] = None,
        timeout_seconds: Optional[int] = None
    ) -> Dict[str, Any]:
        """Execute query strictly read-only with SQLite authorizer and timeout.
        
        Security controls:
        - Opened via SQLite URI mode 'ro' (read-only).
        - PRAGMA query_only = ON.
        - Authorizer callback blocks INSERT, UPDATE, DELETE, DROP, ALTER, ATTACH, DETACH, PRAGMA.
        - Authorizer restricts table reads strictly to 'uploaded_data'.
        - Progress handler enforces configurable query timeout.
        - Results capped at max_rows without altering original SQL logic.
        """
        if not self.has_active_dataset():
            raise RuntimeError("Cannot execute query: no active dataset is loaded.")

        max_rows = max_rows or settings.max_query_rows
        timeout_seconds = timeout_seconds or settings.query_timeout_seconds

        # Resolve URI path for read-only connection
        db_uri = f"file:{self.db_path.as_posix()}?mode=ro"

        # Authorizer to reject any mutating operations
        def authorizer(action, arg1, arg2, dbname, source):
            # Allowed actions for read-only analytics
            if action == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            elif action == sqlite3.SQLITE_READ:
                # arg1 is table name, arg2 is column name
                # Allow reading only from uploaded_data and temp/schema internals
                allowed = {"uploaded_data", "sqlite_master", "sqlite_temp_master"}
                if arg1 and arg1.lower() not in allowed:
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            elif action == sqlite3.SQLITE_FUNCTION:
                # Built-in functions like ROUND, SUM, COUNT, AVG, etc.
                return sqlite3.SQLITE_OK
            
            # Explicitly deny all writes, drops, alters, pragma, attach, etc.
            return sqlite3.SQLITE_DENY

        conn = sqlite3.connect(db_uri, uri=True, timeout=1.0)
        start_time = time.perf_counter()

        try:
            # Enforce read-only at SQLite engine level
            conn.execute("PRAGMA query_only = ON")
            conn.set_authorizer(authorizer)

            # Query timeout enforcement using progress handler (every 1000 opcodes)
            deadline = time.time() + timeout_seconds

            def progress_callback():
                if time.time() > deadline:
                    return 1  # non-zero aborts query with sqlite3.OperationalError: interrupted
                return 0

            conn.set_progress_handler(progress_callback, 1000)

            cursor = conn.cursor()
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)

            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            
            # Fetch up to max_rows + 1 to detect truncation
            fetched_rows = cursor.fetchmany(max_rows + 1)
            is_capped = False
            if len(fetched_rows) > max_rows:
                is_capped = True
                fetched_rows = fetched_rows[:max_rows]

            execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

            # Convert row tuples to list of lists with clean JSON-safe types
            clean_rows = []
            for row in fetched_rows:
                row_vals = []
                for val in row:
                    if val is None:
                        row_vals.append(None)
                    elif isinstance(val, (int, float, str, bool)):
                        row_vals.append(val)
                    else:
                        row_vals.append(str(val))
                clean_rows.append(row_vals)

            return {
                "columns": columns,
                "rows": clean_rows,
                "row_count": len(clean_rows),
                "is_capped": is_capped,
                "max_rows": max_rows,
                "execution_time_ms": execution_time_ms
            }

        except sqlite3.OperationalError as e:
            if "interrupted" in str(e).lower():
                raise TimeoutError(f"Query timed out after {timeout_seconds} seconds.") from e
            raise
        finally:
            conn.close()

    def get_dataset_preview(
        self,
        offset: int = 0,
        limit: int = 50,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_order: str = "asc"
    ) -> Dict[str, Any]:
        """Retrieve paginated, searchable, sortable records from active uploaded_data."""
        if not self.has_active_dataset():
            raise RuntimeError("Cannot preview dataset: no active dataset is loaded.")

        schema_info = self.get_schema_info()
        columns_meta = schema_info.get("columns", [])
        valid_cols = [c["name"] for c in columns_meta]
        total_rows = schema_info.get("row_count", 0)
        filename = schema_info.get("filename", "uploaded_data.csv")

        # Validate offset & limit
        offset = max(0, int(offset))
        limit = max(1, min(int(limit), 200))

        # Validate sorting
        sort_order = (sort_order or "asc").strip().lower()
        if sort_order not in ("asc", "desc"):
            sort_order = "asc"

        sort_sql = "rowid ASC"
        if sort_by and sort_by.strip():
            sort_col = sort_by.strip()
            if sort_col not in valid_cols:
                raise ValueError(f"Invalid sort column: '{sort_col}' does not exist in dataset.")
            # Safe double-quoted identifier to prevent injection
            sort_sql = f'"{sort_col}" {sort_order.upper()}, rowid ASC'

        # Build search condition
        where_clauses = []
        search_params: List[Any] = []
        if search and search.strip():
            term = search.strip()
            # Escape LIKE wildcards % and _ and backslash
            escaped_term = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like_val = f"%{escaped_term}%"
            # Build search condition across all column text representations
            col_search = [f'CAST("{col}" AS TEXT) LIKE ? ESCAPE "\\"' for col in valid_cols]
            if col_search:
                where_clauses.append(f"({' OR '.join(col_search)})")
                search_params = [like_val] * len(valid_cols)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # 1. Total filtered count
        count_sql = f"SELECT COUNT(*) FROM uploaded_data {where_sql};"
        count_res = self.execute_query_readonly(count_sql, params=search_params)
        filtered_total = count_res["rows"][0][0] if count_res["rows"] else 0

        # 2. Paginated rows
        data_sql = f'SELECT * FROM uploaded_data {where_sql} ORDER BY {sort_sql} LIMIT ? OFFSET ?;'
        data_params = search_params + [limit, offset]
        data_res = self.execute_query_readonly(data_sql, params=data_params, max_rows=limit)

        return {
            "status": "success",
            "filename": filename,
            "total_rows": total_rows,
            "filtered_total_rows": filtered_total,
            "total_columns": len(valid_cols),
            "offset": offset,
            "limit": limit,
            "returned_rows": len(data_res["rows"]),
            "search": search or "",
            "sort_by": sort_by if sort_by in valid_cols else None,
            "sort_order": sort_order,
            "columns": [{"name": c["name"], "type": c["type"]} for c in columns_meta],
            "rows": data_res["rows"],
            "execution_time_ms": data_res["execution_time_ms"]
        }


# Global database engine instance
db_engine = DatabaseEngine()
