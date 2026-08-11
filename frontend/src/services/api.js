/**
 * API client for the Synthetic Data Generator backend.
 *
 * Uses Axios with retry interceptor and centralised error handling.
 * All endpoints are prefixed with `/api` (proxied by Vite to the backend).
 */

import axios from "axios";

const apiBase = import.meta.env.VITE_API_BASE || "/api";

/** @type {import('axios').AxiosInstance} */
const api = axios.create({
  baseURL: apiBase,
  timeout: 120000,
});

// ── Auth token interceptor ───────────────────────────────────

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("auth_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ── Retry interceptor ────────────────────────────────────────

const MAX_RETRIES = 2;
const RETRY_DELAY = 1000;
const RETRYABLE_CODES = new Set([408, 429, 502, 503, 504]);

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const config = error.config;
    if (!config) return Promise.reject(error);

    // Auto-logout on 401 (expired/invalid token) — skip for auth endpoints
    if (
      error.response?.status === 401 &&
      !config.url?.startsWith("/auth/")
    ) {
      localStorage.removeItem("auth_token");
      window.location.href = "/login";
      return Promise.reject(error);
    }

    config._retryCount = config._retryCount || 0;

    const isRetryable =
      !error.response ||
      RETRYABLE_CODES.has(error.response.status);

    if (isRetryable && config._retryCount < MAX_RETRIES) {
      config._retryCount += 1;
      const delay = RETRY_DELAY * config._retryCount;
      await new Promise((r) => setTimeout(r, delay));
      return api(config);
    }

    return Promise.reject(error);
  }
);

// ── Error helpers ────────────────────────────────────────────

/**
 * Extract a human-readable error message from an Axios error.
 * @param {import('axios').AxiosError} err
 * @returns {string}
 */
export function parseApiError(err) {
  if (!err.response) {
    if (err.code === "ECONNABORTED") {
      return "Request timed out. The server may be busy — try again or reduce row count.";
    }
    return "Cannot connect to the server. Make sure the backend is running on port 8000.";
  }
  const detail = err.response.data?.detail;
  if (detail) return typeof detail === "string" ? detail : JSON.stringify(detail);
  const status = err.response.status;
  if (status === 413) return "Files are too large. Reduce file size and try again.";
  if (status === 422) return "The server could not process your files. Check file contents.";
  if (status >= 500) return "Server error. Please try again.";
  return err.message || "Something went wrong.";
}

// ── Upload files ─────────────────────────────────────────────

/**
 * Upload files and create a new session.
 * @param {File[]} files
 * @param {(pct: number) => void} [onProgress]
 * @returns {Promise<{session_id: string, files: Array}>}
 */
export async function uploadFiles(files, onProgress) {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  const { data } = await api.post("/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
    onUploadProgress: onProgress
      ? (e) => onProgress(Math.round((e.loaded * 100) / (e.total || 1)))
      : undefined,
  });
  return data;
}

// ── Parse ────────────────────────────────────────────────────

/**
 * Trigger parsing for all files in the session.
 * @param {string} sessionId
 * @returns {Promise<Object>}
 */
export async function parseSession(sessionId, { mergeSchemas = true } = {}) {
  const params = new URLSearchParams({ session_id: sessionId, merge_schemas: mergeSchemas });
  const { data } = await api.post(`/parse?${params.toString()}`);
  return data;
}

// ── Generate ─────────────────────────────────────────────────

/**
 * Generate synthetic data with the given configuration.
 * @param {string} sessionId
 * @param {{rowCount?: number, includeValid?: boolean, includeInvalid?: boolean, includeBoundary?: boolean, includeDuplicates?: boolean}} [config]
 * @returns {Promise<Object>}
 */
export async function generateData(sessionId, config = {}) {
  const params = new URLSearchParams({
    session_id: sessionId,
    row_count: config.rowCount ?? 10,
    include_valid: config.includeValid ?? true,
    include_invalid: config.includeInvalid ?? false,
    include_boundary: config.includeBoundary ?? false,
    include_duplicates: config.includeDuplicates ?? false,
  });
  // Scale timeout with row count — 120s base + 1s per 10K rows
  const rowCount = config.rowCount ?? 10;
  const dynamicTimeout = Math.max(120000, 120000 + Math.ceil(rowCount / 10000) * 1000);
  const { data } = await api.post(`/generate?${params.toString()}`, null, {
    timeout: dynamicTimeout,
  });
  return data;
}

// ── Download ─────────────────────────────────────────────────

/**
 * Build the download URL for an exported format.
 * @param {'csv'|'json'|'sql'} format
 * @param {string} sessionId
 * @returns {string}
 */
export function getDownloadUrl(format, sessionId) {
  return `/api/download/${format}?session_id=${sessionId}`;
}

// ── Summary ──────────────────────────────────────────────────

/**
 * Fetch the full session summary.
 * @param {string} sessionId
 * @returns {Promise<Object>}
 */
export async function getSummary(sessionId) {
  const { data } = await api.get(`/summary?session_id=${sessionId}`);
  return data;
}

// ── Preview ──────────────────────────────────────────────────

/**
 * Fetch a preview of generated rows for a specific table.
 * @param {string} sessionId
 * @param {string} tableName
 * @param {number} [limit=10]
 * @returns {Promise<{table_name: string, total_rows: number, columns: string[], rows: Object[]}>}
 */
export async function getPreview(sessionId, tableName, limit = 10, offset = 0) {
  const { data } = await api.get(
    `/preview/${encodeURIComponent(tableName)}?session_id=${sessionId}&limit=${limit}&offset=${offset}`
  );
  return data;
}

// ── Natural Language ──────────────────────────────────────────

/**
 * Infer a database schema from a natural-language prompt.
 * @param {string} prompt
 * @param {number} [rowCount=100]
 * @returns {Promise<Object>}
 */
export async function nlInferSchema(prompt, rowCount = 100) {
  const { data } = await api.post("/nl/infer-schema", {
    prompt,
    row_count: rowCount,
  });
  return data;
}

/**
 * Generate synthetic data from a natural-language prompt (one-shot).
 * @param {string} prompt
 * @param {number} [rowCount=100]
 * @param {boolean} [includeInvalid=false]
 * @returns {Promise<Object>}
 */
export async function nlGenerate(prompt, rowCount = 100, includeInvalid = false) {
  const dynamicTimeout = Math.max(120000, 120000 + Math.ceil(rowCount / 10000) * 1000);
  const { data } = await api.post("/nl/generate", {
    prompt,
    row_count: rowCount,
    include_invalid: includeInvalid,
  }, { timeout: dynamicTimeout });
  return data;
}

/**
 * Generate synthetic data from a NL prompt with an optional reference document.
 * If a file is provided, sends as multipart form data; otherwise JSON.
 * @param {string} prompt
 * @param {number} [rowCount=100]
 * @param {boolean} [includeInvalid=false]
 * @param {File|null} [file=null]
 * @param {string|null} [docType=null]
 * @returns {Promise<Object>}
 */
export async function nlGenerateWithRef(prompt, rowCount = 100, includeInvalid = false, file = null, docType = null) {
  const dynamicTimeout = Math.max(120000, 120000 + Math.ceil(rowCount / 10000) * 1000);
  if (!file) {
    // No file — use standard JSON endpoint
    const { data } = await api.post("/nl/generate", {
      prompt,
      row_count: rowCount,
      include_invalid: includeInvalid,
    }, { timeout: dynamicTimeout });
    return data;
  }
  // With file — use multipart endpoint
  const formData = new FormData();
  formData.append("prompt", prompt);
  formData.append("row_count", String(rowCount));
  formData.append("include_invalid", String(includeInvalid));
  formData.append("file", file);
  if (docType) formData.append("doc_type", docType);
  const { data } = await api.post("/nl/generate-with-ref", formData, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: dynamicTimeout,
  });
  return data;
}

// ── Reference Document Ingestion ──────────────────────────────

/**
 * Ingest a reference document (image or text) — run OCR + extraction.
 * @param {File} file
 * @param {string|null} [docType]
 * @returns {Promise<Object>}
 */
export async function referenceIngest(file, docType = null) {
  const formData = new FormData();
  formData.append("file", file);
  const params = docType ? `?doc_type=${encodeURIComponent(docType)}` : "";
  const { data } = await api.post(`/reference/ingest${params}`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

/**
 * Ingest + generate synthetic data from a reference document.
 * @param {File} file
 * @param {{docType?: string|null, rowCount?: number, includeInvalid?: boolean}} [config]
 * @returns {Promise<Object>}
 */
export async function referenceGenerate(file, config = {}) {
  const formData = new FormData();
  formData.append("file", file);
  const params = new URLSearchParams({
    row_count: config.rowCount ?? 100,
    include_invalid: config.includeInvalid ?? false,
  });
  if (config.docType) params.set("doc_type", config.docType);
  const rowCount = config.rowCount ?? 100;
  const dynamicTimeout = Math.max(120000, 120000 + Math.ceil(rowCount / 10000) * 1000);
  const { data } = await api.post(
    `/reference/generate?${params.toString()}`,
    formData,
    { headers: { "Content-Type": "multipart/form-data" }, timeout: dynamicTimeout },
  );
  return data;
}

export default api;

// ── History ──────────────────────────────────────────────────

/**
 * Fetch all history records for the current user.
 * @returns {Promise<{records: Object[], total: number}>}
 */
export async function getHistory() {
  const token = localStorage.getItem("auth_token");
  const { data } = await api.get(`/history?token=${token}`);
  return data;
}

/**
 * Fetch a single history record (with full row data).
 * @param {string} recordId
 * @returns {Promise<Object>}
 */
export async function getHistoryRecord(recordId) {
  const token = localStorage.getItem("auth_token");
  const { data } = await api.get(`/history/${recordId}?token=${token}`);
  return data;
}

/**
 * Restore a live session from a history record so analysis endpoints work.
 * @param {string} recordId
 * @returns {Promise<{session_id: string}>}
 */
export async function restoreSessionFromHistory(recordId) {
  const token = localStorage.getItem("auth_token");
  const { data } = await api.post(`/history/${recordId}/restore?token=${token}`);
  return data;
}

/**
 * Update a history record with analysis results.
 * @param {string} recordId
 * @param {Object} updates - Fields to update (edge_cases, partitions, integration_bundle, integration_guide)
 * @returns {Promise<Object>}
 */
export async function updateHistoryRecord(recordId, updates) {
  const token = localStorage.getItem("auth_token");
  const { data } = await api.patch(`/history/${recordId}?token=${token}`, updates);
  return data;
}

/**
 * Delete a single history record.
 * @param {string} recordId
 * @returns {Promise<Object>}
 */
export async function deleteHistoryRecord(recordId) {
  const token = localStorage.getItem("auth_token");
  const { data } = await api.delete(`/history/${recordId}?token=${token}`);
  return data;
}

/**
 * Delete all history records for the current user.
 * @returns {Promise<Object>}
 */
export async function clearHistory() {
  const token = localStorage.getItem("auth_token");
  const { data } = await api.delete(`/history?token=${token}`);
  return data;
}

// ── Integration ──────────────────────────────────────────────

/**
 * Generate the full integration bundle (Postman, SQL, payloads, Swagger tests, CI config).
 * @param {string} sessionId
 * @param {string} [baseUrl="http://localhost:8080"]
 * @returns {Promise<Object>}
 */
export async function generateIntegration(sessionId, baseUrl = "http://localhost:8080", artifacts = null) {
  const params = new URLSearchParams({ session_id: sessionId, base_url: baseUrl });
  if (artifacts && artifacts.length > 0) {
    params.set("artifacts", artifacts.join(","));
  }
  const { data } = await api.post(`/integration/generate?${params.toString()}`);
  return data;
}

/**
 * Build the download URL for the full integration bundle ZIP.
 * @param {string} sessionId
 * @returns {string}
 */
export function getIntegrationDownloadUrl(sessionId) {
  return `/api/integration/download?session_id=${sessionId}`;
}

/**
 * Fetch the Postman collection JSON.
 * @param {string} sessionId
 * @returns {Promise<Object>}
 */
export async function getPostmanCollection(sessionId) {
  const { data } = await api.get(`/integration/postman?session_id=${sessionId}`);
  return data;
}

/**
 * Fetch the Swagger test suite JSON.
 * @param {string} sessionId
 * @returns {Promise<Object>}
 */
export async function getSwaggerTests(sessionId) {
  const { data } = await api.get(`/integration/swagger?session_id=${sessionId}`);
  return data;
}

/**
 * Fetch the CI/CD + QA pipeline configs.
 * @param {string} sessionId
 * @returns {Promise<Object>}
 */
export async function getCIConfig(sessionId) {
  const { data } = await api.get(`/integration/ci?session_id=${sessionId}`);
  return data;
}

/**
 * Generate an AI-powered integration guide for the dataset.
 * @param {string} sessionId
 * @returns {Promise<Object>} IntegrationGuide
 */
export async function getIntegrationGuide(sessionId) {
  const { data } = await api.post(`/integration/guide?session_id=${sessionId}`);
  return data;
}

/**
 * Analyze edge cases for the parsed schema.
 * @param {string} sessionId
 * @param {Object} [toggles] - Optional category toggles
 * @returns {Promise<Object>} EdgeCaseAnalysis
 */
export async function analyzeEdgeCases(sessionId, toggles = {}) {
  const params = new URLSearchParams({ session_id: sessionId });
  for (const [key, val] of Object.entries(toggles)) {
    if (val !== undefined) params.set(key, val);
  }
  const { data } = await api.post(`/edge-cases/analyze?${params.toString()}`);
  return data;
}

/**
 * Run equivalence partitioning analysis on the parsed schema.
 * @param {string} sessionId
 * @param {number} [rowsPerPartition=3]
 * @param {Object} [splitConfig] - Optional split configuration
 * @param {number} [splitConfig.totalRows] - Total rows to generate (enables split mode)
 * @param {number} [splitConfig.validPct] - Percentage for valid partitions
 * @param {number} [splitConfig.invalidPct] - Percentage for invalid partitions
 * @param {number} [splitConfig.boundaryPct] - Percentage for boundary partitions
 * @param {number} [splitConfig.duplicatePct] - Percentage for duplicate partitions
 * @returns {Promise<Object>} PartitionAnalysis
 */
export async function analyzePartitions(sessionId, rowsPerPartition = 3, splitConfig = null) {
  const params = new URLSearchParams({
    session_id: sessionId,
    rows_per_partition: rowsPerPartition,
  });
  if (splitConfig && splitConfig.totalRows) {
    params.set('total_rows', splitConfig.totalRows);
    params.set('valid_pct', splitConfig.validPct ?? 80);
    params.set('invalid_pct', splitConfig.invalidPct ?? 10);
    params.set('boundary_pct', splitConfig.boundaryPct ?? 10);
    params.set('duplicate_pct', splitConfig.duplicatePct ?? 0);
  }
  const { data } = await api.post(`/partitions/analyze?${params.toString()}`);
  return data;
}

// ── Chat (Ask Yoda) ──────────────────────────────────────────

/**
 * Send messages to the Ask Yoda chatbot.
 * @param {Array<{role: string, content: string}>} messages
 * @returns {Promise<{reply: string}>}
 */
export async function askYoda(messages) {
  const { data } = await api.post("/chat/ask", { messages });
  return data;
}
