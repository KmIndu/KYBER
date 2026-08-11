/**
 * History Page — browse, view, and manage past data generation runs.
 */

import { useEffect, useState, useCallback } from "react";
import { Link, useNavigate } from "react-router-dom";
import Card, { CardBody, CardHeader } from "../components/Card";
import Button from "../components/Button";
import Spinner from "../components/Spinner";
import Alert from "../components/Alert";
import Badge from "../components/Badge";
import {
  getHistory,
  getHistoryRecord,
  deleteHistoryRecord,
  clearHistory,
  getDownloadUrl,
  parseApiError,
} from "../services/api";

export default function HistoryPage() {
  const navigate = useNavigate();
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Detail view
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Preview within detail
  const [previewTable, setPreviewTable] = useState(null);
  const [previewPage, setPreviewPage] = useState(0);
  const PAGE_SIZE = 10;

  // Confirm modals
  const [confirmDeleteId, setConfirmDeleteId] = useState(null);
  const [confirmClearAll, setConfirmClearAll] = useState(false);
  const [downloadMenuId, setDownloadMenuId] = useState(null);

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getHistory();
      setRecords(data.records || []);
    } catch (err) {
      setError(parseApiError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  const handleView = async (id) => {
    if (selectedId === id) {
      setSelectedId(null);
      setDetail(null);
      setPreviewTable(null);
      return;
    }
    setSelectedId(id);
    setDetailLoading(true);
    try {
      const data = await getHistoryRecord(id);
      setDetail(data);
      setPreviewTable(null);
      setPreviewPage(0);
    } catch {
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleDelete = async (id) => {
    try {
      await deleteHistoryRecord(id);
      setRecords((prev) => prev.filter((r) => r.id !== id));
      if (selectedId === id) {
        setSelectedId(null);
        setDetail(null);
      }
    } catch (err) {
      setError(parseApiError(err));
    }
    setConfirmDeleteId(null);
  };

  const handleClearAll = async () => {
    try {
      await clearHistory();
      setRecords([]);
      setSelectedId(null);
      setDetail(null);
    } catch (err) {
      setError(parseApiError(err));
    }
    setConfirmClearAll(false);
  };

  const previewRows = previewTable && detail?.data?.[previewTable]
    ? detail.data[previewTable].slice(previewPage * PAGE_SIZE, (previewPage + 1) * PAGE_SIZE)
    : [];
  const totalPreviewRows = previewTable && detail?.data?.[previewTable]
    ? detail.data[previewTable].length
    : 0;
  const totalPages = Math.ceil(totalPreviewRows / PAGE_SIZE);
  const previewColumns = previewRows.length > 0 ? Object.keys(previewRows[0]) : [];

  const formatDate = (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    return d.toLocaleDateString("en-US", {
      month: "short", day: "numeric", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-4">
        <Spinner size="lg" />
        <p className="text-gray-500">Loading history…</p>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Generation History</h1>
          <p className="text-gray-500 dark:text-[rgba(235,235,245,0.6)] mt-1">
            {records.length} past generation{records.length !== 1 ? "s" : ""}
          </p>
        </div>
        {records.length > 0 && (
          <Button
            variant="outline"
            className="text-red-600 border-red-300 hover:bg-red-50 dark:text-red-400 dark:border-red-800 dark:hover:bg-red-900/30"
            onClick={() => setConfirmClearAll(true)}
          >
            <svg className="w-4 h-4 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
            Clear All
          </Button>
        )}
      </div>

      {error && <Alert variant="error" className="mb-4">{error}</Alert>}

      {records.length === 0 ? (
        <Card>
          <CardBody>
            <div className="text-center py-12">
              <div className="w-16 h-16 bg-gray-100 dark:bg-[#2e2e32] rounded-full flex items-center justify-center mx-auto mb-4">
                <svg className="w-8 h-8 text-gray-400 dark:text-[rgba(235,235,245,0.38)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <h3 className="text-lg font-semibold text-gray-700 dark:text-white mb-2">No history yet</h3>
              <p className="text-gray-500 dark:text-[rgba(235,235,245,0.6)] mb-6">
                Generate some synthetic data and it will appear here automatically.
              </p>
              <Link to="/generate">
                <Button>Go to Generate</Button>
              </Link>
            </div>
          </CardBody>
        </Card>
      ) : (
        <div className="space-y-3">
          {records.map((rec) => (
            <Card key={rec.id} className={selectedId === rec.id ? "ring-2 ring-primary-500" : ""}>
              <CardBody>
                <div className="flex items-center justify-between">
                  {/* Left: info — clickable to open Results */}
                  <div
                    className="flex-1 min-w-0 cursor-pointer group"
                    onClick={() => navigate(`/results?history_id=${rec.id}`)}
                    title="Click to view full results"
                  >
                    <div className="flex items-center gap-3 mb-1">
                      <span className="text-sm font-medium text-gray-900 dark:text-white group-hover:text-primary-500 dark:group-hover:text-[#00FF9F] transition-colors truncate">
                        {rec.label
                          || rec.source_files?.map((f) => f.filename).join(", ")
                          || (rec.tables?.length ? rec.tables.join(", ") : `Generation ${rec.id?.slice(0, 8)}`)}
                      </span>
                      <Badge variant="primary">{rec.total_rows} rows</Badge>
                      {rec.negative_cases > 0 && (
                        <Badge variant="warning">{rec.negative_cases} negative</Badge>
                      )}
                    </div>
                    <div className="flex items-center gap-4 text-sm text-gray-500 dark:text-[rgba(235,235,245,0.6)]">
                      <span>{formatDate(rec.created_at)}</span>
                      <span>
                        {rec.tables?.length || 0} table{(rec.tables?.length || 0) !== 1 ? "s" : ""}
                      </span>
                    </div>
                  </div>

                  {/* Right: actions */}
                  <div className="flex items-center gap-2 ml-4">
                    <Button size="sm" variant="outline" onClick={() => handleView(rec.id)}>
                      {selectedId === rec.id ? "Close" : "Preview"}
                    </Button>
                    {/* Download dropdown */}
                    <div className="relative">
                      <button
                        className="p-2 text-gray-400 hover:text-primary-500 transition-colors"
                        title="Download"
                        onClick={() => setDownloadMenuId(downloadMenuId === rec.id ? null : rec.id)}
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                        </svg>
                      </button>
                      {downloadMenuId === rec.id && (
                        <div className="absolute right-0 mt-1 w-36 bg-white dark:bg-[#202127] border border-gray-200 dark:border-[#2e2e32] rounded-lg shadow-lg z-20 py-1">
                          {["csv", "json", "sql"].map((fmt) => (
                            <a
                              key={fmt}
                              href={getDownloadUrl(fmt, rec.id)}
                              download
                              className="block px-4 py-2 text-sm text-gray-700 dark:text-[rgba(255,255,245,0.86)] hover:bg-gray-50 dark:hover:bg-[#2e2e32] transition-colors"
                              onClick={() => setDownloadMenuId(null)}
                            >
                              {fmt.toUpperCase()}
                            </a>
                          ))}
                        </div>
                      )}
                    </div>
                    <button
                      className="p-2 text-gray-400 hover:text-red-500 transition-colors"
                      title="Delete"
                      onClick={() => setConfirmDeleteId(rec.id)}
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                </div>

                {/* Expanded detail */}
                {selectedId === rec.id && (
                  <div className="mt-4 pt-4 border-t border-gray-200 dark:border-[#2e2e32]">
                    {detailLoading ? (
                      <div className="flex items-center gap-2 py-4">
                        <Spinner size="sm" />
                        <span className="text-gray-500 text-sm">Loading data…</span>
                      </div>
                    ) : detail ? (
                      <div>
                        {/* Table selector */}
                        <div className="flex flex-wrap gap-2 mb-4">
                          {detail.tables?.map((t) => (
                            <button
                              key={t.table_name}
                              className={`px-3 py-1.5 text-sm rounded-lg border transition-colors ${
                                previewTable === t.table_name
                                  ? "bg-primary-50 dark:bg-[#00FF9F]/10 border-primary-300 dark:border-[#00FF9F]/30 text-primary-700 dark:text-[#00FF9F]"
                                  : "border-gray-200 dark:border-[#2e2e32] text-gray-600 dark:text-[rgba(235,235,245,0.6)] hover:bg-gray-50 dark:hover:bg-[#2e2e32]"
                              }`}
                              onClick={() => {
                                setPreviewTable(previewTable === t.table_name ? null : t.table_name);
                                setPreviewPage(0);
                              }}
                            >
                              {t.table_name} ({t.row_count} rows)
                            </button>
                          ))}
                        </div>

                        {/* Data preview table */}
                        {previewTable && previewColumns.length > 0 && (
                          <div>
                            <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-[#2e2e32]">
                              <table className="min-w-full text-sm">
                                <thead className="bg-gray-50 dark:bg-[#202127]">
                                  <tr>
                                    {previewColumns.map((col) => (
                                      <th key={col} className="px-3 py-2 text-left font-medium text-gray-600 dark:text-[rgba(235,235,245,0.6)] whitespace-nowrap">
                                        {col}
                                      </th>
                                    ))}
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-100 dark:divide-[#2e2e32]">
                                  {previewRows.map((row, i) => (
                                    <tr key={i} className="hover:bg-gray-50 dark:hover:bg-[#2e2e32]">
                                      {previewColumns.map((col) => (
                                        <td key={col} className="px-3 py-2 text-gray-700 dark:text-[rgba(255,255,245,0.86)] whitespace-nowrap max-w-[200px] truncate">
                                          {row[col] === null ? <span className="text-gray-300 italic">null</span> : String(row[col])}
                                        </td>
                                      ))}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>

                            {/* Pagination */}
                            {totalPages > 1 && (
                              <div className="flex items-center justify-between mt-3">
                                <span className="text-sm text-gray-500 dark:text-[rgba(235,235,245,0.6)]">
                                  Showing {previewPage * PAGE_SIZE + 1}–{Math.min((previewPage + 1) * PAGE_SIZE, totalPreviewRows)} of {totalPreviewRows}
                                </span>
                                <div className="flex gap-1">
                                  <button
                                    className="px-2 py-1 text-sm border rounded disabled:opacity-40"
                                    disabled={previewPage === 0}
                                    onClick={() => setPreviewPage((p) => p - 1)}
                                  >
                                    Prev
                                  </button>
                                  {Array.from({ length: Math.min(totalPages, 5) }, (_, i) => (
                                    <button
                                      key={i}
                                      className={`px-2 py-1 text-sm border rounded ${previewPage === i ? "bg-primary-50 border-primary-300 text-primary-700" : ""}`}
                                      onClick={() => setPreviewPage(i)}
                                    >
                                      {i + 1}
                                    </button>
                                  ))}
                                  <button
                                    className="px-2 py-1 text-sm border rounded disabled:opacity-40"
                                    disabled={previewPage >= totalPages - 1}
                                    onClick={() => setPreviewPage((p) => p + 1)}
                                  >
                                    Next
                                  </button>
                                </div>
                              </div>
                            )}
                          </div>
                        )}

                        {previewTable && previewColumns.length === 0 && (
                          <p className="text-sm text-gray-400 italic">No data available for this table.</p>
                        )}
                      </div>
                    ) : (
                      <p className="text-sm text-gray-400">Could not load record details.</p>
                    )}
                  </div>
                )}
              </CardBody>
            </Card>
          ))}
        </div>
      )}

      {/* Delete single confirm modal */}
      {confirmDeleteId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white dark:bg-[#202127] rounded-xl shadow-xl p-6 max-w-sm w-full mx-4 dark:border dark:border-[#2e2e32]">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">Delete record?</h3>
            <p className="text-sm text-gray-500 dark:text-[rgba(235,235,245,0.6)] mb-4">
              This will permanently delete this generation record and its data.
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setConfirmDeleteId(null)}>Cancel</Button>
              <Button className="bg-red-600 hover:bg-red-700" onClick={() => handleDelete(confirmDeleteId)}>Delete</Button>
            </div>
          </div>
        </div>
      )}

      {/* Clear all confirm modal */}
      {confirmClearAll && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white dark:bg-[#202127] rounded-xl shadow-xl p-6 max-w-sm w-full mx-4 dark:border dark:border-[#2e2e32]">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">Clear all history?</h3>
            <p className="text-sm text-gray-500 dark:text-[rgba(235,235,245,0.6)] mb-4">
              This will permanently delete all {records.length} generation record(s).
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setConfirmClearAll(false)}>Cancel</Button>
              <Button className="bg-red-600 hover:bg-red-700" onClick={handleClearAll}>Delete All</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
