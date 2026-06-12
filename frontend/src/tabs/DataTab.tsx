import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { DatasetSummary, QueryResult, SectionManifest } from "../api/types";
import { useApp } from "../store";
import { Badge, Button, Card, ErrorBox, PageTitle, Spinner } from "../components/ui";

const PAGE_SIZE = 50;

function quote(id: string): string {
  return '"' + id.replace(/"/g, '""') + '"';
}

export function DataTab() {
  const { selectedSection, openDataset, schemaVersion } = useApp();
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [manifest, setManifest] = useState<SectionManifest | null>(null);
  const [table, setTable] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.schema().then((s) => setDatasets(s.datasets)).catch((e) => setError(String(e.message)));
  }, [schemaVersion]);

  useEffect(() => {
    setManifest(null);
    setTable(null);
    setResult(null);
    if (!selectedSection) return;
    api
      .schemaSection(selectedSection)
      .then((m) => {
        setManifest(m);
        setTable(m.tables.find((t) => t.name === "raw")?.name ?? m.tables[0]?.name ?? null);
      })
      .catch((e) => setError(String(e.message)));
  }, [selectedSection]);

  useEffect(() => {
    setResult(null);
    if (!selectedSection || !table) return;
    setError(null);
    api
      .query(`SELECT * FROM ${quote(selectedSection)}.${quote(table)}`, page, PAGE_SIZE)
      .then(setResult)
      .catch((e) => setError(String(e.message)));
  }, [selectedSection, table, page]);

  const filtered = useMemo(() => {
    if (!result) return [];
    if (!filter.trim()) return result.rows;
    const q = filter.toLowerCase();
    return result.rows.filter((r) => r.some((c) => String(c ?? "").toLowerCase().includes(q)));
  }, [result, filter]);

  function exportCsv() {
    if (!result) return;
    const esc = (v: unknown) => {
      const s = String(v ?? "");
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const lines = [
      result.columns.map(esc).join(","),
      ...filtered.map((r) => r.map(esc).join(",")),
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${selectedSection}_${table}_p${page}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  const typeOf = (col: string) =>
    manifest?.tables.find((t) => t.name === table)?.columns.find((c) => c.name === col)
      ?.stored_type ?? "";

  return (
    <div className="flex gap-6">
      {/* Dataset + table selector */}
      <aside className="w-56 shrink-0">
        <PageTitle title="Data" />
        <div className="space-y-1">
          {datasets.map((d) => (
            <button
              key={d.name}
              onClick={() => openDataset(d.name)}
              className={`block w-full truncate rounded-lg px-3 py-2 text-left text-sm ${
                d.name === selectedSection
                  ? "bg-indigo-600 text-white"
                  : "text-slate-600 hover:bg-slate-100"
              }`}
              title={d.source_filename}
            >
              {d.source_filename}
            </button>
          ))}
        </div>
        {manifest && (
          <div className="mt-4">
            <div className="mb-1 text-xs font-semibold uppercase text-slate-400">Tables</div>
            <div className="space-y-1">
              {manifest.tables.map((t) => (
                <button
                  key={t.name}
                  onClick={() => {
                    setTable(t.name);
                    setPage(1);
                  }}
                  className={`flex w-full items-center justify-between rounded px-2 py-1 text-sm ${
                    t.name === table ? "bg-slate-200 font-medium" : "text-slate-600 hover:bg-slate-100"
                  }`}
                >
                  <span>{t.name}</span>
                  <span className="text-xs text-slate-400">{t.row_count.toLocaleString()}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </aside>

      {/* Table view */}
      <div className="min-w-0 flex-1">
        {error && <ErrorBox message={error} />}
        {!selectedSection && <p className="text-sm text-slate-500">Select a dataset.</p>}
        {selectedSection && !result && !error && <Spinner />}
        {result && (
          <Card>
            <div className="mb-3 flex items-center justify-between gap-3">
              <input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter this page…"
                className="w-64 rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
              />
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <Badge>read-only</Badge>
                <Button variant="secondary" onClick={exportCsv}>
                  Export CSV
                </Button>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-slate-200 text-left">
                    {result.columns.map((c) => (
                      <th key={c} className="px-2 py-1.5">
                        <div className="font-semibold text-slate-700">{c}</div>
                        <div className="font-normal text-slate-400">{typeOf(c)}</div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((r, i) => (
                    <tr key={i} className="border-b border-slate-100">
                      {r.map((c, j) => (
                        <td key={j} className="px-2 py-1 text-slate-700">
                          {c === null ? <span className="text-slate-300">∅</span> : String(c)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-3 flex items-center justify-between text-sm text-slate-500">
              <span>
                Page {page} · {filtered.length} shown
                {result.has_more ? " · more available" : ""}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  Prev
                </Button>
                <Button
                  variant="secondary"
                  disabled={!result.has_more}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
