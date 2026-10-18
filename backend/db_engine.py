import io
import re
import time
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Sequence, Set
import pandas as pd

from backend.config import settings

# Thread lock to prevent race conditions during upload / table replacement
_db_write_lock = threading.Lock()

RESERVED_TABLE_PREFIXES = ("sqlite_", "_staging_", "_dataset_metadata")


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
    cleaned = re.sub(r'[\s\-\/\.]+', '_', cleaned)
    cleaned = re.sub(r'[^a-z0-9_]', '', cleaned)
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


def normalize_table_name(name: str) -> str:
    """Normalize a filename or raw table string into a safe, valid SQLite table identifier."""
    if not isinstance(name, str):
        name = str(name) if name is not None else "table"
    cleaned = name.strip()
    if cleaned.lower().endswith(".csv"):
        cleaned = cleaned[:-4]
    cleaned = cleaned.lower()
    cleaned = re.sub(r'[\s\-\/\.]+', '_', cleaned)
    cleaned = re.sub(r'[^a-z0-9_]', '', cleaned)
    cleaned = re.sub(r'_+', '_', cleaned)
    
    is_reserved = any(
        cleaned.startswith(pref) or cleaned.strip('_').startswith(pref.strip('_'))
        for pref in RESERVED_TABLE_PREFIXES
    )
    cleaned = cleaned.strip('_')
    if not cleaned:
        cleaned = "table_1"
    elif cleaned[0].isdigit():
        cleaned = f"tbl_{cleaned}"
    elif is_reserved:
        cleaned = f"tbl_{cleaned}"
    return cleaned


class DatabaseEngine:
    """Manages SQLite ingestion, schema discovery, and safe read-only queries.
    
    Supports both:
    - Mode A: Single-table analytics ('uploaded_data')
    - Mode B: Multi-table relational analytics with verified foreign keys and joins
    """

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

    def get_active_workspace_mode(self) -> str:
        """Return the active workspace mode: 'single', 'relational', or 'none'."""
        meta = self.get_metadata()
        mode = meta.get("active_workspace_mode")
        if mode in ("single", "relational"):
            return mode
        if meta.get("relational_workspace"):
            return "relational"
        if self._table_has_rows("uploaded_data"):
            return "single"
        return "none"

    def set_active_workspace_mode(self, mode: str):
        """Set the active workspace mode ('single', 'relational', or 'none')."""
        if mode not in ("single", "relational", "none"):
            raise ValueError(f"Invalid workspace mode: {mode}")
        self.set_metadata("active_workspace_mode", mode)

    def _table_has_rows(self, table_name: str) -> bool:
        """Check if a table exists in SQLite and contains at least one row."""
        try:
            with self._get_write_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table_name,)
                )
                if not cursor.fetchone():
                    return False
                cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
                row = cursor.fetchone()
                return (row[0] > 0) if row else False
        except Exception:
            return False

    def get_active_tables(self) -> List[str]:
        """Return list of table names in the currently active workspace."""
        mode = self.get_active_workspace_mode()
        if mode == "relational":
            meta = self.get_metadata().get("relational_workspace", {})
            tables = meta.get("tables", {})
            return list(tables.keys())
        elif mode == "single":
            if self._table_has_rows("uploaded_data"):
                return ["uploaded_data"]
            return []
        else:
            if self._table_has_rows("uploaded_data"):
                return ["uploaded_data"]
            meta = self.get_metadata().get("relational_workspace", {})
            tables = meta.get("tables", {})
            if tables:
                return list(tables.keys())
            return []

    def get_allowed_tables(self) -> Set[str]:
        """Return set of table names permitted for querying in the current workspace."""
        return set(self.get_active_tables())

    def has_active_dataset(self) -> bool:
        """Check if the active workspace has loaded data."""
        tables = self.get_active_tables()
        if not tables:
            return False
        return any(self._table_has_rows(t) for t in tables)

    def get_active_currencies(self) -> List[str]:
        """Retrieve list of distinct currency codes across active tables containing a 'currency' column."""
        tables = self.get_active_tables()
        if not tables:
            return []
            
        currencies: Set[str] = set()
        with self._get_write_connection() as conn:
            cursor = conn.cursor()
            for tbl in tables:
                cursor.execute(f'PRAGMA table_info("{tbl}")')
                cols = [row[1].lower() for row in cursor.fetchall()]
                if "currency" in cols:
                    try:
                        cursor.execute(f'SELECT DISTINCT "currency" FROM "{tbl}" WHERE "currency" IS NOT NULL AND "currency" != \'\'')
                        for row in cursor.fetchall():
                            if row[0]:
                                currencies.add(str(row[0]).strip().upper())
                    except Exception as e:
                        logger.warning("Error fetching currencies from %s: %s", tbl, e)
                        
        return sorted(list(currencies))

    def discover_and_verify_relationships(
        self,
        conn: sqlite3.Connection,
        table_names: List[str]
    ) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
        """Discover primary keys and verify foreign key relationships across staged or active tables."""
        cur = conn.cursor()
        pks: Dict[str, str] = {}
        table_cols: Dict[str, List[str]] = {}

        # 1. Discover Primary Keys for each table
        for tbl in table_names:
            cur.execute(f'PRAGMA table_info("{tbl}")')
            col_info = cur.fetchall()
            cols = [c[1] for c in col_info]
            table_cols[tbl] = cols

            # Candidate priority:
            # 1. {tbl}_id or {singular}_id
            # 2. 'id'
            # 3. Any column ending with '_id'
            singular = tbl[:-1] if tbl.endswith('s') else tbl
            candidates = [f"{tbl}_id", f"{singular}_id", "id"] + [c for c in cols if c.endswith("_id")]
            candidate_pks = [c for c in candidates if c in cols]

            verified_pk = None
            for cand in candidate_pks:
                cur.execute(f"""
                    SELECT 
                        COUNT(*), 
                        COUNT(DISTINCT "{cand}"),
                        SUM(CASE WHEN "{cand}" IS NULL THEN 1 ELSE 0 END)
                    FROM "{tbl}"
                """)
                total_cnt, distinct_cnt, null_cnt = cur.fetchone()
                if total_cnt > 0 and distinct_cnt == total_cnt and (null_cnt or 0) == 0:
                    verified_pk = cand
                    break

            if verified_pk:
                pks[tbl] = verified_pk

        # 2. Discover Foreign Key Links
        relationships: List[Dict[str, Any]] = []
        for child_tbl in table_names:
            child_c = table_cols.get(child_tbl, [])
            for parent_tbl, parent_pk in pks.items():
                if child_tbl == parent_tbl:
                    continue
                # If the parent PK exists in child table, check relationship integrity
                if parent_pk in child_c:
                    cur.execute(f"""
                        SELECT 
                            COUNT(DISTINCT c."{parent_pk}"),
                            SUM(CASE WHEN c."{parent_pk}" IS NULL THEN 1 ELSE 0 END)
                        FROM "{child_tbl}" c
                        WHERE c."{parent_pk}" IS NOT NULL 
                          AND c."{parent_pk}" NOT IN (SELECT p."{parent_pk}" FROM "{parent_tbl}" p)
                    """)
                    orphan_row = cur.fetchone()
                    orphan_distinct = orphan_row[0] or 0

                    cur.execute(f'SELECT SUM(CASE WHEN "{parent_pk}" IS NULL THEN 1 ELSE 0 END) FROM "{child_tbl}"')
                    null_row = cur.fetchone()
                    null_cnt = null_row[0] or 0

                    cur.execute(f'SELECT COUNT(DISTINCT "{parent_pk}") FROM "{parent_tbl}"')
                    parent_distinct = cur.fetchone()[0] or 0

                    cur.execute(f"""
                        SELECT COUNT(DISTINCT c."{parent_pk}")
                        FROM "{child_tbl}" c
                        WHERE c."{parent_pk}" IN (SELECT p."{parent_pk}" FROM "{parent_tbl}" p)
                    """)
                    matched_distinct = cur.fetchone()[0] or 0

                    coverage = (matched_distinct / parent_distinct * 100) if parent_distinct > 0 else 0.0

                    rel_status = "verified" if orphan_distinct == 0 else "warning"
                    relationships.append({
                        "source_table": child_tbl,
                        "source_col": parent_pk,
                        "target_table": parent_tbl,
                        "target_col": parent_pk,
                        "child_table": child_tbl,
                        "child_column": parent_pk,
                        "parent_table": parent_tbl,
                        "parent_column": parent_pk,
                        "cardinality": "many_to_one",
                        "status": rel_status,
                        "orphan_count": orphan_distinct,
                        "orphan_keys": orphan_distinct,
                        "null_count": null_cnt,
                        "parent_coverage_pct": round(coverage, 2),
                        "coverage_pct": round(coverage, 2),
                        "parent_key_unique": True,
                        "parent_pk_unique": True
                    })

        return pks, relationships

    def create_relational_indexes(
        self,
        conn: sqlite3.Connection,
        tables: List[str],
        relationships: List[Dict[str, Any]],
        pks: Dict[str, str]
    ):
        """Create B-tree indexes on verified primary keys and foreign keys for instantaneous joins."""
        for tbl, pk in pks.items():
            idx_name = f"idx_pk_{tbl}_{pk}"
            conn.execute(f'CREATE INDEX IF NOT EXISTS "{idx_name}" ON "{tbl}"("{pk}");')

        for rel in relationships:
            src_tbl = rel["source_table"]
            src_col = rel["source_col"]
            idx_name = f"idx_fk_{src_tbl}_{src_col}"
            conn.execute(f'CREATE INDEX IF NOT EXISTS "{idx_name}" ON "{src_tbl}"("{src_col}");')

    def ingest_csv(
        self,
        file_content: Any,
        original_filename: str = "uploaded_data.csv",
        op_record: Optional[Any] = None,
        filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """Parse CSV bytes, normalize headers, and safely replace uploaded_data."""
        if filename:
            original_filename = filename

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
                sample_df = pd.read_csv(io.BytesIO(file_content), nrows=50, encoding=enc, dtype=str)
                dtypes = {}
                for col in sample_df.columns:
                    s = sample_df[col].dropna()
                    if s.str.match(r'^0\d+$').any():
                        dtypes[col] = str

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

        raw_cols = [str(c) for c in df.columns]
        norm_cols, header_mapping = normalize_column_list_with_mapping(raw_cols)
        df.columns = norm_cols

        if op_record:
            op_record.complete_stage("normalize_headers", {
                "column_count": len(norm_cols),
                "sample_mapping": dict(list(header_mapping.items())[:6])
            })
            op_record.start_stage("profile_data")

        df = df.replace([float('inf'), float('-inf')], None)
        df = df.where(pd.notnull(df), None)

        total_rows = len(df)
        total_cols = len(norm_cols)

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

        with _db_write_lock:
            conn = self._get_write_connection()
            try:
                conn.execute("DROP TABLE IF EXISTS _staging_uploaded_data")
                conn.commit()

                df.to_sql(
                    name="_staging_uploaded_data",
                    con=conn,
                    if_exists="replace",
                    index=False,
                    chunksize=5000
                )

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

                conn.execute("DROP TABLE IF EXISTS uploaded_data")
                conn.execute("ALTER TABLE _staging_uploaded_data RENAME TO uploaded_data")

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
                conn.execute(
                    "INSERT OR REPLACE INTO _dataset_metadata (key, value) VALUES ('active_workspace_mode', 'single')"
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

        preview = self.get_preview_rows(table_name="uploaded_data", limit=5)
        schema_info = self.get_schema_info(table_name="uploaded_data")

        return {
            "status": "success",
            "workspace_mode": "single",
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

    def ingest_relational_dataset(
        self,
        files_data: Dict[str, Any],
        op_record: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Safely parse, stage, validate, and activate multiple related CSV tables.
        
        Guarantees atomicity:
        - Validates all files and checks for table name collisions.
        - Parses all CSVs into memory/DataFrames.
        - Loads all tables into _staging_{table_name}.
        - Discovers and validates primary keys and foreign key relationships.
        - Creates indexes for fast join execution.
        - Only on 100% success swaps all staging tables to final tables in SQLite.
        - If any error occurs, all staging tables are cleaned up and prior workspace remains intact.
        """
        if op_record:
            op_record.start_stage("receive_validate")

        # Normalize files_data to dict
        if isinstance(files_data, (list, tuple)):
            files_dict: Dict[str, Any] = {name: content for name, content in files_data}
        else:
            files_dict = dict(files_data)

        if not files_dict or len(files_dict) < 2:
            msg = "A relational dataset requires at least 2 CSV files."
            if op_record:
                op_record.fail_stage("receive_validate", msg)
            raise ValueError(msg)

        # 1. Map filenames to safe table names and check for collisions
        table_file_map: Dict[str, str] = {}
        for original_name in files_dict.keys():
            t_name = normalize_table_name(original_name)
            if t_name in table_file_map:
                msg = f"Duplicate normalized table name (Table name collision): '{original_name}' and '{table_file_map[t_name]}' both normalize to '{t_name}'."
                if op_record:
                    op_record.fail_stage("receive_validate", msg)
                raise ValueError(msg)
            table_file_map[t_name] = original_name

        if op_record:
            op_record.complete_stage("receive_validate", {
                "file_count": len(files_dict),
                "proposed_tables": list(table_file_map.keys())
            })
            op_record.start_stage("parse_csvs")

        # 2. Parse all CSV files
        parsed_dfs: Dict[str, pd.DataFrame] = {}
        parsed_meta: Dict[str, Dict[str, Any]] = {}
        encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']

        for t_name, original_name in table_file_map.items():
            raw_content = files_dict[original_name]
            if isinstance(raw_content, (str, Path)) and Path(raw_content).is_file():
                raw_bytes = Path(raw_content).read_bytes()
            elif isinstance(raw_content, str):
                raw_bytes = raw_content.encode("utf-8")
            else:
                raw_bytes = raw_content

            if not raw_bytes or not raw_bytes.strip():
                msg = f"File '{original_name}' is empty."
                if op_record:
                    op_record.fail_stage("parse_csvs", msg)
                raise ValueError(msg)

            df = None
            last_err = None
            for enc in encodings:
                try:
                    sample_df = pd.read_csv(io.BytesIO(raw_bytes), nrows=50, encoding=enc, dtype=str)
                    dtypes = {}
                    for col in sample_df.columns:
                        s = sample_df[col].dropna()
                        if s.str.match(r'^0\d+$').any():
                            dtypes[col] = str
                    df = pd.read_csv(
                        io.BytesIO(raw_bytes),
                        encoding=enc,
                        dtype=dtypes if dtypes else None,
                        low_memory=False
                    )
                    break
                except Exception as e:
                    last_err = e

            if df is None:
                msg = f"Could not parse '{original_name}': {last_err}"
                if op_record:
                    op_record.fail_stage("parse_csvs", msg)
                raise ValueError(msg)

            if df.empty:
                msg = f"File '{original_name}' contains no data rows."
                if op_record:
                    op_record.fail_stage("parse_csvs", msg)
                raise ValueError(msg)

            parsed_dfs[t_name] = df

        if op_record:
            op_record.complete_stage("parse_csvs", {
                "tables_parsed": len(parsed_dfs),
                "total_rows": sum(len(d) for d in parsed_dfs.values())
            })
            op_record.start_stage("normalize_schemas")

        # 3. Normalize headers and profile quality
        staged_dfs: Dict[str, pd.DataFrame] = {}
        tables_meta: Dict[str, Any] = {}
        all_currencies: Set[str] = set()

        for t_name, df in parsed_dfs.items():
            original_name = table_file_map[t_name]
            raw_cols = [str(c) for c in df.columns]
            norm_cols, header_mapping = normalize_column_list_with_mapping(raw_cols)
            df.columns = norm_cols

            df = df.replace([float('inf'), float('-inf')], None)
            df = df.where(pd.notnull(df), None)

            total_rows = len(df)
            total_cols = len(norm_cols)

            quality_info = {}
            for col in norm_cols:
                null_count = int(df[col].isnull().sum())
                quality_info[col] = {
                    "null_count": null_count,
                    "null_percentage": round((null_count / total_rows) * 100, 2) if total_rows > 0 else 0
                }

            if "currency" in norm_cols:
                unique_curr = [str(c) for c in df["currency"].dropna().unique()]
                all_currencies.update(unique_curr)

            staged_dfs[t_name] = df
            tables_meta[t_name] = {
                "filename": original_name,
                "table_name": t_name,
                "row_count": total_rows,
                "column_count": total_cols,
                "columns": norm_cols,
                "header_mapping": header_mapping,
                "quality": quality_info
            }

        if op_record:
            op_record.complete_stage("normalize_schemas", {
                "tables_normalized": len(staged_dfs),
                "detected_currencies": sorted(list(all_currencies))
            })
            op_record.start_stage("stage_tables")

        # 4. Stage tables into SQLite
        staging_prefix = "_staging_rel_"
        with _db_write_lock:
            conn = self._get_write_connection()
            try:
                # Clean up any leftover staging tables
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '_staging_rel_%'")
                for (old_stg,) in cur.fetchall():
                    conn.execute(f'DROP TABLE IF EXISTS "{old_stg}"')
                conn.commit()

                # Load each dataframe into staging
                for t_name, df in staged_dfs.items():
                    stg_name = f"{staging_prefix}{t_name}"
                    df.to_sql(stg_name, conn, if_exists="replace", index=False, chunksize=5000)
                    cur.execute(f'SELECT COUNT(*) FROM "{stg_name}"')
                    cnt = cur.fetchone()[0]
                    if cnt != len(df):
                        raise RuntimeError(f"Staging count mismatch for '{t_name}': expected {len(df)}, got {cnt}")

                if op_record:
                    op_record.complete_stage("stage_tables", {
                        "staged_tables": len(staged_dfs)
                    })
                    op_record.start_stage("validate_keys")

                # 5. Discover PKs and verify FK relationships across staging tables
                staged_table_names = [f"{staging_prefix}{t}" for t in staged_dfs.keys()]
                staged_pks, staged_rels = self.discover_and_verify_relationships(conn, staged_table_names)

                # Remap staging names back to real table names
                pks: Dict[str, str] = {}
                for stg_tbl, pk in staged_pks.items():
                    real_tbl = stg_tbl.replace(staging_prefix, "")
                    pks[real_tbl] = pk
                    tables_meta[real_tbl]["primary_key"] = pk

                relationships: List[Dict[str, Any]] = []
                for rel in staged_rels:
                    real_src = rel["source_table"].replace(staging_prefix, "")
                    real_tgt = rel["target_table"].replace(staging_prefix, "")
                    relationships.append({
                        "source_table": real_src,
                        "child_table": real_src,
                        "source_col": rel["source_col"],
                        "child_column": rel["source_col"],
                        "target_table": real_tgt,
                        "parent_table": real_tgt,
                        "target_col": rel["target_col"],
                        "parent_column": rel["target_col"],
                        "cardinality": rel["cardinality"],
                        "status": rel["status"],
                        "orphan_count": rel["orphan_count"],
                        "orphan_keys": rel["orphan_count"],
                        "null_count": rel["null_count"],
                        "parent_coverage_pct": rel["parent_coverage_pct"],
                        "coverage_pct": rel["parent_coverage_pct"],
                        "parent_key_unique": rel["parent_key_unique"],
                        "parent_pk_unique": rel["parent_key_unique"]
                    })

                if op_record:
                    op_record.complete_stage("validate_keys", {
                        "primary_keys_found": pks,
                        "verified_relationships": len(relationships)
                    })
                    op_record.start_stage("build_indexes")

                # 6. Build indexes on final tables after swap
                # Atomic swap: drop existing relational tables and rename staging tables
                for t_name in staged_dfs.keys():
                    stg_name = f"{staging_prefix}{t_name}"
                    conn.execute(f'DROP TABLE IF EXISTS "{t_name}"')
                    conn.execute(f'ALTER TABLE "{stg_name}" RENAME TO "{t_name}"')

                # Create indexes on the newly active tables
                self.create_relational_indexes(conn, list(staged_dfs.keys()), relationships, pks)

                if op_record:
                    op_record.complete_stage("build_indexes", {
                        "indexed_tables": len(staged_dfs)
                    })
                    op_record.start_stage("activate_workspace")

                # 7. Persist workspace metadata
                upload_time = datetime.utcnow().isoformat() + "Z"
                workspace_payload = {
                    "tables": tables_meta,
                    "relationships": relationships,
                    "primary_keys": pks,
                    "currencies": sorted(list(all_currencies)),
                    "currency_columns": ["sales", "cost", "profit"] if any("sales" in t["columns"] for t in tables_meta.values()) else [],
                    "upload_time": upload_time
                }

                conn.execute(
                    "INSERT OR REPLACE INTO _dataset_metadata (key, value) VALUES ('relational_workspace', ?)",
                    (json.dumps(workspace_payload),)
                )
                conn.execute(
                    "INSERT OR REPLACE INTO _dataset_metadata (key, value) VALUES ('active_workspace_mode', 'relational')"
                )
                conn.commit()

                if op_record:
                    op_record.complete_stage("activate_workspace", {
                        "active_workspace_mode": "relational",
                        "tables_count": len(tables_meta)
                    })
                    op_record.finish({
                        "workspace_mode": "relational",
                        "tables": list(tables_meta.keys()),
                        "total_rows": sum(t["row_count"] for t in tables_meta.values()),
                        "relationships_count": len(relationships)
                    })

            except Exception as e:
                conn.rollback()
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '_staging_rel_%'")
                    for (stg,) in cur.fetchall():
                        conn.execute(f'DROP TABLE IF EXISTS "{stg}"')
                    conn.commit()
                except Exception:
                    pass
                if op_record:
                    op_record.fail_stage("activate_workspace", f"Relational dataset loading failed: {e}")
                raise RuntimeError(f"Relational dataset loading failed: {e}") from e
            finally:
                conn.close()

        schema_catalog = self.get_schema_info()
        return {
            "status": "success",
            "workspace_mode": "relational",
            "active_tables": list(tables_meta.keys()),
            "total_rows": sum(t["row_count"] for t in tables_meta.values()),
            "tables": tables_meta,
            "relationships": relationships,
            "currencies": sorted(list(all_currencies)),
            "schema_info": schema_catalog,
            "message": f"Successfully activated relational workspace with {len(tables_meta)} tables and {len(relationships)} verified relationships."
        }

    def load_bundled_relational_sample(self, op_record: Optional[Any] = None) -> Dict[str, Any]:
        """Load the five verified sample CSV tables from data/ into a relational workspace."""
        data_dir = settings.data_dir
        expected_files = [
            "customers.csv",
            "products.csv",
            "stores.csv",
            "sales_representatives.csv",
            "sales_transactions.csv"
        ]

        files_data: Dict[str, bytes] = {}
        for fname in expected_files:
            fpath = data_dir / fname
            if not fpath.exists():
                raise FileNotFoundError(f"Bundled sample file '{fname}' not found in {data_dir}.")
            files_data[fname] = fpath.read_bytes()

        return self.ingest_relational_dataset(files_data, op_record=op_record)

    def get_schema_info(self, table_name: Optional[str] = None) -> Dict[str, Any]:
        """Inspect actual SQLite table schemas and construct relationship-aware prompt context."""
        mode = self.get_active_workspace_mode()

        if mode == "relational":
            meta = self.get_metadata().get("relational_workspace", {})
            tables_meta = meta.get("tables", {})
            relationships = meta.get("relationships", [])
            currencies = meta.get("currencies", [])
            currency_cols = meta.get("currency_columns", ["sales", "cost", "profit"])

            if not tables_meta:
                return {
                    "is_loaded": False,
                    "workspace_mode": "relational",
                    "message": "No active relational tables found in workspace."
                }

            # Build comprehensive multi-table schema context for Gemini and UI
            catalog: Dict[str, Any] = {}
            schema_context_parts: List[str] = [
                "### RELATIONAL WORKSPACE DATABASE SCHEMA",
                f"Active Workspace Mode: Relational ({len(tables_meta)} tables)\n"
            ]

            with self._get_write_connection() as conn:
                cur = conn.cursor()
                for tbl, t_meta in tables_meta.items():
                    cur.execute(f'PRAGMA table_info("{tbl}")')
                    col_rows = cur.fetchall()
                    cols_desc = []
                    q_map = t_meta.get("quality", {})
                    for c in col_rows:
                        c_name = c[1]
                        c_type = (c[2] or "TEXT").upper()
                        cols_desc.append({
                            "name": c_name,
                            "type": c_type,
                            "null_count": q_map.get(c_name, {}).get("null_count", 0),
                            "null_percentage": q_map.get(c_name, {}).get("null_percentage", 0.0)
                        })

                    cur.execute(f'SELECT COUNT(*) FROM "{tbl}"')
                    r_cnt = cur.fetchone()[0]
                    prev_rows = self.get_preview_rows(table_name=tbl, limit=5)

                    catalog[tbl] = {
                        "filename": t_meta.get("filename", f"{tbl}.csv"),
                        "row_count": r_cnt,
                        "column_count": len(cols_desc),
                        "columns": cols_desc,
                        "primary_key": t_meta.get("primary_key"),
                        "preview": prev_rows,
                        "header_mapping": t_meta.get("header_mapping", {}),
                        "quality": q_map
                    }

                    # Prompt segment for this table
                    pk_str = f" [PRIMARY KEY: {t_meta.get('primary_key')}]" if t_meta.get("primary_key") else ""
                    schema_context_parts.append(f"Table: {tbl} (Rows: {r_cnt:,}){pk_str}")
                    col_strs = [f"{c['name']} ({c['type']})" for c in cols_desc]
                    schema_context_parts.append("Columns: " + ", ".join(col_strs))
                    if prev_rows:
                        schema_context_parts.append("Sample record: " + json.dumps(prev_rows[0]))
                    schema_context_parts.append("")

            # Relationships section in prompt
            if relationships:
                schema_context_parts.append("### VERIFIED FOREIGN KEY RELATIONSHIPS")
                for r in relationships:
                    schema_context_parts.append(
                        f"- {r['source_table']}.{r['source_col']} -> {r['target_table']}.{r['target_col']} "
                        f"(JOIN condition: ON {r['source_table']}.{r['source_col']} = {r['target_table']}.{r['target_col']})"
                    )
                schema_context_parts.append("")

            # Financial Multi-Currency rules
            if currencies and len(currencies) > 1:
                schema_context_parts.append("### CRITICAL FINANCIAL MULTI-CURRENCY RULE")
                schema_context_parts.append(
                    f"Transactions contain multiple currencies: {', '.join(currencies)}.\n"
                    "Monetary columns ('sales', 'cost', 'profit') MUST NEVER be summed across different currencies into a single total.\n"
                    "When aggregating monetary values, you MUST ALWAYS either:\n"
                    "  1. Filter by currency (e.g., WHERE currency = 'USD') OR\n"
                    "  2. Group by currency (e.g., GROUP BY currency) to keep totals separate."
                )
                schema_context_parts.append("")

            full_schema_context = "\n".join(schema_context_parts)

            # Determine selected table for dataset overview display
            selected_table = None
            if table_name and table_name in catalog:
                selected_table = table_name
            elif "customers" in catalog:
                selected_table = "customers"
            elif "sales_transactions" in catalog:
                selected_table = "sales_transactions"
            elif catalog:
                selected_table = list(catalog.keys())[0]

            sel_info = catalog.get(selected_table, {}) if selected_table else {}

            return {
                "is_loaded": True,
                "workspace_mode": "relational",
                "table_name": selected_table,
                "filename": sel_info.get("filename", f"{selected_table}.csv" if selected_table else ""),
                "row_count": sel_info.get("row_count", 0),
                "column_count": sel_info.get("column_count", 0),
                "columns": sel_info.get("columns", []),
                "primary_key": sel_info.get("primary_key"),
                "preview": sel_info.get("preview", []),
                "active_tables": list(tables_meta.keys()),
                "tables": catalog,
                "relationships": relationships,
                "currencies": currencies,
                "currency_columns": currency_cols,
                "total_rows": sum(c["row_count"] for c in catalog.values()),
                "schema_context": full_schema_context
            }

        else:
            # Single mode
            if not self._table_has_rows("uploaded_data"):
                return {
                    "is_loaded": False,
                    "workspace_mode": "single",
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
                    c_name = col[1]
                    c_type = col[2] or "TEXT"
                    q = quality_map.get(c_name, {})
                    columns_desc.append({
                        "name": c_name,
                        "type": c_type.upper(),
                        "null_count": q.get("null_count", 0),
                        "null_percentage": q.get("null_percentage", 0.0)
                    })

            preview = self.get_preview_rows(table_name="uploaded_data", limit=5)

            schema_lines = [f"Table: uploaded_data (Total Rows: {total_rows:,})", "Columns:"]
            for c in columns_desc:
                schema_lines.append(f"  - {c['name']} ({c['type']})")

            sample_lines = ["Sample records (first 3 rows):"]
            for row in preview[:3]:
                sample_lines.append(f"  {json.dumps(row)}")

            schema_context = "\n".join(schema_lines) + "\n\n" + "\n".join(sample_lines)

            return {
                "is_loaded": True,
                "workspace_mode": "single",
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

    def get_preview_rows(self, table_name: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
        """Fetch sample rows safely for UI display."""
        if not table_name:
            mode = self.get_active_workspace_mode()
            if mode == "single":
                table_name = "uploaded_data"
            else:
                tables = self.get_active_tables()
                table_name = "sales_transactions" if "sales_transactions" in tables else (tables[0] if tables else None)

        if not table_name or not self._table_has_rows(table_name):
            return []

        with self._get_write_connection() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(f'SELECT * FROM "{table_name}" LIMIT {int(limit)}')
            rows = cur.fetchall()
            return [dict(r) for r in rows]

    def execute_query_readonly(
        self,
        sql: str,
        params: Sequence[Any] = (),
        max_rows: Optional[int] = None,
        timeout_seconds: Optional[int] = None
    ) -> Dict[str, Any]:
        """Execute query strictly read-only with SQLite authorizer and timeout."""
        if not self.has_active_dataset():
            raise RuntimeError("Cannot execute query: no active dataset is loaded.")

        max_rows = max_rows or settings.max_query_rows
        timeout_seconds = timeout_seconds or settings.query_timeout_seconds
        allowed_tables = self.get_allowed_tables()
        allowed_set = {t.lower() for t in allowed_tables}

        db_uri = f"file:{self.db_path.as_posix()}?mode=ro"

        def authorizer(action, arg1, arg2, dbname, source):
            if action == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            elif action == sqlite3.SQLITE_READ:
                # arg1 is table name, arg2 is column name
                if arg1 and arg1.lower() not in allowed_set:
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            elif action == sqlite3.SQLITE_FUNCTION:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        conn = sqlite3.connect(db_uri, uri=True, timeout=1.0)
        start_time = time.perf_counter()

        try:
            conn.execute("PRAGMA query_only = ON")
            conn.set_authorizer(authorizer)

            deadline = time.time() + timeout_seconds

            def progress_callback():
                if time.time() > deadline:
                    return 1
                return 0

            conn.set_progress_handler(progress_callback, 1000)

            cursor = conn.cursor()
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)

            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            fetched_rows = cursor.fetchmany(max_rows + 1)
            is_capped = False
            if len(fetched_rows) > max_rows:
                is_capped = True
                fetched_rows = fetched_rows[:max_rows]

            execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

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
        table_name: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_order: str = "asc"
    ) -> Dict[str, Any]:
        """Retrieve paginated, searchable, sortable records from an active workspace table."""
        if not self.has_active_dataset():
            raise RuntimeError("Cannot preview dataset: no active dataset is loaded.")

        allowed = self.get_allowed_tables()
        if not table_name or table_name not in allowed:
            # Default to uploaded_data or sales_transactions or first table
            if "uploaded_data" in allowed:
                table_name = "uploaded_data"
            elif "sales_transactions" in allowed:
                table_name = "sales_transactions"
            elif allowed:
                table_name = sorted(list(allowed))[0]
            else:
                raise ValueError("No valid active tables found in workspace.")

        # Get column definitions
        with self._get_write_connection() as conn:
            cur = conn.cursor()
            cur.execute(f'PRAGMA table_info("{table_name}")')
            col_info = cur.fetchall()
            valid_cols = [c[1] for c in col_info]
            columns_meta = [{"name": c[1], "type": (c[2] or "TEXT").upper()} for c in col_info]
            cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
            total_rows = cur.fetchone()[0]

        offset = max(0, int(offset))
        limit = max(1, min(int(limit), 200))
        sort_order = (sort_order or "asc").strip().lower()
        if sort_order not in ("asc", "desc"):
            sort_order = "asc"

        sort_sql = "rowid ASC"
        if sort_by and sort_by.strip():
            sort_col = sort_by.strip()
            if sort_col not in valid_cols:
                raise ValueError(f"Invalid sort column: '{sort_col}' does not exist in table '{table_name}'.")
            sort_sql = f'"{sort_col}" {sort_order.upper()}, rowid ASC'

        where_clauses = []
        search_params: List[Any] = []
        if search and search.strip():
            term = search.strip()
            escaped_term = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like_val = f"%{escaped_term}%"
            col_search = [f'CAST("{col}" AS TEXT) LIKE ? ESCAPE "\\"' for col in valid_cols]
            if col_search:
                where_clauses.append(f"({' OR '.join(col_search)})")
                search_params = [like_val] * len(valid_cols)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        count_sql = f'SELECT COUNT(*) FROM "{table_name}" {where_sql};'
        count_res = self.execute_query_readonly(count_sql, params=search_params)
        filtered_total = count_res["rows"][0][0] if count_res["rows"] else 0

        data_sql = f'SELECT * FROM "{table_name}" {where_sql} ORDER BY {sort_sql} LIMIT ? OFFSET ?;'
        data_params = search_params + [limit, offset]
        data_res = self.execute_query_readonly(data_sql, params=data_params, max_rows=limit)

        if table_name == "uploaded_data":
            meta = self.get_metadata().get("dataset", {})
            filename = meta.get("filename", "uploaded_data.csv")
        else:
            meta = self.get_metadata().get("relational_workspace", {})
            filename = meta.get("tables", {}).get(table_name, {}).get("filename", f"{table_name}.csv")

        return {
            "status": "success",
            "workspace_mode": self.get_active_workspace_mode(),
            "table_name": table_name,
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
            "columns": columns_meta,
            "rows": data_res["rows"],
            "execution_time_ms": data_res["execution_time_ms"]
        }


# Global database engine instance
db_engine = DatabaseEngine()
