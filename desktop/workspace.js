/** Reflect main-process workspace state in desktop-only navigation. */
const services = {
  vod: { name: "VOD Review", address: "localhost:5174", command: "Backend: cd ~/vod-review && uv run start --reload --port 8000\nFrontend (from ChatTFT): node desktop/vod-frontend.mjs", note: "Desktop reuses compatible running services and starts missing ones automatically. If startup fails, check the launch terminal and installed dependencies, then Retry." },
  wisps: { name: "Wisps", address: "localhost:5175", command: "Backend: cd ~/vod-review-wt2 && uv run start --reload --port 8001\nFrontend (from ChatTFT): node desktop/vod-frontend.mjs --wisps", note: "Uses the wisps checkout in ~/vod-review-wt2. Desktop starts missing services automatically. Check the launch terminal if startup fails, then Retry." },
  langfuse: { name: "Langfuse", address: "localhost:15500", command: "uv run --extra evals chat-tft-evals up --no-browser" },
  database: { name: "CloudBeaver", address: "localhost:8978", command: "docker compose -f desktop/cloudbeaver/compose.yaml up -d" },
};
for (const action of ["chat", "rolldown", "flowchart", "compositions", "vod", "wisps", "langfuse", "database", "retry"]) {
  document.getElementById(action).addEventListener("click", () => window.desktopWorkspace.select(action));
}
window.desktopWorkspace.onState(({ active, state, compositionsEnabled }) => {
  for (const tab of ["chat", "rolldown", "flowchart", "compositions", "vod", "wisps", "langfuse", "database"]) document.getElementById(tab).setAttribute("aria-pressed", String(active === tab));
  document.getElementById("compositions").hidden = !compositionsEnabled;
  const service = services[active];
  document.getElementById("status").hidden = !service || state === "ready";
  if (!service) return;
  document.getElementById("service").textContent = service.name.toUpperCase();
  document.getElementById("heading").textContent = state === "error" ? `${service.name} is unavailable` : `Connecting to ${service.name}…`;
  document.getElementById("message").textContent = state === "error"
    ? `Could not load ${service.address}. Your other workspace tabs are still available.`
    : "Loading your local workspace.";
  document.getElementById("instructions").textContent = ["vod", "wisps"].includes(active)
    ? "Retry checks existing services and starts missing ones. Optional manual startup:"
    : `Start ${service.name} using these commands, then retry:`;
  document.getElementById("command").textContent = service.command;
  document.getElementById("service-note").textContent = service.note || "For a WSL checkout, run this in your WSL terminal. Docker must be running.";
  document.getElementById("recovery").hidden = state !== "error";
});
