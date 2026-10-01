/** Browse shared media in the local shell, retaining state between tabs. */
(() => {
  const element = (id) => document.getElementById(id);
  const bridge = window.desktopWorkspace;
  let resources = [];
  let nextOffset = null;
  let selected;
  let initialized = false;
  let loading = false;
  let generation = 0;
  let listMessage = "";

  /** Render catalogue names as text, never as executable markup. */
  function renderList() {
    const query = element("media-search").value.trim().toLowerCase();
    const kind = element("media-kind").value;
    const visible = resources.filter((resource) => (!kind || resource.kind === kind)
      && `${resource.name} ${resource.source} ${resource.reference}`.toLowerCase().includes(query));
    const list = element("media-list");
    list.replaceChildren();
    for (const resource of visible) {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.setAttribute("aria-pressed", String(selected?.reference === resource.reference));
      const name = document.createElement("strong");
      name.textContent = resource.name;
      const source = document.createElement("span");
      source.textContent = `${resource.kind} · ${resource.source}`;
      button.append(name, source);
      button.addEventListener("click", () => openMedia(resource));
      item.append(button);
      list.append(item);
    }
    element("media-list-status").textContent = listMessage || (visible.length
      ? `${visible.length} resource${visible.length === 1 ? "" : "s"}`
      : query || kind ? "No loaded media matches these filters."
      : "No shared media yet. Publish files to the shared media catalogue to see them here.");
    element("media-more").hidden = nextOffset === null;
    element("media-more").disabled = loading;
    element("media-refresh").disabled = loading;
  }

  /** Fetch another bounded catalogue page or refresh the library. */
  async function loadList(reset = false) {
    if (loading) return;
    loading = true;
    listMessage = "Loading media…";
    renderList();
    try {
      const result = await bridge.media("list", reset ? 0 : nextOffset);
      if (result.error) throw new Error(result.error);
      const entries = reset ? result.resources : [...resources, ...result.resources];
      resources = [...new Map(entries.map((resource) => [resource.reference, resource])).values()];
      nextOffset = result.nextOffset;
      initialized = true;
      listMessage = "";
    } catch (error) {
      listMessage = error.message || "Could not load media. Try Refresh.";
    } finally {
      loading = false;
      renderList();
    }
  }

  /** Stop playback and release the previous resource before changing selection. */
  function clearPreview() {
    const preview = element("media-preview");
    for (const player of preview.querySelectorAll("video, audio")) {
      player.pause();
      player.removeAttribute("src");
      player.load();
    }
    preview.replaceChildren();
  }

  /** Display text or native media while ignoring superseded requests. */
  async function openMedia(resource) {
    selected = resource;
    const current = ++generation;
    renderList();
    element("media-title").textContent = resource.name;
    element("media-source").textContent = resource.source;
    element("media-details").textContent = `${resource.kind} · ${resource.content_type || "Unknown format"} · ${Number(resource.size).toLocaleString()} bytes`;
    element("media-reference").value = resource.reference;
    element("media-reference-controls").hidden = false;
    element("media-copy-status").textContent = "";
    element("media-status").textContent = "Loading preview…";
    element("media-content").textContent = "";
    element("media-retry").hidden = true;
    clearPreview();
    try {
      const result = await bridge.media("read", resource.reference);
      if (current !== generation) return;
      if (result.error) throw new Error(result.error);
      if (typeof result.text === "string") {
        let text = result.text;
        if (resource.kind === "data") {
          try { text = JSON.stringify(JSON.parse(text), null, 2); } catch { /* Non-JSON text retains its original form. */ }
        }
        element("media-content").textContent = text;
        element("media-status").textContent = text ? "" : "This file is empty.";
      } else if (result.contentUrl) {
        const tag = { image: "img", video: "video", audio: "audio" }[resource.kind];
        const preview = document.createElement(tag);
        if (tag === "img") preview.alt = resource.name;
        else { preview.controls = true; preview.preload = "metadata"; }
        preview.addEventListener("error", () => {
          if (current !== generation) return;
          element("media-status").textContent = "Preview unavailable. The file may be missing, damaged or unsupported. You can still copy its reference.";
          element("media-retry").hidden = false;
        });
        preview.src = result.contentUrl;
        element("media-preview").append(preview);
        element("media-status").textContent = "";
      } else {
        element("media-status").textContent = "Preview unavailable for this format. Copy its reference to use it in another app.";
      }
    } catch (error) {
      if (current !== generation) return;
      element("media-status").textContent = error.message || "Could not preview media.";
      element("media-retry").hidden = false;
    }
  }

  element("media-search").addEventListener("input", renderList);
  element("media-kind").addEventListener("change", renderList);
  element("media-refresh").addEventListener("click", () => loadList(true));
  element("media-more").addEventListener("click", () => loadList());
  element("media-retry").addEventListener("click", () => openMedia(selected));
  element("media-copy").addEventListener("click", async () => {
    const current = selected.reference;
    try {
      const result = await bridge.media("copy", current);
      if (current === selected.reference) element("media-copy-status").textContent = result.error || "Reference copied.";
    } catch {
      if (current === selected.reference) element("media-copy-status").textContent = "Could not copy. Select the reference and copy it manually.";
    }
  });
  bridge.onState(({ active }) => {
    element("media-panel").hidden = active !== "media";
    if (active === "media" && !initialized) loadList(true);
    if (active !== "media") {
      for (const player of element("media-preview").querySelectorAll("video, audio")) player.pause();
    }
  });
})();
