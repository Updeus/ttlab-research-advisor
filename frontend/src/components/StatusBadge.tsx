type StatusBadgeProps = {
  label: string;
  tone?: "good" | "warn" | "neutral" | "danger" | "info" | "pending";
};

export function StatusBadge({ label, tone }: StatusBadgeProps) {
  const displayLabel = label.replaceAll("_", " ");
  const badgeTone = tone ?? toneForStatus(label);
  return <span className={`status-badge status-badge--${badgeTone}`}>{displayLabel}</span>;
}

function toneForStatus(label: string): NonNullable<StatusBadgeProps["tone"]> {
  const normalized = label.toLowerCase().replaceAll("_", " ");
  if (
    normalized.includes("approved") ||
    normalized.includes("reviewed") ||
    normalized.includes("grounded") ||
    normalized.includes("generated") ||
    normalized.includes("extracted") ||
    normalized.includes("ready") ||
    normalized.includes("available")
  ) {
    return "good";
  }
  if (
    normalized.includes("failed") ||
    normalized.includes("rejected") ||
    normalized.includes("unsupported") ||
    normalized.includes("missing") ||
    normalized.includes("error")
  ) {
    return "danger";
  }
  if (
    normalized.includes("needs") ||
    normalized.includes("partial") ||
    normalized.includes("review") ||
    normalized.includes("inferred") ||
    normalized.includes("not found")
  ) {
    return "warn";
  }
  if (normalized.includes("suggested") || normalized.includes("public") || normalized.includes("synthetic")) {
    return "info";
  }
  if (normalized.includes("not extracted") || normalized.includes("loading") || normalized.includes("pending") || normalized.includes("processing")) {
    return "pending";
  }
  return "neutral";
}
