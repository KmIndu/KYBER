/**
 * Results Dashboard — statistics, validation, dataset preview, and downloads.
 *
 * Reads the `session_id` from the URL query string and fetches the
 * generation summary from the backend.
 */

import { useEffect, useState, useCallback } from "react";
import { useSearchParams, Link } from "react-router-dom";
import Card, { CardBody, CardHeader } from "../components/Card";
import Button from "../components/Button";
import Spinner from "../components/Spinner";
import Alert from "../components/Alert";
import Badge from "../components/Badge";
import StatCard from "../components/StatCard";
import SpotlightSearch from "../components/SpotlightSearch";
import ResultsTutorial from "../components/ResultsTutorial";
import {
  getSummary,
  getDownloadUrl,
  getPreview,
  parseApiError,
  generateIntegration,
  getIntegrationDownloadUrl,
  getIntegrationGuide,
  analyzeEdgeCases,
  analyzePartitions,
  getHistoryRecord,
  restoreSessionFromHistory,
  updateHistoryRecord,
} from "../services/api";

export default function ResultsPage() {
  const [searchParams] = useSearchParams();
  const sessionId = searchParams.get("session_id");
  const historyId = searchParams.get("history_id");
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [historyData, setHistoryData] = useState(null); // row data from history
  const [restoredSessionId, setRestoredSessionId] = useState(null); // session restored from history

  // The effective session ID: use the live one, or the restored one from history
  const effectiveSessionId = sessionId || restoredSessionId;

  // Preview state
  const [previewTable, setPreviewTable] = useState(null);
  const [previewData, setPreviewData] = useState(null);
  const [previewPage, setPreviewPage] = useState(0);
  const PREVIEW_PAGE_SIZE = 10;
  const [previewLoading, setPreviewLoading] = useState(false);

  // Integration state
  const [integrationBundle, setIntegrationBundle] = useState(null);
  const [integrationLoading, setIntegrationLoading] = useState(false);
  const [integrationError, setIntegrationError] = useState(null);

  // Artifact selection state
  const [selectedArtifacts, setSelectedArtifacts] = useState([]);

  // Integration guide state
  const [guide, setGuide] = useState(null);
  const [guideLoading, setGuideLoading] = useState(false);
  const [guideError, setGuideError] = useState(null);
  const [expandedSection, setExpandedSection] = useState(null);

  // Edge-case analysis state
  const [edgeCases, setEdgeCases] = useState(null);
  const [edgeCaseLoading, setEdgeCaseLoading] = useState(false);
  const [edgeCaseError, setEdgeCaseError] = useState(null);
  const [edgeCaseFilter, setEdgeCaseFilter] = useState("all");

  // Active analysis panel
  const [activeAnalysisPanel, setActiveAnalysisPanel] = useState(null);

  // Partition analysis state
  const [partitions, setPartitions] = useState(null);
  const [partitionLoading, setPartitionLoading] = useState(false);
  const [partitionError, setPartitionError] = useState(null);
  const [partitionFilter, setPartitionFilter] = useState("all");
  const [partitionView, setPartitionView] = useState("partitions"); // "partitions" | "datasets" | "viz"
  const [expandedViz, setExpandedViz] = useState(null);

  // Dataset split controls (initialized from URL params if passed from home page)
  const [splitEnabled, setSplitEnabled] = useState(() => searchParams.get("split") === "1");
  const [splitTotalRows, setSplitTotalRows] = useState(() => parseInt(searchParams.get("split_total")) || 100);
  const [splitValidPct, setSplitValidPct] = useState(() => parseFloat(searchParams.get("split_valid")) || 80);
  const [splitInvalidPct, setSplitInvalidPct] = useState(() => parseFloat(searchParams.get("split_invalid")) || 10);
  const [splitBoundaryPct, setSplitBoundaryPct] = useState(() => parseFloat(searchParams.get("split_boundary")) || 10);
  const [splitDuplicatePct, setSplitDuplicatePct] = useState(() => parseFloat(searchParams.get("split_duplicate")) || 0);

  const splitSum = splitValidPct + splitInvalidPct + splitBoundaryPct + splitDuplicatePct;
  const splitValid = Math.round(splitSum * 100) / 100 === 100;

  const fetchSummary = useCallback(() => {
    if (!sessionId && !historyId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);

    if (historyId) {
      // Load from persisted history instead of in-memory session
      getHistoryRecord(historyId)
        .then((rec) => {
          setHistoryData(rec.data || {});
          setSummary({
            session_id: rec.id,
            uploaded_files: (rec.source_files || []).map(f => typeof f === 'string' ? { name: f, filename: f, file_type: 'unknown', size: 0, size_bytes: 0 } : { name: f.filename || f.name || 'unknown', filename: f.filename || f.name || 'unknown', file_type: f.file_type || 'unknown', size: f.size_bytes || f.size || 0, size_bytes: f.size_bytes || f.size || 0 }),
            tables_parsed: (rec.tables || []).length,
            generation_order: rec.generation_order || [],
            row_count: rec.row_count || 0,
            total_rows: rec.total_rows || 0,
            negative_cases: rec.negative_cases || 0,
            exports: [],
            generated_at: rec.created_at,
            ai_enhanced: rec.ai_enhanced || false,
          });
          // Pre-populate saved analysis results from history
          if (rec.edge_cases) setEdgeCases(rec.edge_cases);
          if (rec.partitions) setPartitions(rec.partitions);
          if (rec.integration_bundle) setIntegrationBundle(rec.integration_bundle);
          if (rec.integration_guide) {
            setGuide(rec.integration_guide);
            if (rec.integration_guide.sections?.length > 0) setExpandedSection(0);
          }
          // Restore a live session from history so analysis endpoints work
          restoreSessionFromHistory(historyId)
            .then((res) => setRestoredSessionId(res.session_id))
            .catch(() => {}); // non-fatal if restore fails (old records without schema)
        })
        .catch((err) => setError(parseApiError(err)))
        .finally(() => setLoading(false));
    } else {
      getSummary(sessionId)
        .then(setSummary)
        .catch((err) => setError(parseApiError(err)))
        .finally(() => setLoading(false));
    }
  }, [sessionId, historyId]);

  useEffect(() => {
    fetchSummary();
  }, [fetchSummary]);

  // Auto-select first table for preview when summary loads
  useEffect(() => {
    if (summary && summary.generation_order?.length > 0 && !previewTable) {
      loadPreview(summary.generation_order[0], 0);
    }
  }, [summary]);

  const loadPreview = async (tableName, page = 0) => {
    if (previewTable === tableName && page === previewPage) {
      setPreviewTable(null);
      setPreviewData(null);
      setPreviewPage(0);
      return;
    }
    setPreviewTable(tableName);
    setPreviewPage(page);
    setPreviewLoading(true);
    try {
      if (historyId && historyData) {
        // Load preview from in-memory history data
        const allRows = historyData[tableName] || [];
        const offset = page * PREVIEW_PAGE_SIZE;
        setPreviewData({
          table: tableName,
          columns: allRows.length > 0 ? Object.keys(allRows[0]) : [],
          rows: allRows.slice(offset, offset + PREVIEW_PAGE_SIZE),
          total: allRows.length,
          total_rows: allRows.length,
          offset,
          limit: PREVIEW_PAGE_SIZE,
        });
      } else {
        const data = await getPreview(sessionId, tableName, PREVIEW_PAGE_SIZE, page * PREVIEW_PAGE_SIZE);
        setPreviewData(data);
      }
    } catch {
      setPreviewData(null);
    } finally {
      setPreviewLoading(false);
    }
  };

  const goToPage = (page) => {
    if (previewTable) loadPreview(previewTable, page);
  };

  const handleGenerateIntegration = async () => {
    if (!effectiveSessionId) { setIntegrationError('No session available. Please generate data first.'); return; }
    setIntegrationLoading(true);
    setIntegrationError(null);
    try {
      const bundle = await generateIntegration(
        effectiveSessionId,
        "http://localhost:8080",
        selectedArtifacts.length > 0 ? selectedArtifacts : null
      );
      setIntegrationBundle(bundle);
      const hid = historyId || sessionId;
      if (hid) updateHistoryRecord(hid, { integration_bundle: bundle }).catch(() => {});
    } catch (err) {
      setIntegrationError(parseApiError(err));
    } finally {
      setIntegrationLoading(false);
    }
  };

  const handleAnalyzeEdgeCases = async () => {
    if (!effectiveSessionId) { setEdgeCaseError('No session available. Please generate data first.'); return; }
    setEdgeCaseLoading(true);
    setEdgeCaseError(null);
    try {
      const data = await analyzeEdgeCases(effectiveSessionId);
      setEdgeCases(data);
      const hid = historyId || sessionId;
      if (hid) updateHistoryRecord(hid, { edge_cases: data }).catch(() => {});
    } catch (err) {
      setEdgeCaseError(parseApiError(err));
    } finally {
      setEdgeCaseLoading(false);
    }
  };

  const handleAnalyzePartitions = async () => {
    if (!effectiveSessionId) { setPartitionError('No session available. Please generate data first.'); return; }
    setPartitionLoading(true);
    setPartitionError(null);
    try {
      const splitConfig = splitEnabled
        ? { totalRows: splitTotalRows, validPct: splitValidPct, invalidPct: splitInvalidPct, boundaryPct: splitBoundaryPct, duplicatePct: splitDuplicatePct }
        : null;
      const data = await analyzePartitions(effectiveSessionId, 3, splitConfig);
      setPartitions(data);
      const hid = historyId || sessionId;
      if (hid) updateHistoryRecord(hid, { partitions: data }).catch(() => {});
    } catch (err) {
      setPartitionError(parseApiError(err));
    } finally {
      setPartitionLoading(false);
    }
  };

  const handleGetGuide = async () => {
    if (!effectiveSessionId) { setGuideError('No session available. Please generate data first.'); return; }
    setGuideLoading(true);
    setGuideError(null);
    try {
      const data = await getIntegrationGuide(effectiveSessionId);
      setGuide(data);
      if (data.sections?.length > 0) {
        setExpandedSection(0);
      }
      if (historyId || sessionId) updateHistoryRecord(historyId || sessionId, { integration_guide: data }).catch(() => {});
    } catch (err) {
      setGuideError(parseApiError(err));
    } finally {
      setGuideLoading(false);
    }
  };

  if (!sessionId && !historyId) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-16 text-center">
        <div className="w-16 h-16 bg-gray-100 dark:bg-[#2e2e32] rounded-full flex items-center justify-center mx-auto mb-6">
          <svg className="w-8 h-8 text-gray-400 dark:text-[rgba(235,235,245,0.38)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
        </div>
        <h2 className="text-xl font-semibold text-gray-700 dark:text-white mb-2">
          No results to display
        </h2>
        <p className="text-gray-500 dark:text-[rgba(235,235,245,0.6)] mb-6">
          Generate data from Upload, Reference, or Prompt to view results here.
        </p>
        <Link to="/generate">
          <Button>Go to Generate</Button>
        </Link>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-4">
        <Spinner size="lg" />
        <p className="text-sm text-gray-500">Loading results...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-8">
        <Alert type="error">{error}</Alert>
        <div className="mt-4 flex gap-3">
          <Button onClick={fetchSummary}>Retry</Button>
          <Link to="/">
            <Button variant="secondary">Back to Upload</Button>
          </Link>
        </div>
      </div>
    );
  }

  if (!summary) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-4">
        <Spinner size="lg" />
        <p className="text-sm text-gray-500">Loading results...</p>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <SpotlightSearch />
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
              Generation Results
            </h1>
            {summary.ai_enhanced && (
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-purple-100 dark:bg-[#9D4EDD]/15 text-purple-800 dark:text-[#9D4EDD] border border-purple-200 dark:border-[#9D4EDD]/30">
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
                AI Enhanced
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3">
          {/* Search trigger */}
          <button
            onClick={() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true }))}
            className="inline-flex items-center gap-2 h-9 px-4 min-w-[200px] rounded-lg border border-gray-200 dark:border-[#2e2e32] bg-white dark:bg-[#202127] text-gray-500 dark:text-[rgba(235,235,245,0.6)] hover:text-primary-600 dark:hover:text-[#00FF9F] hover:border-primary-300 dark:hover:border-[#00FF9F]/30 transition-colors text-sm"
            title="Search results (Ctrl+K)"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <span className="hidden sm:inline">Search tables, columns, data…</span>
            <kbd className="hidden sm:inline text-[10px] font-medium text-gray-400 bg-gray-100 border border-gray-200 rounded px-1 py-0.5">⌘K</kbd>
          </button>
          <Link to="/">
            <Button variant="secondary">
              <svg className="w-4 h-4 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              New Generation
            </Button>
          </Link>
        </div>
      </div>

      <ResultsTutorial />

      {/* ── Stats Row ─────────────────────────────────────── */}
      <div data-tour="tour-stats" className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard
          label="Tables Processed"
          value={summary.tables_parsed}
          color="primary"
          icon={
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2 1 3 3 3h10c2 0 3-1 3-3V7c0-2-1-3-3-3H7c-2 0-3 1-3 3z" />
            </svg>
          }
        />
        <StatCard
          label="Total Records"
          value={summary.total_rows.toLocaleString()}
          color="success"
          icon={
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
          }
        />
        <StatCard
          label="Rows / Table"
          value={summary.row_count.toLocaleString()}
          color="primary"
          icon={
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
            </svg>
          }
        />
        <StatCard
          label="Edge Cases"
          value={summary.negative_cases}
          color="warning"
          icon={<span className="text-base">⚠️</span>}
        />

      </div>

      {/* ── Downloads ─────────────────────────────────────── */}
      <Card data-tour="tour-downloads" className="mb-6">
        <CardHeader>
          <h2 className="text-lg font-semibold text-gray-900">Downloads</h2>
        </CardHeader>
        <CardBody>
          {/* ─ Data Files ─ */}
          <div className="mb-6">
            <div className="flex items-center gap-1.5 mb-3">
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Data Files</p>
              <span className="relative group">
                <svg className="w-3.5 h-3.5 text-gray-400 cursor-help" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 px-2.5 py-1.5 text-xs text-white bg-gray-800 rounded-lg whitespace-nowrap opacity-0 pointer-events-none group-hover:opacity-100 transition-opacity z-30">
                  Download the generated synthetic data in your preferred format
                </span>
              </span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {[
                { format: "csv", icon: "📊", label: "CSV", desc: "Comma-separated values" },
                { format: "json", icon: "📋", label: "JSON", desc: "Structured JSON arrays" },
                { format: "sql", icon: "💾", label: "SQL", desc: "INSERT statements" },
              ].map((dl) => {
                const available = summary.exports.some((e) => e.format === dl.format) || !!effectiveSessionId;
                const restoring = historyId && !effectiveSessionId;
                return (
                  <a
                    key={dl.format}
                    href={available && !restoring ? getDownloadUrl(dl.format, effectiveSessionId) : undefined}
                    download
                    className={`flex items-center gap-3 p-3 border-2 rounded-xl transition-all ${
                      restoring
                        ? "border-gray-200 bg-gray-50 opacity-70 cursor-wait"
                        : available
                        ? "border-gray-200 hover:border-primary-400 hover:bg-primary-50 cursor-pointer"
                        : "border-gray-100 bg-gray-50 opacity-50 pointer-events-none"
                    }`}
                  >
                    <span className="text-xl">{dl.icon}</span>
                    <div className="flex-1 min-w-0">
                      <p className="font-semibold text-gray-900 text-sm">{dl.label}</p>
                      <p className="text-xs text-gray-500">{dl.desc}</p>
                    </div>
                    {available && (
                      <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                      </svg>
                    )}
                  </a>
                );
              })}
            </div>
          </div>

          {/* ─ Divider ─ */}
          <div className="border-t border-gray-200 my-5" />

          {/* ─ Test Artifacts ─ */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-1.5">
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Test Artifacts</p>
                <span className="relative group">
                  <svg className="w-3.5 h-3.5 text-gray-400 cursor-help" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 px-2.5 py-1.5 text-xs text-white bg-gray-800 rounded-lg whitespace-nowrap opacity-0 pointer-events-none group-hover:opacity-100 transition-opacity z-30">
                    Generate Postman, SQL, Swagger, CI/CD &amp; mock artifacts for testing
                  </span>
                </span>
              </div>
              {!integrationBundle && (
                <Button
                  onClick={handleGenerateIntegration}
                  disabled={integrationLoading}
                  variant="primary"
                  size="sm"
                >
                  {integrationLoading ? (
                    <>
                      <Spinner size="sm" className="mr-2" />
                      Generating...
                    </>
                  ) : (
                    <>
                      <svg className="w-4 h-4 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
                      </svg>
                      Generate
                    </>
                  )}
                </Button>
              )}
            </div>

            {integrationError && (
              <Alert type="error" className="mb-4">{integrationError}</Alert>
            )}

            {!integrationBundle && !integrationLoading && !integrationError && (
              <div>
                <p className="text-sm text-gray-500 mb-3">
                  Select artifacts to generate, or leave all unchecked to generate everything:
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-3">
                  {[
                    { key: "postman", icon: "🟠", title: "Postman Collection", desc: "CRUD testing requests" },
                    { key: "sql_insert", icon: "💾", title: "SQL Inserts", desc: "FK-ordered scripts" },
                    { key: "api_json", icon: "📋", title: "API Payloads", desc: "REST-ready JSON" },
                    { key: "mock_payload", icon: "🧪", title: "Mock Payloads", desc: "Positive/negative splits" },
                    { key: "swagger_test", icon: "📘", title: "Swagger Tests", desc: "Status code tests" },
                    { key: "ci_bundle", icon: "⚙️", title: "CI/CD Pipeline", desc: "GitHub Actions configs" },
                  ].map((art) => {
                    const checked = selectedArtifacts.includes(art.key);
                    return (
                      <label
                        key={art.key}
                        className={`flex items-center gap-3 p-3 border-2 rounded-xl cursor-pointer transition-all ${
                          checked
                            ? "border-primary-400 bg-primary-50"
                            : "border-gray-200 hover:border-gray-300"
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setSelectedArtifacts((prev) => [...prev, art.key]);
                            } else {
                              setSelectedArtifacts((prev) => prev.filter((k) => k !== art.key));
                            }
                          }}
                          className="w-4 h-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                        />
                        <div className="min-w-0">
                          <span className="text-sm font-medium text-gray-900">
                            {art.icon} {art.title}
                          </span>
                          <p className="text-xs text-gray-500">{art.desc}</p>
                        </div>
                      </label>
                    );
                  })}
                </div>
                <p className="text-xs text-gray-400">
                  {selectedArtifacts.length === 0
                    ? "All artifacts will be generated"
                    : `${selectedArtifacts.length} artifact${selectedArtifacts.length > 1 ? "s" : ""} selected`}
                </p>
              </div>
            )}

            {integrationLoading && (
              <div className="flex flex-col items-center justify-center py-8 gap-3">
                <Spinner size="lg" />
                <p className="text-sm text-gray-500">Generating integration artifacts...</p>
              </div>
            )}

            {integrationBundle && (
              <div>
                {/* Download full bundle */}
                <div className="mb-4 p-4 bg-gradient-to-r from-primary-50 to-indigo-50 rounded-xl border border-primary-200">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 bg-primary-600 rounded-lg flex items-center justify-center">
                        <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                        </svg>
                      </div>
                      <div>
                        <p className="font-semibold text-gray-900 text-sm">Full Artifact Bundle</p>
                        <p className="text-xs text-gray-500">
                          {integrationBundle.artifacts.length} artifacts &middot; {integrationBundle.total_tables} tables &middot; {integrationBundle.total_rows} rows
                        </p>
                      </div>
                    </div>
                    <a href={getIntegrationDownloadUrl(effectiveSessionId)} download>
                      <Button variant="primary" size="sm">
                        <svg className="w-4 h-4 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                        </svg>
                        Download ZIP
                      </Button>
                    </a>
                  </div>
                </div>

                {/* Artifact cards */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {[
                    { icon: "🟠", title: "Postman Collection", desc: "Import into Postman for CRUD testing", file: "postman_collection.json", format: "postman" },
                    { icon: "💾", title: "SQL Inserts", desc: "Transaction-wrapped, FK-ordered scripts", file: "sql_inserts.sql", format: "sql_insert" },
                    { icon: "📋", title: "API Payloads", desc: "REST-ready JSON per entity (PKs stripped)", file: "api_payloads.json", format: "api_json" },
                    { icon: "🧪", title: "Mock Payloads", desc: "Positive / negative / boundary splits", file: "mock_payloads.json", format: "mock_payload" },
                    { icon: "📘", title: "Swagger Tests", desc: "Test cases with expected status codes", file: "swagger_tests.json", format: "swagger_test" },
                    { icon: "⚙️", title: "CI/CD Pipeline", desc: "GitHub Actions + QA pipeline configs", file: "ci_pipeline.json", format: "ci_bundle" },
                  ].map((artifact) => {
                    const info = integrationBundle.artifacts.find(
                      (a) => a.filename === artifact.file
                    );
                    return (
                      <div
                        key={artifact.format}
                        className="flex items-start gap-3 p-3 border border-gray-200 rounded-xl hover:border-primary-300 hover:bg-primary-50/30 transition-all"
                      >
                        <span className="text-xl">{artifact.icon}</span>
                        <div className="flex-1 min-w-0">
                          <p className="font-semibold text-gray-900 text-sm">{artifact.title}</p>
                          <p className="text-xs text-gray-500 mt-0.5">{artifact.desc}</p>
                          {info && (
                            <p className="text-xs text-gray-400 mt-1">
                              {(info.size_bytes / 1024).toFixed(1)} KB
                            </p>
                          )}
                        </div>
                        <Badge variant="success">✓</Badge>
                      </div>
                    );
                  })}
                </div>

                {/* Regenerate button */}
                <div className="mt-4 flex justify-end">
                  <Button variant="secondary" size="sm" onClick={() => { setIntegrationBundle(null); setSelectedArtifacts([]); }}>
                    Regenerate Artifacts
                  </Button>
                </div>
              </div>
            )}
          </div>
        </CardBody>
      </Card>

      {/* ── Dataset Preview ───────────────────────────────── */}
      <Card data-tour="tour-preview" className="mb-6">
        <CardHeader>
          <h2 className="text-lg font-semibold text-gray-900">
            Dataset Preview
          </h2>
        </CardHeader>
        <CardBody>
          <div className="flex flex-wrap gap-2 mb-4">
            {summary.generation_order.map((table) => (
              <button
                key={table}
                onClick={() => loadPreview(table)}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                  previewTable === table
                    ? "bg-primary-600 text-white shadow-sm"
                    : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                }`}
              >
                {table}
              </button>
            ))}
          </div>

          {previewLoading && (
            <div className="flex items-center justify-center py-8">
              <Spinner size="md" />
            </div>
          )}

          {previewTable && previewData && !previewLoading && ((
            () => {
              const totalPages = Math.ceil(previewData.total_rows / PREVIEW_PAGE_SIZE);
              const startRow = previewPage * PREVIEW_PAGE_SIZE + 1;
              const endRow = Math.min((previewPage + 1) * PREVIEW_PAGE_SIZE, previewData.total_rows);
              return (
            <div>
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs text-gray-500">
                  Showing {startRow}–{endRow} of{" "}
                  {previewData.total_rows} rows
                </span>
                <span className="text-xs text-gray-400">
                  {previewData.columns.length} columns
                </span>
              </div>
              <div className="overflow-x-auto border border-gray-200 rounded-lg">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-gray-50">
                      {previewData.columns.map((col) => (
                        <th
                          key={col}
                          className="text-left py-2.5 px-3 font-semibold text-gray-600 whitespace-nowrap border-b border-gray-200"
                        >
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {previewData.rows.map((row, ri) => (
                      <tr
                        key={ri}
                        className={`${
                          ri % 2 === 0 ? "bg-white" : "bg-gray-50/50"
                        } hover:bg-primary-50/30`}
                      >
                        {previewData.columns.map((col) => (
                          <td
                            key={col}
                            className="py-2 px-3 text-gray-700 whitespace-nowrap border-b border-gray-100 max-w-[200px] truncate"
                            title={String(row[col] ?? "")}
                          >
                            {row[col] === null ? (
                              <span className="text-gray-300 italic">null</span>
                            ) : (
                              String(row[col])
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination Controls */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between mt-4">
                  <button
                    onClick={() => goToPage(previewPage - 1)}
                    disabled={previewPage === 0}
                    className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    ← Previous
                  </button>
                  <div className="flex items-center gap-1">
                    {Array.from({ length: totalPages }, (_, i) => {
                      // Show first, last, and pages around current
                      if (i === 0 || i === totalPages - 1 || Math.abs(i - previewPage) <= 1) {
                        return (
                          <button
                            key={i}
                            onClick={() => goToPage(i)}
                            className={`w-8 h-8 text-xs font-medium rounded-lg transition-colors ${
                              i === previewPage
                                ? "bg-primary-600 text-white"
                                : "text-gray-600 hover:bg-gray-100"
                            }`}
                          >
                            {i + 1}
                          </button>
                        );
                      }
                      if (i === 1 && previewPage > 2) return <span key={i} className="text-gray-400 text-xs px-1">…</span>;
                      if (i === totalPages - 2 && previewPage < totalPages - 3) return <span key={i} className="text-gray-400 text-xs px-1">…</span>;
                      return null;
                    })}
                  </div>
                  <button
                    onClick={() => goToPage(previewPage + 1)}
                    disabled={previewPage >= totalPages - 1}
                    className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    Next →
                  </button>
                </div>
              )}
            </div>
              );
            }
          )())}
        </CardBody>
      </Card>

      {/* ── Analysis Tools (Card Grid) ────────────────── */}
      <div data-tour="tour-analysis" className="mb-6">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <button
            onClick={() => {
              if (activeAnalysisPanel === "edge") { setActiveAnalysisPanel(null); }
              else { setActiveAnalysisPanel("edge"); if (!edgeCases && !edgeCaseLoading) handleAnalyzeEdgeCases(); }
            }}
            className={`flex flex-col items-center justify-center gap-2 p-5 text-sm font-medium rounded-xl border-2 transition-all ${
              activeAnalysisPanel === "edge"
                ? "border-primary-400 bg-primary-50 text-primary-700 shadow-md"
                : "border-gray-200 bg-white text-gray-700 hover:border-gray-300 hover:bg-gray-50 hover:shadow-sm"
            }`}
          >
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
            </svg>
            <span>Edge-Case Analysis</span>
            {edgeCases && <span className="w-2 h-2 rounded-full bg-emerald-500" />}
          </button>
          <button
            onClick={() => {
              if (activeAnalysisPanel === "partition") { setActiveAnalysisPanel(null); }
              else { setActiveAnalysisPanel("partition"); if (!partitions && !partitionLoading) handleAnalyzePartitions(); }
            }}
            className={`flex flex-col items-center justify-center gap-2 p-5 text-sm font-medium rounded-xl border-2 transition-all ${
              activeAnalysisPanel === "partition"
                ? "border-primary-400 bg-primary-50 text-primary-700 shadow-md"
                : "border-gray-200 bg-white text-gray-700 hover:border-gray-300 hover:bg-gray-50 hover:shadow-sm"
            }`}
          >
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h7" />
            </svg>
            <span>Equivalence Partitioning</span>
            {partitions && <span className="w-2 h-2 rounded-full bg-emerald-500" />}
          </button>
          <button
            onClick={() => {
              if (activeAnalysisPanel === "guide") { setActiveAnalysisPanel(null); }
              else { setActiveAnalysisPanel("guide"); if (!guide && !guideLoading) handleGetGuide(); }
            }}
            className={`flex flex-col items-center justify-center gap-2 p-5 text-sm font-medium rounded-xl border-2 transition-all ${
              activeAnalysisPanel === "guide"
                ? "border-primary-400 bg-primary-50 text-primary-700 shadow-md"
                : "border-gray-200 bg-white text-gray-700 hover:border-gray-300 hover:bg-gray-50 hover:shadow-sm"
            }`}
          >
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
            <span>AI Integration Assistant</span>
            {guide && <span className="w-2 h-2 rounded-full bg-emerald-500" />}
          </button>
        </div>
      </div>

      {/* ── Edge-Case Panel ───────────────────────────────── */}
      {activeAnalysisPanel === "edge" && (
      <Card className="mb-6">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Edge-Case Analysis</h2>
              <p className="text-xs text-gray-500 mt-0.5">Null, boundary, negative, overflow, invalid format &amp; duplicate test values</p>
            </div>
          </div>
        </CardHeader>
        <CardBody>
          {edgeCaseError && <Alert type="error" className="mb-4">{edgeCaseError}</Alert>}

          {edgeCaseLoading && (
            <div className="flex flex-col items-center justify-center py-8 gap-3">
              <Spinner size="lg" />
              <p className="text-sm text-gray-500">Analyzing schema for edge cases...</p>
            </div>
          )}

          {edgeCases && (
            <div>
              <div className="grid grid-cols-3 gap-4 mb-6">
                <div className="bg-gray-50 rounded-lg p-3 text-center">
                  <p className="text-2xl font-bold text-gray-900">{edgeCases.total_rules}</p>
                  <p className="text-xs text-gray-500">Total Rules</p>
                </div>
                <div className="bg-gray-50 rounded-lg p-3 text-center">
                  <p className="text-2xl font-bold text-gray-900">{edgeCases.tables_analyzed}</p>
                  <p className="text-xs text-gray-500">Tables</p>
                </div>
                <div className="bg-gray-50 rounded-lg p-3 text-center">
                  <p className="text-2xl font-bold text-gray-900">{edgeCases.columns_analyzed}</p>
                  <p className="text-xs text-gray-500">Columns</p>
                </div>
              </div>

              <div className="flex flex-wrap gap-2 mb-4">
                <button
                  className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                    edgeCaseFilter === "all" ? "bg-primary-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                  }`}
                  onClick={() => setEdgeCaseFilter("all")}
                >
                  All ({edgeCases.total_rules})
                </button>
                {Object.entries(edgeCases.summary).map(([cat, count]) => (
                  <button
                    key={cat}
                    className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                      edgeCaseFilter === cat ? "bg-primary-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                    }`}
                    onClick={() => setEdgeCaseFilter(cat)}
                  >
                    {cat.replace(/_/g, " ")} ({count})
                  </button>
                ))}
              </div>

              <div className="border border-gray-200 rounded-xl overflow-hidden">
                <div className="max-h-96 overflow-y-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 sticky top-0">
                      <tr>
                        <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase">Table</th>
                        <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase">Column</th>
                        <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase">Category</th>
                        <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase">Test Value</th>
                        <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase">Expected</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {edgeCases.rules
                        .filter((r) => edgeCaseFilter === "all" || r.category === edgeCaseFilter)
                        .map((rule, idx) => (
                          <tr key={idx} className="hover:bg-gray-50">
                            <td className="px-4 py-2 text-gray-900 font-medium">{rule.table}</td>
                            <td className="px-4 py-2 text-gray-700">{rule.column}</td>
                            <td className="px-4 py-2">
                              <Badge
                                variant={
                                  rule.category === "null" ? "warning"
                                    : rule.category === "overflow" ? "error"
                                    : rule.category === "boundary" ? "primary"
                                    : rule.category === "negative" ? "error"
                                    : rule.category === "invalid_format" ? "error"
                                    : "default"
                                }
                              >
                                {rule.category.replace(/_/g, " ")}
                              </Badge>
                            </td>
                            <td className="px-4 py-2">
                              <code className="text-xs bg-gray-100 px-1.5 py-0.5 rounded text-gray-800 break-all max-w-xs inline-block truncate">
                                {rule.test_value === null ? "NULL" : String(rule.test_value).slice(0, 60)}
                              </code>
                            </td>
                            <td className="px-4 py-2 text-xs text-gray-500">{rule.expected_behavior}</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="mt-4 flex justify-end">
                <Button variant="secondary" size="sm" onClick={handleAnalyzeEdgeCases}>Re-analyze</Button>
              </div>
            </div>
          )}
        </CardBody>
      </Card>
      )}

      {/* ── Equivalence Partitioning Panel ────────────────── */}
      {activeAnalysisPanel === "partition" && (
      <Card className="mb-6">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Equivalence Partitioning</h2>
              <p className="text-xs text-gray-500 mt-0.5">Valid, invalid &amp; boundary partitions with proportional datasets</p>
            </div>
            {partitions && !partitionLoading && (
              <Button onClick={handleAnalyzePartitions} disabled={splitEnabled && !splitValid} variant="secondary" size="sm">
                Re-analyze
              </Button>
            )}
          </div>
        </CardHeader>
        <CardBody>
          {partitionError && <Alert type="error" className="mb-4">{partitionError}</Alert>}

          {/* Dataset Split Controls */}
          {!partitionLoading && (
            <div className="mb-4 p-4 bg-gray-50 rounded-lg border border-gray-200">
              <div className="flex items-center justify-between mb-3">
                <label className="flex items-center gap-2 text-sm font-medium text-gray-700 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={splitEnabled}
                    onChange={(e) => setSplitEnabled(e.target.checked)}
                    className="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  Enable Dataset Split Controls
                </label>
                {splitEnabled && !splitValid && (
                  <span className="text-xs text-red-500 font-medium">
                    Percentages must sum to 100% (currently {splitSum.toFixed(1)}%)
                  </span>
                )}
                {splitEnabled && splitValid && partitions && (
                  <span className="text-xs text-blue-600 font-medium">
                    Edit &amp; re-analyze to apply changes
                  </span>
                )}
              </div>

              {splitEnabled && (
                <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Total Rows</label>
                    <input
                      type="number"
                      min={1}
                      max={1000000}
                      value={splitTotalRows}
                      onChange={(e) => setSplitTotalRows(Math.max(1, parseInt(e.target.value) || 1))}
                      className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-green-700 mb-1">Positive %</label>
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step={1}
                      value={splitValidPct}
                      onChange={(e) => setSplitValidPct(Math.max(0, Math.min(100, parseFloat(e.target.value) || 0)))}
                      className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded-md focus:ring-green-500 focus:border-green-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-red-700 mb-1">Negative %</label>
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step={1}
                      value={splitInvalidPct}
                      onChange={(e) => setSplitInvalidPct(Math.max(0, Math.min(100, parseFloat(e.target.value) || 0)))}
                      className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded-md focus:ring-red-500 focus:border-red-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-amber-700 mb-1">Boundary %</label>
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step={1}
                      value={splitBoundaryPct}
                      onChange={(e) => setSplitBoundaryPct(Math.max(0, Math.min(100, parseFloat(e.target.value) || 0)))}
                      className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded-md focus:ring-amber-500 focus:border-amber-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-purple-700 mb-1">Duplicate %</label>
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step={1}
                      value={splitDuplicatePct}
                      onChange={(e) => setSplitDuplicatePct(Math.max(0, Math.min(100, parseFloat(e.target.value) || 0)))}
                      className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded-md focus:ring-purple-500 focus:border-purple-500"
                    />
                  </div>
                </div>
              )}

              {splitEnabled && splitValid && (
                <div className="mt-3 flex items-center gap-4 text-xs text-gray-600">
                  <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-green-500"></span>Valid: {Math.round(splitTotalRows * splitValidPct / 100)} rows</span>
                  <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500"></span>Invalid: {Math.round(splitTotalRows * splitInvalidPct / 100)} rows</span>
                  <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-500"></span>Boundary: {Math.round(splitTotalRows * splitBoundaryPct / 100)} rows</span>
                  <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-purple-500"></span>Duplicate: {Math.round(splitTotalRows * splitDuplicatePct / 100)} rows</span>
                </div>
              )}
            </div>
          )}

          {partitionLoading && (
            <div className="flex flex-col items-center justify-center py-8 gap-3">
              <Spinner size="lg" />
              <p className="text-sm text-gray-500">Partitioning schema inputs...</p>
            </div>
          )}

          {partitions && (
            <div>
              {partitions.split_config && (
                <div className="mb-4 px-3 py-2 bg-blue-50 border border-blue-200 rounded-lg flex items-center gap-3 flex-wrap text-xs text-blue-800">
                  <span className="font-medium">Split Applied:</span>
                  <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-green-500"></span>Valid {partitions.split_config.valid_pct}%</span>
                  <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500"></span>Invalid {partitions.split_config.invalid_pct}%</span>
                  <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-500"></span>Boundary {partitions.split_config.boundary_pct}%</span>
                  {partitions.split_config.duplicate_pct > 0 && (
                    <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-purple-500"></span>Duplicate {partitions.split_config.duplicate_pct}%</span>
                  )}
                  <span className="ml-auto text-gray-600">{partitions.total_generated_rows} total rows</span>
                </div>
              )}

              <div className="grid grid-cols-4 gap-4 mb-6">
                <div className="bg-gray-50 rounded-lg p-3 text-center">
                  <p className="text-2xl font-bold text-gray-900">{partitions.total_partitions}</p>
                  <p className="text-xs text-gray-500">Partitions</p>
                </div>
                <div className="bg-green-50 rounded-lg p-3 text-center">
                  <p className="text-2xl font-bold text-green-700">{partitions.summary.valid || 0}</p>
                  <p className="text-xs text-gray-500">Valid</p>
                </div>
                <div className="bg-red-50 rounded-lg p-3 text-center">
                  <p className="text-2xl font-bold text-red-700">{partitions.summary.invalid || 0}</p>
                  <p className="text-xs text-gray-500">Invalid</p>
                </div>
                <div className="bg-amber-50 rounded-lg p-3 text-center">
                  <p className="text-2xl font-bold text-amber-700">{partitions.summary.boundary || 0}</p>
                  <p className="text-xs text-gray-500">Boundary</p>
                </div>
              </div>

              <div className="flex gap-1 mb-4 bg-gray-100 rounded-lg p-1 w-fit">
                {[
                  { key: "partitions", label: "Partitions" },
                  { key: "datasets", label: "Datasets" },
                  { key: "viz", label: "Visualization" },
                ].map((tab) => (
                  <button
                    key={tab.key}
                    className={`px-4 py-1.5 rounded-md text-xs font-medium transition-colors ${
                      partitionView === tab.key ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700"
                    }`}
                    onClick={() => setPartitionView(tab.key)}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>

              {partitionView === "partitions" && (
                <div>
                  <div className="flex flex-wrap gap-2 mb-4">
                    {["all", "valid", "invalid", "boundary"].map((f) => (
                      <button
                        key={f}
                        className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                          partitionFilter === f
                            ? f === "valid" ? "bg-green-600 text-white"
                              : f === "invalid" ? "bg-red-600 text-white"
                              : f === "boundary" ? "bg-amber-600 text-white"
                              : "bg-primary-600 text-white"
                            : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                        }`}
                        onClick={() => setPartitionFilter(f)}
                      >
                        {f.charAt(0).toUpperCase() + f.slice(1)} ({f === "all" ? partitions.total_partitions : partitions.summary[f] || 0})
                      </button>
                    ))}
                  </div>

                  <div className="border border-gray-200 rounded-xl overflow-hidden">
                    <div className="max-h-96 overflow-y-auto">
                      <table className="w-full text-sm">
                        <thead className="bg-gray-50 sticky top-0">
                          <tr>
                            <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase">Table</th>
                            <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase">Column</th>
                            <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase">Type</th>
                            <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase">Label</th>
                            <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase">Samples</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                          {partitions.partitions
                            .filter((p) => partitionFilter === "all" || p.partition_type === partitionFilter)
                            .map((p, idx) => (
                              <tr key={idx} className="hover:bg-gray-50">
                                <td className="px-4 py-2 text-gray-900 font-medium">{p.table}</td>
                                <td className="px-4 py-2 text-gray-700">{p.column}</td>
                                <td className="px-4 py-2">
                                  <Badge variant={p.partition_type === "valid" ? "success" : p.partition_type === "invalid" ? "error" : "warning"}>
                                    {p.partition_type}
                                  </Badge>
                                </td>
                                <td className="px-4 py-2 text-gray-700 text-xs">{p.label}</td>
                                <td className="px-4 py-2">
                                  <div className="flex flex-wrap gap-1">
                                    {(p.sample_values || []).slice(0, 4).map((v, i) => (
                                      <code key={i} className="text-xs bg-gray-100 px-1.5 py-0.5 rounded text-gray-800 truncate max-w-[120px] inline-block">
                                        {v === null ? "NULL" : String(v).slice(0, 30)}
                                      </code>
                                    ))}
                                    {(p.sample_values || []).length > 4 && (
                                      <span className="text-xs text-gray-400">+{p.sample_values.length - 4}</span>
                                    )}
                                  </div>
                                </td>
                              </tr>
                            ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              )}

              {partitionView === "datasets" && (
                <div>
                  <p className="text-xs text-gray-500 mb-3">
                    {partitions.total_generated_rows} rows generated proportionally across partitions
                  </p>
                  {partitions.datasets.map((ds, dsIdx) => (
                    <div key={dsIdx} className="mb-4">
                      <h4 className="text-sm font-semibold text-gray-800 mb-2">
                        {ds.table} <span className="text-gray-400 font-normal">({ds.total_rows} rows)</span>
                      </h4>
                      <div className="border border-gray-200 rounded-xl overflow-hidden">
                        <div className="max-h-64 overflow-y-auto">
                          <table className="w-full text-xs">
                            <thead className="bg-gray-50 sticky top-0">
                              <tr>
                                <th className="px-3 py-2 text-left font-semibold text-gray-500 uppercase">Partition</th>
                                <th className="px-3 py-2 text-left font-semibold text-gray-500 uppercase">Type</th>
                                {ds.rows.length > 0 && Object.keys(ds.rows[0].row).map((k) => (
                                  <th key={k} className="px-3 py-2 text-left font-semibold text-gray-500 uppercase">{k}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100">
                              {ds.rows.map((r, rIdx) => (
                                <tr key={rIdx} className="hover:bg-gray-50">
                                  <td className="px-3 py-1.5 text-gray-700 truncate max-w-[180px]">{r.partition_label}</td>
                                  <td className="px-3 py-1.5">
                                    <Badge variant={r.partition_type === "valid" ? "success" : r.partition_type === "invalid" ? "error" : "warning"}>
                                      {r.partition_type}
                                    </Badge>
                                  </td>
                                  {Object.values(r.row).map((v, vIdx) => (
                                    <td key={vIdx} className="px-3 py-1.5 text-gray-800">
                                      <code className="text-xs truncate max-w-[100px] inline-block">
                                        {v === null ? "NULL" : String(v).slice(0, 25)}
                                      </code>
                                    </td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {partitionView === "viz" && (
                <div className="border border-gray-200 rounded-xl overflow-hidden">
                  <div className="max-h-96 overflow-y-auto divide-y divide-gray-200">
                    {partitions.visualizations.map((viz, vIdx) => (
                      <div key={vIdx}>
                        <button
                          className="w-full flex items-center justify-between px-4 py-2.5 bg-gray-50 hover:bg-gray-100 transition-colors text-left"
                          onClick={() => setExpandedViz(expandedViz === vIdx ? null : vIdx)}
                        >
                          <div className="flex items-center gap-2">
                            <h4 className="text-sm font-semibold text-gray-800">{viz.table}.{viz.column}</h4>
                            <span className="text-gray-400 text-xs">{viz.data_type}</span>
                            <span className="text-gray-400 text-xs">({viz.partitions.length} partitions)</span>
                          </div>
                          <svg className={`w-4 h-4 text-gray-400 transition-transform ${expandedViz === vIdx ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                          </svg>
                        </button>
                        {expandedViz === vIdx && (
                          <div className="px-4 py-3 flex gap-2 flex-wrap bg-white">
                            {viz.partitions.map((vp, vpIdx) => (
                              <div key={vpIdx} className="rounded-lg px-3 py-2 text-xs border" style={{ borderColor: vp.color, backgroundColor: vp.color + "10" }}>
                                <div className="font-semibold" style={{ color: vp.color }}>{vp.type}</div>
                                <div className="text-gray-600 mt-0.5 truncate max-w-[200px]">{vp.label}</div>
                                {vp.low !== null && vp.high !== null && (
                                  <div className="text-gray-400 mt-0.5">[{String(vp.low).slice(0, 12)} … {String(vp.high).slice(0, 12)}]</div>
                                )}
                                <div className="text-gray-400 mt-0.5">{vp.sample_count} samples</div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="mt-4 flex justify-end">
                <Button variant="secondary" size="sm" onClick={handleAnalyzePartitions}>Re-analyze</Button>
              </div>
            </div>
          )}
        </CardBody>
      </Card>
      )}

      {/* ── AI Assistant Panel ────────────────────────────── */}
      {activeAnalysisPanel === "guide" && (
      <Card className="mb-6">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">AI Integration Assistant</h2>
              <p className="text-xs text-gray-500 mt-0.5">Step-by-step guidance for using your datasets in real environments</p>
            </div>
          </div>
        </CardHeader>
        <CardBody>
          {guideError && <Alert type="error" className="mb-4">{guideError}</Alert>}

          {guideLoading && (
            <div className="flex flex-col items-center justify-center py-8 gap-3">
              <Spinner size="lg" />
              <p className="text-sm text-gray-500">Generating integration guide...</p>
            </div>
          )}

          {guide && (
            <div>
              <div className="mb-6 p-4 bg-blue-50 rounded-xl border border-blue-200">
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5">
                    <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                  </div>
                  <div>
                    <p className="font-semibold text-gray-900 text-sm">Overview</p>
                    <p className="text-sm text-gray-700 mt-1">{guide.overview}</p>
                  </div>
                </div>
              </div>

              <div className="space-y-3">
                {guide.sections.map((section, idx) => (
                  <div key={idx} className="border border-gray-200 rounded-xl overflow-hidden">
                    <button
                      className={`w-full flex items-center justify-between px-5 py-4 text-left transition-colors ${
                        expandedSection === idx ? "bg-primary-50 border-b border-primary-100" : "hover:bg-gray-50"
                      }`}
                      onClick={() => setExpandedSection(expandedSection === idx ? null : idx)}
                    >
                      <div className="flex items-center gap-3">
                        <span className="w-7 h-7 rounded-full bg-primary-100 text-primary-700 flex items-center justify-center text-xs font-bold">{idx + 1}</span>
                        <div>
                          <p className="font-semibold text-gray-900 text-sm">{section.scenario}</p>
                          <p className="text-xs text-gray-500 mt-0.5">{section.summary}</p>
                        </div>
                      </div>
                      <svg className={`w-5 h-5 text-gray-400 transition-transform ${expandedSection === idx ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                      </svg>
                    </button>

                    {expandedSection === idx && (
                      <div className="px-5 py-4">
                        {section.prerequisites.length > 0 && (
                          <div className="mb-4">
                            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Prerequisites</p>
                            <ul className="space-y-1">
                              {section.prerequisites.map((p, pi) => (
                                <li key={pi} className="flex items-start gap-2 text-sm text-gray-600">
                                  <span className="text-primary-500 mt-0.5">•</span>{p}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}

                        <div className="space-y-4">
                          {section.steps.map((step) => (
                            <div key={step.step_number} className="relative pl-8">
                              <div className="absolute left-0 top-0.5 w-6 h-6 rounded-full bg-gray-100 text-gray-600 flex items-center justify-center text-xs font-bold">{step.step_number}</div>
                              <div>
                                <p className="font-medium text-gray-900 text-sm">{step.title}</p>
                                <p className="text-xs text-gray-500 mt-0.5 mb-2">{step.description}</p>
                                {step.code_snippet && (
                                  <div className="relative group">
                                    <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto"><code>{step.code_snippet}</code></pre>
                                    {step.language && (
                                      <span className="absolute top-2 right-2 text-[10px] text-gray-500 bg-gray-800 px-2 py-0.5 rounded">{step.language}</span>
                                    )}
                                  </div>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>

                        {section.tips.length > 0 && (
                          <div className="mt-4 p-3 bg-amber-50 rounded-lg border border-amber-200">
                            <p className="text-xs font-semibold text-amber-700 mb-1">💡 Tips</p>
                            <ul className="space-y-1">
                              {section.tips.map((tip, ti) => (
                                <li key={ti} className="text-xs text-amber-800">{tip}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>

              <div className="mt-4 flex items-center justify-between">
                <Badge variant={guide.provider === "gateway" ? "primary" : "default"}>
                  {guide.provider === "gateway" ? "AI-Generated" : "Template-Based"}
                </Badge>
                <Button variant="secondary" size="sm" onClick={handleGetGuide}>Regenerate Guide</Button>
              </div>
            </div>
          )}
        </CardBody>
      </Card>
      )}


    </div>
  );
}
