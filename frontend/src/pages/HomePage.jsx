/**
 * Unified Home Page — tabbed interface combining Upload and NL Prompt
 * (with optional reference document support) into a single dashboard.
 */

import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import UploadTab from "./tabs/UploadTab";
import PromptTab from "./tabs/PromptTab";

const TABS = [
  {
    key: "upload",
    label: "Upload Files",
    icon: "📄",
    description: "SQL, OpenAPI, or BDD files",
  },
  {
    key: "prompt",
    label: "Prompt Me",
    icon: "💬",
    description: "Natural language + optional reference docs",
  },
];

export default function HomePage() {
  const [searchParams] = useSearchParams();
  const [activeTab, setActiveTab] = useState(
    () => ["upload", "prompt"].includes(searchParams.get("tab")) ? searchParams.get("tab") : "upload"
  );

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
          Generate Synthetic Test Data
        </h1>
        <p className="text-gray-500 dark:text-[rgba(235,235,245,0.6)] mt-2">
          Choose how you'd like to define your data — upload schema files,
          describe what you need in plain English, or upload reference documents.
        </p>
      </div>

      {/* Tab Selector */}
      <div className="flex gap-2 mb-8 p-1 bg-gray-100 dark:bg-[#202127] rounded-xl">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-lg text-sm font-medium transition-all ${
              activeTab === tab.key
                ? "bg-white dark:bg-[#2e2e32] text-gray-900 dark:text-white shadow-sm"
                : "text-gray-500 dark:text-[rgba(235,235,245,0.6)] hover:text-gray-700 dark:hover:text-[rgba(255,255,245,0.86)]"
            }`}
          >
            <span className="text-lg">{tab.icon}</span>
            <div className="text-left hidden sm:block">
              <div>{tab.label}</div>
              <div
                className={`text-xs ${
                  activeTab === tab.key ? "text-gray-400" : "text-gray-400"
                }`}
              >
                {tab.description}
              </div>
            </div>
            <span className="sm:hidden">{tab.label}</span>
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === "upload" && <UploadTab />}
      {activeTab === "prompt" && <PromptTab />}
    </div>
  );
}
