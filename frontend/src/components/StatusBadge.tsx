type StatusBadgeProps = {
  label: string;
  tone?: "good" | "warn" | "neutral" | "danger" | "info" | "pending";
};

export function StatusBadge({ label, tone }: StatusBadgeProps) {
  const displayLabel = label.replaceAll("_", " ");
  const badgeTone = tone ?? toneForStatus(label);
  return <span className={`status-badge status-badge--${badgeTone}`}>{displayLabel}</span>;
}

export function toneForStatus(label: string): NonNullable<StatusBadgeProps["tone"]> {
  const normalized = label.toLowerCase().replaceAll("_", " ");
  if (
    normalized.includes("not available") ||
    normalized.includes("unavailable") ||
    normalized.includes("not ready") ||
    normalized.includes("not generated") ||
    normalized.includes("not extracted") ||
    normalized.includes("not run") ||
    normalized.includes("invalid") ||
    normalized.includes("failed") ||
    normalized.includes("rejected") ||
    normalized.includes("unsupported") ||
    normalized.includes("missing") ||
    normalized.includes("error")
  ) {
    return "danger";
  }
  if (
    normalized.includes("ai reviewed") ||
    normalized.includes("needs") ||
    normalized.includes("partial") ||
    normalized.includes("review") ||
    normalized.includes("inferred") ||
    normalized.includes("not found") ||
    normalized.includes("stale")
  ) {
    return "warn";
  }
  if (normalized.includes("loading") || normalized.includes("pending") || normalized.includes("processing")) {
    return "pending";
  }
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
  if (normalized.includes("suggested") || normalized.includes("public") || normalized.includes("synthetic")) {
    return "info";
  }
  return "neutral";
}
