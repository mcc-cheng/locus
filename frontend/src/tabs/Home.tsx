import { useEffect, useState } from "react";
import { api, formatBytes } from "../api/client";
import type { WarehouseSummary } from "../api/types";
import { useApp } from "../store";
import { Badge, Button, Card, EmptyState, ErrorBox, PageTitle, Skeleton } from "../components/ui";
import { DataIcon, ShieldIcon, UploadIcon } from "../components/icons";
import type { ReactNode } from "react";

export function Home() {
  const { openDataset, setTab, refreshSchema, schemaVersion } = useApp();
  const [summary, setSummary] = useState<WarehouseSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    setSummary(null);
    api.schema().then(setSummary).catch((e) => setError(String(e.message ?? e)));
  }, [schemaVersion]);

  async function remove(section: string, filename: string) {
    if (!window.confirm(`Delete "${filename}"? This permanently removes the dataset.`)) return;
    try {
      await api.deleteDataset(section);
      refreshSchema();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  }

  if (error) return <ErrorBox message={error} />;

  const empty = summary?.dataset_count === 0;

  return (
    <div>
      <PageTitle title="Home" subtitle="Your aggregated datasets at a glance." />

      {/* Stat cards */}
      <div className="mb-5 grid grid-cols-3 gap-4">
        <Stat
          label="Datasets"
          value={summary?.dataset_count.toLocaleString()}
          icon={<DataIcon className="h-5 w-5" />}
          accent="from-indigo-500 to-violet-600"
        />
        <Stat
          label="Total rows"
          value={summary?.total_rows.toLocaleString()}
          icon={<RowsGlyph />}
          accent="from-sky-500 to-cyan-600"
        />
        <Stat
          label="Stored (source)"
          value={summary ? formatBytes(summary.total_source_bytes) : undefined}
          icon={<DiskGlyph />}
          accent="from-emerald-500 to-teal-600"
        />
      </div>

      {/* Reassurance strip */}
      <div className="mb-7 flex items-center gap-2.5 rounded-xl border border-emerald-200/70 bg-emerald-50/60 px-4 py-2.5 text-sm text-emerald-800">
        <ShieldIcon className="h-4 w-4 shrink-0 text-emerald-600" />
        Every value is stored exactly as uploaded — verified by a round-trip check on every ingest.
      </div>

      {!summary ? (
        <Card>
          <Skeleton className="mb-3 h-5 w-40" />
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="mb-2 h-9 w-full" />
          ))}
        </Card>
      ) : empty ? (
        <EmptyState
          icon={<UploadIcon className="h-10 w-10" />}
          title="No datasets yet"
          body="Upload your first CSV — Locus stores it verbatim and builds a queryable schema without changing any of your data."
          action={<Button onClick={() => setTab("upload")}>Upload a CSV</Button>}
        />
      ) : (
        <Card pad={false}>
          <div className="border-b border-slate-100 px-5 py-3.5 text-sm font-semibold text-slate-700">
            Recent uploads
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-slate-400">
                <th className="px-5 py-2 font-medium">File</th>
                <th className="font-medium">Uploaded</th>
                <th className="text-right font-medium">Rows</th>
                <th className="font-medium">Engine</th>
                <th className="font-medium">Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {summary.datasets.map((d) => (
                <tr
                  key={d.name}
                  className="border-t border-slate-100 transition hover:bg-slate-50/70"
                >
                  <td className="px-5 py-3 font-medium text-slate-800">{d.source_filename}</td>
                  <td className="text-slate-500">
                    {new Date(d.upload_timestamp).toLocaleDateString(undefined, {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </td>
                  <td className="tabular text-right text-slate-700">
                    {d.row_count.toLocaleString()}
                  </td>
                  <td>
                    <Badge tone="indigo">{d.engine}</Badge>
                  </td>
                  <td>
                    <Badge tone="green">{d.status}</Badge>
                  </td>
                  <td className="px-5 text-right">
                    <div className="flex justify-end gap-2">
                      <Button variant="secondary" size="sm" onClick={() => openDataset(d.name)}>
                        Open
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => remove(d.name, d.source_filename)}
                      >
                        Delete
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  icon,
  accent,
}: {
  label: string;
  value?: string;
  icon: ReactNode;
  accent: string;
}) {
  return (
    <Card className="relative overflow-hidden">
      <div className="flex items-start justify-between">
        <div className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</div>
        <div
          className={`flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br ${accent} text-white shadow-sm`}
        >
          {icon}
        </div>
      </div>
      {value === undefined ? (
        <Skeleton className="mt-3 h-8 w-20" />
      ) : (
        <div className="tabular mt-2 text-3xl font-semibold tracking-tight text-slate-900">
          {value}
        </div>
      )}
    </Card>
  );
}

const RowsGlyph = () => (
  <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
    <rect x="3" y="5" width="18" height="4" rx="1" />
    <rect x="3" y="11" width="18" height="4" rx="1" />
    <rect x="3" y="17" width="18" height="2.5" rx="1" />
  </svg>
);
const DiskGlyph = () => (
  <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
    <ellipse cx="12" cy="6" rx="8" ry="3" />
    <path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6" />
  </svg>
);
