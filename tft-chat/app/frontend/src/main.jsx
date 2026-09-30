import React from "react";
import { createRoot } from "react-dom/client";
import "./theme.css";
import "./styles.css";
import { TooltipProvider } from "@/components/ui/tooltip";
import App from "./app.jsx";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <TooltipProvider><App /></TooltipProvider>
  </React.StrictMode>,
);
