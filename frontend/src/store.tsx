import { createContext, useContext, useState, type ReactNode } from "react";
import type { ChartRequest } from "./api/types";

export type Tab = "home" | "upload" | "data" | "visualize" | "sandbox";

interface AppState {
  tab: Tab;
  setTab: (t: Tab) => void;
  selectedSection: string | null;
  openDataset: (section: string) => void;
  panelOpen: boolean;
  setPanelOpen: (b: boolean) => void;
  /** A chart handed off from the agent panel to the Visualize tab. */
  vizHandoff: ChartRequest | null;
  openInVisualize: (req: ChartRequest) => void;
  consumeVizHandoff: () => ChartRequest | null;
  /** Bumped whenever data changes (e.g. after an upload) so tabs refetch. */
  schemaVersion: number;
  refreshSchema: () => void;
}

const Ctx = createContext<AppState | null>(null);

const PANEL_KEY = "locus.panelOpen";

export function AppProvider({ children }: { children: ReactNode }) {
  const [tab, setTab] = useState<Tab>("home");
  const [selectedSection, setSelectedSection] = useState<string | null>(null);
  const [panelOpen, setPanelOpenState] = useState<boolean>(
    () => localStorage.getItem(PANEL_KEY) === "1",
  );
  const [vizHandoff, setVizHandoff] = useState<ChartRequest | null>(null);
  const [schemaVersion, setSchemaVersion] = useState(0);

  const setPanelOpen = (b: boolean) => {
    setPanelOpenState(b);
    localStorage.setItem(PANEL_KEY, b ? "1" : "0");
  };

  const openDataset = (section: string) => {
    setSelectedSection(section);
    setTab("data");
  };

  const openInVisualize = (req: ChartRequest) => {
    setVizHandoff(req);
    setSelectedSection(req.section);
    setTab("visualize");
  };

  const consumeVizHandoff = () => {
    const h = vizHandoff;
    setVizHandoff(null);
    return h;
  };

  const refreshSchema = () => setSchemaVersion((v) => v + 1);

  const value: AppState = {
    tab,
    setTab,
    selectedSection,
    openDataset,
    panelOpen,
    setPanelOpen,
    vizHandoff,
    openInVisualize,
    consumeVizHandoff,
    schemaVersion,
    refreshSchema,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp must be used within AppProvider");
  return v;
}
