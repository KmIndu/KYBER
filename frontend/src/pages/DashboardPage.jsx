/**
 * Dashboard — KYBER home page with welcome banner, quick-start cards,
 * recent activity, stats at a glance, and tips.
 */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { getHistory } from "../services/api";
import GuidedTour from "../components/GuidedTour";

/* ── Kyber crystal SVG (reused from favicon) ── */
function KyberCrystal({ size = 40 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <defs>
        <linearGradient id="kd" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#00FF9F" />
          <stop offset="100%" stopColor="#00E6CC" />
        </linearGradient>
      </defs>
      <path d="M12 2L6 8v8l6 6 6-6V8l-6-6zm0 3l4 4v6l-4 4-4-4v-6l4-4z" fill="url(#kd)" />
      <path d="M12 9l-2 2v2l2 2 2-2v-2l-2-2z" fill="url(#kd)" opacity="0.6" />
    </svg>
  );
}

/* ── Quick-start cards ── */
const QUICK_STARTS = [
  {
    key: "upload",
    title: "Upload Schema",
    desc: "SQL, OpenAPI, or BDD feature files",
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
      </svg>
    ),
    tab: "upload",
  },
  {
    key: "prompt",
    title: "Prompt Me",
    desc: "Natural language + optional reference docs",
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.076-4.076a1.526 1.526 0 011.037-.443 48.282 48.282 0 005.68-.494c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
      </svg>
    ),
    tab: "prompt",
  },
];

/* ── Yoda's Wisdom ── */
const YODA_TIPS = [
  "Upload a SQL DDL file, you should. Auto-detect tables and constraints, KYBER will.",
  "Describe in English, you may: 'Generate 500 rows of insurance claims,' hmm, yes.",
  "Screenshots and ERDs, upload you can. Parse them with AI vision, KYBER does.",
  "CSV, JSON, or SQL INSERT — download your results from History, you must.",
  "Referential integrity across tables, KYBER preserves. Worry, you should not.",
  "The path to good testing, paved with synthetic data it is.",
  "Null values lead to suffering. Constraints, define you must.",
  "When 900 rows you generate, look as good you will not. Generate more, hmm.",
];

export default function DashboardPage() {
  const { user } = useAuth();

  const [stats, setStats] = useState({ total: 0, tables: 0, rows: 0 });
  const [tipIdx] = useState(() => Math.floor(Math.random() * YODA_TIPS.length));

  useEffect(() => {
    getHistory()
      .then((data) => {
        const list = data?.records || data || [];
        const sorted = [...list].sort(
          (a, b) => new Date(b.created_at) - new Date(a.created_at)
        );
        // Compute aggregate stats
        let tables = 0;
        let rows = 0;
        sorted.forEach((r) => {
          tables += r.tables?.length || 0;
          rows += r.total_rows || 0;
        });
        setStats({ total: sorted.length, tables, rows });
      })
      .catch(() => {});
  }, []);

  const firstName = user?.name?.split(" ")[0] || user?.email?.split("@")[0] || "Agent";

  return (
    <div className="max-w-4xl mx-auto px-4 py-6 space-y-10 min-h-[calc(100vh-5rem)] flex flex-col justify-center">
      {/* ── Welcome Header ── */}
      <div className="text-center">
        <h1 className="text-2xl sm:text-3xl lg:text-4xl font-semibold text-gray-900 dark:text-[rgba(255,255,245,0.86)] leading-tight">
          Greetings, Jedi {firstName}
        </h1>
        <p className="text-gray-500 dark:text-[rgba(235,235,245,0.6)] mt-2 text-sm sm:text-base">
          Your kyber crystal is charged. The data forge awaits.
        </p>
      </div>

      {/* ── Quick-Start Cards ── */}
      <section data-tour="tour-quickstart">
        <h2 className="text-lg font-semibold text-gray-800 dark:text-[rgba(255,255,245,0.86)] mb-4 text-center">
          Quick Start
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {QUICK_STARTS.map((qs) => (
            <Link
              key={qs.key}
              to={`/generate?tab=${qs.tab}`}
              className="group relative rounded-xl border border-gray-200 dark:border-[#2e2e32] bg-white dark:bg-[#202127] p-5 hover:border-[#00FF9F]/40 dark:hover:border-[#00FF9F]/40 hover:shadow-lg hover:shadow-[#00FF9F]/5 transition-all duration-200"
            >
              <div className="w-10 h-10 rounded-lg bg-[#00FF9F]/10 dark:bg-[#00FF9F]/10 flex items-center justify-center text-[#00FF9F] mb-3 group-hover:scale-110 transition-transform">
                {qs.icon}
              </div>
              <h3 className="font-semibold text-gray-900 dark:text-white text-sm">
                {qs.title}
              </h3>
              <p className="text-xs text-gray-500 dark:text-[rgba(235,235,245,0.6)] mt-1">
                {qs.desc}
              </p>
              {/* Arrow */}
              <svg className="absolute top-5 right-5 w-4 h-4 text-gray-300 dark:text-[#3a3a3e] group-hover:text-[#00FF9F] transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
              </svg>
            </Link>
          ))}
        </div>
      </section>

      {/* ── Stats + Tip row ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {/* Stats */}
        <div data-tour="tour-stats" className="rounded-xl border border-gray-200 dark:border-[#2e2e32] bg-white dark:bg-[#202127] p-5">
          <h2 className="text-sm font-semibold text-gray-500 dark:text-[rgba(235,235,245,0.6)] uppercase tracking-wider mb-4">
            At a Glance
          </h2>
          <div className="grid grid-cols-3 gap-4 text-center">
            {[
              { label: "Generations", value: stats.total },
              { label: "Tables Created", value: stats.tables },
              { label: "Total Rows", value: stats.rows.toLocaleString() },
            ].map((s) => (
              <div key={s.label}>
                <div className="text-2xl font-bold text-[#00FF9F]">{s.value}</div>
                <div className="text-xs text-gray-500 dark:text-[rgba(235,235,245,0.6)] mt-0.5">
                  {s.label}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Yoda's Wisdom */}
        <div data-tour="tour-tip" className="rounded-xl border border-[#00E6CC]/20 dark:border-[#00E6CC]/15 bg-[#00E6CC]/5 dark:bg-[#00E6CC]/5 p-5 flex items-start gap-3">
          <div className="w-8 h-8 rounded-lg bg-[#00E6CC]/15 flex items-center justify-center flex-shrink-0 mt-0.5 text-xl">
            🧑‍🏫
          </div>
          <div>
            <h3 className="text-sm font-semibold text-[#0A3D3A] dark:text-[#00E6CC]">
              Yoda's Wisdom
            </h3>
            <p className="text-xs text-gray-600 dark:text-[rgba(235,235,245,0.6)] mt-1 leading-relaxed italic">
              "{YODA_TIPS[tipIdx]}"
            </p>
          </div>
        </div>
      </div>

      <GuidedTour />
    </div>
  );
}
