/**
 * Drag-and-drop file upload zone with extension validation.
 *
 * Accepts .sql, .yaml, .yml, .json, .feature, and .txt files
 * up to 5 MB each. Invalid files are reported via the
 * `onValidationError` callback.
 */

import { useCallback, useState } from "react";

const ACCEPTED_EXTENSIONS = {
  ".sql": { type: "sql", label: "SQL Schema", color: "text-blue-600 bg-blue-50" },
  ".yaml": { type: "openapi", label: "OpenAPI", color: "text-purple-600 bg-purple-50" },
  ".yml": { type: "openapi", label: "OpenAPI", color: "text-purple-600 bg-purple-50" },
  ".json": { type: "openapi", label: "JSON / OpenAPI", color: "text-purple-600 bg-purple-50" },
  ".feature": { type: "bdd", label: "BDD", color: "text-green-600 bg-green-50" },
  ".txt": { type: "bdd", label: "BDD", color: "text-green-600 bg-green-50" },
  ".csv": { type: "csv", label: "CSV", color: "text-orange-600 bg-orange-50" },
  ".xlsx": { type: "xlsx", label: "Excel", color: "text-emerald-600 bg-emerald-50" },
  ".xml": { type: "xml", label: "XML", color: "text-rose-600 bg-rose-50" },
};

function getExtension(filename) {
  const idx = filename.lastIndexOf(".");
  return idx !== -1 ? filename.slice(idx).toLowerCase() : "";
}

export function validateFile(file) {
  const ext = getExtension(file.name);
  const entry = ACCEPTED_EXTENSIONS[ext];
  if (!entry) {
    return { valid: false, reason: `Unsupported file type: ${ext || "no extension"}` };
  }
  if (file.size > 5 * 1024 * 1024) {
    return { valid: false, reason: "File exceeds 5 MB limit" };
  }
  if (file.size === 0) {
    return { valid: false, reason: "File is empty" };
  }
  return { valid: true, type: entry.type, label: entry.label, color: entry.color };
}

export default function FileDropzone({ onFilesSelected, onValidationError, maxFiles = 10 }) {
  const [isDragging, setIsDragging] = useState(false);

  const processFiles = useCallback(
    (rawFiles) => {
      const accepted = [];
      const rejected = [];

      for (const file of rawFiles.slice(0, maxFiles)) {
        const result = validateFile(file);
        if (result.valid) {
          accepted.push(file);
        } else {
          rejected.push({ name: file.name, reason: result.reason });
        }
      }

      if (accepted.length > 0) {
        onFilesSelected(accepted);
      }
      if (rejected.length > 0 && onValidationError) {
        onValidationError(rejected);
      }
    },
    [onFilesSelected, onValidationError, maxFiles]
  );

  const handleDrop = useCallback(
    (e) => {
      e.preventDefault();
      setIsDragging(false);
      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0) processFiles(files);
    },
    [processFiles]
  );

  const handleDragOver = (e) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleFileInput = (e) => {
    const files = Array.from(e.target.files);
    if (files.length > 0) processFiles(files);
    e.target.value = "";
  };

  return (
    <div
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      className={`relative border-2 border-dashed rounded-xl p-10 text-center transition-all duration-200 ${
        isDragging
          ? "border-primary-400 bg-primary-50 scale-[1.01] shadow-lg"
          : "border-gray-300 hover:border-primary-300 hover:bg-gray-50"
      }`}
    >
      <input
        type="file"
        multiple
        accept=".sql,.yaml,.yml,.json,.feature,.txt,.csv,.xlsx,.xml"
        onChange={handleFileInput}
        className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
      />
      <div className="flex flex-col items-center gap-4">
        <div
          className={`w-14 h-14 rounded-full flex items-center justify-center transition-colors ${
            isDragging ? "bg-primary-200" : "bg-primary-100"
          }`}
        >
          <svg
            className={`w-7 h-7 transition-colors ${
              isDragging ? "text-primary-700" : "text-primary-600"
            }`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
            />
          </svg>
        </div>
        <div>
          <p className="text-sm font-semibold text-gray-700">
            {isDragging ? "Drop files here..." : "Drag & drop files here, or click to browse"}
          </p>
          <p className="text-xs text-gray-400 mt-2">Max 5 MB per file</p>
        </div>
        <div className="flex flex-wrap justify-center gap-2 mt-1">
          <span className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium bg-blue-50 text-blue-700">
            .sql
          </span>
          <span className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium bg-purple-50 text-purple-700">
            .yaml / .json
          </span>
          <span className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium bg-green-50 text-green-700">
            .feature / .txt
          </span>
          <span className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium bg-orange-50 text-orange-700">
            .csv
          </span>
          <span className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium bg-emerald-50 text-emerald-700">
            .xlsx
          </span>
          <span className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium bg-rose-50 text-rose-700">
            .xml
          </span>
        </div>
      </div>
    </div>
  );
}
