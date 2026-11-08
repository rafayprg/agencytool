// "Editing styles" page: preset list, editor, style-from-reference.
import { api, esc, state, styleMini, toast } from "./api.js";
import { renderStylePicker } from "./create.js";

let fonts = {};
let editingId = null;

const COLOR_LABELS = { bg1: "Background", bg2: "Glow", accent: "Highlight", accent2: "Badge", text: "Text" };

async function reloadStyles() {
  state.styles = await api("/api/styles");
  renderList();
  renderStylePicker();
}

function renderList() {
  const box = document.getElementById("style-list");
  box.innerHTML = state.styles
    .map(
      (s) => `<button type="button" class="style-card ${s.id === editingId ? "selected" : ""}" data-style="${esc(s.id)}">
        ${styleMini(s)}<span class="info"><b>${esc(s.name)}</b><small>${esc(s.description)}</small></span></button>`,
    )
    .join("");
  box.querySelectorAll("[data-style]").forEach((el) => el.addEventListener("click", () => openEditor(el.dataset.style)));
}

function openEditor(id) {
  editingId = id;
  renderList();
  const s = state.styles.find((x) => x.id === id);
  const form = document.getElementById("style-editor");
  form.hidden = false;
  const fontOpts = Object.entries(fonts)
    .map(([k, v]) => `<option value="${esc(v)}" ${v === s.font ? "selected" : ""}>${esc(k)}</option>`)
    .join("");
  form.innerHTML = `<h3>Edit “${esc(s.name)}”</h3>
    <div id="ed-preview">${styleMini(s)}</div>
    <label class="field"><span>Name</span><input name="name" maxlength="40" value="${esc(s.name)}" /></label>
    <label class="field"><span>Description</span><input name="description" maxlength="200" value="${esc(s.description)}" /></label>
    <div class="colors">${Object.keys(COLOR_LABELS)
      .map((k) => `<label><input type="color" name="c-${k}" value="${esc(s.colors[k])}" />${COLOR_LABELS[k]}</label>`)
      .join("")}</div>
    <div class="row wrap">
      <label class="field grow"><span>Font</span><select name="font">${fontOpts}</select></label>
      <label class="field grow"><span>Phone position</span><select name="layout">
        <option value="phone-right" ${s.layout === "phone-right" ? "selected" : ""}>Right</option>
        <option value="phone-left" ${s.layout === "phone-left" ? "selected" : ""}>Left</option></select></label>
    </div>
    <label class="field"><span>Caption size <b id="cs-l">${Math.round(s.captionScale * 100)}%</b></span>
      <input type="range" name="captionScale" min="0.7" max="1.4" step="0.05" value="${s.captionScale}" /></label>
    <div class="row wrap">
      <label class="check"><input type="checkbox" name="grid" ${s.grid ? "checked" : ""} /> <span>Grid texture</span></label>
      <label class="check"><input type="checkbox" name="music" ${s.music ? "checked" : ""} /> <span>Background music</span></label>
    </div>
    <label class="field"><span>Music volume</span><input type="range" name="musicVolume" min="0" max="0.2" step="0.01" value="${s.musicVolume}" /></label>
    <div class="row wrap">
      <button class="btn primary" type="submit">Save</button>
      <button class="btn" type="button" id="dup">Save as copy</button>
    </div>`;
  const collect = () => ({
    id,
    name: form.name.value.trim() || s.name,
    description: form.description.value.trim(),
    colors: Object.fromEntries(Object.keys(COLOR_LABELS).map((k) => [k, form[`c-${k}`].value])),
    font: form.font.value,
    layout: form.layout.value,
    captionScale: Number(form.captionScale.value),
    grid: form.grid.checked,
    music: form.music.checked,
    musicVolume: Number(form.musicVolume.value),
  });
  form.oninput = () => {
    document.getElementById("ed-preview").innerHTML = styleMini(collect());
    document.getElementById("cs-l").textContent = `${Math.round(form.captionScale.value * 100)}%`;
  };
  const save = async (style) => {
    try {
      const saved = await api(`/api/styles/${encodeURIComponent(style.id)}`, { method: "PUT", body: style });
      editingId = saved.id;
      await reloadStyles();
      openEditor(saved.id);
      toast("Style saved");
    } catch (err) {
      toast(err.message, true);
    }
  };
  form.onsubmit = (e) => {
    e.preventDefault();
    save(collect());
  };
  document.getElementById("dup").onclick = () => {
    const copy = collect();
    const slug = copy.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40) || "style";
    save({ ...copy, id: `${slug}-${Date.now().toString(36)}`, name: `${copy.name} copy` });
  };
}

export function initStyles() {
  api("/api/styles/fonts").then((f) => (fonts = f)).catch(() => {});
  document.getElementById("ref-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const file = document.getElementById("ref-file").files[0];
    const msg = document.getElementById("ref-msg");
    if (!file) return (msg.textContent = "Choose an image or video first.");
    const fd = new FormData();
    fd.append("file", file);
    fd.append("name", document.getElementById("ref-name").value.trim());
    msg.textContent = "Reading the reference…";
    try {
      const style = await api("/api/styles/reference", { method: "POST", form: fd });
      msg.textContent = `Created “${style.name}”. It is now selectable on New video.`;
      await reloadStyles();
      openEditor(style.id);
    } catch (err) {
      msg.textContent = err.message;
    }
  });
}

export function showStyles() {
  renderList();
  if (editingId) openEditor(editingId);
}
