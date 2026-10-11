/** Reflect main-process workspace state in desktop-only navigation. */
const services = {
  vod: { name: "VOD Review", address: "localhost:5174", command: "From tft-apps: python3 scripts/setup.py", note: "Desktop starts the VOD Review services. If startup fails, check the launch terminal, resolve occupied ports, then Retry." },
  langfuse: { name: "Langfuse", address: "localhost:15510", command: "From tft-apps/tft-chat: uv run --extra evals chat-tft-evals up --no-browser" },
  database: { name: "CloudBeaver", address: "localhost:8979", command: "From tft-apps: docker compose -f desktop/cloudbeaver/compose.yaml up -d" },
};
for (const action of ["chat", "rolldown", "flowchart", "compositions", "vod", "langfuse", "database", "media", "retry"]) {
  document.getElementById(action).addEventListener("click", () => window.desktopWorkspace.select(action));
}
window.desktopWorkspace.onState(({ active, state, compositionsEnabled }) => {
  for (const tab of ["chat", "rolldown", "flowchart", "compositions", "vod", "langfuse", "database", "media"]) document.getElementById(tab).setAttribute("aria-pressed", String(active === tab));
  document.getElementById("compositions").hidden = !compositionsEnabled;
  const service = services[active];
  document.getElementById("status").hidden = !service || state === "ready";
  if (!service) return;
  document.getElementById("service").textContent = service.name.toUpperCase();
  document.getElementById("heading").textContent = state === "error" ? `${service.name} is unavailable` : `Connecting to ${service.name}…`;
  document.getElementById("message").textContent = state === "error"
    ? `Could not load ${service.address}. Your other workspace tabs are still available.`
    : "Loading your local workspace.";
  document.getElementById("instructions").textContent = active === "vod"
    ? "Retry restarts the owned VOD services. Check dependencies with:"
    : `Start ${service.name} using these commands, then retry:`;
  document.getElementById("command").textContent = service.command;
  document.getElementById("service-note").textContent = service.note || "For a WSL checkout, run this in your WSL terminal. Docker must be running.";
  document.getElementById("recovery").hidden = state !== "error";
});
