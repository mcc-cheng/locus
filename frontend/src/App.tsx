import { useApp, type Tab } from "./store";
import { Home } from "./tabs/Home";
import { Upload } from "./tabs/Upload";
import { DataTab } from "./tabs/DataTab";
import { Visualize } from "./tabs/Visualize";
import { Sandbox } from "./tabs/Sandbox";
import { ChatPanel } from "./agent/ChatPanel";
import type { ComponentType } from "react";
import {
  BeakerIcon,
  ChartIcon,
  ChatIcon,
  DataIcon,
  HomeIcon,
  UploadIcon,
} from "./components/icons";
import { StatusBar } from "./components/StatusBar";

const TABS: { id: Tab; label: string; Icon: ComponentType<{ className?: string }> }[] = [
  { id: "home", label: "Home", Icon: HomeIcon },
  { id: "upload", label: "Upload", Icon: UploadIcon },
  { id: "data", label: "Data", Icon: DataIcon },
  { id: "visualize", label: "Visualize", Icon: ChartIcon },
  { id: "sandbox", label: "Sandbox", Icon: BeakerIcon },
];

export function App() {
  const { tab, setTab, panelCollapsed, setPanelCollapsed } = useApp();

  return (
    <div className="flex h-full w-full overflow-hidden">
      {/* Left navigation */}
      <nav className="flex w-[216px] shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 text-sm font-bold text-white shadow-sm">
            L
          </div>
          <div>
            <div className="text-[15px] font-semibold leading-tight text-slate-900">Locus</div>
            <div className="text-[11px] leading-tight text-slate-400">Data Aggregator</div>
          </div>
        </div>
        <ul className="flex-1 space-y-0.5 px-3 pt-2">
          {TABS.map(({ id, label, Icon }) => (
            <li key={id}>
              <button
                onClick={() => setTab(id)}
                className={`group relative flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium transition ${
                  tab === id
                    ? "bg-indigo-50 text-indigo-700"
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                }`}
              >
                {tab === id && (
                  <span className="absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-indigo-600" />
                )}
                <Icon className={`h-5 w-5 ${tab === id ? "text-indigo-600" : "text-slate-400 group-hover:text-slate-500"}`} />
                {label}
              </button>
            </li>
          ))}
        </ul>
        <div className="flex items-center gap-2 px-5 py-4 text-[11px] text-slate-400">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
          Non-destructive by design
        </div>
      </nav>

      {/* Main content */}
      <main className="flex min-w-0 flex-1 flex-col overflow-auto">
        <StatusBar />
        <div className="mx-auto w-full max-w-5xl px-10 py-9">
          <div key={tab} className="animate-in">
            {tab === "home" && <Home />}
            {tab === "upload" && <Upload />}
            {tab === "data" && <DataTab />}
            {tab === "visualize" && <Visualize />}
            {tab === "sandbox" && <Sandbox />}
          </div>
        </div>
      </main>

      {/* Right agent panel — always present */}
      {panelCollapsed ? (
        <button
          onClick={() => setPanelCollapsed(false)}
          title="Open the analyst"
          className="flex w-14 shrink-0 flex-col items-center gap-3 border-l border-slate-200 bg-white py-5 text-slate-500 hover:bg-slate-50"
        >
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
            <ChatIcon />
          </span>
          <span
            className="text-xs font-medium text-slate-400"
            style={{ writingMode: "vertical-rl" }}
          >
            Analyst
          </span>
        </button>
      ) : (
        <aside className="flex w-[384px] shrink-0 flex-col border-l border-slate-200 bg-white">
          <ChatPanel onCollapse={() => setPanelCollapsed(true)} />
        </aside>
      )}
    </div>
  );
}
