/**
 * Session Timeout Manager — tracks user inactivity and shows
 * a warning modal before auto-logout when idle too long.
 */

import { useEffect, useState, useRef, useCallback } from "react";
import { useAuth } from "./AuthContext";
import api from "../services/api";

const ACTIVITY_EVENTS = ["mousemove", "mousedown", "keydown", "scroll", "touchstart", "pointerdown"];

export default function SessionTimeout() {
  const { user, authEnabled, logout } = useAuth();
  const [showWarning, setShowWarning] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [sessionMinutes, setSessionMinutes] = useState(null);
  const warningTimerRef = useRef(null);
  const countdownRef = useRef(null);
  const logoutRef = useRef(logout);
  const lastActivityRef = useRef(Date.now());

  // Keep logout ref current
  useEffect(() => { logoutRef.current = logout; }, [logout]);

  // Fetch session timeout from backend config once
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { data } = await api.get("/auth/config");
        if (!cancelled && data.session_timeout_minutes) {
          setSessionMinutes(data.session_timeout_minutes);
        }
      } catch { /* ignore */ }
    })();
    return () => { cancelled = true; };
  }, []);

  const clearAllTimers = useCallback(() => {
    if (warningTimerRef.current) clearTimeout(warningTimerRef.current);
    if (countdownRef.current) clearInterval(countdownRef.current);
    warningTimerRef.current = null;
    countdownRef.current = null;
  }, []);

  const doLogout = useCallback(() => {
    clearAllTimers();
    setShowWarning(false);
    logoutRef.current();
  }, [clearAllTimers]);

  // Reset the inactivity timer on any user activity
  const resetTimer = useCallback(() => {
    lastActivityRef.current = Date.now();

    // If warning is showing and user interacts, dismiss it and restart
    if (showWarning) {
      clearAllTimers();
      setShowWarning(false);
    }
  }, [showWarning, clearAllTimers]);

  // Attach activity listeners
  useEffect(() => {
    if (!authEnabled || !user) return;

    const handler = () => resetTimer();
    ACTIVITY_EVENTS.forEach((evt) => document.addEventListener(evt, handler, { passive: true }));
    return () => {
      ACTIVITY_EVENTS.forEach((evt) => document.removeEventListener(evt, handler));
    };
  }, [authEnabled, user, resetTimer]);

  // Inactivity check — poll every 10s to see if idle time exceeded threshold
  useEffect(() => {
    if (!authEnabled || !user || sessionMinutes === null) return;

    const totalMs = sessionMinutes * 60 * 1000;
    const warningMs = Math.min(30 * 1000, totalMs * 0.5); // warn 30s before or at 50%
    const idleThreshold = totalMs - warningMs;

    const interval = setInterval(() => {
      if (showWarning) return; // already warning, don't restart

      const idle = Date.now() - lastActivityRef.current;
      if (idle >= idleThreshold) {
        // Show warning and start countdown
        const countdownSec = Math.floor(warningMs / 1000);
        setSecondsLeft(countdownSec);
        setShowWarning(true);

        let remaining = countdownSec;
        countdownRef.current = setInterval(() => {
          remaining -= 1;
          if (remaining <= 0) {
            clearInterval(countdownRef.current);
            countdownRef.current = null;
            setShowWarning(false);
            logoutRef.current();
          } else {
            setSecondsLeft(remaining);
          }
        }, 1000);
      }
    }, 10_000);

    return () => {
      clearInterval(interval);
      clearAllTimers();
      setShowWarning(false);
    };
  }, [authEnabled, user, sessionMinutes, showWarning, clearAllTimers]);

  const extendSession = useCallback(async () => {
    try {
      const token = localStorage.getItem("auth_token");
      if (!token) return;
      const { data } = await api.post("/auth/refresh", { token });
      localStorage.setItem("auth_token", data.token);
      clearAllTimers();
      setShowWarning(false);
      lastActivityRef.current = Date.now();
    } catch {
      doLogout();
    }
  }, [clearAllTimers, doLogout]);

  if (!showWarning) return null;

  const mins = Math.floor(secondsLeft / 60);
  const secs = secondsLeft % 60;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl p-8 max-w-sm w-full mx-4 text-center space-y-5">
        {/* Warning icon */}
        <div className="flex justify-center">
          <div className="w-14 h-14 bg-amber-100 rounded-full flex items-center justify-center">
            <svg className="w-7 h-7 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L3.34 16.5c-.77.833.192 2.5 1.732 2.5z" />
            </svg>
          </div>
        </div>

        <h2 className="text-xl font-bold text-gray-900">Session Expiring</h2>
        <p className="text-gray-600">You've been inactive. Your session will expire in</p>

        {/* Countdown */}
        <div className="text-3xl font-mono font-bold text-amber-600">
          {mins}:{secs.toString().padStart(2, "0")}
        </div>

        <p className="text-sm text-gray-500">You will be logged out automatically.</p>

        <div className="flex gap-3">
          <button
            onClick={doLogout}
            className="flex-1 px-4 py-2.5 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 font-medium transition-colors"
          >
            Logout Now
          </button>
          <button
            onClick={extendSession}
            className="flex-1 px-4 py-2.5 bg-primary-600 text-white rounded-lg hover:bg-primary-700 font-medium transition-colors"
          >
            Extend Session
          </button>
        </div>
      </div>
    </div>
  );
}
