// Run metadata badges. Per spec §18 + data-model §1.2: render only the
// fields that are present and non-null. Status badge is colored.

import clsx from "clsx";
import type { ResponseStatus, RunMetadata as RunMetadataType } from "../api/types";

export type RunMetadataProps = {
  metadata: RunMetadataType | null;
};

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

export function RunMetadata({ metadata }: RunMetadataProps) {
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
      <Badge
        label="run"
        value={truncateId(metadata.run_id)}
        testId="run-metadata-run-id"
      />
      <Badge
        label="thread"
        value={truncateId(metadata.thread_id)}
        testId="run-metadata-thread-id"
      />
    </div>
  );
}
