/**
 * Route guard — redirects unauthenticated users to the login page
 * when SSO is enabled.  Passes through freely when auth is disabled.
 */

import { Navigate } from "react-router-dom";
import { useAuth } from "./AuthContext";

export default function ProtectedRoute({ children }) {
  const { user, loading, authEnabled } = useAuth();

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary-600" />
      </div>
    );
  }

  if (authEnabled && !user) {
    return <Navigate to="/login" replace />;
  }

  return children;
}
