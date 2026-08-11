/**
 * Upload Dashboard — file upload, generation configuration, and pipeline trigger.
 *
 * The three-step pipeline (Upload → Parse → Generate) runs
 * sequentially with progress indication, then navigates to ResultsPage.
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Card, { CardBody, CardHeader } from "../components/Card";
import Button from "../components/Button";
import FileDropzone, { validateFile } from "../components/FileDropzone";
import Spinner from "../components/Spinner";
import Alert from "../components/Alert";
import Badge from "../components/Badge";
import { uploadFiles, parseSession, generateData, parseApiError } from "../services/api";

const FILE_ICONS = {
  sql: "📄",
  openapi: "📋",
  bdd: "🧪",
};

const STEPS = [
  { key: "upload", label: "Uploading files" },
  { key: "parse", label: "Parsing schemas" },
  { key: "generate", label: "Generating data" },
];

export default function UploadPage() {
  const navigate = useNavigate();
  const [files, setFiles] = useState([]);
  const [rejections, setRejections] = useState([]);

  // Generation config
  const [rowCount, setRowCount] = useState(100);
  const [includeValid, setIncludeValid] = useState(true);
  const [includeInvalid, setIncludeInvalid] = useState(false);
  const [includeBoundary, setIncludeBoundary] = useState(false);
  const [includeDuplicates, setIncludeDuplicates] = useState(false);
  const [mergeSchemas, setMergeSchemas] = useState(true);

  // Progress state
  const [loading, setLoading] = useState(false);
  const [currentStep, setCurrentStep] = useState(-1);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState(null);

  const handleFilesSelected = (newFiles) => {
    setFiles((prev) => [...prev, ...newFiles]);
    setError(null);
    setRejections([]);
  };

  const handleValidationError = (rejected) => {
    setRejections(rejected);
  };

  const removeFile = (index) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const getFileType = (filename) => {
    const ext = filename.toLowerCase();
    if (ext.endsWith(".sql")) return "sql";
    if (ext.endsWith(".yaml") || ext.endsWith(".yml") || ext.endsWith(".json"))
      return "openapi";
    if (ext.endsWith(".feature") || ext.endsWith(".txt")) return "bdd";
    return "unknown";
  };

  const getFileTypeBadge = (type) => {
    const variants = { sql: "primary", openapi: "warning", bdd: "success" };
    return variants[type] || "default";
  };

  const handleGenerate = async () => {
    if (files.length === 0) {
      setError("Please upload at least one file.");
      return;
    }

    if (!includeValid && !includeInvalid && !includeBoundary && !includeDuplicates) {
      setError("Select at least one case type to generate.");
      return;
    }

    setLoading(true);
    setError(null);
    setUploadProgress(0);

    try {
      // Step 1: Upload
      setCurrentStep(0);
      const uploadResult = await uploadFiles(files, (pct) => setUploadProgress(pct));
      const sessionId = uploadResult.session_id;

      // Step 2: Parse
      setCurrentStep(1);
      await parseSession(sessionId, { mergeSchemas });

      // Step 3: Generate
      setCurrentStep(2);
      await generateData(sessionId, {
        rowCount,
        includeValid,
        includeInvalid,
        includeBoundary,
        includeDuplicates,
      });

      // Navigate to results
      navigate(`/results?session_id=${sessionId}`);
    } catch (err) {
      setError(parseApiError(err));
    } finally {
      setLoading(false);
      setCurrentStep(-1);
      setUploadProgress(0);
    }
  };

  const totalSize = files.reduce((s, f) => s + f.size, 0);

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">
          Generate Synthetic Test Data
        </h1>
        <p className="text-gray-500 mt-2">
          Upload your SQL schemas, OpenAPI specs, or BDD feature files to
          generate realistic test data with referential integrity.
        </p>
      </div>

      {/* Upload Card */}
      <Card className="mb-6">
        <CardHeader>
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-gray-900">
              Upload Files
            </h2>
            {files.length > 0 && (
              <span className="text-xs text-gray-400">
                {files.length} file{files.length !== 1 ? "s" : ""} &middot;{" "}
                {(totalSize / 1024).toFixed(1)} KB
              </span>
            )}
          </div>
        </CardHeader>
        <CardBody>
          <FileDropzone
            onFilesSelected={handleFilesSelected}
            onValidationError={handleValidationError}
          />

          {/* Rejected files warning */}
          {rejections.length > 0 && (
            <Alert type="warning" className="mt-3">
              <span className="font-medium">Some files were rejected:</span>
              <ul className="mt-1 list-disc list-inside text-xs">
                {rejections.map((r, i) => (
                  <li key={i}>
                    {r.name} &mdash; {r.reason}
                  </li>
                ))}
              </ul>
            </Alert>
          )}

          {/* File list */}
          {files.length > 0 && (
            <div className="mt-4 space-y-2">
              {files.map((file, i) => {
                const type = getFileType(file.name);
                return (
                  <div
                    key={i}
                    className="flex items-center justify-between bg-gray-50 rounded-lg px-4 py-2.5 group hover:bg-gray-100 transition-colors"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="text-lg shrink-0">
                        {FILE_ICONS[type] || "📁"}
                      </span>
                      <span className="text-sm font-medium text-gray-700 truncate">
                        {file.name}
                      </span>
                      <Badge variant={getFileTypeBadge(type)}>{type.toUpperCase()}</Badge>
                      <span className="text-xs text-gray-400 shrink-0">
                        {(file.size / 1024).toFixed(1)} KB
                      </span>
                    </div>
                    <button
                      onClick={() => removeFile(i)}
                      className="text-gray-300 hover:text-red-500 transition-colors opacity-0 group-hover:opacity-100"
                      title="Remove file"
                    >
                      <svg
                        className="w-4 h-4"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M6 18L18 6M6 6l12 12"
                        />
                      </svg>
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </CardBody>
      </Card>

      {/* Configuration Card */}
      <Card className="mb-6">
        <CardHeader>
          <h2 className="text-lg font-semibold text-gray-900">
            Generation Configuration
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
                      Math.min(1000000, Math.max(1, Number(e.target.value) || 1))
                    )
                  }
                  className="w-32 px-3 py-2 border border-gray-300 rounded-lg text-sm text-center focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                />
                <span className="text-xs text-gray-400">max 1,000,000</span>
              </div>
            </div>

            {/* Schema merge toggle */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-3">
                Multi-File Schema Mode
              </label>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <ToggleCard
                  checked={mergeSchemas}
                  onChange={setMergeSchemas}
                  icon="🔗"
                  title="Merge All Schemas"
                  description="Combine tables from all uploaded files into one unified schema"
                />
                <ToggleCard
                  checked={!mergeSchemas}
                  onChange={(v) => setMergeSchemas(!v)}
                  icon="📂"
                  title="Highest Priority Only"
                  description="Use only the highest-priority file (SQL > OpenAPI > CSV > XLSX > XML)"
                />
              </div>
            </div>

            {/* Case type toggles */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-3">
                Case Types
              </label>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <ToggleCard
                  checked={includeValid}
                  onChange={setIncludeValid}
                  icon="✅"
                  title="Positive Cases"
                  description="Realistic rows that satisfy all constraints and relationships"
                />
                <ToggleCard
                  checked={includeInvalid}
                  onChange={setIncludeInvalid}
                  icon="❌"
                  title="Negative Cases"
                  description="Null required fields, broken FKs, invalid emails & enums"
                />
                <ToggleCard
                  checked={includeBoundary}
                  onChange={setIncludeBoundary}
                  icon="📏"
                  title="Boundary Cases"
                  description="Min/max values, edge-of-range dates, zero-length strings"
                />
                <ToggleCard
                  checked={includeDuplicates}
                  onChange={setIncludeDuplicates}
                  icon="🔁"
                  title="Duplicate Cases"
                  description="Duplicate values on unique/PK columns to test constraints"
                />
              </div>
            </div>
          </div>
        </CardBody>
      </Card>

      {/* Error */}
      {error && !loading && (
        <Alert type="error" className="mb-6">
          <div className="flex items-start justify-between gap-4">
            <span>{error}</span>
            <button
              onClick={handleGenerate}
              className="shrink-0 text-xs font-semibold text-red-700 hover:text-red-900 underline"
            >
              Retry
            </button>
          </div>
        </Alert>
      )}

      {/* Progress Indicator */}
      {loading && (
        <Card className="mb-6">
          <CardBody>
            <div className="space-y-4">
              {STEPS.map((s, i) => (
                <div key={s.key} className="flex items-center gap-3">
                  <div className="flex-shrink-0">
                    {currentStep > i ? (
                      <div className="w-6 h-6 rounded-full bg-emerald-500 flex items-center justify-center">
                        <svg
                          className="w-3.5 h-3.5 text-white"
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={3}
                            d="M5 13l4 4L19 7"
                          />
                        </svg>
                      </div>
                    ) : currentStep === i ? (
                      <Spinner size="sm" />
                    ) : (
                      <div className="w-6 h-6 rounded-full border-2 border-gray-200" />
                    )}
                  </div>
                  <span
                    className={`text-sm font-medium ${
                      currentStep === i
                        ? "text-primary-700"
                        : currentStep > i
                        ? "text-emerald-600"
                        : "text-gray-400"
                    }`}
                  >
                    {s.label}
                    {currentStep === 0 && i === 0 && uploadProgress > 0 && uploadProgress < 100 && (
                      <span className="ml-2 text-xs font-normal text-gray-400">
                        {uploadProgress}%
                      </span>
                    )}
                  </span>
                </div>
              ))}

              {/* Upload progress bar */}
              {currentStep === 0 && (
                <div className="ml-9">
                  <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-primary-500 rounded-full transition-all duration-300 ease-out"
                      style={{ width: `${uploadProgress}%` }}
                    />
                  </div>
                </div>
              )}
            </div>
          </CardBody>
        </Card>
      )}

      {/* Generate Button */}
      <div className="flex items-center gap-4">
        <Button
          size="lg"
          onClick={handleGenerate}
          disabled={loading || files.length === 0}
        >
          {loading ? (
            <>
              <Spinner size="sm" className="mr-2" />
              Processing...
            </>
          ) : (
            <>
              <svg
                className="w-5 h-5 mr-2"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M13 10V3L4 14h7v7l9-11h-7z"
                />
              </svg>
              Generate Data
            </>
          )}
        </Button>
        {files.length === 0 && !loading && (
          <span className="text-sm text-gray-400">
            Upload at least one file to get started
          </span>
        )}
      </div>
    </div>
  );
}

/* ── Toggle card sub-component ──────────────────────────────── */

function ToggleCard({ checked, onChange, icon, title, description }) {
  return (
    <label
      className={`relative flex items-start gap-3 p-4 rounded-xl border-2 cursor-pointer transition-all ${
        checked
          ? "border-primary-500 bg-primary-50/50 shadow-sm"
          : "border-gray-200 hover:border-gray-300 bg-white"
      }`}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="sr-only"
      />
      <span className="text-xl mt-0.5">{icon}</span>
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-gray-900">{title}</span>
          <div
            className={`w-8 h-5 rounded-full transition-colors flex items-center ${
              checked ? "bg-primary-600 justify-end" : "bg-gray-300 justify-start"
            }`}
          >
            <div className="w-3.5 h-3.5 bg-white rounded-full mx-0.5 shadow-sm" />
          </div>
        </div>
        <p className="text-xs text-gray-500 mt-0.5 leading-relaxed">{description}</p>
      </div>
    </label>
  );
}
