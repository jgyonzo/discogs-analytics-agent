// Tabular preview of dataframe_preview rows.
// Per spec §17: render up to 20 rows; infer columns from row 0; horizontal
// scroll for wide tables; placeholder when empty.

const MAX_ROWS = 20;
const EMPTY_COPY = "No data preview available.";

export type DataPreviewTableProps = {
  rows: Record<string, unknown>[];
};

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  // Defensive: agent's V1 always returns primitives, but stringify
  // anything else rather than crashing.
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function isNumericColumn(rows: Record<string, unknown>[], key: string): boolean {
  for (const row of rows) {
    const v = row[key];
    if (v === null || v === undefined) continue;
    if (typeof v !== "number") return false;
  }
  return true;
}

export function DataPreviewTable({ rows }: DataPreviewTableProps) {
  if (rows.length === 0) {
    return (
      <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-500">
        {EMPTY_COPY}
      </div>
    );
  }

  const visible = rows.slice(0, MAX_ROWS);
  const columns = Object.keys(visible[0]!);
  const numericByCol = new Map(
    columns.map((c) => [c, isNumericColumn(visible, c)]),
  );

  return (
    <section
      aria-label="Data preview"
      className="rounded-md border border-slate-200 bg-white overflow-x-auto"
    >
      <table className="w-full text-xs text-slate-800" data-testid="data-preview-table">
        <thead className="bg-slate-50">
          <tr>
            {columns.map((col) => (
              <th
                key={col}
                scope="col"
                className="px-3 py-1 text-left font-medium text-slate-700 border-b border-slate-200 whitespace-nowrap"
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {visible.map((row, i) => (
            <tr key={i} className="even:bg-slate-50/50">
              {columns.map((col) => (
                <td
                  key={col}
                  className={
                    numericByCol.get(col)
                      ? "px-3 py-1 text-right tabular-nums whitespace-nowrap"
                      : "px-3 py-1 whitespace-nowrap"
                  }
                >
                  {formatCell(row[col])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
