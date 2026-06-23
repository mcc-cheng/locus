import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { DataRow } from "../api/types";
import { Button, Field } from "../components/ui";

/** Columns whose sampled values are mostly numeric — so we can insert a cast
 *  automatically when building a formula. */
function numericColumns(columns: string[], rows: DataRow[]): Set<string> {
  const out = new Set<string>();
  columns.forEach((c, ci) => {
    let num = 0;
    let tot = 0;
    for (const r of rows.slice(0, 50)) {
      const v = r.cells[ci];
      if (v == null || v.trim() === "") continue;
      tot++;
      if (!Number.isNaN(Number(v))) num++;
    }
    if (tot > 0 && num / tot >= 0.8) out.add(c);
  });
  return out;
}

/** Add a column to a dataset — empty, or computed from a spreadsheet-style
 *  formula (a SQL expression over the other columns). */
export function AddColumnDialog({
  section,
  columns,
  rows,
  onClose,
  onAdded,
}: {
  section: string;
  columns: string[];
  rows: DataRow[];
  onClose: () => void;
  onAdded: () => void;
}) {
  const [name, setName] = useState("");
  const [formula, setFormula] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const numeric = useMemo(() => numericColumns(columns, rows), [columns, rows]);

  function insertRef(col: string) {
    const ref = numeric.has(col) ? `TRY_CAST("${col}" AS DOUBLE)` : `"${col}"`;
    setFormula((f) => (f.trim() ? `${f} ${ref}` : ref));
  }

  async function submit() {
    if (!name.trim()) {
      setError("Give the column a name.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.addColumn(section, name.trim(), formula.trim() || undefined);
      onAdded();
      onClose();
    } catch (e) {
      setError(String((e as Error).message ?? e));
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-2xl bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-base font-semibold text-slate-800">Add column</h2>
        <p className="mt-0.5 text-xs text-slate-400">
          Leave the formula blank for an empty column, or compute it from the other columns
          (like an Excel formula).
        </p>

        <div className="mt-4 space-y-3">
          <Field label="Column name">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
              placeholder="e.g. bmi"
              className="w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
            />
          </Field>

          <Field label="Formula (optional)">
            <textarea
              value={formula}
              onChange={(e) => setFormula(e.target.value)}
              rows={2}
              placeholder={'e.g. TRY_CAST("weight" AS DOUBLE) / (TRY_CAST("height" AS DOUBLE) * TRY_CAST("height" AS DOUBLE))'}
              className="w-full resize-none rounded-lg border border-slate-300 px-3 py-1.5 font-mono text-[12px] outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
            />
          </Field>

          <div>
            <div className="mb-1 text-[11px] text-slate-400">
              Click a column to insert it (numeric columns are cast automatically):
            </div>
            <div className="flex flex-wrap gap-1.5">
              {columns.map((c) => (
                <button
                  key={c}
                  onClick={() => insertRef(c)}
                  className={`rounded-md border px-2 py-1 text-[11px] transition hover:bg-slate-50 ${
                    numeric.has(c)
                      ? "border-indigo-200 text-indigo-700"
                      : "border-slate-200 text-slate-600"
                  }`}
                >
                  {c}
                  {numeric.has(c) && <span className="ml-1 text-indigo-300">#</span>}
                </button>
              ))}
            </div>
            <p className="mt-2 text-[11px] text-slate-400">
              You can use any DuckDB SQL: <code>+ - * /</code>, <code>CASE WHEN … THEN … END</code>,
              <code> CONCAT</code>, <code>ROUND(x, 2)</code>, etc.
            </p>
          </div>

          {error && <p className="text-xs text-red-600">{error}</p>}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button size="sm" onClick={submit} disabled={busy || !name.trim()}>
            {busy ? "Adding…" : "Add column"}
          </Button>
        </div>
      </div>
    </div>
  );
}
