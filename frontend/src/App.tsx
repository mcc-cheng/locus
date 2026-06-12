import { useApp, type Tab } from "./store";
import { Home } from "./tabs/Home";
import { Upload } from "./tabs/Upload";
import { DataTab } from "./tabs/DataTab";
import { Visualize } from "./tabs/Visualize";
import { Sandbox } from "./tabs/Sandbox";
import { ChatPanel } from "./agent/ChatPanel";

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "home", label: "Home", icon: "🏠" },
  { id: "upload", label: "Upload", icon: "⬆️" },
  { id: "data", label: "Data", icon: "🗂️" },
  { id: "visualize", label: "Visualize", icon: "📊" },
  { id: "sandbox", label: "Sandbox", icon: "🧪" },
];

export function App() {
  const { tab, setTab, panelOpen, setPanelOpen } = useApp();

  return (
    <div className="flex h-full w-full text-slate-800">
      {/* Left sidebar */}
      <nav className="flex w-52 flex-col border-r border-slate-200 bg-slate-50">
        <div className="px-4 py-5 text-xl font-semibold tracking-tight text-slate-900">
          Locus
        </div>
        <ul className="flex-1 space-y-1 px-2">
          {TABS.map((t) => (
            <li key={t.id}>
              <button
                onClick={() => setTab(t.id)}
                className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium transition ${
                  tab === t.id
                    ? "bg-indigo-600 text-white shadow-sm"
                    : "text-slate-600 hover:bg-slate-200"
                }`}
              >
                <span aria-hidden>{t.icon}</span>
                {t.label}
              </button>
            </li>
          ))}
        </ul>
        <div className="px-4 py-3 text-xs text-slate-400">Non-destructive by design</div>
      </nav>

      {/* Main content */}
      <main className="relative flex-1 overflow-auto bg-white">
        <div className="mx-auto max-w-6xl px-8 py-8">
          {tab === "home" && <Home />}
          {tab === "upload" && <Upload />}
          {tab === "data" && <DataTab />}
          {tab === "visualize" && <Visualize />}
          {tab === "sandbox" && <Sandbox />}
        </div>

        {/* Agent toggle button (like Copilot) */}
        {!panelOpen && (
          <button
            onClick={() => setPanelOpen(true)}
            className="fixed right-5 bottom-5 rounded-full bg-indigo-600 px-5 py-3 text-sm font-semibold text-white shadow-lg hover:bg-indigo-700"
          >
            💬 Ask the analyst
          </button>
        )}
      </main>

      {/* Right agent panel (persists across tab changes) */}
      {panelOpen && (
        <aside className="flex w-[380px] flex-col border-l border-slate-200 bg-slate-50">
          <ChatPanel onClose={() => setPanelOpen(false)} />
        </aside>
      )}
    </div>
  );
}
