import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { AppProvider } from "./store";
import { setApiBase } from "./api/client";
import "./index.css";

// In the Tauri desktop app, the Rust shell injects the sidecar's URL.
const injected = (window as unknown as { __LOCUS_API__?: string }).__LOCUS_API__;
if (injected) setApiBase(injected);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppProvider>
      <App />
    </AppProvider>
  </StrictMode>,
);
