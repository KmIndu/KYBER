/**
 * OAuth2 callback page — receives the authorization code from the provider,
 * exchanges it for a session token, then redirects to the home page.
 */

import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export default function CallbackPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { handleCallback } = useAuth();
  const [error, setError] = useState(null);

  useEffect(() => {
    const code = searchParams.get("code");
    const state = searchParams.get("state");
    const errParam = searchParams.get("error");

    if (errParam) {
      setError(searchParams.get("error_description") || errParam);
      return;
    }

    if (!code || !state) {
      setError("Missing authorization code or state parameter.");
      return;
    }

    handleCallback(code, state)
      .then(() => navigate("/", { replace: true }))
      .catch((err) => setError(err?.response?.data?.detail || "Authentication failed."));
  }, [searchParams, handleCallback, navigate]);

  if (error) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center">
        <div className="bg-white rounded-xl shadow p-8 max-w-md text-center space-y-4">
          <div className="text-red-500 text-4xl">⚠</div>
          <h2 className="text-xl font-semibold text-gray-900">Authentication Error</h2>
          <p className="text-gray-600">{error}</p>
          <button
            onClick={() => navigate("/login", { replace: true })}
            className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
          >
            Back to Login
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <div className="text-center space-y-3">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary-600 mx-auto" />
        <p className="text-gray-500">Completing sign-in…</p>
      </div>
    </div>
  );
}
