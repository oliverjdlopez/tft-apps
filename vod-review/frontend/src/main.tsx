import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import ViewingLibrary from "./ViewingLibrary";
import "./theme.css";
import "./styles.css";
import { TooltipProvider } from "@/components/ui/tooltip";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <TooltipProvider>{window.location.pathname === "/watch" ? <ViewingLibrary /> : <App />}</TooltipProvider>
  </StrictMode>,
);
