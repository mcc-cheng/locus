import { useEffect, useState } from "react";
import { api, formatBytes } from "../api/client";
import type { WarehouseSummary } from "../api/types";
import { useApp } from "../store";
import { Badge, Button, Card, ErrorBox, PageTitle, Spinner } from "../components/ui";

export function Home() {
  const { openDataset, setTab, schemaVersion } = useApp();
  const [summary, setSummary] = useState<WarehouseSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    api.schema().then(setSummary).catch((e) => setError(String(e.message ?? e)));
  }, [schemaVersion]);

  if (error) return <ErrorBox message={error} />;
  if (!summary) return <Spinner />;

  const empty = summary.dataset_count === 0;

  return (
    <div>
      <PageTitle title="Home" subtitle="Your aggregated datasets at a glance." />

      <div className="mb-8 grid grid-cols-3 gap-4">
        <Stat label="Datasets" value={summary.dataset_count.toLocaleString()} />
        <Stat label="Total rows" value={summary.total_rows.toLocaleString()} />
        <Stat label="Stored (source)" value={formatBytes(summary.total_source_bytes)} />
      </div>

      {empty ? (
        <Card>
          <p className="text-sm text-slate-600">
            No datasets yet. Head to the Upload tab to add your first CSV — Locus will store it
            verbatim and build a queryable schema without changing any of your data.
          </p>
          <div className="mt-4">
            <Button onClick={() => setTab("upload")}>Upload a CSV</Button>
          </div>
        </Card>
      ) : (
        <Card>
          <h2 className="mb-3 text-sm font-semibold text-slate-700">Recent uploads</h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs uppercase text-slate-400">
                <th className="py-2">File</th>
                <th>Uploaded</th>
                <th className="text-right">Rows</th>
                <th>Engine</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {summary.datasets.map((d) => (
                <tr key={d.name} className="border-b border-slate-100 last:border-0">
                  <td className="py-2 font-medium text-slate-800">{d.source_filename}</td>
                  <td className="text-slate-500">
                    {new Date(d.upload_timestamp).toLocaleString()}
                  </td>
                  <td className="text-right tabular-nums">{d.row_count.toLocaleString()}</td>
                  <td>
                    <Badge tone="indigo">{d.engine}</Badge>
                  </td>
                  <td>
                    <Badge tone="green">{d.status}</Badge>
                  </td>
                  <td className="text-right">
                    <Button variant="secondary" onClick={() => openDataset(d.name)}>
                      Open
                    </Button>
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

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <div className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-slate-900 tabular-nums">{value}</div>
    </Card>
  );
}
