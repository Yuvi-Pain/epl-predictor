import type { ReactNode } from "react";
import { ApiError } from "../api/client";

export function LoadingState({ label, rows = 4 }: { label: string; rows?: number }) {
  return (
    <div className="skeleton" role="status" aria-live="polite">
      <span className="visually-hidden">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          className="skeleton__bar"
          style={{ width: `${100 - ((i * 17) % 45)}%` }}
          aria-hidden="true"
        />
      ))}
    </div>
  );
}

export function ErrorState({
  title,
  error,
  onRetry,
}: {
  title: string;
  error: unknown;
  onRetry?: () => void;
}) {
  return (
    <div className="state state--error" role="alert">
      <p className="state__title">{title}</p>
      <p>{describeError(error)}</p>
      {onRetry && (
        <button type="button" className="button" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state" role="status">
      <p className="state__title">{title}</p>
      {children && <div className="muted">{children}</div>}
    </div>
  );
}

function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.detail;
  if (error instanceof TypeError) return "Could not reach the server. Is the backend running?";
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}
