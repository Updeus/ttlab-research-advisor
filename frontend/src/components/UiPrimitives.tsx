import type { ButtonHTMLAttributes, CSSProperties, ReactNode } from "react";
import { AlertCircle, CheckCircle2, Info, Loader2, Search, Sparkles, X } from "lucide-react";

export type ToastTone = "success" | "warning" | "error" | "info";

export type ToastMessage = {
  id: number;
  message: string;
  tone?: ToastTone;
};

type SkeletonBlockProps = {
  width?: string;
  height?: string;
  className?: string;
  rounded?: boolean;
};

export function SkeletonBlock({ width = "100%", height = "1rem", className = "", rounded = false }: SkeletonBlockProps) {
  const style: CSSProperties = { width, height };
  return <span aria-hidden="true" className={`skeleton ${rounded ? "skeleton--round" : ""} ${className}`} style={style} />;
}

export function MetricSkeletonGrid({ count = 6, compact = false }: { count?: number; compact?: boolean }) {
  return (
    <div className={compact ? "metric-skeleton-grid metric-skeleton-grid--compact" : "metric-skeleton-grid"} aria-hidden="true">
      {Array.from({ length: count }).map((_, index) => (
        <article className="metric skeleton-card" key={index}>
          <SkeletonBlock width="68%" height="0.78rem" />
          <SkeletonBlock width="44%" height={compact ? "1.35rem" : "2rem"} />
        </article>
      ))}
    </div>
  );
}

export function CardSkeleton({ lines = 3, compact = false }: { lines?: number; compact?: boolean }) {
  return (
    <article className={compact ? "skeleton-card skeleton-card--compact" : "skeleton-card"} aria-hidden="true">
      <div className="skeleton-row">
        <SkeletonBlock width="72px" height="0.75rem" />
        <SkeletonBlock width="112px" height="0.75rem" />
      </div>
      <SkeletonBlock width="72%" height="1.05rem" />
      {Array.from({ length: lines }).map((_, index) => (
        <SkeletonBlock key={index} width={index === lines - 1 ? "58%" : "100%"} height="0.82rem" />
      ))}
    </article>
  );
}

export function ListSkeleton({ count = 3, lines = 3 }: { count?: number; lines?: number }) {
  return (
    <div className="paper-list" role="status" aria-label="Loading content" aria-busy="true">
      {Array.from({ length: count }).map((_, index) => (
        <CardSkeleton key={index} lines={lines} />
      ))}
    </div>
  );
}

export function DetailSkeleton() {
  return (
    <div className="detail-skeleton" role="status" aria-label="Loading paper detail" aria-busy="true">
      <CardSkeleton lines={2} />
      <MetricSkeletonGrid count={4} compact />
      <ListSkeleton count={2} lines={4} />
    </div>
  );
}

export function InlineProgress({ label }: { label: string }) {
  return (
    <div className="inline-progress" role="status" aria-live="polite">
      <Loader2 className="spin" size={18} aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state" role="status">
      <strong>{title}</strong>
      {body ? <p>{body}</p> : null}
      {action ? <div className="empty-state__action">{action}</div> : null}
    </div>
  );
}

type BusyButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  busy?: boolean;
  busyLabel?: string;
  icon?: ReactNode;
  variant?: "primary" | "secondary" | "danger" | "ghost";
};

export function BusyButton({
  busy = false,
  busyLabel,
  icon,
  variant = "primary",
  children,
  className = "",
  disabled,
  ...props
}: BusyButtonProps) {
  const variantClass = variant === "primary" ? "" : ` action-button--${variant}`;
  return (
    <button className={`action-button${variantClass} ${className}`} disabled={disabled || busy} {...props}>
      {busy ? <Loader2 className="button-icon spin" size={16} aria-hidden="true" /> : icon ? <span className="button-icon">{icon}</span> : null}
      <span>{busy && busyLabel ? busyLabel : children}</span>
    </button>
  );
}

export function SearchActionButton({
  busy,
  children = "Search",
  ...props
}: Omit<BusyButtonProps, "icon" | "busyLabel">) {
  return (
    <BusyButton busy={busy} busyLabel="Searching..." icon={<Search size={16} aria-hidden="true" />} {...props}>
      {children}
    </BusyButton>
  );
}

export function GenerateButton({
  busy,
  children,
  busyLabel = "Generating...",
  ...props
}: Omit<BusyButtonProps, "icon">) {
  return (
    <BusyButton busy={busy} busyLabel={busyLabel} icon={<Sparkles size={16} aria-hidden="true" />} {...props}>
      {children}
    </BusyButton>
  );
}

export function ToastStack({ messages, onDismiss }: { messages: ToastMessage[]; onDismiss: (id: number) => void }) {
  if (!messages.length) {
    return null;
  }
  return (
    <div className="toast-stack" aria-live="polite" aria-relevant="additions removals">
      {messages.map((toast) => (
        <div className={`toast toast--${toast.tone ?? "info"}`} role={toast.tone === "error" ? "alert" : "status"} key={toast.id}>
          {toastIcon(toast.tone ?? "info")}
          <span>{toast.message}</span>
          <button aria-label="Dismiss notification" onClick={() => onDismiss(toast.id)}>
            <X size={14} aria-hidden="true" />
          </button>
        </div>
      ))}
    </div>
  );
}

function toastIcon(tone: ToastTone) {
  if (tone === "success") {
    return <CheckCircle2 size={18} aria-hidden="true" />;
  }
  if (tone === "error") {
    return <AlertCircle size={18} aria-hidden="true" />;
  }
  if (tone === "warning") {
    return <AlertCircle size={18} aria-hidden="true" />;
  }
  return <Info size={18} aria-hidden="true" />;
}
