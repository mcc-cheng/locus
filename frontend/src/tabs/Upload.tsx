import { useRef, useState } from "react";
import { api } from "../api/client";
import type { IngestResult } from "../api/types";
import { useApp } from "../store";
import { Badge, Button, Card, ErrorBox, PageTitle } from "../components/ui";

const BIOPACK_WARNING =
  "This will normalize SMILES strings and parse gene/dose columns. " +
  "Original values will be preserved in a _raw column alongside.";

type Engine = "deterministic" | "agentic";
type Transform = "none" | "smiles" | "gene" | "dose";

interface Preview {
  header: string[];
  rows: string[][];
}

function parsePreview(text: string): Preview {
  const lines = text.split(/\r?\n/).filter((l) => l.length > 0).slice(0, 6);
  const cells = lines.map((l) => l.split(","));
  return { header: cells[0] ?? [], rows: cells.slice(1) };
}

const STAGES = ["Preserving source", "Landing verbatim", "Inferring schema", "Running QC checks", "Sealing"];

export function Upload() {
  const { refreshSchema, openDataset } = useApp();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [engine, setEngine] = useState<Engine>("deterministic");
  const [biopackOn, setBiopackOn] = useState(false);
  const [transforms, setTransforms] = useState<Record<string, Transform>>({});
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState(0);
  const [result, setResult] = useState<IngestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  function choose(f: File) {
    setFile(f);
    setResult(null);
    setError(null);
    f.text().then((t) => setPreview(parsePreview(t)));
  }

  function biopackConfig(): Record<string, string> {
    if (!biopackOn) return {};
    const cfg: Record<string, string> = {};
    for (const [col, t] of Object.entries(transforms)) if (t !== "none") cfg[col] = t;
    return cfg;
  }

  async function runIngest() {
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    setStage(0);
    const timer = setInterval(() => setStage((s) => Math.min(s + 1, STAGES.length - 1)), 600);
    try {
      const res = await api.ingest(file, engine, biopackConfig());
      setResult(res);
      refreshSchema();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      clearInterval(timer);
      setBusy(false);
    }
  }

  return (
    <div>
      <PageTitle title="Upload" subtitle="Add a CSV. Your data is stored exactly as-is." />

      {/* Drop zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const f = e.dataTransfer.files?.[0];
          if (f) choose(f);
        }}
        onClick={() => fileRef.current?.click()}
        className={`flex h-40 cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed transition ${
          dragging ? "border-indigo-500 bg-indigo-50" : "border-slate-300 bg-slate-50"
        }`}
      >
        <div className="text-sm font-medium text-slate-600">
          Drag &amp; drop a CSV here, or click to browse
        </div>
        {file && <div className="mt-2 text-xs text-slate-500">{file.name}</div>}
        <input
          ref={fileRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && choose(e.target.files[0])}
        />
      </div>

      {preview && (
        <Card className="mt-5">
          <h2 className="mb-2 text-sm font-semibold text-slate-700">Preview (first rows)</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-slate-400">
                  {preview.header.map((h, i) => (
                    <th key={i} className="px-2 py-1">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((r, i) => (
                  <tr key={i} className="border-t border-slate-100">
                    {r.map((c, j) => (
                      <td key={j} className="px-2 py-1 text-slate-700">{c}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Engine selector */}
          <div className="mt-5 grid grid-cols-2 gap-3">
            <EngineCard
              selected={engine === "deterministic"}
              onSelect={() => setEngine("deterministic")}
              title="Deterministic"
              desc="Rule-based schema inference. Fast, predictable, no model needed."
            />
            <EngineCard
              selected={engine === "agentic"}
              onSelect={() => setEngine("agentic")}
              title="Agentic (local AI)"
              desc="A local model suggests the structure; every choice is verified against your data."
            />
          </div>

          {/* Biopack */}
          <div className="mt-5">
            <label className="flex items-center gap-2 text-sm font-medium text-slate-700">
              <input
                type="checkbox"
                checked={biopackOn}
                onChange={(e) => setBiopackOn(e.target.checked)}
              />
              Enable biomedical normalization (biopack)
            </label>
            {biopackOn && (
              <div className="mt-2 space-y-3">
                <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  ⚠️ {BIOPACK_WARNING}
                </div>
                <div className="grid grid-cols-2 gap-2">
                  {preview.header.map((col) => (
                    <div key={col} className="flex items-center justify-between gap-2 text-xs">
                      <span className="truncate text-slate-600">{col}</span>
                      <select
                        className="rounded border border-slate-300 px-1 py-0.5"
                        value={transforms[col] ?? "none"}
                        onChange={(e) =>
                          setTransforms((t) => ({ ...t, [col]: e.target.value as Transform }))
                        }
                      >
                        <option value="none">— none —</option>
                        <option value="smiles">SMILES</option>
                        <option value="gene">gene</option>
                        <option value="dose">dose</option>
                      </select>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="mt-5">
            <Button onClick={runIngest} disabled={busy}>
              {busy ? "Ingesting…" : "Ingest"}
            </Button>
          </div>
        </Card>
      )}

      {busy && (
        <Card className="mt-5">
          <div className="space-y-1 text-sm">
            {STAGES.map((s, i) => (
              <div key={s} className={i <= stage ? "text-indigo-600" : "text-slate-400"}>
                {i < stage ? "✓" : i === stage ? "…" : "○"} {s}
              </div>
            ))}
          </div>
        </Card>
      )}

      {error && (
        <div className="mt-5">
          <ErrorBox message={error} />
        </div>
      )}

      {result && (
        <Card className="mt-5">
          <div className="mb-2 flex items-center gap-2">
            <h2 className="text-sm font-semibold text-slate-700">
              Ingested {result.section}
            </h2>
            <Badge tone={result.qc_passed ? "green" : "amber"}>
              {result.qc_passed ? "QC passed" : "QC failed"}
            </Badge>
          </div>
          <ul className="text-sm text-slate-600">
            <li>Rows: {result.row_count.toLocaleString()}</li>
            <li>
              Tables: {result.tables.map((t) => t.name).join(", ")} ({result.tables.length})
            </li>
            <li>Foreign keys: {result.foreign_keys}</li>
            {result.grain && <li>Grain: {result.grain}</li>}
          </ul>
          <div className="mt-4">
            <Button variant="secondary" onClick={() => openDataset(result.section)}>
              Open in Data
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
}

function EngineCard({
  selected,
  onSelect,
  title,
  desc,
}: {
  selected: boolean;
  onSelect: () => void;
  title: string;
  desc: string;
}) {
  return (
    <button
      onClick={onSelect}
      className={`rounded-lg border p-3 text-left transition ${
        selected ? "border-indigo-500 bg-indigo-50" : "border-slate-200 hover:bg-slate-50"
      }`}
    >
      <div className="text-sm font-semibold text-slate-800">{title}</div>
      <div className="mt-1 text-xs text-slate-500">{desc}</div>
    </button>
  );
}
