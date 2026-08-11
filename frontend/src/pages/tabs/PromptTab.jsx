/**
 * Prompt Tab — natural language data description and generation.
 * Includes optional reference document upload for additional context.
 */

import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import Card, { CardBody, CardHeader } from "../../components/Card";
import Button from "../../components/Button";
import Spinner from "../../components/Spinner";
import Alert from "../../components/Alert";
import Badge from "../../components/Badge";
import { nlInferSchema, nlGenerateWithRef, parseApiError } from "../../services/api";

const EXAMPLE_PROMPTS = [
  {
    label: "Banking",
    icon: "🏦",
    prompt:
      "Generate banking customer data with accounts, transactions, and failed KYC verification cases",
  },
  {
    label: "Insurance",
    icon: "🛡️",
    prompt:
      "Create insurance data with policyholders, policies, claims, and denied claim scenarios",
  },
  {
    label: "E-commerce",
    icon: "🛒",
    prompt:
      "Generate e-commerce data with customers, products, orders, and refund edge cases",
  },
  {
    label: "Healthcare",
    icon: "🏥",
    prompt:
      "Create patient records with doctors, appointments, prescriptions, and missed appointment cases",
  },
  {
    label: "Education",
    icon: "🎓",
    prompt:
      "Generate university data with students, courses, enrollments, and academic probation cases",
  },
];

const STEPS = [
  { key: "infer", label: "Inferring schema from prompt" },
  { key: "reference", label: "Processing reference document" },
  { key: "generate", label: "Generating synthetic data" },
];

const DOC_TYPES = [
  { value: "", label: "Auto-detect", icon: "🔍" },
  { value: "screenshot", label: "Screenshot", icon: "📸" },
  { value: "schema_image", label: "Schema / ERD", icon: "🗄️" },
  { value: "brd_snippet", label: "BRD / Requirements", icon: "📋" },
  { value: "api_screenshot", label: "API / Swagger", icon: "🔌" },
];

const ACCEPTED = ".png,.jpg,.jpeg,.gif,.webp,.bmp,.tiff,.txt,.md,.html,.pdf,.sql,.json,.yaml,.yml";
const MAX_SIZE = 10 * 1024 * 1024; // 10 MB

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function PromptTab() {
  const navigate = useNavigate();

  // Form state
  const [prompt, setPrompt] = useState("");
  const [rowCount, setRowCount] = useState(100);
  const [includeValid, setIncludeValid] = useState(true);
  const [includeInvalid, setIncludeInvalid] = useState(false);
  const [includeBoundary, setIncludeBoundary] = useState(false);
  const [includeDuplicates, setIncludeDuplicates] = useState(false);

  // Dataset split config
  const [splitEnabled, setSplitEnabled] = useState(false);
  const [splitValidPct, setSplitValidPct] = useState(80);
  const [splitInvalidPct, setSplitInvalidPct] = useState(10);
  const [splitBoundaryPct, setSplitBoundaryPct] = useState(10);
  const [splitDuplicatePct, setSplitDuplicatePct] = useState(0);

  const splitSum = splitValidPct + splitInvalidPct + splitBoundaryPct + splitDuplicatePct;
  const splitIsValid = Math.round(splitSum * 100) / 100 === 100;

  const redistributeSplit = (valid, invalid, boundary, duplicate) => {
    if (!splitEnabled) return;
    const active = [
      valid && "valid",
      invalid && "invalid",
      boundary && "boundary",
      duplicate && "duplicate",
    ].filter(Boolean);
    if (active.length === 0) {
      setSplitValidPct(0); setSplitInvalidPct(0); setSplitBoundaryPct(0); setSplitDuplicatePct(0);
      return;
    }
    const each = Math.floor(100 / active.length);
    const remainder = 100 - each * active.length;
    setSplitValidPct(active.includes("valid") ? each + (active[0] === "valid" ? remainder : 0) : 0);
    setSplitInvalidPct(active.includes("invalid") ? each + (active[0] === "invalid" ? remainder : 0) : 0);
    setSplitBoundaryPct(active.includes("boundary") ? each + (active[0] === "boundary" ? remainder : 0) : 0);
    setSplitDuplicatePct(active.includes("duplicate") ? each + (active[0] === "duplicate" ? remainder : 0) : 0);
  };

  const handleToggleValid = (val) => { setIncludeValid(val); redistributeSplit(val, includeInvalid, includeBoundary, includeDuplicates); };
  const handleToggleInvalid = (val) => { setIncludeInvalid(val); redistributeSplit(includeValid, val, includeBoundary, includeDuplicates); };
  const handleToggleBoundary = (val) => { setIncludeBoundary(val); redistributeSplit(includeValid, includeInvalid, val, includeDuplicates); };
  const handleToggleDuplicate = (val) => { setIncludeDuplicates(val); redistributeSplit(includeValid, includeInvalid, includeBoundary, val); };

  // Settings collapse
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Reference doc state
  const [refFile, setRefFile] = useState(null);
  const [docType, setDocType] = useState("");

  // Schema preview
  const [schemaPreview, setSchemaPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // Generation state
  const [loading, setLoading] = useState(false);
  const [currentStep, setCurrentStep] = useState(-1);
  const [error, setError] = useState(null);

  const charCount = prompt.length;
  const isPromptValid = charCount >= 5 && charCount <= 2000;

  // ── File handling ────────────────────

  const handleFile = useCallback((f) => {
    if (!f) return;
    if (f.size > MAX_SIZE) {
      setError(`File exceeds 10 MB limit (${formatBytes(f.size)})`);
      return;
    }
    setRefFile(f);
    setError(null);
  }, []);

  const onDrop = useCallback(
    (e) => {
      e.preventDefault();
      const dropped = e.dataTransfer.files?.[0];
      handleFile(dropped);
    },
    [handleFile],
  );

  const onDragOver = useCallback((e) => {
    e.preventDefault();
  }, []);

  const removeFile = () => {
    setRefFile(null);
    setError(null);
  };

  const handlePreviewSchema = async () => {
    if (!isPromptValid) return;
    setPreviewLoading(true);
    setError(null);
    setSchemaPreview(null);
    try {
      const result = await nlInferSchema(prompt, rowCount);
      setSchemaPreview(result);
    } catch (err) {
      setError(parseApiError(err));
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleGenerate = async () => {
    if (!isPromptValid) return;
    setLoading(true);
    setError(null);
    setCurrentStep(0);

    try {
      setCurrentStep(0);
      await new Promise((r) => setTimeout(r, 400));

      if (refFile) {
        setCurrentStep(1);
        await new Promise((r) => setTimeout(r, 300));
      }

      setCurrentStep(2);
      const result = await nlGenerateWithRef(prompt, rowCount, includeInvalid, refFile, docType || null);

      navigate(`/results?session_id=${result.session_id}`);
    } catch (err) {
      setError(parseApiError(err));
    } finally {
      setLoading(false);
      setCurrentStep(-1);
    }
  };

  const selectExample = (exPrompt) => {
    setPrompt(exPrompt);
    setSchemaPreview(null);
    setError(null);
  };

  return (
    <>
      {/* Prompt Card */}
      <Card className="mb-6">
        <CardHeader>
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-gray-900">
              Your Prompt
            </h2>
            <span
              className={`text-xs ${
                charCount > 2000
                  ? "text-red-500"
                  : charCount > 0
                  ? "text-gray-400"
                  : "text-gray-300"
              }`}
            >
              {charCount} / 2,000
            </span>
          </div>
        </CardHeader>
        <CardBody>
          <div className="relative">
            <textarea
              value={prompt}
              onChange={(e) => {
                setPrompt(e.target.value);
                setSchemaPreview(null);
              }}
              placeholder="e.g. Generate banking customer data with accounts, transactions, and failed KYC verification cases..."
              rows={4}
              maxLength={2000}
              className="w-full px-4 py-3 pr-12 border border-gray-300 rounded-lg text-sm text-gray-900 placeholder-gray-400 focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none resize-y"
            />
            <button
              type="button"
              onClick={() => document.getElementById("ref-file-input").click()}
              className="absolute bottom-3 right-3 w-8 h-8 flex items-center justify-center rounded-full bg-gray-100 hover:bg-primary-100 text-gray-500 hover:text-primary-600 transition-colors border border-gray-200 hover:border-primary-300"
              title="Attach a file"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
            </button>
            <input
              id="ref-file-input"
              type="file"
              accept={ACCEPTED}
              className="hidden"
              onChange={(e) => handleFile(e.target.files?.[0])}
            />
          </div>

          {/* Attached file indicator */}
          {refFile && (
            <div className="mt-2 flex items-center gap-2 px-3 py-2 bg-gray-50 rounded-lg border border-gray-200">
              <span className="text-sm">
                {refFile.type.startsWith("image/") ? "🖼️" : "📄"}
              </span>
              <span className="text-sm font-medium text-gray-700 truncate flex-1">{refFile.name}</span>
              <span className="text-xs text-gray-400">{formatBytes(refFile.size)}</span>
              <button
                onClick={removeFile}
                className="text-gray-400 hover:text-red-500 transition-colors p-0.5"
                title="Remove attachment"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          )}

          {/* Example prompts */}
          <div className="mt-4">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
              Try an example
            </p>
            <div className="flex flex-wrap gap-2">
              {EXAMPLE_PROMPTS.map((ex) => (
                <button
                  key={ex.label}
                  onClick={() => selectExample(ex.prompt)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gray-100 text-sm font-medium text-gray-700 hover:bg-gray-200 transition-colors"
                >
                  <span>{ex.icon}</span>
                  {ex.label}
                </button>
              ))}
            </div>
          </div>

        </CardBody>
      </Card>

      {/* Configuration Card */}
      <Card className="mb-6">
        <CardHeader>
          <button
            type="button"
            onClick={() => setSettingsOpen(!settingsOpen)}
            className="w-full flex items-center justify-between"
          >
            <h2 className="text-lg font-semibold text-gray-900">
              Generation Settings
            </h2>
            <svg
              className={`w-5 h-5 text-gray-500 transition-transform ${settingsOpen ? "rotate-180" : ""}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
        </CardHeader>
        {settingsOpen && <CardBody>
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

            {/* Case type toggles */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-3">
                Case Types
              </label>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <ToggleCard
                  checked={includeValid}
                  onChange={handleToggleValid}
                  icon="✅"
                  title="Positive Cases"
                  description="Realistic rows that satisfy all constraints and relationships"
                />
                <ToggleCard
                  checked={includeInvalid}
                  onChange={handleToggleInvalid}
                  icon="❌"
                  title="Negative Cases"
                  description="Null required fields, broken FKs, invalid emails & enums"
                />
                <ToggleCard
                  checked={includeBoundary}
                  onChange={handleToggleBoundary}
                  icon="📏"
                  title="Boundary Cases"
                  description="Min/max values, edge-of-range dates, zero-length strings"
                />
                <ToggleCard
                  checked={includeDuplicates}
                  onChange={handleToggleDuplicate}
                  icon="🔁"
                  title="Duplicate Cases"
                  description="Duplicate values on unique/PK columns to test constraints"
                />
              </div>
            </div>

            {/* Dataset Split Distribution */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <label className="flex items-center gap-2 text-sm font-medium text-gray-700 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={splitEnabled}
                    onChange={(e) => {
                      const enabled = e.target.checked;
                      setSplitEnabled(enabled);
                      if (enabled) redistributeSplit(includeValid, includeInvalid, includeBoundary, includeDuplicates);
                    }}
                    className="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  Partition Split Distribution
                </label>
                {splitEnabled && !splitIsValid && (
                  <span className="text-xs text-red-500 font-medium">
                    Must sum to 100% (currently {splitSum.toFixed(1)}%)
                  </span>
                )}
              </div>
              <p className="text-xs text-gray-400 mb-3">
                Control how partition analysis distributes rows across valid, invalid &amp; boundary types
              </p>

              {splitEnabled && (
                <>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
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

                  {splitIsValid && (
                    <div className="mt-3 flex items-center gap-4 text-xs text-gray-600">
                      <span className="flex items-center gap-1">
                        <span className="w-2 h-2 rounded-full bg-green-500"></span>
                        Positive: {Math.round(rowCount * splitValidPct / 100)} rows
                      </span>
                      <span className="flex items-center gap-1">
                        <span className="w-2 h-2 rounded-full bg-red-500"></span>
                        Negative: {Math.round(rowCount * splitInvalidPct / 100)} rows
                      </span>
                      <span className="flex items-center gap-1">
                        <span className="w-2 h-2 rounded-full bg-amber-500"></span>
                        Boundary: {Math.round(rowCount * splitBoundaryPct / 100)} rows
                      </span>
                      <span className="flex items-center gap-1">
                        <span className="w-2 h-2 rounded-full bg-purple-500"></span>
                        Duplicate: {Math.round(rowCount * splitDuplicatePct / 100)} rows
                      </span>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </CardBody>}
      </Card>

      {/* Schema Preview */}
      {schemaPreview && (
        <Card className="mb-6">
          <CardHeader>
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-gray-900">
                Inferred Schema
              </h2>
              <Badge variant="primary">{schemaPreview.domain || "generic"}</Badge>
            </div>
          </CardHeader>
          <CardBody>
            {/* Generation order */}
            {schemaPreview.generation_order.length > 0 && (
              <div className="mb-5">
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                  Tables ({schemaPreview.generation_order.length})
                </p>
                <div className="flex flex-wrap items-center gap-2">
                  {schemaPreview.generation_order.map((table, i) => (
                    <div key={table} className="flex items-center gap-2">
                      <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary-50 text-primary-700 text-sm font-medium">
                        <span className="w-5 h-5 bg-primary-600 text-white rounded-full text-xs flex items-center justify-center font-bold">
                          {i + 1}
                        </span>
                        {table}
                      </span>
                      {i < schemaPreview.generation_order.length - 1 && (
                        <svg
                          className="w-4 h-4 text-gray-300"
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M9 5l7 7-7 7"
                          />
                        </svg>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Entities detail */}
            {schemaPreview.entities &&
              schemaPreview.entities.map((entity) => (
                <div
                  key={entity.name}
                  className="border border-gray-200 rounded-lg p-4 mb-3 last:mb-0"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <span className="font-semibold text-gray-900 text-sm">
                      {entity.name}
                    </span>
                    {entity.description && (
                      <span className="text-xs text-gray-400">
                        — {entity.description}
                      </span>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {entity.columns.map((col) => (
                      <span
                        key={col.name}
                        className="inline-flex items-center gap-1 px-2 py-0.5 bg-gray-50 rounded text-xs text-gray-600"
                        title={`${col.sql_type || col.type}${col.is_primary_key ? " PK" : ""}${col.is_nullable === false ? " NOT NULL" : ""}`}
                      >
                        {col.is_primary_key && (
                          <span className="text-amber-500">🔑</span>
                        )}
                        {col.name}
                        <span className="text-gray-400">
                          {col.sql_type || col.type}
                        </span>
                      </span>
                    ))}
                  </div>
                </div>
              ))}

            {/* SQL DDL toggle */}
            {schemaPreview.generated_sql && (
              <details className="mt-4">
                <summary className="text-xs font-semibold text-gray-500 uppercase tracking-wide cursor-pointer hover:text-gray-700">
                  View SQL DDL
                </summary>
                <pre className="mt-2 p-4 bg-gray-900 text-gray-100 rounded-lg text-xs overflow-x-auto leading-relaxed max-h-64">
                  {schemaPreview.generated_sql}
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
                  </span>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>
      )}

      {/* Action Buttons */}
      <div className="flex items-center gap-4">
        <Button
          size="lg"
          onClick={handleGenerate}
          disabled={loading || !isPromptValid}
        >
          {loading ? (
            <>
              <Spinner size="sm" className="mr-2" />
              Generating...
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

        <Button
          variant="secondary"
          onClick={handlePreviewSchema}
          disabled={loading || previewLoading || !isPromptValid}
        >
          {previewLoading ? (
            <>
              <Spinner size="sm" className="mr-2" />
              Inferring...
            </>
          ) : (
            "Preview Schema"
          )}
        </Button>
      </div>
    </>
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
