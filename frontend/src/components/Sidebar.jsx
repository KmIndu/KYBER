import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useSidebar } from "../context/SidebarContext";

function getInitials(name, email) {
  if (name) {
    const parts = name.trim().split(/\s+/);
    if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    return parts[0][0].toUpperCase();
  }
  if (email) return email[0].toUpperCase();
  return "U";
}

const NAV_ITEMS = [
  {
    to: "/generate",
    label: "Generate",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z" />
      </svg>
    ),
  },
  {
    to: "/results",
    label: "Results",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 01-1.125-1.125M3.375 19.5h7.5c.621 0 1.125-.504 1.125-1.125m-9.75 0V5.625m0 12.75v-1.5c0-.621.504-1.125 1.125-1.125m18.375 2.625V5.625m0 12.75c0 .621-.504 1.125-1.125 1.125m1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125m0 3.75h-7.5A1.125 1.125 0 0112 18.375m9.75-12.75c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125m19.5 0v1.5c0 .621-.504 1.125-1.125 1.125M2.25 5.625v1.5c0 .621.504 1.125 1.125 1.125m0 0h17.25m-17.25 0h7.5c.621 0 1.125.504 1.125 1.125M3.375 8.25c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125m17.25-3.75h-7.5c-.621 0-1.125.504-1.125 1.125m8.625-1.125c.621 0 1.125.504 1.125 1.125v1.5c0 .621-.504 1.125-1.125 1.125m-17.25 0h7.5m-7.5 0c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125M12 10.875v-1.5m0 1.5c0 .621-.504 1.125-1.125 1.125M12 10.875c0 .621.504 1.125 1.125 1.125m-2.25 0c.621 0 1.125.504 1.125 1.125M13.125 12h7.5m-7.5 0c-.621 0-1.125.504-1.125 1.125M20.625 12c.621 0 1.125.504 1.125 1.125v1.5c0 .621-.504 1.125-1.125 1.125m-17.25 0h7.5M12 14.625v-1.5m0 1.5c0 .621-.504 1.125-1.125 1.125M12 14.625c0 .621.504 1.125 1.125 1.125m-2.25 0c.621 0 1.125.504 1.125 1.125m0 0v1.5c0 .621-.504 1.125-1.125 1.125m1.125-2.625c-.621 0-1.125.504-1.125 1.125" />
      </svg>
    ),
  },
  {
    to: "/history",
    label: "History",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
];

export default function Sidebar() {
  const { pathname } = useLocation();
  const { user, logout, authEnabled } = useAuth();
  const { collapsed, setCollapsed } = useSidebar();

  if (pathname === "/login" || pathname === "/auth/callback") return null;

  return (
    <aside
      className={`fixed left-0 top-14 bottom-0 z-40 flex flex-col bg-[#0B0F14] border-r border-[#0A3D3A]/40 transition-all duration-300 ${
        collapsed ? "w-14" : "w-48"
      }`}
    >
      {/* Collapse/Expand toggle */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        className="absolute -right-3 top-5 w-6 h-6 bg-[#0B0F14] border border-[#0A3D3A]/60 rounded-full flex items-center justify-center text-gray-400 hover:text-[#00FF9F] hover:border-[#00FF9F]/40 transition-colors duration-200 cursor-pointer z-50"
      >
        <svg className={`w-3.5 h-3.5 transition-transform duration-300 ${collapsed ? "rotate-0" : "rotate-180"}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
      </button>

      {/* Nav links */}
      <nav className="flex-1 flex flex-col gap-1 pt-3 px-2">
        {NAV_ITEMS.map(({ to, label, icon }) => {
          const active = pathname === to;
          return (
            <Link
              key={to}
              to={to}
              title={collapsed ? label : undefined}
              className={`flex items-center gap-3 px-2.5 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 group ${
                active
                  ? "bg-[#00FF9F]/10 text-[#00FF9F] shadow-[0_0_8px_rgba(0,255,159,0.1)]"
                  : "text-gray-400 hover:text-[#00FF9F] hover:bg-[#00FF9F]/5"
              }`}
            >
              <span className="flex-shrink-0">{icon}</span>
              <span
                className={`whitespace-nowrap overflow-hidden transition-all duration-300 ${
                  collapsed ? "w-0 opacity-0" : "w-auto opacity-100"
                }`}
              >
                {label}
              </span>
              {/* Active indicator dot (collapsed state) */}
              {active && collapsed && (
                <span className="absolute left-0 w-[3px] h-5 rounded-r-full bg-[#00FF9F]" />
              )}
            </Link>
          );
        })}
      </nav>

      {/* About link */}
      <div className="px-2 pb-2">
        <Link
          to="/about"
          title={collapsed ? "About Us" : undefined}
          className={`flex items-center gap-3 px-2.5 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 ${
            pathname === "/about"
              ? "bg-[#00FF9F]/10 text-[#00FF9F] shadow-[0_0_8px_rgba(0,255,159,0.1)]"
              : "text-gray-400 hover:text-[#00FF9F] hover:bg-[#00FF9F]/5"
          }`}
        >
          <span className="flex-shrink-0">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z" />
            </svg>
          </span>
          <span
            className={`whitespace-nowrap overflow-hidden transition-all duration-300 ${
              collapsed ? "w-0 opacity-0" : "w-auto opacity-100"
            }`}
          >
            About Us
          </span>
        </Link>
      </div>

      {/* User profile */}
      <div className="px-2 pb-3 border-t border-[#0A3D3A]/40 pt-3">
        {user ? (
          <div className="flex items-center gap-3 px-2.5 py-2 rounded-lg">
            <div className="w-8 h-8 bg-gradient-to-br from-[#00FF9F] to-[#00E6CC] text-[#0B0F14] rounded-full flex items-center justify-center text-xs font-semibold flex-shrink-0">
              {getInitials(user.name, user.email)}
            </div>
            {!collapsed && (
              <div className="min-w-0 flex-1">
                {user.name && <p className="text-xs font-medium text-[#E0E0E0] truncate">{user.name}</p>}
                <p className="text-[0.65rem] text-gray-500 truncate">{user.email}</p>
                {authEnabled && (
                  <button
                    onClick={logout}
                    className="text-[0.65rem] text-gray-400 hover:text-[#00FF9F] mt-1 transition-colors cursor-pointer"
                  >
                    Sign out
                  </button>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="flex items-center justify-center py-2">
            <div className="w-8 h-8 rounded-full bg-[#0A3D3A]/40 flex items-center justify-center">
              <svg className="w-4 h-4 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
              </svg>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
