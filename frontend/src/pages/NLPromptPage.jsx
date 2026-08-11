/**
 * Natural Language Prompt Page — describe data in plain English and generate.
 *
 * Users type a prompt (e.g. "Generate banking data with failed KYC"),
 * configure row count & edge-case toggle, then hit Generate.
 * The backend infers a schema and produces the data in one shot;
 * the user is redirected to the ResultsPage with the session.
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Card, { CardBody, CardHeader } from "../components/Card";
import Button from "../components/Button";
import Spinner from "../components/Spinner";
import Alert from "../components/Alert";
import Badge from "../components/Badge";
import { nlInferSchema, nlGenerate, parseApiError } from "../services/api";

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
  { key: "generate", label: "Generating synthetic data" },
];

export default function NLPromptPage() {
  const navigate = useNavigate();

  // Form state
  const [prompt, setPrompt] = useState("");
  const [rowCount, setRowCount] = useState(100);
  const [includeInvalid, setIncludeInvalid] = useState(false);

  // Schema preview
  const [schemaPreview, setSchemaPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // Generation state
  const [loading, setLoading] = useState(false);
  const [currentStep, setCurrentStep] = useState(-1);
  const [error, setError] = useState(null);

  const charCount = prompt.length;
  const isPromptValid = charCount >= 5 && charCount <= 2000;

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
      // Step 1: Infer (visual only — the /generate endpoint does both)
      setCurrentStep(0);
      // Brief pause so user sees the step
      await new Promise((r) => setTimeout(r, 400));

      // Step 2: Generate
      setCurrentStep(1);
      const result = await nlGenerate(prompt, rowCount, includeInvalid);

      // Navigate to results
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
    <div className="max-w-4xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">
          Describe Your Data
        </h1>
        <p className="text-gray-500 mt-2">
          Tell us what data you need in plain English. We'll infer the schema,
          generate realistic records, and validate everything automatically.
        </p>
      </div>

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
          <textarea
            value={prompt}
            onChange={(e) => {
              setPrompt(e.target.value);
              setSchemaPreview(null);
            }}
            placeholder="e.g. Generate banking customer data with accounts, transactions, and failed KYC verification cases..."
            rows={4}
            maxLength={2000}
            className="w-full px-4 py-3 border border-gray-300 rounded-lg text-sm text-gray-900 placeholder-gray-400 focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none resize-y"
          />

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
                      Math.min(1000000, Math.max(1, Number(e.target.value) || 1))
                    )
                  }
                  className="w-32 px-3 py-2 border border-gray-300 rounded-lg text-sm text-center focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                />
                <span className="text-xs text-gray-400">max 1,000,000</span>
              </div>
            </div>

            {/* Include invalid toggle */}
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
                  Add invalid emails, null required fields, broken FKs, boundary values, and duplicates
                </p>
              </div>
            </label>
          </div>
        </CardBody>
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
            <>
              <svg
                className="w-4 h-4 mr-1.5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                />
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                />
              </svg>
              Preview Schema
            </>
          )}
        </Button>

        {!isPromptValid && prompt.length > 0 && prompt.length < 5 && (
          <span className="text-sm text-gray-400">
            Prompt must be at least 5 characters
          </span>
        )}
        {prompt.length === 0 && !loading && (
          <span className="text-sm text-gray-400">
            Describe the data you need to get started
          </span>
        )}
      </div>
    </div>
  );
}
