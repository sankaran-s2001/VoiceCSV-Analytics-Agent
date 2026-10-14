/**
 * VoiceCSV Analytics Agent - Core Application Controller
 * Handles file upload, API calls, dynamic table rendering, pagination, and UX state.
 */

document.addEventListener('DOMContentLoaded', () => {
  // DOM Elements - Badges & Status
  const serverBadge = document.getElementById('serverBadge');
  const geminiBadge = document.getElementById('geminiBadge');
  const datasetBadge = document.getElementById('datasetBadge');

  // DOM Elements - Upload
  const dropZone = document.getElementById('dropZone');
  const fileInput = document.getElementById('fileInput');
  const browseBtn = document.getElementById('browseBtn');
  const uploadProgress = document.getElementById('uploadProgress');
  const uploadProgressText = document.getElementById('uploadProgressText');
  const fileInfoBar = document.getElementById('fileInfoBar');
  const selectedFileName = document.getElementById('selectedFileName');
  const selectedFileSize = document.getElementById('selectedFileSize');
  const reuploadBtn = document.getElementById('reuploadBtn');

  // DOM Elements - Dataset Overview
  const datasetOverviewCard = document.getElementById('datasetOverviewCard');
  const activeTableName = document.getElementById('activeTableName');
  const overviewRows = document.getElementById('overviewRows');
  const overviewCols = document.getElementById('overviewCols');
  const previewHead = document.getElementById('previewHead');
  const previewBody = document.getElementById('previewBody');
  const schemaListBody = document.getElementById('schemaListBody');
  const tabButtons = document.querySelectorAll('.tab-btn');
  const tabPanes = document.querySelectorAll('.tab-pane');

  // DOM Elements - Query
  const questionInput = document.getElementById('questionInput');
  const runQueryBtn = document.getElementById('runQueryBtn');
  const chipButtons = document.querySelectorAll('.chip-btn');

  // DOM Elements - Pipeline & Alerts
  const executionPipeline = document.getElementById('executionPipeline');
  const pipelineStatusText = document.getElementById('pipelineStatusText');
  const pipelineStepsContainer = document.getElementById('pipelineStepsContainer');
  const uploadPipelineSteps = document.getElementById('uploadPipelineSteps');
  const errorBanner = document.getElementById('errorBanner');
  const errorMessage = document.getElementById('errorMessage');
  const closeErrorBtn = document.getElementById('closeErrorBtn');

  // DOM Elements - Results
  const resultsSection = document.getElementById('resultsSection');
  const executiveSummaryText = document.getElementById('executiveSummaryText');
  const sqlCode = document.getElementById('sqlCode');
  const copySqlBtn = document.getElementById('copySqlBtn');
  const copySqlText = document.getElementById('copySqlText');
  const healBadge = document.getElementById('healBadge');
  const resultCountBadge = document.getElementById('resultCountBadge');
  const cappedNotice = document.getElementById('cappedNotice');
  const resultsHead = document.getElementById('resultsHead');
  const resultsBody = document.getElementById('resultsBody');
  const pageInfo = document.getElementById('pageInfo');
  const prevPageBtn = document.getElementById('prevPageBtn');
  const nextPageBtn = document.getElementById('nextPageBtn');

  // DOM Elements - Metrics
  const metricOpId = document.getElementById('metricOpId');
  const metricSqlTime = document.getElementById('metricSqlTime');
  const metricDbTime = document.getElementById('metricDbTime');
  const metricSummaryTime = document.getElementById('metricSummaryTime');
  const metricTotalTime = document.getElementById('metricTotalTime');
  const metricRepairs = document.getElementById('metricRepairs');

  // Real-Time Operation Tracking Helpers
  function generateOpId(prefix) {
    const rand = Math.random().toString(36).substring(2, 9);
    return `op_${prefix}_${rand}`;
  }

  function renderStages(containerEl, stages) {
    if (!containerEl || !stages) return;
    containerEl.innerHTML = '';
    stages.forEach((stage, idx) => {
      const div = document.createElement('div');
      div.className = `step-item ${stage.status}`;
      
      let text = `${idx + 1}. ${stage.label}`;
      if (stage.status === 'completed' && stage.duration_ms !== null && stage.duration_ms !== undefined) {
        text += ` · ${stage.duration_ms}ms`;
      } else if (stage.status === 'skipped') {
        text += ` · Skipped`;
      } else if (stage.status === 'failed') {
        text += ` · Failed`;
      }
      div.textContent = text;
      containerEl.appendChild(div);
    });
  }

  function createOperationPoller(opId, onUpdate, intervalMs = 120) {
    let active = true;
    let timer = null;

    async function poll() {
      if (!active) return;
      try {
        const res = await fetch(`/api/operations/${opId}`);
        if (res.ok) {
          const data = await res.json();
          onUpdate(data);
          if (data.status === 'completed' || data.status === 'failed') {
            active = false;
            return;
          }
        }
      } catch (err) {
        // Suppress network jitter
      }
      if (active) {
        timer = setTimeout(poll, intervalMs);
      }
    }

    poll();

    return {
      stop: () => {
        active = false;
        if (timer) clearTimeout(timer);
      }
    };
  }

  // State
  let currentResults = { columns: [], rows: [] };
  let currentPage = 1;
  const pageSize = 25;
  let pipelineTimer = null;

  // -------------------------------------------------------------
  // Initialization & Health Check
  // -------------------------------------------------------------

  async function checkHealth() {
    try {
      const res = await fetch('/api/health');
      if (!res.ok) throw new Error(`Health check failed (${res.status})`);
      const data = await res.json();

      // Update server status
      setBadge(serverBadge, 'Connected', 'badge-success');

      // Update Gemini status
      if (data.gemini_configured) {
        setBadge(geminiBadge, `AI: ${data.gemini_model || 'Ready'}`, 'badge-success');
      } else {
        setBadge(geminiBadge, 'AI: Not Configured', 'badge-pending');
      }

      // Update Dataset status
      if (data.dataset_loaded) {
        const rowsFormatted = data.row_count ? Number(data.row_count).toLocaleString() : 'Active';
        const name = data.filename || 'uploaded_data';
        setBadge(datasetBadge, `${name} (${rowsFormatted})`, 'badge-success');
        // Fetch and display active schema
        loadActiveSchema();
      } else {
        setBadge(datasetBadge, 'No Dataset', 'badge-neutral');
      }
    } catch (err) {
      console.warn('Backend unavailable:', err);
      setBadge(serverBadge, 'Server Offline', 'badge-error');
      setBadge(geminiBadge, 'AI: Offline', 'badge-neutral');
      setBadge(datasetBadge, 'Database: Offline', 'badge-neutral');
    }
  }

  function setBadge(el, text, className) {
    if (!el) return;
    el.className = `status-badge ${className}`;
    const txtEl = el.querySelector('.badge-text');
    if (txtEl) txtEl.textContent = text;
  }

  function showError(msg) {
    if (!errorBanner) return;
    errorMessage.textContent = msg;
    errorBanner.classList.remove('hidden');
    // Scroll error into view if not visible
    errorBanner.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function hideError() {
    if (!errorBanner) return;
    errorBanner.classList.add('hidden');
    errorMessage.textContent = '';
  }

  if (closeErrorBtn) {
    closeErrorBtn.addEventListener('click', hideError);
  }

  // -------------------------------------------------------------
  // Schema & Dataset Display
  // -------------------------------------------------------------

  async function loadActiveSchema() {
    try {
      const res = await fetch('/api/schema');
      if (!res.ok) return;
      const data = await res.json();
      renderDatasetOverview(data);
    } catch (err) {
      console.warn('Could not load schema:', err);
    }
  }

  function renderDatasetOverview(data) {
    if (!datasetOverviewCard) return;

    datasetOverviewCard.classList.remove('hidden');
    if (overviewRows) overviewRows.textContent = Number(data.row_count || 0).toLocaleString();
    if (overviewCols) overviewCols.textContent = Number(data.column_count || 0).toLocaleString();
    if (activeTableName) activeTableName.textContent = data.table_name || 'uploaded_data';

    if (data.filename && fileInfoBar) {
      selectedFileName.textContent = data.filename;
      selectedFileSize.textContent = `${Number(data.row_count).toLocaleString()} rows loaded`;
      fileInfoBar.classList.remove('hidden');
    }

    // Render Preview Table
    renderTable(previewHead, previewBody, data.columns ? data.columns.map(c => c.name) : [], data.preview || []);

    // Render Schema Table
    if (schemaListBody && data.columns) {
      schemaListBody.innerHTML = '';
      data.columns.forEach(col => {
        const tr = document.createElement('tr');
        
        const tdName = document.createElement('td');
        tdName.textContent = col.name;
        tdName.style.fontWeight = '600';

        const tdType = document.createElement('td');
        const typeSpan = document.createElement('span');
        typeSpan.className = 'type-pill';
        typeSpan.textContent = col.type || 'TEXT';
        tdType.appendChild(typeSpan);

        const tdNulls = document.createElement('td');
        tdNulls.textContent = `${col.null_count || 0} (${col.null_percentage || 0}%)`;
        tdNulls.style.color = (col.null_count > 0) ? 'var(--warning)' : 'var(--text-muted)';

        tr.appendChild(tdName);
        tr.appendChild(tdType);
        tr.appendChild(tdNulls);
        schemaListBody.appendChild(tr);
      });
    }
  }

  // Tabs logic
  tabButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      tabButtons.forEach(b => b.classList.remove('active'));
      tabPanes.forEach(p => p.classList.remove('active'));

      btn.classList.add('active');
      const targetPane = document.getElementById(btn.getAttribute('data-tab'));
      if (targetPane) targetPane.classList.add('active');
    });
  });

  // -------------------------------------------------------------
  // File Upload Handlers
  // -------------------------------------------------------------

  if (browseBtn && fileInput) {
    browseBtn.addEventListener('click', () => fileInput.click());
  }

  if (dropZone && fileInput) {
    dropZone.addEventListener('click', (e) => {
      if (e.target !== browseBtn) fileInput.click();
    });

    ['dragenter', 'dragover'].forEach(event => {
      dropZone.addEventListener(event, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.add('drag-over');
      });
    });

    ['dragleave', 'drop'].forEach(event => {
      dropZone.addEventListener(event, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.remove('drag-over');
      });
    });

    dropZone.addEventListener('drop', (e) => {
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        handleFileSelect(e.dataTransfer.files[0]);
      }
    });

    fileInput.addEventListener('change', (e) => {
      if (e.target.files && e.target.files.length > 0) {
        handleFileSelect(e.target.files[0]);
      }
    });
  }

  if (reuploadBtn && fileInput) {
    reuploadBtn.addEventListener('click', () => fileInput.click());
  }

  function formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  }

  async function handleFileSelect(file) {
    hideError();

    if (!file.name.toLowerCase().endsWith('.csv')) {
      showError('Invalid file type. Please upload a CSV file (.csv).');
      return;
    }

    if (file.size > 100 * 1024 * 1024) {
      showError('File exceeds maximum upload limit of 100 MB.');
      return;
    }

    const opId = generateOpId('upload');

    // Show upload progress
    const dropContent = dropZone.querySelector('.drop-zone-content');
    if (dropContent) dropContent.classList.add('hidden');
    uploadProgress.classList.remove('hidden');
    uploadProgressText.textContent = `Validating ${file.name}...`;
    if (uploadPipelineSteps) {
      uploadPipelineSteps.innerHTML = '';
      uploadPipelineSteps.classList.remove('hidden');
    }

    const poller = createOperationPoller(opId, (opData) => {
      if (opData.stages && uploadPipelineSteps) {
        renderStages(uploadPipelineSteps, opData.stages);
      }
      const activeStage = opData.stages ? opData.stages.find(s => s.status === 'active') : null;
      if (activeStage) {
        uploadProgressText.textContent = `${activeStage.label}...`;
      }
    }, 120);

    const formData = new FormData();
    formData.append('file', file);
    formData.append('operation_id', opId);

    try {
      const response = await fetch('/api/upload', {
        method: 'POST',
        body: formData
      });

      const result = await response.json();

      if (!response.ok) {
        throw new Error(result.detail || 'Upload failed. Please check the CSV format.');
      }

      // Success! Update UI
      if (selectedFileName) selectedFileName.textContent = file.name;
      if (selectedFileSize) selectedFileSize.textContent = formatBytes(file.size);
      if (fileInfoBar) fileInfoBar.classList.remove('hidden');

      renderDatasetOverview(result);
      setBadge(datasetBadge, `${result.filename} (${Number(result.row_count).toLocaleString()})`, 'badge-success');

    } catch (err) {
      console.error('Upload error:', err);
      showError(err.message || 'An error occurred during CSV upload.');
    } finally {
      poller.stop();
      setTimeout(() => {
        uploadProgress.classList.add('hidden');
        if (dropContent) dropContent.classList.remove('hidden');
        fileInput.value = '';
      }, 700);
    }
  }

  // -------------------------------------------------------------
  // Query Execution & Pipeline Animation
  // -------------------------------------------------------------

  if (runQueryBtn) {
    runQueryBtn.addEventListener('click', () => submitQuestion());
  }

  if (questionInput) {
    questionInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        submitQuestion();
      }
    });
  }

  // Quick prompt chip triggers
  chipButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      const q = btn.getAttribute('data-query');
      if (q && questionInput) {
        questionInput.value = q;
        submitQuestion();
      }
    });
  });

  async function submitQuestion() {
    hideError();
    const question = questionInput ? questionInput.value.trim() : '';

    if (!question) {
      showError('Please type or speak a question before running analysis.');
      return;
    }

    const opId = generateOpId('query');

    // Disable button during query
    runQueryBtn.disabled = true;
    if (executionPipeline) executionPipeline.classList.remove('hidden');
    if (pipelineStatusText) pipelineStatusText.textContent = 'Accepting analysis request...';
    if (metricOpId) metricOpId.textContent = opId;

    // Reset pipeline steps with initial waiting status
    if (pipelineStepsContainer) {
      pipelineStepsContainer.innerHTML = '';
      const initialStep = document.createElement('div');
      initialStep.className = 'step-item active';
      initialStep.textContent = 'Initiating pipeline...';
      pipelineStepsContainer.appendChild(initialStep);
    }

    // Stop ongoing speech synthesis if any
    if (window.ttsController) {
      window.ttsController.stop();
    }

    const poller = createOperationPoller(opId, (opData) => {
      if (opData.stages && pipelineStepsContainer) {
        renderStages(pipelineStepsContainer, opData.stages);
      }
      const activeStage = opData.stages ? opData.stages.find(s => s.status === 'active') : null;
      if (activeStage && pipelineStatusText) {
        pipelineStatusText.textContent = `${activeStage.label}...`;
      }
    }, 120);

    try {
      const response = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, operation_id: opId })
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || 'Query execution failed.');
      }

      renderQueryResults(data);

    } catch (err) {
      console.error('Query error:', err);
      showError(err.message || 'An error occurred while analyzing the question.');
    } finally {
      poller.stop();
      runQueryBtn.disabled = false;
      // Fetch final operation telemetry to render exact durations
      try {
        const finalRes = await fetch(`/api/operations/${opId}`);
        if (finalRes.ok) {
          const finalOp = await finalRes.json();
          if (finalOp.stages && pipelineStepsContainer) {
            renderStages(pipelineStepsContainer, finalOp.stages);
          }
          if (pipelineStatusText) {
            if (finalOp.status === 'completed') {
              pipelineStatusText.textContent = `Completed in ${finalOp.total_duration_ms || 0} ms`;
            } else if (finalOp.status === 'failed') {
              pipelineStatusText.textContent = `Failed: ${finalOp.error || 'Execution halted'}`;
            }
          }
        }
      } catch (e) {
        // Suppress
      }
      setTimeout(() => {
        if (executionPipeline && resultsSection && !resultsSection.classList.contains('hidden')) {
          executionPipeline.classList.add('hidden');
        }
      }, 4000);
    }
  }

  // -------------------------------------------------------------
  // Results & Pagination Rendering
  // -------------------------------------------------------------

  function renderQueryResults(data) {
    if (!resultsSection) return;
    resultsSection.classList.remove('hidden');

    // 1. Executive Summary
    if (executiveSummaryText) {
      executiveSummaryText.textContent = data.summary || 'Query executed successfully.';
    }

    // 2. SQL Display
    if (sqlCode) {
      sqlCode.textContent = data.sql || '-- No SQL returned';
    }

    // Self-healing badge
    if (healBadge) {
      if (data.heal_attempts && data.heal_attempts > 0) {
        healBadge.textContent = `Healed in ${data.heal_attempts} repair${data.heal_attempts > 1 ? 's' : ''}`;
        healBadge.classList.remove('hidden');
      } else {
        healBadge.classList.add('hidden');
      }
    }

    // Capped notice
    if (cappedNotice) {
      if (data.is_capped) {
        cappedNotice.classList.remove('hidden');
      } else {
        cappedNotice.classList.add('hidden');
      }
    }

    // 3. Results Table with pagination
    currentResults = {
      columns: data.columns || [],
      rows: data.rows || []
    };
    currentPage = 1;
    renderResultsPage();

    if (resultCountBadge) {
      resultCountBadge.textContent = `${Number(data.row_count || 0).toLocaleString()} rows`;
    }

    // 4. Metrics
    if (metricOpId && data.operation_id) metricOpId.textContent = data.operation_id;
    if (metricSqlTime) metricSqlTime.textContent = `${data.sql_generation_time_ms || 0} ms`;
    if (metricDbTime) metricDbTime.textContent = `${data.execution_time_ms || 0} ms`;
    if (metricSummaryTime) metricSummaryTime.textContent = `${data.summary_generation_time_ms || 0} ms`;
    if (metricTotalTime) metricTotalTime.textContent = `${data.total_time_ms || 0} ms`;
    if (metricRepairs) metricRepairs.textContent = data.heal_attempts || 0;

    // Scroll to results cleanly
    resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function renderResultsPage() {
    const totalRows = currentResults.rows.length;
    const totalPages = Math.max(1, Math.ceil(totalRows / pageSize));

    const startIdx = (currentPage - 1) * pageSize;
    const endIdx = Math.min(startIdx + pageSize, totalRows);
    const pageRows = currentResults.rows.slice(startIdx, endIdx);

    // Convert row arrays to objects for the table renderer if needed
    const objectRows = pageRows.map(rowArr => {
      const obj = {};
      currentResults.columns.forEach((col, idx) => {
        obj[col] = rowArr[idx];
      });
      return obj;
    });

    renderTable(resultsHead, resultsBody, currentResults.columns, objectRows);

    if (pageInfo) {
      pageInfo.textContent = `Showing ${totalRows === 0 ? 0 : startIdx + 1}–${endIdx} of ${totalRows.toLocaleString()} rows (Page ${currentPage} of ${totalPages})`;
    }

    if (prevPageBtn) prevPageBtn.disabled = (currentPage <= 1);
    if (nextPageBtn) nextPageBtn.disabled = (currentPage >= totalPages);
  }

  if (prevPageBtn) {
    prevPageBtn.addEventListener('click', () => {
      if (currentPage > 1) {
        currentPage--;
        renderResultsPage();
      }
    });
  }

  if (nextPageBtn) {
    nextPageBtn.addEventListener('click', () => {
      const totalPages = Math.ceil(currentResults.rows.length / pageSize);
      if (currentPage < totalPages) {
        currentPage++;
        renderResultsPage();
      }
    });
  }

  /**
   * Safely render dynamic tables using textContent to prevent XSS.
   */
  function renderTable(headEl, bodyEl, columns, rows) {
    if (!headEl || !bodyEl) return;
    headEl.innerHTML = '';
    bodyEl.innerHTML = '';

    if (!columns || columns.length === 0) {
      const emptyRow = document.createElement('tr');
      const td = document.createElement('td');
      td.textContent = 'No records found.';
      td.className = 'null-cell';
      emptyRow.appendChild(td);
      bodyEl.appendChild(emptyRow);
      return;
    }

    // Render Headers
    const headerRow = document.createElement('tr');
    columns.forEach(colName => {
      const th = document.createElement('th');
      th.textContent = colName;
      headerRow.appendChild(th);
    });
    headEl.appendChild(headerRow);

    // Render Rows
    if (!rows || rows.length === 0) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = columns.length;
      td.textContent = 'No records returned.';
      td.className = 'null-cell';
      tr.appendChild(td);
      bodyEl.appendChild(tr);
      return;
    }

    rows.forEach(rowObj => {
      const tr = document.createElement('tr');
      columns.forEach(colName => {
        const td = document.createElement('td');
        const val = rowObj[colName];

        if (val === null || val === undefined) {
          td.innerHTML = '<span class="null-cell">NULL</span>';
        } else if (typeof val === 'number') {
          td.textContent = Number.isInteger(val) ? val.toLocaleString() : val.toFixed(2);
          td.style.textAlign = 'right';
        } else {
          td.textContent = String(val);
        }
        tr.appendChild(td);
      });
      bodyEl.appendChild(tr);
    });
  }

  // -------------------------------------------------------------
  // Copy SQL to Clipboard
  // -------------------------------------------------------------

  if (copySqlBtn && sqlCode) {
    copySqlBtn.addEventListener('click', async () => {
      const sqlText = sqlCode.textContent.trim();
      if (!sqlText) return;

      try {
        await navigator.clipboard.writeText(sqlText);
        if (copySqlText) copySqlText.textContent = 'Copied!';
        copySqlBtn.classList.add('badge-success');
        setTimeout(() => {
          if (copySqlText) copySqlText.textContent = 'Copy SQL';
          copySqlBtn.classList.remove('badge-success');
        }, 2000);
      } catch (err) {
        console.warn('Clipboard write failed:', err);
      }
    });
  }

  // -------------------------------------------------------------
  // Full Dataset Explorer Controller
  // -------------------------------------------------------------
  const datasetExplorerModal = document.getElementById('datasetExplorerModal');
  const openFullExplorerBtn = document.getElementById('openFullExplorerBtn');
  const closeExplorerBtn = document.getElementById('closeExplorerBtn');
  const explorerTitle = document.getElementById('explorerTitle');
  const explorerFileName = document.getElementById('explorerFileName');
  const expTotalRows = document.getElementById('expTotalRows');
  const expTotalCols = document.getElementById('expTotalCols');
  const explorerSearchInput = document.getElementById('explorerSearchInput');
  const clearSearchBtn = document.getElementById('clearSearchBtn');
  const explorerSearchCountBadge = document.getElementById('explorerSearchCountBadge');
  const explorerPageSize = document.getElementById('explorerPageSize');
  const expFirstBtn = document.getElementById('expFirstBtn');
  const expPrevBtn = document.getElementById('expPrevBtn');
  const expPageInfo = document.getElementById('expPageInfo');
  const expNextBtn = document.getElementById('expNextBtn');
  const expLastBtn = document.getElementById('expLastBtn');
  const expRefreshBtn = document.getElementById('expRefreshBtn');
  const explorerTableWrapper = document.getElementById('explorerTableWrapper');
  const explorerLoadingOverlay = document.getElementById('explorerLoadingOverlay');
  const explorerDataTable = document.getElementById('explorerDataTable');
  const explorerTableHead = document.getElementById('explorerTableHead');
  const explorerTableBody = document.getElementById('explorerTableBody');
  const explorerEmptyState = document.getElementById('explorerEmptyState');
  const explorerEmptyMessage = document.getElementById('explorerEmptyMessage');
  const explorerResetSearchBtn = document.getElementById('explorerResetSearchBtn');
  const explorerRangeText = document.getElementById('explorerRangeText');
  const explorerSortText = document.getElementById('explorerSortText');

  let expOffset = 0;
  let expLimit = 50;
  let expSearch = '';
  let expSortBy = null;
  let expSortOrder = 'asc';
  let expTotalRowCount = 0;
  let expFilteredRowCount = 0;
  let expSearchDebounceTimer = null;
  let expAbortController = null;

  function openExplorer() {
    if (!datasetExplorerModal) return;
    datasetExplorerModal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    fetchExplorerData();
    if (explorerSearchInput) {
      setTimeout(() => explorerSearchInput.focus(), 80);
    }
  }

  function closeExplorer() {
    if (!datasetExplorerModal) return;
    datasetExplorerModal.classList.add('hidden');
    document.body.style.overflow = '';
    if (openFullExplorerBtn) {
      openFullExplorerBtn.focus();
    }
  }

  async function fetchExplorerData() {
    if (!datasetExplorerModal) return;

    if (expAbortController) {
      expAbortController.abort();
    }
    expAbortController = new AbortController();

    if (explorerLoadingOverlay) {
      explorerLoadingOverlay.classList.remove('hidden');
    }

    const params = new URLSearchParams({
      offset: expOffset.toString(),
      limit: expLimit.toString()
    });

    if (expSearch) {
      params.append('search', expSearch);
    }
    if (expSortBy) {
      params.append('sort_by', expSortBy);
      params.append('sort_order', expSortOrder);
    }

    try {
      const response = await fetch(`/api/data/preview?${params.toString()}`, {
        signal: expAbortController.signal
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Server error (${response.status})`);
      }

      const data = await response.json();
      renderExplorerView(data);
    } catch (err) {
      if (err.name === 'AbortError') return;
      console.error('Failed to load explorer records:', err);
      if (explorerEmptyState) {
        explorerEmptyState.classList.remove('hidden');
        if (explorerEmptyMessage) {
          explorerEmptyMessage.textContent = `Unable to fetch records: ${err.message}`;
        }
      }
      if (explorerTableBody) explorerTableBody.innerHTML = '';
    } finally {
      if (explorerLoadingOverlay) {
        explorerLoadingOverlay.classList.add('hidden');
      }
    }
  }

  function renderExplorerView(data) {
    expTotalRowCount = data.total_rows || 0;
    expFilteredRowCount = data.filtered_total_rows !== undefined ? data.filtered_total_rows : (data.total_rows || 0);

    // Header metadata
    if (explorerFileName) explorerFileName.textContent = data.filename || 'dataset.csv';
    if (expTotalRows) expTotalRows.textContent = Number(data.total_rows || 0).toLocaleString();
    if (expTotalCols) expTotalCols.textContent = Number(data.total_columns || 0).toLocaleString();

    // Search count badge & clear button
    if (expSearch) {
      if (clearSearchBtn) clearSearchBtn.classList.remove('hidden');
      if (explorerSearchCountBadge) {
        explorerSearchCountBadge.textContent = `${Number(expFilteredRowCount).toLocaleString()} matches`;
        explorerSearchCountBadge.classList.remove('hidden');
      }
    } else {
      if (clearSearchBtn) clearSearchBtn.classList.add('hidden');
      if (explorerSearchCountBadge) explorerSearchCountBadge.classList.add('hidden');
    }

    // Render Table Header with sorting carets
    renderExplorerHeader(data.columns);

    // Render Table Rows or Empty State
    if (!data.rows || data.rows.length === 0) {
      if (explorerTableBody) explorerTableBody.innerHTML = '';
      if (explorerEmptyState) {
        explorerEmptyState.classList.remove('hidden');
        if (explorerEmptyMessage) {
          explorerEmptyMessage.textContent = expSearch
            ? `No records found matching "${expSearch}".`
            : 'No records available in this dataset.';
        }
      }
    } else {
      if (explorerEmptyState) explorerEmptyState.classList.add('hidden');
      renderExplorerRows(data.columns, data.rows, data.offset);
    }

    // Pagination controls status
    updateExplorerPagination(data.offset, data.limit, expFilteredRowCount, data.rows ? data.rows.length : 0);
  }

  function renderExplorerHeader(columns) {
    if (!explorerTableHead) return;
    explorerTableHead.innerHTML = '';

    const tr = document.createElement('tr');

    // Index column #
    const thIdx = document.createElement('th');
    thIdx.className = 'col-index';
    thIdx.textContent = '#';
    thIdx.title = 'Row number';
    tr.appendChild(thIdx);

    (columns || []).forEach(col => {
      const th = document.createElement('th');
      th.setAttribute('data-col', col.name);
      th.title = `Click to sort by ${col.name} (${col.type || 'TEXT'})`;

      const isCurrentSort = (expSortBy === col.name);
      if (isCurrentSort) {
        th.classList.add(expSortOrder === 'desc' ? 'sorted-desc' : 'sorted-asc');
      }

      const contentDiv = document.createElement('div');
      contentDiv.className = 'th-content';

      const colTitle = document.createElement('span');
      colTitle.textContent = col.name;
      contentDiv.appendChild(colTitle);

      const sortSpan = document.createElement('span');
      sortSpan.className = 'sort-indicator';
      if (isCurrentSort) {
        sortSpan.textContent = (expSortOrder === 'desc') ? '▼' : '▲';
      } else {
        sortSpan.textContent = '⇅';
      }
      contentDiv.appendChild(sortSpan);

      th.appendChild(contentDiv);

      th.addEventListener('click', () => {
        if (expSortBy === col.name) {
          if (expSortOrder === 'asc') {
            expSortOrder = 'desc';
          } else {
            // Reset to default
            expSortBy = null;
            expSortOrder = 'asc';
          }
        } else {
          expSortBy = col.name;
          expSortOrder = 'asc';
        }
        expOffset = 0;
        fetchExplorerData();
      });

      tr.appendChild(th);
    });

    explorerTableHead.appendChild(tr);
  }

  function renderExplorerRows(columns, rows, offset) {
    if (!explorerTableBody) return;
    explorerTableBody.innerHTML = '';

    const fragment = document.createDocumentFragment();

    rows.forEach((row, i) => {
      const tr = document.createElement('tr');

      // Row Index #
      const tdIdx = document.createElement('td');
      tdIdx.className = 'cell-index';
      tdIdx.textContent = Number(offset + i + 1).toLocaleString();
      tr.appendChild(tdIdx);

      // Data Columns
      columns.forEach((col, colIdx) => {
        const td = document.createElement('td');
        const val = Array.isArray(row) ? row[colIdx] : row[col.name];

        if (val === null || val === undefined) {
          td.className = 'null-cell';
          td.textContent = 'NULL';
        } else if (typeof val === 'number') {
          td.className = 'num-cell';
          td.textContent = Number.isInteger(val) ? val.toLocaleString() : val.toLocaleString(undefined, { maximumFractionDigits: 6 });
        } else if (typeof val === 'string' && val.trim() === '') {
          td.className = 'null-cell';
          td.textContent = '""';
        } else {
          td.textContent = String(val);
        }
        tr.appendChild(td);
      });

      fragment.appendChild(tr);
    });

    explorerTableBody.appendChild(fragment);
  }

  function updateExplorerPagination(offset, limit, totalFiltered, currentBatchCount) {
    const totalPages = Math.max(1, Math.ceil(totalFiltered / limit));
    const currentPageNum = Math.floor(offset / limit) + 1;

    if (expPageInfo) {
      expPageInfo.textContent = `Page ${currentPageNum.toLocaleString()} of ${totalPages.toLocaleString()}`;
    }

    if (expFirstBtn) expFirstBtn.disabled = (currentPageNum <= 1);
    if (expPrevBtn) expPrevBtn.disabled = (currentPageNum <= 1);
    if (expNextBtn) expNextBtn.disabled = (currentPageNum >= totalPages);
    if (expLastBtn) expLastBtn.disabled = (currentPageNum >= totalPages);

    // Footer range text
    if (explorerRangeText) {
      const start = totalFiltered === 0 ? 0 : offset + 1;
      const end = offset + currentBatchCount;
      let text = `Showing ${start.toLocaleString()}–${end.toLocaleString()} of ${totalFiltered.toLocaleString()} rows`;
      if (totalFiltered !== expTotalRowCount) {
        text += ` (filtered from ${expTotalRowCount.toLocaleString()} total)`;
      }
      explorerRangeText.textContent = text;
    }

    // Footer sort hint
    if (explorerSortText) {
      if (expSortBy) {
        explorerSortText.textContent = `Sorted by ${expSortBy} (${expSortOrder.toUpperCase()})`;
      } else {
        explorerSortText.textContent = 'Default order (rowid ASC)';
      }
    }
  }

  // Event Listeners for Explorer
  if (openFullExplorerBtn) {
    openFullExplorerBtn.addEventListener('click', openExplorer);
  }

  if (closeExplorerBtn) {
    closeExplorerBtn.addEventListener('click', closeExplorer);
  }

  if (datasetExplorerModal) {
    datasetExplorerModal.addEventListener('click', (e) => {
      if (e.target === datasetExplorerModal) {
        closeExplorer();
      }
    });
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && datasetExplorerModal && !datasetExplorerModal.classList.contains('hidden')) {
      closeExplorer();
    }
  });

  if (explorerSearchInput) {
    explorerSearchInput.addEventListener('input', () => {
      const val = explorerSearchInput.value.trim();
      if (val) {
        if (clearSearchBtn) clearSearchBtn.classList.remove('hidden');
      } else {
        if (clearSearchBtn) clearSearchBtn.classList.add('hidden');
      }

      if (expSearchDebounceTimer) clearTimeout(expSearchDebounceTimer);
      expSearchDebounceTimer = setTimeout(() => {
        expSearch = val;
        expOffset = 0;
        fetchExplorerData();
      }, 300);
    });
  }

  if (clearSearchBtn) {
    clearSearchBtn.addEventListener('click', () => {
      if (explorerSearchInput) explorerSearchInput.value = '';
      clearSearchBtn.classList.add('hidden');
      expSearch = '';
      expOffset = 0;
      fetchExplorerData();
      if (explorerSearchInput) explorerSearchInput.focus();
    });
  }

  if (explorerResetSearchBtn) {
    explorerResetSearchBtn.addEventListener('click', () => {
      if (explorerSearchInput) explorerSearchInput.value = '';
      if (clearSearchBtn) clearSearchBtn.classList.add('hidden');
      expSearch = '';
      expOffset = 0;
      fetchExplorerData();
    });
  }

  if (explorerPageSize) {
    explorerPageSize.addEventListener('change', () => {
      expLimit = parseInt(explorerPageSize.value, 10) || 50;
      expOffset = 0;
      fetchExplorerData();
    });
  }

  if (expFirstBtn) {
    expFirstBtn.addEventListener('click', () => {
      if (expOffset > 0) {
        expOffset = 0;
        fetchExplorerData();
      }
    });
  }

  if (expPrevBtn) {
    expPrevBtn.addEventListener('click', () => {
      if (expOffset > 0) {
        expOffset = Math.max(0, expOffset - expLimit);
        fetchExplorerData();
      }
    });
  }

  if (expNextBtn) {
    expNextBtn.addEventListener('click', () => {
      if (expOffset + expLimit < expFilteredRowCount) {
        expOffset += expLimit;
        fetchExplorerData();
      }
    });
  }

  if (expLastBtn) {
    expLastBtn.addEventListener('click', () => {
      const maxOffset = Math.max(0, Math.floor((expFilteredRowCount - 1) / expLimit) * expLimit);
      if (expOffset !== maxOffset) {
        expOffset = maxOffset;
        fetchExplorerData();
      }
    });
  }

  if (expRefreshBtn) {
    expRefreshBtn.addEventListener('click', () => {
      fetchExplorerData();
    });
  }

  // Hook into renderDatasetOverview to reset explorer state on CSV upload
  const originalRenderDatasetOverview = renderDatasetOverview;
  renderDatasetOverview = function(data) {
    originalRenderDatasetOverview(data);
    expOffset = 0;
    expSearch = '';
    expSortBy = null;
    expSortOrder = 'asc';
    if (explorerSearchInput) explorerSearchInput.value = '';
    if (clearSearchBtn) clearSearchBtn.classList.add('hidden');
    if (datasetExplorerModal && !datasetExplorerModal.classList.contains('hidden')) {
      fetchExplorerData();
    }
  };

  // Run initial health check on load
  checkHealth();
});
