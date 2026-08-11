/** Coloured pill badge for status / category labels. */
export default function Badge({ children, variant = "default", className = "" }) {
  const styles = {
    default: "bg-gray-100 text-gray-700 dark:bg-[#2e2e32] dark:text-[rgba(235,235,245,0.6)]",
    primary: "bg-primary-100 text-primary-700 dark:bg-[rgba(0,255,159,0.1)] dark:text-[#00FF9F]",
    success: "bg-emerald-100 text-emerald-700 dark:bg-[rgba(16,185,129,0.15)] dark:text-[#6ee7b7]",
    warning: "bg-amber-100 text-amber-700 dark:bg-[rgba(245,158,11,0.15)] dark:text-[#fcd34d]",
    error: "bg-red-100 text-red-700 dark:bg-[rgba(239,68,68,0.15)] dark:text-[#fca5a5]",
  };

  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${styles[variant]} ${className}`}
    >
      {children}
    </span>
  );
}
