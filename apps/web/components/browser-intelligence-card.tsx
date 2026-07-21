"use client";

import { useSyncExternalStore } from "react";
import { detectBrowserIntelligenceCapabilities } from "@catora/browser-intelligence";

type State = ReturnType<typeof detectBrowserIntelligenceCapabilities>;

let cachedCapabilities: State | null = null;
const subscribe = () => () => undefined;
const getServerSnapshot = () => null;
const getSnapshot = () => {
  cachedCapabilities ??= detectBrowserIntelligenceCapabilities();
  return cachedCapabilities;
};

export function BrowserIntelligenceCard() {
  const capabilities = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  return (
    <div className="browser-card" aria-live="polite">
      <span>LOCAL INFERENCE READINESS</span>
      <div className="status-row">
        <span>WebGPU acceleration</span>
        <span className="status">{capabilities?.webGpu ? "Available" : "Fallback"}</span>
      </div>
      <div className="status-row">
        <span>WebAssembly runtime</span>
        <span className="status">{capabilities?.webAssembly ? "Available" : "Unavailable"}</span>
      </div>
      <div className="status-row">
        <span>Preferred execution</span>
        <span className="status">{capabilities?.preferredDevice ?? "Detecting"}</span>
      </div>
      <p>Models load only after explicit user action; no catalog content is sent by this component.</p>
    </div>
  );
}
