/**
 * ResultsTutorial — Spotlight walkthrough that highlights actual page elements
 * with arrows pointing to them. No blurred modal overlay.
 * Persists dismissal in localStorage.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { createPortal } from "react-dom";

const RESULTS_TOUR_KEY = "kyber_results_tour_completed";

const STEPS = [
  { target: "tour-stats", label: "Generation stats at a glance" },
  { target: "tour-downloads", label: "Download data & test artifacts" },
  { target: "tour-preview", label: "Preview generated rows" },
  { target: "tour-analysis", label: "Analysis tools — click to auto-run" },
];

export default function ResultsTutorial() {
  const [visible, setVisible] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [pos, setPos] = useState(null);
  const tooltipRef = useRef(null);

  useEffect(() => {
    const completed = localStorage.getItem(RESULTS_TOUR_KEY);
    if (!completed) {
      // small delay so elements render first
      const t = setTimeout(() => setVisible(true), 600);
      return () => clearTimeout(t);
    }
  }, []);

  const computePosition = useCallback(() => {
    const step = STEPS[currentStep];
    const el = document.querySelector(`[data-tour="${step.target}"]`);
    if (!el) return;

    el.scrollIntoView({ behavior: "smooth", block: "center" });

    // wait for scroll
    setTimeout(() => {
      const rect = el.getBoundingClientRect();
      const vh = window.innerHeight;
      const vw = window.innerWidth;

      // Highlight box (viewport-relative for fixed container)
      const top = rect.top - 6;
      const left = Math.max(4, rect.left - 6);
      const width = Math.min(rect.width + 12, vw - left - 4);
      const height = rect.height + 12;

      // Tooltip: prefer below, flip above if it would overflow viewport
      const tooltipHeight = 80;
      const spaceBelow = vh - rect.bottom;
      const placeAbove = spaceBelow < tooltipHeight + 20;
      const tipTop = placeAbove ? rect.top - tooltipHeight - 12 : rect.bottom + 12;
      const tipLeft = Math.max(120, Math.min(rect.left + rect.width / 2, vw - 120));

      setPos({ top, left, width, height, tipTop, tipLeft, placeAbove });
    }, 350);
  }, [currentStep]);

  useEffect(() => {
    if (!visible) return;
    computePosition();
    window.addEventListener("resize", computePosition);
    return () => window.removeEventListener("resize", computePosition);
  }, [visible, currentStep, computePosition]);

  const dismiss = () => {
    setVisible(false);
    localStorage.setItem(RESULTS_TOUR_KEY, "true");
  };

  const next = () => {
    if (currentStep < STEPS.length - 1) setCurrentStep(currentStep + 1);
    else dismiss();
  };

  const prev = () => {
    if (currentStep > 0) setCurrentStep(currentStep - 1);
  };

  if (!visible || !pos) return null;

  const step = STEPS[currentStep];

  return createPortal(
    <div className="fixed inset-0 z-[9999] pointer-events-none">
      {/* Dim overlay with cutout */}
      <svg className="absolute inset-0 w-full h-full">
        <defs>
          <mask id="tour-mask">
            <rect x="0" y="0" width="100%" height="100%" fill="white" />
            <rect
              x={pos.left}
              y={pos.top}
              width={pos.width}
              height={pos.height}
              rx="12"
              fill="black"
            />
          </mask>
        </defs>
        <rect
          x="0" y="0" width="100%" height="100%"
          fill="rgba(0,0,0,0.45)"
          mask="url(#tour-mask)"
        />
      </svg>

      {/* Highlight ring */}
      <div
        className="absolute rounded-xl border-2 border-[#00FF9F] transition-all duration-300"
        style={{
          top: pos.top,
          left: pos.left,
          width: pos.width,
          height: pos.height,
          boxShadow: "0 0 0 4px rgba(0,255,159,0.15)",
        }}
      />

      {/* Arrow + Tooltip */}
      <div
        ref={tooltipRef}
        className={`absolute pointer-events-auto flex items-center ${pos.placeAbove ? "flex-col-reverse" : "flex-col"}`}
        style={{
          top: pos.tipTop,
          left: pos.tipLeft,
          transform: "translateX(-50%)",
        }}
      >
        {/* Arrow */}
        <div className={`w-3 h-3 bg-gray-900 rotate-45 border-gray-700 ${pos.placeAbove ? "-mt-1.5 border-b border-r" : "-mb-1.5 border-t border-l"}`} />

        {/* Tooltip body */}
        <div className="bg-gray-900 text-white rounded-lg px-4 py-3 shadow-xl max-w-xs">
          <p className="text-sm font-medium mb-2">{step.label}</p>

          {/* Controls */}
          <div className="flex items-center justify-between gap-4">
            <span className="text-xs text-gray-400">{currentStep + 1}/{STEPS.length}</span>
            <div className="flex gap-2">
              {currentStep > 0 && (
                <button
                  onClick={prev}
                  className="text-xs text-gray-400 hover:text-white transition-colors"
                >
                  Back
                </button>
              )}
              <button
                onClick={next}
                className="text-xs font-semibold text-[#00FF9F] hover:text-[#00E6CC] transition-colors"
              >
                {currentStep === STEPS.length - 1 ? "Done" : "Next →"}
              </button>
              <button
                onClick={dismiss}
                className="text-xs text-gray-500 hover:text-gray-300 transition-colors ml-1"
              >
                Skip
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}
