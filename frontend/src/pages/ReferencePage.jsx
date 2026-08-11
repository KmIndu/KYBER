/**
 * Reference Document Ingestion Page — upload screenshots, schema images,
 * BRD snippets, or API screenshots and generate synthetic data.
 *
 * The backend runs OCR + heuristic extraction + AI enrichment,
 * then generates data based on the inferred schema.
 */

import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import Card, { CardBody, CardHeader } from "../components/Card";
import Button from "../components/Button";
import Spinner from "../components/Spinner";
import Alert from "../components/Alert";
import Badge from "../components/Badge";
import {
  referenceIngest,
  referenceGenerate,
  parseApiError,
} from "../services/api";

const DOC_TYPES = [
  { value: "", label: "Auto-detect", icon: "🔍" },
  { value: "screenshot", label: "Screenshot", icon: "📸" },
  { value: "schema_image", label: "Schema / ERD", icon: "🗄️" },
  { value: "brd_snippet", label: "BRD / Requirements", icon: "📋" },
  { value: "api_screenshot", label: "API / Swagger", icon: "🔌" },
];

const ACCEPTED = ".png,.jpg,.jpeg,.gif,.webp,.bmp,.tiff,.txt,.md,.html,.pdf";
const MAX_SIZE = 10 * 1024 * 1024; // 10 MB

const STEPS = [
  { key: "upload", label: "Uploading & running OCR" },
  { key: "extract", label: "Extracting entities & relationships" },
  { key: "generate", label: "Generating synthetic data" },
];

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function ConfidenceMeter({ value }) {
  const pct = Math.round(value * 100);
  const color =
    pct >= 70 ? "bg-emerald-500" : pct >= 40 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 h-2 bg-gray-200 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-gray-500">{pct}%</span>
    </div>
  );
}

export default function ReferencePage() {
  const navigate = useNavigate();

  // File state
  const [file, setFile] = useState(null);
  const [docType, setDocType] = useState("");
  const [isDragging, setIsDragging] = useState(false);

  // Config
  const [rowCount, setRowCount] = useState(100);
  const [includeInvalid, setIncludeInvalid] = useState(false);

  // Preview (ingest-only)
  const [preview, setPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // Generation state
  const [loading, setLoading] = useState(false);
  const [currentStep, setCurrentStep] = useState(-1);
  const [error, setError] = useState(null);

  // ── File handling ────────────────────

  const handleFile = useCallback((f) => {
    if (!f) return;
    if (f.size > MAX_SIZE) {
      setError(`File exceeds 10 MB limit (${formatBytes(f.size)})`);
      return;
    }
    setFile(f);
    setPreview(null);
    setError(null);
  }, []);

  const onDrop = useCallback(
    (e) => {
      e.preventDefault();
      setIsDragging(false);
      const dropped = e.dataTransfer.files?.[0];
      handleFile(dropped);
    },
    [handleFile],
  );

  const onDragOver = useCallback((e) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const onDragLeave = useCallback(() => setIsDragging(false), []);

  const removeFile = () => {
    setFile(null);
    setPreview(null);
    setError(null);
  };

  // ── Preview (ingest only) ────────────

  const handlePreview = async () => {
    if (!file) return;
    setPreviewLoading(true);
    setError(null);
    setPreview(null);
    try {
      const result = await referenceIngest(file, docType || null);
      setPreview(result);
    } catch (err) {
      setError(parseApiError(err));
    } finally {
      setPreviewLoading(false);
    }
  };

  // ── Generate ─────────────────────────

  const handleGenerate = async () => {
    if (!file) return;
    setLoading(true);
    setError(null);
    setCurrentStep(0);

    try {
      await new Promise((r) => setTimeout(r, 300));
      setCurrentStep(1);
      await new Promise((r) => setTimeout(r, 300));
      setCurrentStep(2);

      const result = await referenceGenerate(file, {
        docType: docType || null,
        rowCount,
        includeInvalid,
      });

      navigate(`/results?session_id=${result.session_id}`);
    } catch (err) {
      setError(parseApiError(err));
    } finally {
      setLoading(false);
      setCurrentStep(-1);
    }
  };

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">
          Reference Document Ingestion
        </h1>
        <p className="text-gray-500 mt-2">
          Upload screenshots, schema diagrams, BRD snippets, or API docs.
          We'll extract entities, infer relationships, and generate synthetic
          data automatically.
        </p>
      </div>

      {/* Upload Card */}
      <Card className="mb-6">
        <CardHeader>
          <h2 className="text-lg font-semibold text-gray-900">
            Upload Document
          </h2>
        </CardHeader>
        <CardBody>
          {!file ? (
            <div
              onDrop={onDrop}
              onDragOver={onDragOver}
              onDragLeave={onDragLeave}
              className={`border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-all ${
                isDragging
                  ? "border-primary-500 bg-primary-50"
                  : "border-gray-300 hover:border-gray-400 bg-gray-50"
              }`}
              onClick={() => document.getElementById("ref-file-input").click()}
            >
              <div className="flex flex-col items-center gap-3">
                <div className="w-12 h-12 bg-primary-100 text-primary-600 rounded-xl flex items-center justify-center text-2xl">
                  📄
                </div>
                <div>
                  <p className="text-sm font-medium text-gray-700">
                    Drop a file here or{" "}
                    <span className="text-primary-600 underline">browse</span>
                  </p>
                  <p className="text-xs text-gray-400 mt-1">
                    Images (PNG, JPG, WEBP, BMP, TIFF) or text (TXT, MD, HTML) — up to 10 MB
                  </p>
                </div>
              </div>
              <input
                id="ref-file-input"
                type="file"
                accept={ACCEPTED}
                className="hidden"
                onChange={(e) => handleFile(e.target.files?.[0])}
              />
            </div>
          ) : (
            <div className="flex items-center justify-between p-4 bg-gray-50 rounded-lg border border-gray-200">
              <div className="flex items-center gap-3 min-w-0">
                <span className="text-2xl">
                  {file.type.startsWith("image/") ? "🖼️" : "📄"}
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-900 truncate">
                    {file.name}
                  </p>
                  <p className="text-xs text-gray-400">
                    {formatBytes(file.size)}
                  </p>
                </div>
              </div>
              <button
                onClick={removeFile}
                className="text-gray-400 hover:text-red-500 transition-colors p-1"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          )}

          {/* Doc type selector */}
          <div className="mt-4">
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Document Type
            </label>
            <div className="flex flex-wrap gap-2">
              {DOC_TYPES.map((dt) => (
                <button
                  key={dt.value}
                  onClick={() => setDocType(dt.value)}
                  className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                    docType === dt.value
                      ? "bg-primary-600 text-white"
                      : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                  }`}
                >
                  <span>{dt.icon}</span>
                  {dt.label}
                </button>
              ))}
            </div>
          </div>
        </CardBody>
      </Card>

      {/* Configuration Card */}
      <Card className="mb-6">
        <CardHeader>
          <h2 className="text-lg font-semibold text-gray-900">
            Generation Settings
          </h2>
        </CardHeader>
        <CardBody>
          <div className="space-y-6">
            {/* Row count */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Rows per table
              </label>
              <div className="flex flex-wrap gap-2 mb-2">
                {[100, 1000, 10000, 100000, 500000, 1000000].map((preset) => (
                  <button
                    key={preset}
                    type="button"
                    onClick={() => setRowCount(preset)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                      rowCount === preset
                        ? "bg-primary-600 text-white shadow-sm"
                        : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                    }`}
                  >
                    {preset.toLocaleString()}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-500">Custom:</span>
                <input
                  type="number"
                  min={1}
                  max={1000000}
                  value={rowCount}
                  onChange={(e) =>
                    setRowCount(
                      Math.min(1000000, Math.max(1, Number(e.target.value) || 1)),
                    )
                  }
                  className="w-32 px-3 py-2 border border-gray-300 rounded-lg text-sm text-center focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                />
                <span className="text-xs text-gray-400">max 1,000,000</span>
              </div>
            </div>

            {/* Edge cases toggle */}
            <label
              className={`relative flex items-start gap-3 p-4 rounded-xl border-2 cursor-pointer transition-all ${
                includeInvalid
                  ? "border-primary-500 bg-primary-50/50 shadow-sm"
                  : "border-gray-200 hover:border-gray-300 bg-white"
              }`}
            >
              <input
                type="checkbox"
                checked={includeInvalid}
                onChange={(e) => setIncludeInvalid(e.target.checked)}
                className="sr-only"
              />
              <span className="text-xl mt-0.5">❌</span>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-gray-900">
                    Include Edge Cases
                  </span>
                  <div
                    className={`w-8 h-5 rounded-full transition-colors flex items-center ${
                      includeInvalid
                        ? "bg-primary-600 justify-end"
                        : "bg-gray-300 justify-start"
                    }`}
                  >
                    <div className="w-3.5 h-3.5 bg-white rounded-full mx-0.5 shadow-sm" />
                  </div>
                </div>
                <p className="text-xs text-gray-500 mt-0.5 leading-relaxed">
                  Add invalid, boundary, and duplicate records for negative testing
                </p>
              </div>
            </label>
          </div>
        </CardBody>
      </Card>

      {/* Extraction Preview */}
      {preview && (
        <Card className="mb-6">
          <CardHeader>
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-gray-900">
                Extracted Schema
              </h2>
              <div className="flex items-center gap-2">
                <Badge variant="primary">{preview.domain || "generic"}</Badge>
                <ConfidenceMeter value={preview.avg_confidence} />
              </div>
            </div>
          </CardHeader>
          <CardBody>
            {/* Warnings */}
            {preview.warnings?.length > 0 && (
              <div className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                <p className="text-xs font-semibold text-amber-700 mb-1">Warnings</p>
                <ul className="text-xs text-amber-600 space-y-0.5">
                  {preview.warnings.map((w, i) => (
                    <li key={i}>• {w}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Entities */}
            {preview.entities?.length > 0 ? (
              preview.entities.map((entity) => (
                <div
                  key={entity.name}
                  className="border border-gray-200 rounded-lg p-4 mb-3 last:mb-0"
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-gray-900 text-sm">
                        {entity.name}
                      </span>
                      <Badge
                        variant={
                          entity.source === "ai" ? "primary" : "default"
                        }
                      >
                        {entity.source}
                      </Badge>
                    </div>
                    <ConfidenceMeter value={entity.confidence} />
                  </div>
                  {entity.fields?.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {entity.fields.map((col) => (
                        <span
                          key={col.name}
                          className="inline-flex items-center gap-1 px-2 py-0.5 bg-gray-50 rounded text-xs text-gray-600"
                          title={`${col.data_type}${col.is_primary_key ? " PK" : ""}${col.nullable === false ? " NOT NULL" : ""} (${Math.round(col.confidence * 100)}%)`}
                        >
                          {col.is_primary_key && (
                            <span className="text-amber-500">🔑</span>
                          )}
                          {col.name}
                          <span className="text-gray-400">
                            {col.data_type}
                          </span>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))
            ) : (
              <p className="text-sm text-gray-400 italic">
                No entities extracted. Try a different document type or ensure
                the image contains readable schema information.
              </p>
            )}

            {/* Relationships */}
            {preview.relationships?.length > 0 && (
              <div className="mt-4">
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                  Relationships
                </p>
                <div className="space-y-1">
                  {preview.relationships.map((rel, i) => (
                    <div
                      key={i}
                      className="flex items-center gap-2 text-xs text-gray-600"
                    >
                      <span className="font-medium">{rel.from_entity}</span>
                      <span className="text-gray-400">.{rel.from_field}</span>
                      <svg className="w-4 h-4 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
                      </svg>
                      <span className="font-medium">{rel.to_entity}</span>
                      <span className="text-gray-400">.{rel.to_field}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* SQL DDL */}
            {preview.schema_sql && (
              <details className="mt-4">
                <summary className="text-xs font-semibold text-gray-500 uppercase tracking-wide cursor-pointer hover:text-gray-700">
                  View SQL DDL
                </summary>
                <pre className="mt-2 p-4 bg-gray-900 text-gray-100 rounded-lg text-xs overflow-x-auto leading-relaxed max-h-64">
                  {preview.schema_sql}
                </pre>
              </details>
            )}
          </CardBody>
        </Card>
      )}

      {/* Error */}
      {error && !loading && (
        <Alert type="error" className="mb-6">
          <div className="flex items-start justify-between gap-4">
            <span>{error}</span>
            <button
              onClick={() => setError(null)}
              className="shrink-0 text-xs font-semibold text-red-700 hover:text-red-900 underline"
            >
              Dismiss
            </button>
          </div>
        </Alert>
      )}

      {/* Progress */}
      {loading && (
        <Card className="mb-6">
          <CardBody>
            <div className="space-y-4">
              {STEPS.map((s, i) => (
                <div key={s.key} className="flex items-center gap-3">
                  <div className="flex-shrink-0">
                    {currentStep > i ? (
                      <div className="w-6 h-6 rounded-full bg-emerald-500 flex items-center justify-center">
                        <svg className="w-3.5 h-3.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                        </svg>
                      </div>
                    ) : currentStep === i ? (
                      <Spinner size="sm" />
                    ) : (
                      <div className="w-6 h-6 rounded-full bg-gray-200" />
                    )}
                  </div>
                  <span
                    className={`text-sm ${
                      currentStep >= i
                        ? "text-gray-900 font-medium"
                        : "text-gray-400"
                    }`}
                  >
                    {s.label}
                  </span>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>
      )}

      {/* Actions */}
      <div className="flex items-center gap-3">
        <Button
          onClick={handlePreview}
          variant="secondary"
          disabled={!file || loading || previewLoading}
        >
          {previewLoading ? (
            <>
              <Spinner size="sm" className="mr-2" /> Analyzing…
            </>
          ) : (
            "Preview Schema"
          )}
        </Button>
        <Button
          onClick={handleGenerate}
          disabled={!file || loading}
        >
          {loading ? (
            <>
              <Spinner size="sm" className="mr-2" /> Generating…
            </>
          ) : (
            "Generate Data"
          )}
        </Button>
      </div>
    </div>
  );
}
