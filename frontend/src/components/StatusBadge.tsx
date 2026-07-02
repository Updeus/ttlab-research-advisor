type StatusBadgeProps = {
  label: string;
  tone?: "good" | "warn" | "neutral";
};

export function StatusBadge({ label, tone = "neutral" }: StatusBadgeProps) {
  return <span className={`status-badge status-badge--${tone}`}>{label.replaceAll("_", " ")}</span>;
}
