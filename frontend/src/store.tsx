import { createContext, useContext, useState, type ReactNode } from "react";
import type { ChartRequest } from "./api/types";

export type Tab = "home" | "upload" | "data" | "visualize" | "saved";

interface AppState {
  tab: Tab;
  setTab: (t: Tab) => void;
  selectedSection: string | null;
  openDataset: (section: string) => void;
  setSelectedSection: (s: string | null) => void;
  /** The agent panel is always present; this only narrows it to a rail. */
  panelCollapsed: boolean;
  setPanelCollapsed: (b: boolean) => void;
  navCollapsed: boolean;
  setNavCollapsed: (b: boolean) => void;
  /** A chart handed off from the agent panel to the Visualize tab. */
  vizHandoff: ChartRequest | null;
  openInVisualize: (req: ChartRequest) => void;
  consumeVizHandoff: () => ChartRequest | null;
  /** Bumped whenever data changes (e.g. after an upload) so tabs refetch. */
  schemaVersion: number;
  refreshSchema: () => void;
  /** Bumped whenever the saved-chats list changes, so the sidebar refetches. */
  chatsVersion: number;
  refreshChats: () => void;
  /** Chat session the ChatPanel should show; null = a fresh chat. */
  openChatId: string | null;
  /** Bumped on every open/new request so the panel reacts even if id repeats. */
  chatNonce: number;
  openChat: (id: string) => void;
  newChat: () => void;
}

const Ctx = createContext<AppState | null>(null);

const PANEL_KEY = "annulus.panelCollapsed";
const NAV_KEY = "annulus.navCollapsed";

export function AppProvider({ children }: { children: ReactNode }) {
  const [tab, setTab] = useState<Tab>("home");
  const [selectedSection, setSelectedSection] = useState<string | null>(null);
  const [panelCollapsed, setPanelCollapsedState] = useState<boolean>(
    () => localStorage.getItem(PANEL_KEY) === "1",
  );
  const [navCollapsed, setNavCollapsedState] = useState<boolean>(
    () => localStorage.getItem(NAV_KEY) === "1",
  );
  const [vizHandoff, setVizHandoff] = useState<ChartRequest | null>(null);
  const [schemaVersion, setSchemaVersion] = useState(0);
  const [chatsVersion, setChatsVersion] = useState(0);
  const [openChatId, setOpenChatId] = useState<string | null>(null);
  const [chatNonce, setChatNonce] = useState(0);

  const setPanelCollapsed = (b: boolean) => {
    setPanelCollapsedState(b);
    localStorage.setItem(PANEL_KEY, b ? "1" : "0");
  };
  const setNavCollapsed = (b: boolean) => {
    setNavCollapsedState(b);
    localStorage.setItem(NAV_KEY, b ? "1" : "0");
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
  const refreshChats = () => setChatsVersion((v) => v + 1);

  const openChat = (id: string) => {
    setOpenChatId(id);
    setChatNonce((n) => n + 1);
    setPanelCollapsed(false);
  };
  const newChat = () => {
    setOpenChatId(null);
    setChatNonce((n) => n + 1);
    setPanelCollapsed(false);
  };

  const value: AppState = {
    tab,
    setTab,
    selectedSection,
    openDataset,
    setSelectedSection,
    panelCollapsed,
    setPanelCollapsed,
    navCollapsed,
    setNavCollapsed,
    vizHandoff,
    openInVisualize,
    consumeVizHandoff,
    schemaVersion,
    refreshSchema,
    chatsVersion,
    refreshChats,
    openChatId,
    chatNonce,
    openChat,
    newChat,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp must be used within AppProvider");
  return v;
}
