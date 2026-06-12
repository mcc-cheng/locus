import { useEffect, useState } from "react";
import { api } from "../api/client";

type Health = "checking" | "up" | "down";
type Ollama = "checking" | "ready" | "unavailable";

export function StatusBar() {
  const [engine, setEngine] = useState<Health>("checking");
  const [ollama, setOllama] = useState<Ollama>("checking");

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        await api.health();
        if (alive) setEngine("up");
        try {
          const d = await api.healthDeps();
          if (alive) setOllama(d.ollama.status === "ready" ? "ready" : "unavailable");
        } catch {
          if (alive) setOllama("unavailable");
        }
      } catch {
        if (alive) {
          setEngine("down");
          setOllama("unavailable");
        }
      }
    };
    tick();
    const id = setInterval(tick, 15000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  return (
    <div className="sticky top-0 z-10 flex items-center justify-end gap-2 border-b border-slate-200/70 bg-white/70 px-6 py-2.5 backdrop-blur-md">
      <Pill
        label="Engine"
        tone={engine === "up" ? "green" : engine === "down" ? "red" : "slate"}
        text={engine === "up" ? "connected" : engine === "down" ? "offline" : "…"}
      />
      <Pill
        label="AI analyst"
        tone={ollama === "ready" ? "green" : ollama === "unavailable" ? "amber" : "slate"}
        text={ollama === "ready" ? "ready" : ollama === "unavailable" ? "set up Ollama" : "…"}
      />
    </div>
  );
}

function Pill({ label, text, tone }: { label: string; text: string; tone: string }) {
  const dot: Record<string, string> = {
    green: "bg-emerald-500",
    red: "bg-red-500",
    amber: "bg-amber-500",
    slate: "bg-slate-300",
  };
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-500">
      <span className={`h-1.5 w-1.5 rounded-full ${dot[tone] ?? dot.slate}`} />
      <span className="text-slate-400">{label}</span>
      <span className="text-slate-700">{text}</span>
    </span>
  );
}
