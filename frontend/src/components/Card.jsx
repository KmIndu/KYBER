/** Reusable card container with optional header and body sections. */
export default function Card({ children, className = "", ...rest }) {
  return (
    <div className={`bg-white dark:bg-[#202127] rounded-xl border border-gray-200 dark:border-[#2e2e32] shadow-sm ${className}`} {...rest}>
      {children}
    </div>
  );
}

export function CardHeader({ children, className = "" }) {
  return (
    <div className={`px-6 py-4 border-b border-gray-100 dark:border-[#2e2e32] ${className}`}>
      {children}
    </div>
  );
}

export function CardBody({ children, className = "" }) {
  return <div className={`px-6 py-4 ${className}`}>{children}</div>;
}
