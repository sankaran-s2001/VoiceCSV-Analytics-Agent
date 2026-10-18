"""FastAPI application entrypoint for VoiceCSV Analytics Agent.

Provides REST API endpoints for health, CSV upload, schema reflection,
and natural language analytics queries, and serves the dashboard frontend.
"""

import time
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.config import PROJECT_ROOT, settings
from backend.db_engine import db_engine
from backend.agent import analytics_agent
from backend.summarizer import executive_summarizer
from backend.operations import operation_tracker

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("voice_csv_agent")

app = FastAPI(
    title="VoiceCSV Analytics Agent",
    description="Local voice-enabled AI analytics agent powered by FastAPI, SQLite, and Gemini",
    version="1.0.0"
)

# Optional CORS middleware for local convenience (same-origin works automatically)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = PROJECT_ROOT / "frontend"


# ---------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------

class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000, description="Business question to answer")
    operation_id: Optional[str] = Field(None, description="Optional client-generated operation tracking ID")
    source: Optional[str] = Field("text", description="Input modality: 'voice' | 'text' | 'chip'")


class ColumnInfo(BaseModel):
    name: str
    type: str
    null_count: int = 0
    null_percentage: float = 0.0


class HealthResponse(BaseModel):
    status: str
    dataset_loaded: bool
    workspace_mode: str = "single"
    table_name: Optional[str] = None
    row_count: Optional[int] = None
    filename: Optional[str] = None
    active_tables: List[str] = []
    relationships: List[Dict[str, Any]] = []
    total_tables: int = 1
    gemini_configured: bool
    gemini_model: str
    database_available: bool


# ---------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------

@app.get("/api/health", response_model=HealthResponse)
def get_health():
    """Report application and service readiness without exposing sensitive keys."""
    is_loaded = db_engine.has_active_dataset()
    workspace_mode = db_engine.get_active_workspace_mode()
    active_tables = db_engine.get_active_tables()
    db_available = True
    row_count = None
    filename = None
    table_name = None
    relationships = []
    total_tables = len(active_tables)

    if is_loaded:
        try:
            if workspace_mode == "relational":
                meta = db_engine.get_metadata().get("relational_workspace", {})
                row_count = meta.get("total_rows")
                filename = f"Relational Dataset ({len(active_tables)} tables)"
                table_name = ", ".join(active_tables)
                relationships = meta.get("relationships", [])
            else:
                meta = db_engine.get_metadata().get("dataset", {})
                table_name = "uploaded_data"
                row_count = meta.get("row_count")
                filename = meta.get("filename")
        except Exception as e:
            logger.error("Failed to read dataset metadata for health check: %s", e)
            db_available = False

    return HealthResponse(
        status="healthy",
        dataset_loaded=is_loaded,
        workspace_mode=workspace_mode,
        table_name=table_name,
        row_count=row_count,
        filename=filename,
        active_tables=active_tables,
        relationships=relationships,
        total_tables=total_tables,
        gemini_configured=settings.is_gemini_configured,
        gemini_model=settings.gemini_model,
        database_available=db_available
    )


@app.get("/api/operations/{operation_id}")
def get_operation_status(operation_id: str):
    """Retrieve live stage progression and telemetry for an active or completed operation."""
    op_data = operation_tracker.get_operation(operation_id)
    if not op_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Operation ID not found."
        )
    return JSONResponse(status_code=status.HTTP_200_OK, content=op_data)


@app.post("/api/upload")
async def upload_csv(
    file: UploadFile = File(...),
    operation_id: Optional[str] = Form(None)
):
    """Upload and ingest a CSV file into SQLite uploaded_data with real-time stage tracking."""
    op_record = operation_tracker.create_upload_operation(op_id=operation_id)
    op_record.start_stage("receive_validate")

    # 1. Validate file extension
    if not file.filename or not file.filename.lower().endswith(".csv"):
        op_record.fail_stage("receive_validate", "Invalid file extension. Expected .csv.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file format. Please upload a file with a .csv extension."
        )

    # 2. Read content and check file size
    try:
        content = await file.read()
    except Exception as e:
        logger.error("Failed to read uploaded file: %s", e)
        op_record.fail_stage("receive_validate", f"Could not read upload content: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not read uploaded file content."
        )

    if len(content) == 0:
        op_record.fail_stage("receive_validate", "Uploaded file is empty (0 bytes).")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is empty."
        )

    if len(content) > settings.max_upload_bytes:
        op_record.fail_stage("receive_validate", f"File exceeds {settings.max_upload_mb} MB limit.")
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size of {settings.max_upload_mb} MB."
        )

    # 3. Ingest into SQLite staging and swap
    try:
        result = db_engine.ingest_csv(content, file.filename, op_record=op_record)
        result["operation_id"] = op_record.op_id
        return JSONResponse(status_code=status.HTTP_200_OK, content=result)
    except ValueError as ve:
        logger.warning("CSV validation error: %s", ve)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        logger.error("Internal error during CSV ingestion: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process CSV file: {str(e)}"
        )


@app.post("/api/upload-relational")
async def upload_relational_csvs(
    files: List[UploadFile] = File(...),
    operation_id: Optional[str] = Form(None)
):
    """Upload and ingest multiple related CSV files into separate relational tables."""
    op_record = operation_tracker.create_relational_upload_operation(op_id=operation_id)
    op_record.start_stage("receive_validate")

    if not files or len(files) < 1:
        op_record.fail_stage("receive_validate", "At least one CSV file must be provided.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please select at least one CSV file."
        )

    files_payload = []
    for f in files:
        if not f.filename or not f.filename.lower().endswith(".csv"):
            op_record.fail_stage("receive_validate", f"Invalid file format: '{f.filename}'. Expected .csv.")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid file format for '{f.filename}'. Please only upload files with a .csv extension."
            )
        try:
            content = await f.read()
        except Exception as e:
            op_record.fail_stage("receive_validate", f"Failed reading '{f.filename}': {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not read content of '{f.filename}'."
            )

        if len(content) == 0:
            op_record.fail_stage("receive_validate", f"File '{f.filename}' is empty (0 bytes).")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"The uploaded file '{f.filename}' is empty."
            )

        if len(content) > settings.max_upload_bytes:
            op_record.fail_stage("receive_validate", f"File '{f.filename}' exceeds size limit.")
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File '{f.filename}' exceeds maximum allowed size of {settings.max_upload_mb} MB."
            )

        files_payload.append((f.filename, content))

    try:
        result = db_engine.ingest_relational_dataset(files_payload, op_record=op_record)
        result["operation_id"] = op_record.op_id
        return JSONResponse(status_code=status.HTTP_200_OK, content=result)
    except ValueError as ve:
        logger.warning("Relational CSV validation error: %s", ve)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        logger.error("Internal error during relational CSV ingestion: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process relational dataset: {str(e)}"
        )


@app.post("/api/load-sample-relational")
def load_bundled_sample(operation_id: Optional[str] = Form(None)):
    """Load the bundled 5-table relational sample dataset from data/ directory."""
    op_record = operation_tracker.create_relational_upload_operation(op_id=operation_id)
    try:
        result = db_engine.load_bundled_relational_sample(op_record=op_record)
        result["operation_id"] = op_record.op_id
        return JSONResponse(status_code=status.HTTP_200_OK, content=result)
    except FileNotFoundError as fe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(fe))
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        logger.error("Internal error loading bundled sample: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load bundled relational sample: {str(e)}"
        )


@app.get("/api/schema")
def get_schema(table: Optional[str] = Query(None, description="Optional table name to retrieve schema for")):
    """Retrieve schema, column data types, row count, and preview for the active dataset."""
    schema_info = db_engine.get_schema_info(table_name=table)
    if not schema_info.get("is_loaded"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No dataset is currently loaded. Please upload a CSV file."
        )
    return JSONResponse(status_code=status.HTTP_200_OK, content=schema_info)


@app.get("/api/data/preview")
def get_data_preview(
    table: Optional[str] = Query(None, description="Table name to preview (defaults to active dataset)"),
    offset: int = Query(0, ge=0, description="Offset of first row to return"),
    limit: int = Query(50, ge=1, le=200, description="Number of rows to return (1-200)"),
    search: Optional[str] = Query(None, description="Global search keyword across all columns"),
    sort_by: Optional[str] = Query(None, description="Column to sort by"),
    sort_order: str = Query("asc", pattern="^(asc|desc|ASC|DESC)$", description="Sort direction")
):
    """Retrieve server-side paginated, searchable, sortable rows from the active dataset."""
    if not db_engine.has_active_dataset():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No dataset is currently loaded. Please upload a CSV file."
        )

    try:
        data = db_engine.get_dataset_preview(
            table_name=table,
            offset=offset,
            limit=limit,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=data)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        logger.error("Error retrieving dataset preview: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve dataset rows."
        )


@app.post("/api/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """Transcribe spoken business question from audio recording using Gemini."""
    if not settings.is_gemini_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gemini API is not configured. Please add GOOGLE_API_KEY to your .env file."
        )

    try:
        content = await file.read()
    except Exception as e:
        logger.error("Failed reading audio upload: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not read audio stream."
        )

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded audio is empty."
        )

    try:
        transcript = analytics_agent.transcribe_audio(content, mime_type=file.content_type or "audio/webm")
        return JSONResponse(status_code=status.HTTP_200_OK, content={"text": transcript})
    except Exception as e:
        logger.error("Speech transcription error: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Speech transcription failed: {str(e)}"
        )


@app.post("/api/query")
def run_query(payload: QueryRequest):
    """Translate natural language or spoken question to SQL, execute safely, and summarize."""
    question = payload.question.strip()
    op_record = operation_tracker.create_query_operation(op_id=payload.operation_id)

    if not question:
        op_record.fail_stage("validate_request", "Question string is empty.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide a non-empty question."
        )

    if not db_engine.has_active_dataset():
        op_record.fail_stage("validate_request", "No dataset is currently loaded in database.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No dataset is loaded. Please upload a CSV before asking questions."
        )

    if not settings.is_gemini_configured:
        op_record.fail_stage("validate_request", "Gemini API key is not configured in .env.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gemini API is not configured. Please add GOOGLE_API_KEY to your .env file."
        )

    try:
        # Run SQL generation, validation, and self-healing execution
        result = analytics_agent.answer_question(question, op_record=op_record)

        raw_question = result.get("raw_question", question)
        refined_question = result.get("refined_question", question)
        input_source = (payload.source or "text").strip().lower()

        # Generate business executive summary using refined intent
        op_record.start_stage("gemini_summary")
        summary_result = executive_summarizer.generate_summary(
            question=refined_question or question,
            columns=result["columns"],
            rows=result["rows"],
            row_count=result["row_count"]
        )
        op_record.complete_stage("gemini_summary", {
            "summary_latency_ms": summary_result["summary_latency_ms"],
            "summary_preview": (summary_result["summary"][:60] + "...") if len(summary_result["summary"]) > 60 else summary_result["summary"]
        })

        op_record.start_stage("serialize_response")

        total_server_time = round(result["total_time_ms"] + summary_result["summary_latency_ms"], 2)

        response_payload = {
            "status": "success",
            "operation_id": op_record.op_id,
            "question": result.get("question", question),
            "raw_question": raw_question,
            "refined_question": refined_question,
            "source": input_source,
            "sql": result["sql"],
            "columns": result["columns"],
            "rows": result["rows"],
            "row_count": result["row_count"],
            "is_capped": result.get("is_capped", False),
            "summary": summary_result["summary"],
            "execution_time_ms": result["execution_time_ms"],
            "sql_generation_time_ms": result["sql_generation_time_ms"],
            "summary_generation_time_ms": summary_result["summary_latency_ms"],
            "total_time_ms": total_server_time,
            "heal_attempts": result["heal_attempts"]
        }

        op_record.complete_stage("serialize_response", {
            "delivered_rows": len(result["rows"]),
            "source": input_source,
            "refined_question": refined_question
        })
        op_record.finish({
            "total_server_time_ms": total_server_time,
            "raw_question": raw_question,
            "refined_question": refined_question,
            "source": input_source
        })

        return JSONResponse(status_code=status.HTTP_200_OK, content=response_payload)

    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except TimeoutError as te:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(te))
    except RuntimeError as re:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(re))
    except Exception as e:
        logger.error("Query pipeline failed: %s", e, exc_info=True)
        if op_record:
            op_record.fail_stage("serialize_response", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while analyzing your question. Please try rephrasing."
        )


# ---------------------------------------------------------
# Static File Mounting and Root Dashboard
# ---------------------------------------------------------

# Mount static asset folders (css, js, assets)
css_dir = FRONTEND_DIR / "css"
js_dir = FRONTEND_DIR / "js"
assets_dir = FRONTEND_DIR / "assets"
css_dir.mkdir(parents=True, exist_ok=True)
js_dir.mkdir(parents=True, exist_ok=True)
assets_dir.mkdir(parents=True, exist_ok=True)

app.mount("/css", StaticFiles(directory=str(css_dir)), name="css")
app.mount("/js", StaticFiles(directory=str(js_dir)), name="js")
app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")


@app.get("/")
def serve_dashboard():
    """Serve the single-page application dashboard."""
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"message": "Frontend index.html is being prepared."}
        )
    return FileResponse(
        str(index_file),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )
