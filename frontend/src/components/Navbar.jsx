/** Top navigation bar — clean, professional layout. */

import { useState, useRef, useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useTheme } from "../context/ThemeContext";

function getInitials(name, email) {
  if (name) {
    const parts = name.trim().split(/\s+/);
    if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    return parts[0][0].toUpperCase();
  }
  if (email) return email[0].toUpperCase();
  return "U";
}

export default function Navbar() {
  const { pathname } = useLocation();
  const { user, authEnabled, logout } = useAuth();
  const { dark, toggle } = useTheme();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(null);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  if (pathname === "/login" || pathname === "/auth/callback") return null;

  const isActive = (path) => pathname === path;

  return (
    <nav className="bg-[#0B0F14] border-b border-[#0A3D3A]/60 sticky top-0 z-50">
      <div className="px-4 sm:px-6 h-14 flex items-center">
        {/* Left: Logo */}
        <div className="flex items-center gap-2.5 flex-shrink-0">
          <Link to="/" className="flex items-center gap-2.5 group">
            <img
              src="/logo.jpg"
              alt="KYBER"
              className="w-8 h-8 rounded-md object-cover shadow-[0_0_12px_rgba(0,255,159,0.3)] group-hover:shadow-[0_0_20px_rgba(0,255,159,0.5)] transition-shadow"
            />
            <span className="font-['Orbitron',sans-serif] font-semibold text-sm text-[#00FF9F] hidden sm:block whitespace-nowrap tracking-wider">
              KYBER
            </span>
          </Link>
        </div>

        {/* Center: spacer */}
        <div className="flex-1" />

        {/* Right: Actions */}
        <div className="flex items-center gap-1">

          {/* Theme toggle — pill switch like fakerjs.dev */}
          <button
            onClick={toggle}
            className="relative w-12 h-6 rounded-full flex items-center transition-colors duration-300 focus:outline-none"
            style={{ background: dark ? '#0A3D3A' : '#E0E0E0' }}
            title={dark ? "Switch to light mode" : "Switch to dark mode"}
            aria-label="Toggle dark mode"
          >
            {/* Sliding knob */}
            <span
              className="absolute top-0.5 w-5 h-5 rounded-full flex items-center justify-center shadow-md transition-all duration-300"
              style={{
                left: dark ? 'calc(100% - 1.375rem)' : '0.125rem',
                background: dark ? '#00FF9F' : '#ffffff',
                boxShadow: dark ? '0 0 6px rgba(0,255,159,0.4)' : '0 1px 2px rgba(0,0,0,0.2)',
              }}
            >
              {dark ? (
                <svg className="w-3 h-3 text-[#0B0F14]" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21 12.79A9 9 0 1111.21 3a7 7 0 009.79 9.79z" />
                </svg>
              ) : (
                <svg className="w-3 h-3 text-gray-600" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                  <circle cx="12" cy="12" r="4" />
                  <path strokeLinecap="round" d="M12 2v2m0 16v2m-10-10h2m16 0h2m-3.5-7.5L17 6M7 18l-1.5 1.5M20.5 18.5L19 17M5 6 3.5 4.5" />
                </svg>
              )}
            </span>
          </button>

          {/* User avatar + dropdown */}
          <div className="w-px h-5 bg-[#0A3D3A] mx-1.5" />
          {user ? (
            <div className="relative" ref={menuRef}>
              <button
                onClick={() => setMenuOpen((o) => !o)}
                className="w-9 h-9 bg-gradient-to-br from-[#00FF9F] to-[#00E6CC] text-[#0B0F14] rounded-full flex items-center justify-center text-sm font-semibold hover:shadow-[0_0_12px_rgba(0,255,159,0.4)] transition-all cursor-pointer"
                title={user.email || user.name}
              >
                {getInitials(user.name, user.email)}
              </button>

              {menuOpen && (
                  <div className="absolute right-0 mt-2 w-60 bg-[#111820] rounded-lg shadow-lg border border-[#0A3D3A]/60 py-2 z-50">
                    {/* Avatar + info */}
                    <div className="px-4 py-3 flex items-center gap-3 border-b border-[#0A3D3A]/40">
                      <div className="w-10 h-10 bg-gradient-to-br from-[#00FF9F] to-[#00E6CC] text-[#0B0F14] rounded-full flex items-center justify-center text-sm font-semibold flex-shrink-0">
                        {getInitials(user.name, user.email)}
                      </div>
                      <div className="min-w-0">
                        {user.name && (
                          <p className="text-sm font-medium text-[#E0E0E0] truncate">{user.name}</p>
                        )}
                        <p className="text-xs text-gray-500 truncate">{user.email}</p>
                      </div>
                    </div>
                    {/* Logout */}
                    {authEnabled && (
                      <button
                        onClick={() => { setMenuOpen(false); logout(); }}
                        className="w-full text-left px-4 py-2.5 text-sm text-gray-300 hover:bg-[#00FF9F]/5 hover:text-[#00FF9F] flex items-center gap-2.5 transition-colors"
                      >
                        <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a2 2 0 01-2 2H6a2 2 0 01-2-2V7a2 2 0 012-2h5a2 2 0 012 2v1" />
                        </svg>
                        Sign out
                      </button>
                    )}
                  </div>
                )}
              </div>
          ) : (
            <div className="w-9 h-9 rounded-full bg-[#0A3D3A]/60 flex items-center justify-center">
              <svg className="w-5 h-5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
              </svg>
            </div>
          )}
        </div>
      </div>
    </nav>
  );
}
