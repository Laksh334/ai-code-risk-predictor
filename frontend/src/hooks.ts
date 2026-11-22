import { useEffect, useRef, useState } from "react";

/** Browser-tab title, e.g. "pallets/flask · Code Risk Predictor" (also read out by screen readers). */
export function usePageTitle(title: string | null | undefined) {
  useEffect(() => {
    document.title = title ? `${title} · Code Risk Predictor` : "Code Risk Predictor";
  }, [title]);
}

/** false while the browser reports no network connection. */
export function useOnline() {
  const [online, setOnline] = useState(() => navigator.onLine);
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => { window.removeEventListener("online", up); window.removeEventListener("offline", down); };
  }, []);
  return online;
}

/** Call `fn` every `ms` while `active` is true (e.g. while a scan is running).
 *  Pauses while the browser tab is hidden, so idle tabs don't keep hitting the server. */
export function usePolling(fn: () => unknown, active: boolean, ms = 3000) {
  const saved = useRef(fn);
  saved.current = fn;
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") saved.current();
    }, ms);
    return () => window.clearInterval(id);
  }, [active, ms]);
}
