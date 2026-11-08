// "New video" page.
import { api, esc, rateString, readLangChips, renderLangChips, renderVoices, state, styleMini, toast } from "./api.js";

const form = () => document.getElementById("create-form");
let source = "link";
let pickedVoice = null;
let pickedStyle = null;
let file = null;

const rate = () => rateString(document.getElementById("rate").value);

function setSource(kind) {
  source = kind;
  document.querySelectorAll(".seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.src === kind));
  document.querySelectorAll("[data-src-panel]").forEach((p) => (p.hidden = p.dataset.srcPanel !== kind));
}

function setFile(f) {
  file = f;
  document.getElementById("drop-text").innerHTML = f
    ? `<b>${esc(f.name)}</b> · ${(f.size / 1024 / 1024).toFixed(1)} MB — click to change`
    : `<b>Drop a video here</b> or click to choose (mp4, mov, mkv, webm)`;
}

async function loadVoices() {
  const lang = document.getElementById("lang").value;
  const extraBox = document.getElementById("extra-langs");
  renderLangChips(extraBox, lang, readLangChips(extraBox));
  const s = state.meta.settings;
  const langDefault = state.meta.languages.find((l) => l.code === lang)?.voice;
  const preferred = s.default_voice?.startsWith(lang) ? s.default_voice : langDefault;
  await renderVoices(document.getElementById("voice-list"), lang, preferred, rate, (id) => (pickedVoice = id));
}

export function renderStylePicker() {
  const box = document.getElementById("style-picker");
  if (!pickedStyle || !state.styles.some((s) => s.id === pickedStyle)) {
    pickedStyle = state.styles.some((s) => s.id === state.meta.settings.default_style)
      ? state.meta.settings.default_style
      : state.styles[0]?.id;
  }
  box.innerHTML =
    state.styles
      .map(
        (s) => `<button type="button" class="style-card ${s.id === pickedStyle ? "selected" : ""}" data-style="${esc(s.id)}">
          ${styleMini(s)}<span class="info"><b>${esc(s.name)}</b><small>${esc(s.description)}</small></span></button>`,
      )
      .join("") +
    `<a class="style-card add" href="#styles"><span><b>+</b>New style from a reference</span></a>`;
  box.querySelectorAll("[data-style]").forEach((el) =>
    el.addEventListener("click", () => {
      pickedStyle = el.dataset.style;
      box.querySelectorAll("[data-style]").forEach((x) => x.classList.toggle("selected", x === el));
    }),
  );
}

async function submit(e) {
  e.preventDefault();
  const err = document.getElementById("create-error");
  err.textContent = "";
  const formats = [...document.querySelectorAll('input[name="fmt"]:checked')].map((i) => i.value);
  const url = document.getElementById("src-url").value.trim();
  if (source === "link" && !/^https?:\/\//.test(url)) return (err.textContent = "Paste a YouTube or Google Drive link.");
  if (source === "upload" && !file) return (err.textContent = "Choose a video file to upload.");
  if (!pickedVoice) return (err.textContent = "Pick a voice.");
  if (!formats.length) return (err.textContent = "Pick at least one output format.");
  const crop = document.getElementById("crop").value.trim();
  if (crop && !/^\d+:\d+:\d+:\d+$/.test(crop)) return (err.textContent = "Crop must look like W:H:X:Y.");

  const fd = new FormData();
  if (source === "link") fd.append("url", url);
  else fd.append("file", file);
  fd.append("lang", document.getElementById("lang").value);
  fd.append("voice", pickedVoice);
  fd.append("rate", rate());
  fd.append("style", pickedStyle);
  fd.append("formats", formats.join(","));
  fd.append("review", document.getElementById("review").checked ? "true" : "false");
  fd.append("crop", crop);
  fd.append("extra_langs", readLangChips(document.getElementById("extra-langs")).join(","));
  fd.append("allow_duplicate", document.getElementById("allow-dup").checked ? "true" : "false");

  const btn = document.getElementById("create-btn");
  btn.disabled = true;
  btn.textContent = source === "upload" ? "Uploading…" : "Starting…";
  try {
    const job = await api("/api/jobs", { method: "POST", form: fd });
    toast("Agents started");
    document.getElementById("src-url").value = "";
    setFile(null);
    location.hash = `job/${job.id}`;
  } catch (ex) {
    err.textContent = ex.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "Start the agents →";
  }
}

export function initCreate() {
  const langSel = document.getElementById("lang");
  langSel.innerHTML = state.meta.languages.map((l) => `<option value="${esc(l.code)}">${esc(l.name)}</option>`).join("");
  langSel.value = state.meta.settings.default_lang || "es";
  langSel.addEventListener("change", loadVoices);
  document.getElementById("review").checked = state.meta.settings.review_script !== false;

  const rateInput = document.getElementById("rate");
  rateInput.addEventListener("input", () => (document.getElementById("rate-label").textContent = rate()));

  document.querySelectorAll(".seg-btn").forEach((b) => b.addEventListener("click", () => setSource(b.dataset.src)));
  const dz = document.getElementById("dropzone");
  document.getElementById("src-file").addEventListener("change", (e) => setFile(e.target.files[0] || null));
  ["dragenter", "dragover"].forEach((ev) =>
    dz.addEventListener(ev, (e) => {
      e.preventDefault();
      dz.classList.add("drag");
    }),
  );
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, () => dz.classList.remove("drag")));
  dz.addEventListener("drop", (e) => {
    e.preventDefault();
    if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
  });
  form().addEventListener("submit", submit);
  loadVoices();
  renderStylePicker();
}

export function refreshCreate() {
  renderStylePicker();
}
