/** Dismissible alert banner with type-based colour theming. */
export default function Alert({ type = "info", children, className = "" }) {
  const styles = {
    info: "bg-blue-50 border-blue-200 text-blue-800 dark:bg-[rgba(59,130,246,0.1)] dark:border-[rgba(59,130,246,0.25)] dark:text-[#93c5fd]",
    success: "bg-emerald-50 border-emerald-200 text-emerald-800 dark:bg-[rgba(16,185,129,0.1)] dark:border-[rgba(16,185,129,0.25)] dark:text-[#6ee7b7]",
    warning: "bg-amber-50 border-amber-200 text-amber-800 dark:bg-[rgba(245,158,11,0.1)] dark:border-[rgba(245,158,11,0.25)] dark:text-[#fcd34d]",
    error: "bg-red-50 border-red-200 text-red-800 dark:bg-[rgba(239,68,68,0.1)] dark:border-[rgba(239,68,68,0.25)] dark:text-[#fca5a5]",
  };

  return (
    <div
      className={`rounded-lg border px-4 py-3 text-sm ${styles[type]} ${className}`}
      role="alert"
    >
      {children}
    </div>
  );
}
