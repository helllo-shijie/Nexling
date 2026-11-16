import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles/global.css";
import { mark } from "./perf/marks";

const rootEl = document.getElementById("root");
if (!rootEl) {
  throw new Error("missing #root mount point");
}

createRoot(rootEl).render(
  <StrictMode>
    <App />
  </StrictMode>
);
mark("react_mounted");
