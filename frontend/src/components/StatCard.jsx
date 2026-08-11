/** Statistic card displaying a labelled metric with icon. */
export default function StatCard({ label, value, icon, color = "primary" }) {
  const colors = {
    primary: "bg-primary-100 text-primary-600 dark:bg-[rgba(0,255,159,0.1)] dark:text-[#00FF9F]",
    success: "bg-emerald-100 text-emerald-600 dark:bg-[rgba(16,185,129,0.15)] dark:text-[#34d399]",
    warning: "bg-amber-100 text-amber-600 dark:bg-[rgba(245,158,11,0.15)] dark:text-[#fbbf24]",
    error: "bg-red-100 text-red-600 dark:bg-[rgba(239,68,68,0.15)] dark:text-[#f87171]",
  };

  return (
    <div className="bg-white dark:bg-[#202127] rounded-xl border border-gray-200 dark:border-[#2e2e32] p-5 shadow-sm">
      <div className="flex items-center gap-3">
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${colors[color]}`}>
          {icon}
        </div>
        <div>
          <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
          <p className="text-sm text-gray-500 dark:text-[rgba(235,235,245,0.6)]">{label}</p>
        </div>
      </div>
    </div>
  );
}
