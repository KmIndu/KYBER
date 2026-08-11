/** Spotlight search — Ctrl+K to open, searches visible page text and scrolls to matches. */

import { useState, useEffect, useRef, useCallback } from "react";

export default function SpotlightSearch() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState([]);
  const [activeIdx, setActiveIdx] = useState(0);
  const inputRef = useRef(null);
  const prevHighlights = useRef([]);

  // Open with Ctrl+K
  useEffect(() => {
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
      if (e.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // Focus input when opened
  useEffect(() => {
    if (open) {
      setQuery("");
      setMatches([]);
      setActiveIdx(0);
      clearHighlights();
      setTimeout(() => inputRef.current?.focus(), 50);
    } else {
      clearHighlights();
    }
  }, [open]);

  const clearHighlights = useCallback(() => {
    prevHighlights.current.forEach((el) => {
      el.style.removeProperty("background-color");
      el.style.removeProperty("outline");
      el.style.removeProperty("border-radius");
      el.style.removeProperty("scroll-margin-top");
    });
    prevHighlights.current = [];
  }, []);

  // Search visible text nodes in <main>
  const doSearch = useCallback(
    (text) => {
      clearHighlights();
      if (!text || text.length < 2) {
        setMatches([]);
        setActiveIdx(0);
        return;
      }

      const main = document.querySelector("main");
      if (!main) return;

      const lower = text.toLowerCase();
      const found = [];

      // Walk all elements with text content
      const els = main.querySelectorAll(
        "h1, h2, h3, h4, h5, h6, p, span, label, button, a, td, th, li, div, textarea, input"
      );

      els.forEach((el) => {
        // Only match elements whose own direct text matches (not children)
        const ownText = Array.from(el.childNodes)
          .filter((n) => n.nodeType === Node.TEXT_NODE)
          .map((n) => n.textContent)
          .join("");

        if (ownText.toLowerCase().includes(lower)) {
          // Avoid duplicates (parent containing same text)
          const dominated = found.some(
            (f) => f.el.contains(el) || el.contains(f.el)
          );
          if (!dominated) {
            // Remove any parent already found that this element is inside
            const filtered = found.filter((f) => !el.contains(f.el));
            found.length = 0;
            found.push(...filtered);

            const tag = el.tagName.toLowerCase();
            const label =
              ownText.trim().slice(0, 80) || el.getAttribute("placeholder") || tag;
            const section = el.closest("section, [data-section], form, .card, [class*='Card']");
            const sectionName = section?.getAttribute("data-section") || "";
            found.push({ el, label, section: sectionName, tag });
          }
        }
      });

      setMatches(found);
      setActiveIdx(0);

      // Highlight all matches lightly
      found.forEach((m) => {
        m.el.style.scrollMarginTop = "100px";
        prevHighlights.current.push(m.el);
      });

      // Scroll to first
      if (found.length > 0) {
        scrollToMatch(found[0], found, 0);
      }
    },
    [clearHighlights]
  );

  const scrollToMatch = (match, allMatches, idx) => {
    // Reset all highlights
    allMatches.forEach((m) => {
      m.el.style.backgroundColor = "";
      m.el.style.outline = "";
      m.el.style.borderRadius = "";
    });
    // Highlight active
    match.el.style.backgroundColor = "rgba(59,130,246,0.15)";
    match.el.style.outline = "2px solid rgba(59,130,246,0.5)";
    match.el.style.borderRadius = "4px";
    match.el.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const handleChange = (e) => {
    const v = e.target.value;
    setQuery(v);
    doSearch(v);
  };

  const goTo = (idx) => {
    if (matches.length === 0) return;
    const i = ((idx % matches.length) + matches.length) % matches.length;
    setActiveIdx(i);
    scrollToMatch(matches[i], matches, i);
  };

  const handleKeyDown = (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      goTo(activeIdx + 1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      goTo(activeIdx - 1);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (matches.length > 0) {
        scrollToMatch(matches[activeIdx], matches, activeIdx);
        setOpen(false);
      }
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh]">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/30 dark:bg-black/50"
        onClick={() => setOpen(false)}
      />

      {/* Search panel */}
      <div className="relative w-full max-w-lg mx-4 bg-white dark:bg-[#202127] rounded-xl shadow-2xl border border-gray-200 dark:border-[#2e2e32] overflow-hidden">
        {/* Input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-100 dark:border-[#2e2e32]">
          <svg
            className="w-5 h-5 text-gray-400 flex-shrink-0"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            placeholder="Search this page…"
            className="flex-1 bg-transparent outline-none text-sm text-gray-900 dark:text-white placeholder-gray-400"
          />
          <kbd className="hidden sm:inline-flex items-center px-1.5 py-0.5 text-[10px] font-medium text-gray-400 bg-gray-100 dark:bg-[#2e2e32] rounded">
            ESC
          </kbd>
        </div>

        {/* Results */}
        {query.length >= 2 && (
          <div className="max-h-64 overflow-y-auto">
            {matches.length === 0 ? (
              <div className="px-4 py-6 text-center text-sm text-gray-400">
                No matches found
              </div>
            ) : (
              <ul className="py-1">
                {matches.map((m, i) => (
                  <li key={i}>
                    <button
                      onClick={() => {
                        setActiveIdx(i);
                        scrollToMatch(m, matches, i);
                        setOpen(false);
                      }}
                      className={`w-full text-left px-4 py-2.5 text-sm flex items-center gap-3 transition-colors ${
                        i === activeIdx
                          ? "bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300"
                          : "text-gray-700 dark:text-[rgba(235,235,245,0.6)] hover:bg-gray-50 dark:hover:bg-[#2e2e32]/50"
                      }`}
                    >
                      <span className="flex-shrink-0 w-5 h-5 rounded bg-gray-100 dark:bg-[#2e2e32] flex items-center justify-center">
                        <svg
                          className="w-3 h-3 text-gray-400"
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M7 20l4-16m2 16l4-16M6 9h14M4 15h14"
                          />
                        </svg>
                      </span>
                      <span className="truncate">{m.label}</span>
                      <span className="ml-auto text-xs text-gray-400 flex-shrink-0">
                        {m.tag}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {/* Footer hint */}
        <div className="px-4 py-2 border-t border-gray-100 dark:border-[#2e2e32] flex items-center gap-4 text-[11px] text-gray-400">
          <span>
            <kbd className="px-1 py-0.5 bg-gray-100 dark:bg-[#2e2e32] rounded text-[10px]">↑↓</kbd> navigate
          </span>
          <span>
            <kbd className="px-1 py-0.5 bg-gray-100 dark:bg-[#2e2e32] rounded text-[10px]">Enter</kbd> go to
          </span>
          <span>
            <kbd className="px-1 py-0.5 bg-gray-100 dark:bg-[#2e2e32] rounded text-[10px]">Esc</kbd> close
          </span>
          {matches.length > 0 && (
            <span className="ml-auto">{activeIdx + 1}/{matches.length}</span>
          )}
        </div>
      </div>
    </div>
  );
}
