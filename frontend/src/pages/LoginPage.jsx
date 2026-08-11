/**
 * Login page — two-step OTP email verification.
 * Step 1: Enter corporate email → sends OTP
 * Step 2: Enter 6-digit OTP → verifies and signs in
 *
 * Enhanced with Star Wars themed UI:
 * - Animated starfield background
 * - Lightsaber divider
 * - Pulsing kyber crystal logo
 * - Hologram grid overlay
 * - Orbitron headings
 * - Yoda-speak labels
 * - Smooth step transitions
 */

import { useState, useRef, useEffect, useMemo } from "react";
import { useAuth } from "../auth/AuthContext";
import { Navigate, useNavigate } from "react-router-dom";

const CHAT_EXCHANGES = [
  [
    { from: "padawan", text: "Master, how do I generate realistic test data?" },
    { from: "yoda", text: "Upload your schema, you must. Handle the rest, KYBER will. Hmmm." },
  ],
  [
    { from: "padawan", text: "But what about edge cases? They're so hard to think of!" },
    { from: "yoda", text: "Much to learn, you still have. Negative cases and boundary values, KYBER generates for you." },
  ],
  [
    { from: "padawan", text: "Can I just describe what I need in plain English?" },
    { from: "yoda", text: "Yes! 'Generate 500 insurance claims,' say you can. Understand, KYBER does." },
  ],
  [
    { from: "padawan", text: "What if my tables have foreign keys and relationships?" },
    { from: "yoda", text: "Always two there are — a primary key and a foreign key. Referential integrity, KYBER preserves." },
  ],
  [
    { from: "padawan", text: "I keep using production data for testing… is that bad?" },
    { from: "yoda", text: "The dark side of production data, avoid you must! Synthetic data — safe, compliant, powerful it is." },
  ],
  [
    { from: "padawan", text: "How long does it take to generate good data?" },
    { from: "yoda", text: "Patience you must have, young Padawan. But fast, KYBER is. Seconds, not hours." },
  ],
  [
    { from: "padawan", text: "What formats can I export the data in?" },
    { from: "yoda", text: "CSV, JSON, SQL INSERT, Excel — download you can. Flexible, KYBER is. Hmmm." },
  ],
  [
    { from: "padawan", text: "Is one schema really enough to generate good data?" },
    { from: "yoda", text: "Size matters not. A single schema, powerful it can be. Judge it by its size, do you?" },
  ],
];

/* ── Starfield: generates random stars via CSS ── */
function Starfield({ count = 50 }) {
  const stars = useMemo(() =>
    Array.from({ length: count }, (_, i) => ({
      id: i,
      left: `${Math.random() * 100}%`,
      top: `${Math.random() * 200}%`,
      size: `${1 + Math.random() * 1.5}px`,
      twinkle: `${2 + Math.random() * 4}s`,
      drift: `${40 + Math.random() * 80}s`,
      delay: `${Math.random() * 5}s`,
    })), [count]
  );
  return (
    <div className="starfield">
      {stars.map(s => (
        <div
          key={s.id}
          className="star"
          style={{
            left: s.left,
            top: s.top,
            width: s.size,
            height: s.size,
            '--twinkle-duration': s.twinkle,
            '--drift-duration': s.drift,
            animationDelay: `${s.delay}, 0s`,
          }}
        />
      ))}
    </div>
  );
}

export default function LoginPage() {
  const { user, loading, login, guestLogin, sendOtp, verifyOtp, authEnabled, ssoConfigured } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState(1); // 1 = email, 2 = otp
  const [email, setEmail] = useState(() => localStorage.getItem("kyber_last_email") || "");
  const [otp, setOtp] = useState(["" , "", "", "", "", ""]);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const [emailSent, setEmailSent] = useState(false);
  const otpRefs = useRef([]);
  const [chatIdx, setChatIdx] = useState(() => Math.floor(Math.random() * CHAT_EXCHANGES.length));

  // Cycle chat exchanges every 10 seconds
  useEffect(() => {
    const t = setInterval(() => setChatIdx((i) => (i + 1) % CHAT_EXCHANGES.length), 10000);
    return () => clearInterval(t);
  }, []);

  // If auth is off or user already signed in, skip to home
  if (!loading && (!authEnabled || user)) {
    return <Navigate to="/" replace />;
  }

  // Countdown timer for resend
  useEffect(() => {
    if (countdown <= 0) return;
    const t = setTimeout(() => setCountdown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [countdown]);

  const handleSendOtp = async (e) => {
    e.preventDefault();
    setError("");
    setSuccess("");
    if (!email.trim()) {
      setError("Please enter your email address.");
      return;
    }
    setSubmitting(true);
    try {
      const result = await sendOtp(email.trim());
      localStorage.setItem("kyber_last_email", email.trim());
      setStep(2);
      setOtp(["", "", "", "", "", ""]);
      setCountdown(60);
      setEmailSent(result.email_sent);
      setSuccess(
        result.email_sent
          ? `A 6-digit code has been sent to ${email}`
          : `Check the server console for your OTP code (SMTP not configured)`
      );
      // Focus first OTP input
      setTimeout(() => otpRefs.current[0]?.focus(), 100);
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to send OTP. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleOtpChange = (index, value) => {
    // Only allow digits
    if (value && !/^\d$/.test(value)) return;
    const newOtp = [...otp];
    newOtp[index] = value;
    setOtp(newOtp);
    setError("");

    // Auto-focus next input
    if (value && index < 5) {
      otpRefs.current[index + 1]?.focus();
    }

    // Auto-submit when all 6 digits entered
    if (value && index === 5 && newOtp.every((d) => d !== "")) {
      submitOtp(newOtp.join(""));
    }
  };

  const handleOtpKeyDown = (index, e) => {
    if (e.key === "Backspace" && !otp[index] && index > 0) {
      otpRefs.current[index - 1]?.focus();
    }
  };

  const handleOtpPaste = (e) => {
    e.preventDefault();
    const pasted = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, 6);
    if (!pasted) return;
    const newOtp = [...otp];
    for (let i = 0; i < 6; i++) {
      newOtp[i] = pasted[i] || "";
    }
    setOtp(newOtp);
    if (pasted.length === 6) {
      submitOtp(pasted);
    } else {
      otpRefs.current[pasted.length]?.focus();
    }
  };

  const submitOtp = async (code) => {
    setError("");
    setSubmitting(true);
    try {
      await verifyOtp(email.trim(), code);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err?.response?.data?.detail || "Verification failed. Please try again.");
      // Clear OTP on failure
      setOtp(["", "", "", "", "", ""]);
      otpRefs.current[0]?.focus();
    } finally {
      setSubmitting(false);
    }
  };

  const handleVerify = (e) => {
    e.preventDefault();
    const code = otp.join("");
    if (code.length < 6) {
      setError("Please enter the complete 6-digit code.");
      return;
    }
    submitOtp(code);
  };

  const handleResend = () => {
    if (countdown > 0) return;
    handleSendOtp({ preventDefault: () => {} });
  };

  const handleGuestLogin = async () => {
    setError("");
    setSuccess("");
    setSubmitting(true);
    try {
      await guestLogin();
      navigate("/", { replace: true });
    } catch (err) {
      setError(err?.response?.data?.detail || "Guest sign-in failed. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleBackToEmail = () => {
    setStep(1);
    setOtp(["", "", "", "", "", ""]);
    setError("");
    setSuccess("");
    setCountdown(0);
  };

  return (
    <div className="min-h-screen flex flex-col lg:flex-row">
      {/* Left side — KYBER branded panel */}
      <div className="hidden lg:flex lg:w-[45%] bg-[#0B0F14] text-white flex-col justify-between p-12 relative overflow-hidden">
        {/* Animated starfield */}
        <Starfield count={60} />
        {/* Subtle glow effect */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] bg-[#00FF9F]/5 rounded-full blur-[120px] pointer-events-none" />
        <div className="relative z-10">
          <div className="flex items-center gap-3 mb-10">
            <img src="/logo.jpg" alt="KYBER" className="w-14 h-14 rounded-lg object-cover kyber-pulse" />
            <span className="font-['Orbitron',sans-serif] font-semibold text-xl text-[#00FF9F] tracking-wider">KYBER</span>
          </div>
          <h2 className="text-3xl font-light leading-snug text-white/90 max-w-md">
            Generating balanced data<br/>with the Force.
          </h2>
          <p className="text-sm text-[#00FF9F]/50 mt-4 italic">May the Synthetic Data Be With You</p>
        </div>
        <div className="relative z-10 mb-10">
          <div className="max-w-sm">
            {/* Holographic transmission terminal */}
            <div className="holo-terminal rounded-lg border border-[#00FF9F]/20 bg-[#00FF9F]/[0.03] backdrop-blur-sm p-4 relative overflow-hidden">
              {/* Scanline overlay */}
              <div className="holo-scanline" />
              {/* Terminal header */}
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <div className="flex gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#00FF9F]/60 animate-pulse" />
                    <span className="w-1.5 h-1.5 rounded-full bg-[#00FF9F]/30" />
                    <span className="w-1.5 h-1.5 rounded-full bg-[#00FF9F]/30" />
                  </div>
                  <span className="text-[10px] font-mono text-[#00FF9F]/40 uppercase tracking-widest">Holocron Transmission</span>
                </div>
                <span className="text-[9px] font-mono text-[#00FF9F]/25">◉ LIVE</span>
              </div>
              {/* Chat messages */}
              <div key={chatIdx} className="space-y-3">
                {/* Padawan message — slides in first */}
                <div className="chat-msg-padawan flex items-start gap-2.5">
                  <div className="flex-shrink-0 w-8 h-8 rounded-full bg-[#00E6CC]/10 border border-[#00E6CC]/30 flex items-center justify-center text-sm" title="Padawan">
                    ⚔️
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-[10px] font-semibold text-[#00E6CC]/70 mb-1">Padawan</p>
                    <div className="bg-white/[0.04] rounded-lg rounded-tl-none px-3 py-2 border border-white/[0.06]">
                      <p className="text-[13px] text-white/60 leading-relaxed">{CHAT_EXCHANGES[chatIdx][0].text}</p>
                    </div>
                  </div>
                </div>
                {/* Yoda reply — slides in after delay */}
                <div className="chat-msg-yoda flex items-start gap-2.5">
                  <div className="flex-shrink-0 w-8 h-8 rounded-full bg-[#00FF9F]/10 border border-[#00FF9F]/30 flex items-center justify-center text-sm" title="Master Yoda">
                    🧙
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-[10px] font-semibold text-[#00FF9F]/70 mb-1">Master Yoda</p>
                    <div className="bg-white/[0.04] rounded-lg rounded-tl-none px-3 py-2 border border-white/[0.06]">
                      <p className="text-[13px] text-white/70 italic leading-relaxed">
                        {CHAT_EXCHANGES[chatIdx][1].text}
                        <span className="holo-cursor">▊</span>
                      </p>
                    </div>
                  </div>
                </div>
              </div>
              {/* Navigation dots */}
              <div className="flex items-center justify-center gap-1.5 mt-3 pt-2 border-t border-[#00FF9F]/10">
                {CHAT_EXCHANGES.map((_, i) => (
                  <span
                    key={i}
                    className={`block w-1 h-1 rounded-full transition-all duration-500 ${
                      i === chatIdx ? 'bg-[#00FF9F]/70 w-3' : 'bg-[#00FF9F]/20'
                    }`}
                  />
                ))}
              </div>
            </div>
          </div>
        </div>
        <p className="relative z-10 text-[11px] text-white/30">© {new Date().getFullYear()} <span className="font-['Orbitron',sans-serif] text-[#00FF9F]/30 tracking-wider">KYBER</span> · Built by Team JEDI @ Sun Life</p>
      </div>

      {/* Lightsaber divider */}
      <div className="hidden lg:block lightsaber-divider" />

      {/* Right side — form */}
      <div className="flex-1 flex items-center justify-center bg-[#111820] px-6 py-16 lg:py-0 relative overflow-hidden">
        {/* Hologram grid overlay */}
        <div className="absolute inset-0 holo-grid pointer-events-none" />

        <div className="w-full max-w-sm relative z-10">

          {/* Mobile header */}
          <div className="lg:hidden mb-10 flex items-center gap-2.5">
            <img src="/logo.jpg" alt="KYBER" className="w-12 h-12 rounded-lg object-cover kyber-pulse" />
            <span className="font-['Orbitron',sans-serif] text-lg font-medium text-[#00FF9F] tracking-wider">KYBER</span>
          </div>

          <h1 className="text-[28px] font-light text-[#E0E0E0] mb-1">
            {step === 1 ? "Sign in" : "Verification"}
          </h1>
          <p className="text-sm text-gray-500 mb-8">
            {step === 1
              ? "Identify yourself, you must."
              : <>Holocron code sent to <span className="text-[#00E6CC]">{email}</span></>
            }
          </p>

        {step === 1 ? (
          <form onSubmit={handleSendOtp} className="space-y-6 animate-fadeSlideIn">
            <div>
              <label htmlFor="email" className="block text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">
                Jedi Identifier
              </label>
              <input
                id="email"
                type="email"
                placeholder="jedi@sunlife.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-4 py-3 bg-[#0B0F14] border border-[#0A3D3A] text-[#E0E0E0] text-sm rounded focus:outline-none focus:border-[#00FF9F]/60 focus:shadow-[0_0_8px_rgba(0,255,159,0.1)] transition-all placeholder:text-gray-600"
                autoFocus
                required
              />
            </div>
            {error && <p className="text-xs text-red-500">{error}</p>}
            <button
              type="submit"
              disabled={submitting || loading}
              className="w-full py-3 bg-[#00FF9F] text-[#0B0F14] text-sm font-semibold rounded hover:bg-[#00E6CC] hover:shadow-[0_0_16px_rgba(0,255,159,0.3)] transition-all disabled:opacity-40"
            >
              {submitting ? "Transmitting…" : "Transmit Code"}
            </button>
          </form>
        ) : (
          <>
            {success && (
              <p className="text-xs text-emerald-600 dark:text-emerald-400 mb-5">{success}</p>
            )}

            <form onSubmit={handleVerify} className="space-y-6 animate-fadeSlideIn">
              <div>
                <label className="block text-xs font-medium text-gray-400 uppercase tracking-wider mb-3">
                  Holocron Access Code
                </label>
                <div className="flex gap-2.5" onPaste={handleOtpPaste}>
                  {otp.map((digit, i) => (
                    <input
                      key={i}
                      ref={(el) => (otpRefs.current[i] = el)}
                      type="text"
                      inputMode="numeric"
                      maxLength={1}
                      value={digit}
                      onChange={(e) => handleOtpChange(i, e.target.value)}
                      onKeyDown={(e) => handleOtpKeyDown(i, e)}
                      className="w-11 h-12 text-center text-lg bg-[#0B0F14] border border-[#0A3D3A] text-[#00FF9F] rounded focus:outline-none focus:border-[#00FF9F]/60 focus:shadow-[0_0_8px_rgba(0,255,159,0.1)] transition-all"
                    />
                  ))}
                </div>
              </div>

              {error && <p className="text-xs text-red-500">{error}</p>}

              <button
                type="submit"
                disabled={submitting || otp.some((d) => !d)}
                className="w-full py-3 bg-[#00FF9F] text-[#0B0F14] text-sm font-semibold rounded hover:bg-[#00E6CC] hover:shadow-[0_0_16px_rgba(0,255,159,0.3)] transition-all disabled:opacity-40"
              >
                {submitting ? "Verifying…" : "Access the Forge"}
              </button>
            </form>

            <div className="flex items-center justify-between mt-5">
              <button
                onClick={handleBackToEmail}
                className="text-xs text-gray-500 hover:text-[#00FF9F] transition-colors"
              >
                ← Different email
              </button>
              <button
                onClick={handleResend}
                disabled={countdown > 0}
                className="text-xs text-gray-500 hover:text-[#00FF9F] disabled:text-gray-600 disabled:cursor-not-allowed transition-colors"
              >
                {countdown > 0 ? `Resend in ${countdown}s` : "Resend code"}
              </button>
            </div>
          </>
        )}

        {ssoConfigured && (
          <>
            <div className="flex items-center gap-4 my-7">
              <div className="flex-1 h-px bg-[#0A3D3A]/40" />
              <span className="text-[10px] text-gray-600 uppercase tracking-widest">or</span>
              <div className="flex-1 h-px bg-[#0A3D3A]/40" />
            </div>
            <button
              onClick={login}
              disabled={loading}
              className="w-full py-3 border border-[#0A3D3A] text-gray-300 text-sm rounded hover:bg-[#00FF9F]/5 hover:border-[#00FF9F]/40 transition-all disabled:opacity-40"
            >
              Sign in with SSO
            </button>
          </>
        )}

        <button
          onClick={handleGuestLogin}
          disabled={loading || submitting}
          className="w-full mt-4 py-3 border border-[#00FF9F]/25 text-[#00FF9F] text-sm rounded hover:bg-[#00FF9F]/8 hover:border-[#00FF9F]/50 transition-all disabled:opacity-40"
        >
          Continue as Guest
        </button>

        </div>
      </div>
    </div>
  );
}
