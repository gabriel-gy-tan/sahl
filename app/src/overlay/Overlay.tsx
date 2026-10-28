import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import type { Box } from "../api";
import "./overlay.css";

type Ring = { box: Box; label: string; origin: [number, number] };

/** Full-screen, click-through layer on the form's monitor. Draws one ring around the box the panel says is next. */
export default function Overlay() {
  const [ring, setRing] = useState<Ring | null>(null);
  useEffect(() => {
    const un = listen<Ring | null>("ring", (e) => setRing(e.payload));
    return () => void un.then((f) => f());
  }, []);
  if (!ring) return null;
  const [ox, oy] = ring.origin; // boxes are in global screen points; this window starts at the monitor's corner
  const [x0, y0, x1, y1] = ring.box;
  const pad = 6;
  return (
    <div className="ring" style={{ left: x0 - ox - pad, top: y0 - oy - pad, width: x1 - x0 + 2 * pad, height: y1 - y0 + 2 * pad }}>
      <span className="ring-tag">{ring.label}</span>
    </div>
  );
}
