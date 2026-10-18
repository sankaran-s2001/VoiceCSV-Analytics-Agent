/**
 * VoiceCSV Analytics Agent - Core Application Controller
 * Handles file upload, API calls, dynamic table rendering, pagination, and UX state.
 */

document.addEventListener('DOMContentLoaded', () => {
  // DOM Elements - Badges & Status
  const serverBadge = document.getElementById('serverBadge');
  const geminiBadge = document.getElementById('geminiBadge');
  const datasetBadge = document.getElementById('datasetBadge');
  const workspaceModeBadge = document.getElementById('workspaceModeBadge');

  // Mode Switcher Elements
  const modeSingleTabBtn = document.getElementById('modeSingleTabBtn');
  const modeRelationalTabBtn = document.getElementById('modeRelationalTabBtn');
  const singleUploadContainer = document.getElementById('singleUploadContainer');
  const relationalUploadContainer = document.getElementById('relationalUploadContainer');

  // Relational Upload Elements
  const loadBundledSampleBtn = document.getElementById('loadBundledSampleBtn');
  const relationalFileInput = document.getElementById('relationalFileInput');
  const browseRelationalBtn = document.getElementById('browseRelationalBtn');
  const relationalDropZone = document.getElementById('relationalDropZone');
  const relationalUploadProgress = document.getElementById('relationalUploadProgress');
  const relationalUploadProgressText = document.getElementById('relationalUploadProgressText');
  const relationalPipelineSteps = document.getElementById('relationalPipelineSteps');
  const relationalQueueContainer = document.getElementById('relationalQueueContainer');
  const relationalQueueList = document.getElementById('relationalQueueList');
  const queueCountBadge = document.getElementById('queueCountBadge');
  const startRelationalImportBtn = document.getElementById('startRelationalImportBtn');
  const clearRelationalQueueBtn = document.getElementById('clearRelationalQueueBtn');

  // Overview Table Switcher & Relationships Card
  const overviewTableSelectWrapper = document.getElementById('overviewTableSelectWrapper');
  const overviewTableSelect = document.getElementById('overviewTableSelect');
  const relationshipsCard = document.getElementById('relationshipsCard');
  const relationshipsCountBadge = document.getElementById('relationshipsCountBadge');
  const relTablesGrid = document.getElementById('relTablesGrid');
  const relPathsList = document.getElementById('relPathsList');
  const currencySafeguardBanner = document.getElementById('currencySafeguardBanner');
  const currencySafeguardDesc = document.getElementById('currencySafeguardDesc');

  // Query Prompt Chips
  const chipsList = document.getElementById('chipsList');
  const relationalChipsList = document.getElementById('relationalChipsList');

  // Explorer Table Selector
  const explorerTableSelectWrapper = document.getElementById('explorerTableSelectWrapper');
  const explorerTableSelect = document.getElementById('explorerTableSelect');

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
  let currentInputSource = 'text'; // 'text' | 'voice' | 'chip'

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
  const queryContextCard = document.getElementById('queryContextCard');
  const querySourceBadge = document.getElementById('querySourceBadge');
  const querySourceIcon = document.getElementById('querySourceIcon');
  const querySourceText = document.getElementById('querySourceText');
  const copyQuestionBtn = document.getElementById('copyQuestionBtn');
  const contextRawQuestion = document.getElementById('contextRawQuestion');
  const contextRefinedQuestion = document.getElementById('contextRefinedQuestion');
  const contextRawLabel = document.getElementById('contextRawLabel');
  const contextRawHint = document.getElementById('contextRawHint');
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
  let activeWorkspaceMode = 'single';
  let activeTablesList = [];
  let currentOverviewTable = null;
  let relationalSelectedFiles = [];
  let expTable = null;

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

      // Update Workspace Mode
      activeWorkspaceMode = data.workspace_mode || 'single';
      activeTablesList = data.active_tables || [];
      if (workspaceModeBadge) {
        const modeLabel = activeWorkspaceMode === 'relational'
          ? `Mode: Relational (${activeTablesList.length} Tables)`
          : 'Mode: Single CSV';
        setBadge(workspaceModeBadge, modeLabel, activeWorkspaceMode === 'relational' ? 'badge-success' : 'badge-neutral');
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

      // Sync workspace mode tabs
      syncWorkspaceModeUI(activeWorkspaceMode);
    } catch (err) {
      console.warn('Backend unavailable:', err);
      setBadge(serverBadge, 'Server Offline', 'badge-error');
      setBadge(geminiBadge, 'AI: Offline', 'badge-neutral');
      setBadge(datasetBadge, 'Database: Offline', 'badge-neutral');
      if (workspaceModeBadge) setBadge(workspaceModeBadge, 'Mode: Offline', 'badge-neutral');
    }
  }

  function syncWorkspaceModeUI(mode) {
    if (mode === 'relational') {
      if (modeRelationalTabBtn) modeRelationalTabBtn.classList.add('active');
      if (modeSingleTabBtn) modeSingleTabBtn.classList.remove('active');
      if (relationalUploadContainer) relationalUploadContainer.classList.remove('hidden');
      if (singleUploadContainer) singleUploadContainer.classList.add('hidden');
      if (relationalChipsList) relationalChipsList.classList.remove('hidden');
      if (chipsList) chipsList.classList.add('hidden');
    } else {
      if (modeSingleTabBtn) modeSingleTabBtn.classList.add('active');
      if (modeRelationalTabBtn) modeRelationalTabBtn.classList.remove('active');
      if (singleUploadContainer) singleUploadContainer.classList.remove('hidden');
      if (relationalUploadContainer) relationalUploadContainer.classList.add('hidden');
      if (chipsList) chipsList.classList.remove('hidden');
      if (relationalChipsList) relationalChipsList.classList.add('hidden');
    }
  }

  if (modeSingleTabBtn && modeRelationalTabBtn) {
    modeSingleTabBtn.addEventListener('click', () => {
      syncWorkspaceModeUI('single');
    });
    modeRelationalTabBtn.addEventListener('click', () => {
      syncWorkspaceModeUI('relational');
    });
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

  let tableSelectionSeq = 0;

  async function loadTableSchema(tableName) {
    if (!tableName) return;
    const currentSeq = ++tableSelectionSeq;
    try {
      if (overviewRows) overviewRows.textContent = '...';
      if (overviewCols) overviewCols.textContent = '...';

      const res = await fetch(`/api/schema?table=${encodeURIComponent(tableName)}`);
      if (!res.ok) {
        showError(`Could not load schema for table "${tableName}"`);
        return;
      }
      const schemaData = await res.json();
      if (currentSeq !== tableSelectionSeq) return;

      currentOverviewTable = tableName;
      renderDatasetOverview(schemaData);
    } catch (err) {
      if (currentSeq !== tableSelectionSeq) return;
      console.warn('Failed to switch table schema view:', err);
      showError(`Failed to load table "${tableName}": ${err.message}`);
    }
  }

  function renderDatasetOverview(data) {
    if (!datasetOverviewCard) return;

    datasetOverviewCard.classList.remove('hidden');
    currentOverviewTable = data.table_name || 'uploaded_data';
    if (overviewRows) overviewRows.textContent = Number(data.row_count || 0).toLocaleString();
    if (overviewCols) overviewCols.textContent = Number(data.column_count || 0).toLocaleString();

    if (data.workspace_mode === 'relational') {
      if (activeTableName) {
        activeTableName.textContent = data.table_name || '';
        activeTableName.classList.add('hidden');
      }
    } else {
      if (activeTableName) {
        activeTableName.textContent = data.table_name || 'uploaded_data';
        activeTableName.classList.remove('hidden');
      }
    }

    if (data.filename && fileInfoBar) {
      selectedFileName.textContent = data.filename;
      selectedFileSize.textContent = `${Number(data.row_count).toLocaleString()} rows loaded`;
      fileInfoBar.classList.remove('hidden');
    }

    // Multi-table overview dropdown
    if (data.workspace_mode === 'relational' && data.tables) {
      if (overviewTableSelectWrapper) overviewTableSelectWrapper.classList.remove('hidden');
      if (overviewTableSelect) {
        const tableNames = Object.keys(data.tables);
        if (overviewTableSelect.options.length !== tableNames.length) {
          overviewTableSelect.innerHTML = '';
          tableNames.forEach(tName => {
            const opt = document.createElement('option');
            opt.value = tName;
            opt.textContent = `${tName} (${Number(data.tables[tName].row_count).toLocaleString()} rows)`;
            if (tName === data.table_name) opt.selected = true;
            overviewTableSelect.appendChild(opt);
          });
        }
        overviewTableSelect.value = data.table_name || tableNames[0];
      }
    } else {
      if (overviewTableSelectWrapper) overviewTableSelectWrapper.classList.add('hidden');
    }

    // Render Relationships Card for relational workspace
    if (data.workspace_mode === 'relational') {
      if (relationshipsCard) relationshipsCard.classList.remove('hidden');

      // 1. Render active tables cards
      if (relTablesGrid && data.tables) {
        relTablesGrid.innerHTML = '';
        Object.entries(data.tables).forEach(([tblName, tblInfo]) => {
          const card = document.createElement('div');
          card.className = 'rel-table-card';
          card.innerHTML = `
            <span class="rel-table-name" title="${tblName}">${tblName}</span>
            <span class="rel-table-rows">${Number(tblInfo.row_count || 0).toLocaleString()} rows &bull; ${tblInfo.column_count} cols</span>
            <span class="rel-table-pk">PK: ${tblInfo.primary_key || 'none'}</span>
          `;
          relTablesGrid.appendChild(card);
        });
      }

      // 2. Render verified relationships
      if (relPathsList) {
        relPathsList.innerHTML = '';
        const rels = data.relationships || [];
        if (relationshipsCountBadge) relationshipsCountBadge.textContent = `${rels.length} Verified JOINs`;

        rels.forEach(rel => {
          const item = document.createElement('div');
          item.className = 'rel-path-item';
          const coveragePct = rel.coverage_pct !== undefined ? `${rel.coverage_pct}%` : '100%';
          item.innerHTML = `
            <div class="rel-path-header">
              <span class="rel-path-expr">${rel.child_table}.${rel.child_column} &rarr; ${rel.parent_table}.${rel.parent_column}</span>
              <span class="rel-path-badge verified">&check; Verified (${rel.status || 'verified'})</span>
            </div>
            <div class="rel-path-stats">
              <span>Cardinality: ${rel.cardinality || 'N:1'}</span>
              <span>Coverage: ${coveragePct}</span>
              <span>Orphans: ${rel.orphan_keys || 0}</span>
              <span>Parent Unique: ${rel.parent_pk_unique ? 'Yes' : 'No'}</span>
            </div>
          `;
          relPathsList.appendChild(item);
        });
      }

      // 3. Render currency safeguard info
      if (currencySafeguardDesc) {
        const currencies = data.currencies || ['USD', 'INR', 'AUD', 'CAD', 'GBP', 'SGD'];
        currencySafeguardDesc.textContent = `Active Currencies: ${currencies.join(', ')}. Aggregations on monetary columns (sales, profit, cost) must filter or group by currency.`;
      }
    } else {
      if (relationshipsCard) relationshipsCard.classList.add('hidden');
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

  if (overviewTableSelect) {
    overviewTableSelect.addEventListener('change', (e) => {
      loadTableSchema(e.target.value);
    });
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
  // Relational Dataset Handlers: Bundled Sample & Multi-Upload
  // -------------------------------------------------------------

  if (loadBundledSampleBtn) {
    loadBundledSampleBtn.addEventListener('click', async () => {
      hideError();
      loadBundledSampleBtn.disabled = true;
      const opId = generateOpId('sample');

      if (relationalUploadProgress) {
        relationalUploadProgress.classList.remove('hidden');
        if (relationalUploadProgressText) relationalUploadProgressText.textContent = 'Loading bundled 5-table relational dataset...';
        if (relationalPipelineSteps) {
          relationalPipelineSteps.innerHTML = '';
          relationalPipelineSteps.classList.remove('hidden');
        }
      }

      const poller = createOperationPoller(opId, (opData) => {
        if (opData.stages && relationalPipelineSteps) {
          renderStages(relationalPipelineSteps, opData.stages);
        }
        const activeStage = opData.stages ? opData.stages.find(s => s.status === 'active') : null;
        if (activeStage && relationalUploadProgressText) {
          relationalUploadProgressText.textContent = `${activeStage.label}...`;
        }
      }, 120);

      try {
        const formData = new FormData();
        formData.append('operation_id', opId);
        const res = await fetch('/api/load-sample-relational', {
          method: 'POST',
          body: formData
        });
        poller.stop();

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `Server error (${res.status})`);
        }

        const data = await res.json();
        if (relationalUploadProgress) relationalUploadProgress.classList.add('hidden');
        await checkHealth();
        await loadActiveSchema();
      } catch (err) {
        poller.stop();
        if (relationalUploadProgress) relationalUploadProgress.classList.add('hidden');
        showError(`Failed to load bundled sample: ${err.message}`);
      } finally {
        loadBundledSampleBtn.disabled = false;
      }
    });
  }

  // Multi-CSV upload handlers
  if (browseRelationalBtn && relationalFileInput) {
    browseRelationalBtn.addEventListener('click', () => relationalFileInput.click());
  }

  if (relationalDropZone && relationalFileInput) {
    relationalDropZone.addEventListener('click', (e) => {
      if (e.target !== browseRelationalBtn) relationalFileInput.click();
    });

    ['dragenter', 'dragover'].forEach(event => {
      relationalDropZone.addEventListener(event, (e) => {
        e.preventDefault();
        e.stopPropagation();
        relationalDropZone.classList.add('drag-over');
      });
    });

    ['dragleave', 'drop'].forEach(event => {
      relationalDropZone.addEventListener(event, (e) => {
        e.preventDefault();
        e.stopPropagation();
        relationalDropZone.classList.remove('drag-over');
      });
    });

    relationalDropZone.addEventListener('drop', (e) => {
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        addFilesToRelationalQueue(Array.from(e.dataTransfer.files));
      }
    });

    relationalFileInput.addEventListener('change', (e) => {
      if (e.target.files && e.target.files.length > 0) {
        addFilesToRelationalQueue(Array.from(e.target.files));
      }
    });
  }

  function normalizeTableName(name) {
    return name.replace(/\.csv$/i, '')
      .toLowerCase()
      .replace(/[\s\-\/\.]+/g, '_')
      .replace(/[^a-z0-9_]/g, '')
      .replace(/_+/g, '_')
      .replace(/^_+|_+$/g, '') || 'table';
  }

  function addFilesToRelationalQueue(files) {
    hideError();
    const validCsvs = files.filter(f => f.name.toLowerCase().endsWith('.csv'));
    if (validCsvs.length === 0) {
      showError('Please select CSV files (.csv).');
      return;
    }

    validCsvs.forEach(newFile => {
      if (!relationalSelectedFiles.some(f => f.name === newFile.name)) {
        relationalSelectedFiles.push(newFile);
      }
    });

    renderRelationalQueue();
  }

  function renderRelationalQueue() {
    if (!relationalQueueContainer || !relationalQueueList) return;
    if (relationalSelectedFiles.length === 0) {
      relationalQueueContainer.classList.add('hidden');
      return;
    }

    relationalQueueContainer.classList.remove('hidden');
    if (queueCountBadge) queueCountBadge.textContent = `${relationalSelectedFiles.length} files`;
    relationalQueueList.innerHTML = '';

    relationalSelectedFiles.forEach((file, index) => {
      const item = document.createElement('div');
      item.className = 'queue-item';
      const inferredTable = normalizeTableName(file.name);
      item.innerHTML = `
        <div>
          <span class="queue-item-name">${file.name}</span> &rarr; <code>${inferredTable}</code>
          <span class="queue-item-meta">(${formatBytes(file.size)})</span>
        </div>
        <button type="button" class="queue-remove-btn" title="Remove file" data-index="${index}">&times;</button>
      `;
      relationalQueueList.appendChild(item);
    });

    relationalQueueList.querySelectorAll('.queue-remove-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const idx = parseInt(e.currentTarget.getAttribute('data-index'), 10);
        relationalSelectedFiles.splice(idx, 1);
        renderRelationalQueue();
      });
    });
  }

  if (clearRelationalQueueBtn) {
    clearRelationalQueueBtn.addEventListener('click', () => {
      relationalSelectedFiles = [];
      renderRelationalQueue();
    });
  }

  if (startRelationalImportBtn) {
    startRelationalImportBtn.addEventListener('click', async () => {
      if (relationalSelectedFiles.length < 1) {
        showError('Please select at least one CSV file to import.');
        return;
      }
      hideError();
      startRelationalImportBtn.disabled = true;
      const opId = generateOpId('rel_import');

      if (relationalUploadProgress) {
        relationalUploadProgress.classList.remove('hidden');
        if (relationalUploadProgressText) relationalUploadProgressText.textContent = 'Importing relational dataset...';
        if (relationalPipelineSteps) {
          relationalPipelineSteps.innerHTML = '';
          relationalPipelineSteps.classList.remove('hidden');
        }
      }

      const poller = createOperationPoller(opId, (opData) => {
        if (opData.stages && relationalPipelineSteps) {
          renderStages(relationalPipelineSteps, opData.stages);
        }
        const activeStage = opData.stages ? opData.stages.find(s => s.status === 'active') : null;
        if (activeStage && relationalUploadProgressText) {
          relationalUploadProgressText.textContent = `${activeStage.label}...`;
        }
      }, 120);

      try {
        const formData = new FormData();
        formData.append('operation_id', opId);
        relationalSelectedFiles.forEach(f => {
          formData.append('files', f);
        });

        const res = await fetch('/api/upload-relational', {
          method: 'POST',
          body: formData
        });
        poller.stop();

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `Server error (${res.status})`);
        }

        const data = await res.json();
        relationalSelectedFiles = [];
        renderRelationalQueue();
        if (relationalUploadProgress) relationalUploadProgress.classList.add('hidden');
        await checkHealth();
        await loadActiveSchema();
      } catch (err) {
        poller.stop();
        if (relationalUploadProgress) relationalUploadProgress.classList.add('hidden');
        showError(`Relational import failed: ${err.message}`);
      } finally {
        startRelationalImportBtn.disabled = false;
      }
    });
  }

  // -------------------------------------------------------------
  // Query Execution & Pipeline Animation
  // -------------------------------------------------------------

  if (runQueryBtn) {
    runQueryBtn.addEventListener('click', () => submitQuestion());
  }

  if (questionInput) {
    questionInput.addEventListener('speech-transcribed', () => {
      currentInputSource = 'voice';
    });

    questionInput.addEventListener('input', () => {
      if (questionInput.dataset.source === 'voice') {
        currentInputSource = 'voice';
      } else {
        currentInputSource = 'text';
      }
    });

    questionInput.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') {
        currentInputSource = 'text';
      }
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
        currentInputSource = 'chip';
        questionInput.value = q;
        submitQuestion();
      }
    });
  });

  if (copyQuestionBtn) {
    copyQuestionBtn.addEventListener('click', () => {
      const rawText = contextRawQuestion ? contextRawQuestion.textContent : '';
      if (rawText && rawText !== '-' && questionInput) {
        questionInput.value = rawText;
        questionInput.focus();
        currentInputSource = 'text';
        questionInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    });
  }

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
        body: JSON.stringify({
          question,
          operation_id: opId,
          source: currentInputSource
        })
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

    // 0. Executed Query Context
    if (queryContextCard) {
      queryContextCard.classList.remove('hidden');

      const rawQ = data.raw_question || data.question || '';
      const refinedQ = data.refined_question || data.question || '';
      const source = data.source || 'text';

      if (contextRawQuestion) {
        contextRawQuestion.textContent = rawQ || '-';
      }

      if (contextRefinedQuestion) {
        contextRefinedQuestion.textContent = refinedQ || '-';
      }

      if (querySourceBadge) {
        querySourceBadge.className = 'query-source-badge';
        if (source === 'voice') {
          querySourceBadge.classList.add('badge-voice');
          if (querySourceIcon) querySourceIcon.textContent = '🎤';
          if (querySourceText) querySourceText.textContent = 'Spoken Voice';
          if (contextRawLabel) contextRawLabel.textContent = 'Transcribed Spoken Audio (Raw)';
          if (contextRawHint) contextRawHint.textContent = 'Directly as spoken';
        } else if (source === 'chip') {
          querySourceBadge.classList.add('badge-chip');
          if (querySourceIcon) querySourceIcon.textContent = '⚡';
          if (querySourceText) querySourceText.textContent = 'Quick Prompt';
          if (contextRawLabel) contextRawLabel.textContent = 'Selected Prompt (Raw)';
          if (contextRawHint) contextRawHint.textContent = 'From quick prompts';
        } else {
          querySourceBadge.classList.add('badge-text');
          if (querySourceIcon) querySourceIcon.textContent = '⌨';
          if (querySourceText) querySourceText.textContent = 'Typed Input';
          if (contextRawLabel) contextRawLabel.textContent = 'User Input (Raw)';
          if (contextRawHint) contextRawHint.textContent = 'Directly as typed';
        }
      }
    }

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

    rows.forEach(rowItem => {
      const tr = document.createElement('tr');
      columns.forEach((colName, colIdx) => {
        const td = document.createElement('td');
        const val = Array.isArray(rowItem) ? rowItem[colIdx] : (rowItem ? rowItem[colName] : null);

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
    if (activeWorkspaceMode === 'relational' && activeTablesList.length > 0) {
      expTable = currentOverviewTable || activeTablesList[0];
    } else {
      expTable = null;
    }
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

    if (expTable) {
      params.append('table', expTable);
    }
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

    // Table Selector for Relational Workspace
    if (activeWorkspaceMode === 'relational' && activeTablesList.length > 0) {
      if (explorerTableSelectWrapper) explorerTableSelectWrapper.classList.remove('hidden');
      if (explorerTableSelect) {
        if (explorerTableSelect.options.length !== activeTablesList.length) {
          explorerTableSelect.innerHTML = '';
          activeTablesList.forEach(tbl => {
            const opt = document.createElement('option');
            opt.value = tbl;
            opt.textContent = tbl;
            if (tbl === (expTable || data.table_name)) opt.selected = true;
            explorerTableSelect.appendChild(opt);
          });
        } else {
          explorerTableSelect.value = expTable || data.table_name;
        }
      }
    } else {
      if (explorerTableSelectWrapper) explorerTableSelectWrapper.classList.add('hidden');
    }

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

  if (explorerTableSelect) {
    explorerTableSelect.addEventListener('change', (e) => {
      expTable = e.target.value;
      expOffset = 0;
      expSortBy = null;
      expSortOrder = 'asc';
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
