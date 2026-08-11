/** Site-wide footer — KYBER branded, matches dark navbar aesthetic. */

import { useLocation } from "react-router-dom";

export default function Footer() {
  const { pathname } = useLocation();

  // Hide footer on login/callback pages
  if (pathname === "/login" || pathname === "/auth/callback") return null;

  return (
    <footer className="bg-[#0B0F14] border-t border-[#0A3D3A]/40 mt-auto">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 h-10 flex items-center justify-center">
        <p className="text-gray-500 text-[11px] tracking-wide">
          © {new Date().getFullYear()} <span className="font-['Orbitron',sans-serif] text-[#00FF9F]/50 font-semibold tracking-wider">KYBER</span> · Built by <span className="text-[#00FF9F]/40 font-medium">Team JEDI</span> @ Sun Life
        </p>
      </div>
    </footer>
  );
}
