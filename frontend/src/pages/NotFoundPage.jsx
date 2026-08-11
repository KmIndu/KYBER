/** 404 catch-all — shown for unrecognised routes; auto-redirects to home. */

import { useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import Button from "../components/Button";

export default function NotFoundPage() {
  const navigate = useNavigate();
  const [countdown, setCountdown] = useState(5);

  useEffect(() => {
    if (countdown <= 0) {
      navigate("/");
      return;
    }
    const timer = setTimeout(() => setCountdown((c) => c - 1), 1000);
    return () => clearTimeout(timer);
  }, [countdown, navigate]);

  return (
    <div className="max-w-md mx-auto px-4 py-20 text-center">
      <div className="w-20 h-20 bg-red-50 rounded-full flex items-center justify-center mx-auto mb-6">
        <span className="text-4xl">🚫</span>
      </div>
      <h1 className="text-5xl font-bold text-gray-900 mb-2">404</h1>
      <h2 className="text-xl font-semibold text-gray-700 mb-3">
        Page Not Found
      </h2>
      <p className="text-gray-500 mb-6">
        The page you're looking for doesn't exist or has been moved.
        <br />
        Redirecting to home in{" "}
        <span className="font-semibold text-primary-600">{countdown}s</span>…
      </p>
      <Link to="/">
        <Button>Go Home Now</Button>
      </Link>
    </div>
  );
}
