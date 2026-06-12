import { useState } from "react";
import Editor from "@monaco-editor/react";
import { api } from "../api/client";
import type { SandboxRunResult } from "../api/types";
import { Badge, Button, Card, EmptyState, ErrorBox, PageTitle } from "../components/ui";
import { BeakerIcon, PlayIcon, ShieldIcon } from "../components/icons";

const STARTER = `# You have a read/write COPY of your data in 'con' (a DuckDB connection).
# pandas (pd), numpy (np), matplotlib (plt) and scikit-learn are available.
tables = con.execute("""
  SELECT table_schema, table_name
  FROM information_schema.tables
  WHERE table_schema NOT IN ('information_schema')
  ORDER BY 1, 2
""").fetchall()
for schema, name in tables:
    print(schema, name)
`;

const IMAGE_RE = /\.(png|svg|jpe?g|gif)$/i;

export function Sandbox() {
  const [sandboxId, setSandboxId] = useState<string | null>(null);
  const [code, setCode] = useState(STARTER);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<SandboxRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function createSandbox() {
    setError(null);
    try {
      const { sandbox_id } = await api.createSandbox();
      setSandboxId(sandbox_id);
      setResult(null);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  }

  async function run() {
    if (!sandboxId) return;
    setRunning(true);
    setError(null);
    try {
      setResult(await api.runSandbox(sandboxId, code));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setRunning(false);
    }
  }

  async function destroy() {
    if (!sandboxId) return;
    await api.deleteSandbox(sandboxId);
    setSandboxId(null);
    setResult(null);
  }

  const images = result?.artifacts.filter((a) => IMAGE_RE.test(a)) ?? [];

  return (
    <div>
      <PageTitle title="Sandbox" subtitle="Run Python experiments against a disposable copy." />

      <div className="mb-5 flex items-start gap-2.5 rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900">
        <ShieldIcon className="mt-0.5 h-5 w-5 shrink-0 text-sky-600" />
        <span>
          You are working on a <strong>copy</strong> of your data. Nothing you run here can
          affect your original dataset.
        </span>
      </div>

      {!sandboxId ? (
        <>
          <EmptyState
            icon={<BeakerIcon className="h-10 w-10" />}
            title="Start a sandbox"
            body="Get an isolated, writable copy of your warehouse to run Python experiments against."
            action={<Button onClick={createSandbox}>Create sandbox</Button>}
          />
          {error && (
            <div className="mt-4">
              <ErrorBox message={error} />
            </div>
          )}
        </>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <Badge tone="green">sandbox {sandboxId.slice(0, 8)}</Badge>
            </div>
            <div className="flex gap-2">
              <Button onClick={run} disabled={running}>
                <PlayIcon className="h-4 w-4" /> {running ? "Running…" : "Run"}
              </Button>
              <Button variant="danger" onClick={destroy}>
                Destroy
              </Button>
            </div>
          </div>

          <div className="overflow-hidden rounded-xl border border-slate-200">
            <Editor
              height="320px"
              defaultLanguage="python"
              value={code}
              onChange={(v) => setCode(v ?? "")}
              options={{ minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false }}
            />
          </div>

          {error && <ErrorBox message={error} />}

          {result && (
            <Card>
              <div className="mb-2 flex items-center gap-2 text-sm">
                <Badge tone={result.ok ? "green" : "amber"}>
                  {result.timed_out ? "timed out" : result.ok ? "ok" : `exit ${result.exit_code}`}
                </Badge>
                <span className="text-slate-500">{result.execution_ms.toFixed(0)} ms</span>
              </div>
              {result.stdout && (
                <Output title="stdout" body={result.stdout} tone="text-slate-800" />
              )}
              {result.stderr && (
                <Output title="stderr" body={result.stderr} tone="text-red-600" />
              )}
              {images.length > 0 && (
                <div className="mt-3">
                  <div className="mb-1 text-xs font-semibold uppercase text-slate-400">Plots</div>
                  <div className="flex flex-wrap gap-3">
                    {images.map((name) => (
                      <img
                        key={name}
                        src={api.artifactUrl(sandboxId, result.run_id, name)}
                        alt={name}
                        className="max-h-72 rounded-lg border border-slate-200"
                      />
                    ))}
                  </div>
                </div>
              )}
            </Card>
          )}
        </div>
      )}
    </div>
  );
}

function Output({ title, body, tone }: { title: string; body: string; tone: string }) {
  return (
    <div className="mt-2">
      <div className="mb-1 text-xs font-semibold uppercase text-slate-400">{title}</div>
      <pre className={`max-h-60 overflow-auto rounded-lg bg-slate-50 p-3 text-xs ${tone}`}>
        {body}
      </pre>
    </div>
  );
}
