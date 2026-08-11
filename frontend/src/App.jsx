/** Application root – renders the navbar and client-side routes. */

import { lazy, Suspense } from "react";
import { Routes, Route, useLocation } from "react-router-dom";
import Navbar from "./components/Navbar";
import Footer from "./components/Footer";
import Sidebar from "./components/Sidebar";
import LoginPage from "./pages/LoginPage";
import CallbackPage from "./pages/CallbackPage";
import { AuthProvider } from "./auth/AuthContext";
import { SidebarProvider, useSidebar } from "./context/SidebarContext";
import ProtectedRoute from "./auth/ProtectedRoute";
import SessionTimeout from "./auth/SessionTimeout";
import AskYoda from "./components/AskYoda";

const DashboardPage = lazy(() => import("./pages/DashboardPage"));
const HomePage = lazy(() => import("./pages/HomePage"));
const ResultsPage = lazy(() => import("./pages/ResultsPage"));
const HistoryPage = lazy(() => import("./pages/HistoryPage"));
const AboutPage = lazy(() => import("./pages/AboutPage"));
const NotFoundPage = lazy(() => import("./pages/NotFoundPage"));

export default function App() {
  const location = useLocation();
  const hideYoda = location.pathname === "/login" || location.pathname === "/auth/callback";
  const showSidebar = !hideYoda;

  return (
    <AuthProvider>
      <SidebarProvider>
      <SessionTimeout />
      <AppContent showSidebar={showSidebar} hideYoda={hideYoda} />
      </SidebarProvider>
    </AuthProvider>
  );
}

function AppContent({ showSidebar, hideYoda }) {
  const { collapsed } = useSidebar();

  return (
      <div className="min-h-screen flex flex-col bg-gray-50 dark:bg-[#1b1b1f] transition-colors duration-200">
        <Navbar />
        <Sidebar />
        <div className={`flex-1 flex flex-col transition-all duration-300 ${showSidebar ? (collapsed ? "ml-14" : "ml-48") : ""}`}>
          <main className="flex-1">
            <Suspense fallback={<div className="flex-1 flex items-center justify-center py-20"><div className="w-8 h-8 border-2 border-[#00FF9F] border-t-transparent rounded-full animate-spin" /></div>}>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/auth/callback" element={<CallbackPage />} />
              <Route path="/" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
              <Route path="/generate" element={<ProtectedRoute><HomePage /></ProtectedRoute>} />
              <Route path="/results" element={<ProtectedRoute><ResultsPage /></ProtectedRoute>} />
              <Route path="/history" element={<ProtectedRoute><HistoryPage /></ProtectedRoute>} />
              <Route path="/about" element={<AboutPage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Routes>
            </Suspense>
          </main>
          <Footer />
        </div>
        {!hideYoda && <AskYoda />}
      </div>
  );
}
