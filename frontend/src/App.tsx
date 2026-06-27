import { useApp, type Tab } from "./store";
import { Home } from "./tabs/Home";
import { Upload } from "./tabs/Upload";
import { DataTab } from "./tabs/DataTab";
import { Visualize } from "./tabs/Visualize";
import { Saved } from "./tabs/Saved";
import { ChatPanel } from "./agent/ChatPanel";
import type { ComponentType } from "react";
import {
  BookmarkIcon,
  ChartIcon,
  ChatIcon,
  ChevronLeft,
  DataIcon,
  HomeIcon,
  MenuIcon,
  UploadIcon,
} from "./components/icons";
import { StatusBar } from "./components/StatusBar";
import { AnnulusLogo } from "./components/AnnulusLogo";
import { ChatHistory } from "./agent/ChatHistory";

const TABS: { id: Tab; label: string; Icon: ComponentType<{ className?: string }> }[] = [
  { id: "home", label: "Home", Icon: HomeIcon },
  { id: "upload", label: "Upload", Icon: UploadIcon },
  { id: "data", label: "Data", Icon: DataIcon },
  { id: "visualize", label: "Visualize", Icon: ChartIcon },
  { id: "saved", label: "Saved", Icon: BookmarkIcon },
];

export function App() {
  const { tab, setTab, panelCollapsed, setPanelCollapsed, navCollapsed, setNavCollapsed } = useApp();

  return (
    <div className="flex h-full w-full overflow-hidden">
      {/* Left navigation (collapsible) */}
      <nav
        className={`flex shrink-0 flex-col border-r border-slate-200 bg-white transition-all duration-200 ${
          navCollapsed ? "w-16" : "w-[216px]"
        }`}
      >
        <div className={`flex items-center py-5 ${navCollapsed ? "justify-center px-0" : "gap-2.5 px-5"}`}>
          <AnnulusLogo className="h-8 w-8 shrink-0 rounded-lg shadow-sm" />
          {!navCollapsed && (
            <>
              <div className="flex-1">
                <div className="text-[15px] font-semibold leading-tight text-slate-900">Annulus AI</div>
                <div className="text-[11px] leading-tight text-slate-400">Local data analyst</div>
              </div>
              <button
                onClick={() => setNavCollapsed(true)}
                title="Collapse sidebar"
                className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
            </>
          )}
        </div>

        {navCollapsed && (
          <button
            onClick={() => setNavCollapsed(false)}
            title="Expand sidebar"
            className="mx-auto mb-1 rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            <MenuIcon className="h-5 w-5" />
          </button>
        )}

        <ul className={`space-y-0.5 pt-2 ${navCollapsed ? "px-2" : "px-3"}`}>
          {TABS.map(({ id, label, Icon }) => (
            <li key={id}>
              <button
                onClick={() => setTab(id)}
                title={navCollapsed ? label : undefined}
                className={`group relative flex w-full items-center rounded-lg text-left text-sm font-medium transition ${
                  navCollapsed ? "justify-center px-0 py-2.5" : "gap-3 px-3 py-2"
                } ${
                  tab === id
                    ? "bg-indigo-50 text-indigo-700"
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                }`}
              >
                {tab === id && !navCollapsed && (
                  <span className="absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-indigo-600" />
                )}
                <Icon className={`h-5 w-5 ${tab === id ? "text-indigo-600" : "text-slate-400 group-hover:text-slate-500"}`} />
                {!navCollapsed && label}
              </button>
            </li>
          ))}
        </ul>
        {!navCollapsed && <ChatHistory />}
        {navCollapsed && <div className="flex-1" />}
        {!navCollapsed && (
          <div className="flex items-center gap-2 px-5 py-4 text-[11px] text-slate-400">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            Non-destructive by design
          </div>
        )}
      </nav>

      {/* Main content — full width; narrow tabs self-constrain. */}
      <main className="flex min-w-0 flex-1 flex-col overflow-auto">
        <StatusBar />
        <div className="w-full flex-1 px-8 py-8">
          <div key={tab} className="animate-in h-full">
            {tab === "home" && (
              <div className="mx-auto max-w-5xl">
                <Home />
              </div>
            )}
            {tab === "upload" && (
              <div className="mx-auto max-w-3xl">
                <Upload />
              </div>
            )}
            {tab === "data" && <DataTab />}
            {tab === "visualize" && <Visualize />}
            {tab === "saved" && <Saved />}
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
