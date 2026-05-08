// Collapsible "Generated SQL" panel with copy-to-clipboard.
// Per spec §16: hidden when no SQL available, default-collapsed when present,
// readable + copyable when expanded.

import { useState } from "react";
import { Check, ChevronDown, ChevronUp, Copy } from "lucide-react";

export type SqlViewerProps = {
  sql: string | null;
};

export function SqlViewer({ sql }: SqlViewerProps) {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  if (sql === null || sql.trim().length === 0) return null;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard access can fail (insecure context, permission denied).
      // We silently no-op — the SQL is still visible to the user.
    }
  };

  return (
    <section
      aria-label="Generated SQL"
      className="rounded-md border border-slate-200 bg-white"
    >
      <header className="flex items-center justify-between px-3 py-2">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="inline-flex items-center gap-1 text-xs font-medium text-slate-700 hover:text-slate-900"
          aria-expanded={expanded}
          aria-controls="sql-viewer-body"
        >
          {expanded ? (
            <ChevronUp className="h-3 w-3" aria-hidden="true" />
          ) : (
            <ChevronDown className="h-3 w-3" aria-hidden="true" />
          )}
          <span>Generated SQL</span>
        </button>
        {expanded && (
          <button
            type="button"
            onClick={handleCopy}
            className="inline-flex items-center gap-1 rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100"
            aria-label="Copy SQL to clipboard"
          >
            {copied ? (
              <>
                <Check className="h-3 w-3" aria-hidden="true" />
                <span>Copied</span>
              </>
            ) : (
              <>
                <Copy className="h-3 w-3" aria-hidden="true" />
                <span>Copy</span>
              </>
            )}
          </button>
        )}
      </header>
      {expanded && (
        <pre
          id="sql-viewer-body"
          className="border-t border-slate-200 px-3 py-2 text-xs text-slate-800 overflow-x-auto whitespace-pre-wrap break-words"
        >
          <code>{sql}</code>
        </pre>
      )}
    </section>
  );
}
