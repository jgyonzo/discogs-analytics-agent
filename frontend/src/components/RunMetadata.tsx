// Run metadata badges. Per spec §18 + data-model §1.2: render only the
// fields that are present and non-null. Status badge is colored.
//
// The run-id and thread-id badges carry a copy control (016): the badge
// shows a truncated id, but the copy button writes the FULL untruncated
// id to the clipboard with a transient "copied" confirmation. A rejected
// or unavailable clipboard leaves no success state and never throws.

import { useRef, useState } from "react";
import clsx from "clsx";
import { Check, Copy } from "lucide-react";
import type { ResponseStatus, RunMetadata as RunMetadataType } from "../api/types";

export type RunMetadataProps = {
  metadata: RunMetadataType | null;
};

type CopyKey = "run" | "thread";

const STATUS_STYLE: Record<ResponseStatus, string> = {
  succeeded: "bg-green-100 text-green-800 border-green-200",
  failed_unsupported: "bg-slate-100 text-slate-700 border-slate-200",
  failed_clarification_needed: "bg-amber-100 text-amber-800 border-amber-200",
  failed_safety: "bg-red-100 text-red-800 border-red-200",
  failed_validation: "bg-red-100 text-red-800 border-red-200",
};

const NEUTRAL_BADGE =
  "bg-slate-100 text-slate-700 border border-slate-200";

function truncateId(id: string, prefixLen = 6): string {
  if (id.length <= prefixLen) return id;
  return `${id.slice(0, prefixLen)}…`;
}

function Badge({
  label,
  value,
  className,
  testId,
}: {
  label: string;
  value: string;
  className?: string;
  testId?: string;
}) {
  return (
    <span
      data-testid={testId}
      className={clsx(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium border",
        className ?? NEUTRAL_BADGE,
      )}
      title={`${label}: ${value}`}
    >
      <span className="text-slate-500">{label}</span>
      <span>{value}</span>
    </span>
  );
}

// A neutral badge that displays a truncated id and exposes a copy button
// that writes the full (untruncated) id to the clipboard.
function CopyableIdBadge({
  label,
  fullValue,
  copied,
  onCopy,
  testId,
  copyTestId,
}: {
  label: string;
  fullValue: string;
  copied: boolean;
  onCopy: () => void;
  testId?: string;
  copyTestId?: string;
}) {
  return (
    <span
      data-testid={testId}
      className={clsx(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        NEUTRAL_BADGE,
      )}
      title={`${label}: ${fullValue}`}
    >
      <span className="text-slate-500">{label}</span>
      <span>{truncateId(fullValue)}</span>
      <button
        type="button"
        data-testid={copyTestId}
        onClick={onCopy}
        aria-label={copied ? `${label} id copied` : `Copy ${label} id`}
        title={copied ? "Copied" : `Copy full ${label} id`}
        className={clsx(
          "ml-0.5 inline-flex items-center justify-center rounded-sm p-0.5",
          "text-slate-400 hover:text-slate-700 hover:bg-slate-200",
          "focus:outline-none focus:ring-1 focus:ring-slate-400",
          copied && "text-green-600 hover:text-green-700",
        )}
      >
        {copied ? (
          <Check className="h-3 w-3" aria-hidden="true" />
        ) : (
          <Copy className="h-3 w-3" aria-hidden="true" />
        )}
      </button>
    </span>
  );
}

export function RunMetadata({ metadata }: RunMetadataProps) {
  const [copied, setCopied] = useState<CopyKey | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Hooks must run unconditionally; the early return below is fine because
  // it comes after all hook calls.
  const handleCopy = async (key: CopyKey, value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(key);
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      timeoutRef.current = setTimeout(() => setCopied(null), 1500);
    } catch {
      // Clipboard unavailable or permission denied: no success state, no
      // crash. Intentionally swallow — the badge still shows the value.
    }
  };

  if (metadata === null) return null;

  const showComplexity = typeof metadata.complexity === "string" && metadata.complexity.length > 0;
  const showModel =
    typeof metadata.selected_model === "string" && metadata.selected_model.length > 0;

  return (
    <div
      aria-label="Run metadata"
      data-testid="run-metadata"
      className="flex flex-wrap items-center gap-1.5"
    >
      <Badge
        label="status"
        value={metadata.status}
        className={STATUS_STYLE[metadata.status]}
        testId="run-metadata-status"
      />
      {showComplexity && (
        <Badge
          label="complexity"
          value={metadata.complexity!}
          testId="run-metadata-complexity"
        />
      )}
      {showModel && (
        <Badge
          label="model"
          value={metadata.selected_model as string}
          testId="run-metadata-model"
        />
      )}
      <CopyableIdBadge
        label="run"
        fullValue={metadata.run_id}
        copied={copied === "run"}
        onCopy={() => void handleCopy("run", metadata.run_id)}
        testId="run-metadata-run-id"
        copyTestId="copy-run-id"
      />
      <CopyableIdBadge
        label="thread"
        fullValue={metadata.thread_id}
        copied={copied === "thread"}
        onCopy={() => void handleCopy("thread", metadata.thread_id)}
        testId="run-metadata-thread-id"
        copyTestId="copy-thread-id"
      />
      <span className="sr-only" role="status" aria-live="polite">
        {copied ? `Copied ${copied} id` : ""}
      </span>
    </div>
  );
}
