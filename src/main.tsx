import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import "./App.css";
import { installTheme } from "./design/theme";
import { App } from "./App";

// Colours first, so the first frame is already in the right theme.
installTheme();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
