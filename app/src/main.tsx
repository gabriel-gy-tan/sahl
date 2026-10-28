import React from "react";
import ReactDOM from "react-dom/client";
import { getCurrentWindow } from "@tauri-apps/api/window";
import Panel from "./panel/Panel";
import Overlay from "./overlay/Overlay";

// one bundle, two windows: the panel and the click-through ring overlay
const isOverlay = getCurrentWindow().label === "overlay";
document.documentElement.dataset.window = isOverlay ? "overlay" : "panel";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>{isOverlay ? <Overlay /> : <Panel />}</React.StrictMode>,
);
