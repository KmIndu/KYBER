/**
 * Authentication context — manages user session state across the app.
 *
 * Stores JWT in localStorage and exposes login/logout helpers plus
 * the current user object to any component via useAuth().
 */

import { createContext, useContext, useState, useEffect, useCallback } from "react";
import api from "../services/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [authEnabled, setAuthEnabled] = useState(false);
  const [ssoConfigured, setSsoConfigured] = useState(false);

  // Check auth config + restore session on mount
  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get("/auth/config");
        setAuthEnabled(data.auth_enabled);
        setSsoConfigured(data.sso_configured || false);

        if (!data.auth_enabled) {
          setUser({ name: "Anonymous", email: "" });
          setLoading(false);
          return;
        }

        // Try to restore session from stored token
        const token = localStorage.getItem("auth_token");
        if (token) {
          try {
            const { data: profile } = await api.get(`/auth/me?token=${token}`);
            setUser(profile);
          } catch {
            localStorage.removeItem("auth_token");
          }
        }
      } catch {
        // Backend unreachable — treat as auth disabled
        setUser({ name: "Anonymous", email: "" });
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  /** Initiate SSO login — redirects browser to the OAuth2 provider. */
  const login = useCallback(async () => {
    try {
      const { data } = await api.get("/auth/login");
      window.location.href = data.authorization_url;
    } catch (err) {
      console.error("Login failed:", err);
    }
  }, []);

  /** Demo login — for development/testing without a real SSO provider. */
  const demoLogin = useCallback(async () => {
    try {
      const { data } = await api.post("/auth/demo-login");
      localStorage.setItem("auth_token", data.token);
      setUser(data.user);
      return data;
    } catch (err) {
      console.error("Demo login failed:", err);
      throw err;
    }
  }, []);

  /** Guest login — anonymous session for trying the app without OTP. */
  const guestLogin = useCallback(async () => {
    try {
      const { data } = await api.post("/auth/guest-login");
      localStorage.setItem("auth_token", data.token);
      setUser(data.user);
      return data;
    } catch (err) {
      console.error("Guest login failed:", err);
      throw err;
    }
  }, []);

  /** Send OTP to corporate email. */
  const sendOtp = useCallback(async (email) => {
    const { data } = await api.post("/auth/send-otp", { email });
    return data;
  }, []);

  /** Verify OTP and sign in. */
  const verifyOtp = useCallback(async (email, otp) => {
    const { data } = await api.post("/auth/verify-otp", { email, otp });
    localStorage.setItem("auth_token", data.token);
    setUser(data.user);
    return data.user;
  }, []);

  /** Email login — kept for backwards compat, triggers OTP send. */
  const emailLogin = useCallback(async (email) => {
    return await sendOtp(email);
  }, [sendOtp]);

  /** Handle the OAuth2 callback (called from CallbackPage). */
  const handleCallback = useCallback(async (code, state) => {
    const { data } = await api.get(`/auth/callback?code=${code}&state=${state}`);
    localStorage.setItem("auth_token", data.token);
    setUser(data.user);
    return data.user;
  }, []);

  /** Logout — clear local session and optionally redirect to provider logout. */
  const logout = useCallback(async () => {
    try {
      const { data } = await api.post("/auth/logout");
      localStorage.removeItem("auth_token");
      setUser(null);
      if (data.logout_url) {
        window.location.href = data.logout_url;
        return;
      }
    } catch {
      localStorage.removeItem("auth_token");
      setUser(null);
    }
    window.location.href = "/login";
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, authEnabled, ssoConfigured, login, demoLogin, guestLogin, emailLogin, sendOtp, verifyOtp, logout, handleCallback }}>
      {children}
    </AuthContext.Provider>
  );
}

/** @returns {{ user: object|null, loading: boolean, authEnabled: boolean, login: Function, logout: Function, handleCallback: Function }} */
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
