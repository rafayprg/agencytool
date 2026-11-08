// Autopilot page: watched folder → automatic remakes, with Start/Stop and live status.
import { api, esc, rateString, readLangChips, renderLangChips, renderVoices, state, toast } from "./api.js";

const $ = (id) => document.getElementById(id);
const POLL_MS = 3000;
let timer = null;
let voice = null;
let formLoaded = false;

const STATUS_TEXT = { queued: "queued", running: "working", waiting: "waiting", done: "ready", error: "failed", cancelled: "stopped", review: "needs you", deleted: "deleted", duplicate: "already made" };

export function stopAutopilot() {
  clearInterval(timer);
  timer = null;
}

function ago(t) {
  if (!t) return "never";
  const s = Math.max(0, Math.round(Date.now() / 1000 - t));
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : new Date(t * 1000).toLocaleString();
}

function renderStatus(st) {
  const on = st.config.enabled;
  const pill = $("ap-state");
  pill.textContent = on ? "running" : "off";
  pill.className = `status ${on ? "done" : "cancelled"}`;
  $("ap-toggle").textContent = on ? "Stop autopilot" : "Start autopilot";
  $("ap-toggle").classList.toggle("primary", !on);
  $("ap-toggle").classList.toggle("danger", on);
  $("ap-scan").textContent = on ? `· last check ${ago(st.state.last_scan)} · watching ${st.config.watch_dir}` : "";
  $("ap-error").textContent = st.state.last_error || "";
  const c = st.counts;
  const k = st.stats || {};
  const tiles = [
    [k.remaining, "left to make"],
    [c.queued + c.running, "being made now"],
    [c.done, "finished"],
    [k.done_today, "finished today"],
    [c.error, "failed"],
    [k.duplicates, "skipped (already made)"],
    [k.avg_minutes ? `${k.avg_minutes} min` : "—", "average per video"],
    [k.eta_hours != null && k.remaining ? `${k.eta_hours} h` : "—", "time to finish the folder"],
    [k.per_day ?? "—", "videos per day (this PC)"],
    [st.state.free_gb != null ? `${st.state.free_gb} GB` : "—", "free disk space"],
  ];
  $("ap-counts").innerHTML = tiles
    .map(([n, label]) => `<div class="ap-count"><b>${esc(n ?? 0)}</b><span>${label}</span></div>`)
    .join("");
  $("ap-empty").hidden = st.recent.length > 0;
  $("ap-recent").innerHTML = st.recent
    .map((r) => {
      const agent = state.meta.agents.find((a) => a.stage === r.stage)?.name || "";
      const where = r.status === "running" ? ` · ${agent} ${Math.round((r.progress || 0) * 100)}%`
        : r.duplicate && r.where ? ` · made in ${r.where}` : "";
      const langs = r.langs && r.langs.length > 1 ? ` · ${r.langs.join(" + ")}` : "";
      const link = r.status === "deleted" ? "" : `href="#job/${esc(r.job)}"`;
      return `<a class="ap-row" ${link}><div style="min-width:0"><div class="name">${esc(r.name)}</div>
        <div class="hint">${esc(new Date(r.at * 1000).toLocaleString())}${esc(langs)}${esc(where)}</div></div>
        <span class="status ${esc(r.status)}">${esc(STATUS_TEXT[r.status] || r.status)}</span></a>`;
    })
    .join("");
}

const rate = () => rateString($("ap-rate").value);

async function fillForm(cfg) {
  $("ap-watch").value = cfg.watch_dir;
  $("ap-output").value = cfg.output_dir;
  $("ap-sub").checked = cfg.include_subfolders;
  $("ap-lang").value = cfg.lang;
  $("ap-style").innerHTML = state.styles
    .map((s) => `<option value="${esc(s.id)}" ${s.id === cfg.style ? "selected" : ""}>${esc(s.name)}</option>`)
    .join("");
  $("ap-rate").value = parseInt(cfg.rate, 10) || 0;
  $("ap-rate-l").textContent = rate();
  document.querySelectorAll('input[name="ap-fmt"]').forEach((i) => (i.checked = cfg.formats.includes(i.value)));
  $("ap-max").value = cfg.max_queue;
  $("ap-age").value = cfg.min_age_sec;
  $("ap-free").value = cfg.min_free_gb;
  $("ap-cleanup").checked = cfg.cleanup;
  renderLangChips($("ap-extra"), cfg.lang, cfg.extra_langs || []);
  voice = cfg.voice;
  await renderVoices($("ap-voices"), cfg.lang, cfg.voice, rate, (id) => (voice = id));
}

async function refresh() {
  try {
    const st = await api("/api/autopilot");
    renderStatus(st);
    if (!formLoaded) {
      formLoaded = true;
      await fillForm(st.config);
    }
  } catch (err) {
    $("ap-error").textContent = err.message;
  }
}

async function save(e) {
  e.preventDefault();
  const body = {
    watch_dir: $("ap-watch").value.trim(),
    output_dir: $("ap-output").value.trim(),
    include_subfolders: $("ap-sub").checked,
    lang: $("ap-lang").value,
    voice,
    rate: rate(),
    style: $("ap-style").value,
    formats: [...document.querySelectorAll('input[name="ap-fmt"]:checked')].map((i) => i.value),
    max_queue: Number($("ap-max").value),
    min_age_sec: Number($("ap-age").value),
    min_free_gb: Number($("ap-free").value),
    cleanup: $("ap-cleanup").checked,
    extra_langs: readLangChips($("ap-extra")),
  };
  try {
    renderStatus(await api("/api/autopilot", { method: "PUT", body }));
    $("ap-msg").textContent = "Saved. New pickups use these settings.";
    toast("Autopilot settings saved");
  } catch (err) {
    $("ap-msg").textContent = err.message;
  }
}

async function toggle() {
  const on = $("ap-toggle").textContent.startsWith("Stop");
  try {
    renderStatus(await api(`/api/autopilot/${on ? "stop" : "start"}`, { method: "POST" }));
    toast(on ? "Autopilot stopped — videos already being made will finish" : "Autopilot started");
  } catch (err) {
    toast(err.message, true);
  }
}

export function initAutopilot() {
  $("lib-q").addEventListener("input", () => {
    clearTimeout(libTimer);
    libTimer = setTimeout(loadLibrary, 300);
  });
  $("lib-status").addEventListener("change", loadLibrary);
  $("ap-lang").innerHTML = state.meta.languages.map((l) => `<option value="${esc(l.code)}">${esc(l.name)}</option>`).join("");
  $("ap-lang").addEventListener("change", () => {
    renderLangChips($("ap-extra"), $("ap-lang").value, readLangChips($("ap-extra")));
    renderVoices($("ap-voices"), $("ap-lang").value, null, rate, (id) => (voice = id));
  });
  $("ap-rate").addEventListener("input", () => ($("ap-rate-l").textContent = rate()));
  $("ap-form").addEventListener("submit", save);
  $("ap-toggle").addEventListener("click", toggle);
  $("ap-scan-now").addEventListener("click", async () => {
    try {
      renderStatus(await api("/api/autopilot/scan", { method: "POST" }));
      toast("Checking the folder…");
    } catch (err) {
      toast(err.message, true);
    }
  });
}

let libTimer = null;
async function loadLibrary() {
  const q = encodeURIComponent($("lib-q").value.trim());
  const st = encodeURIComponent($("lib-status").value);
  try {
    const res = await api(`/api/library?q=${q}&status=${st}`);
    $("lib-total").textContent = `${res.total} video${res.total === 1 ? "" : "s"}${res.total > res.rows.length ? ` (showing ${res.rows.length})` : ""}`;
    $("lib-rows").innerHTML = res.rows
      .map((r) => {
        const link = r.status === "deleted" ? "" : `href="#job/${esc(r.job)}"`;
        const times = r.times > 1 ? ` · made ${r.times}×` : "";
        return `<a class="ap-row" ${link}><div style="min-width:0"><div class="name">${esc(r.name)}</div>
          <div class="hint">${esc(new Date(r.last * 1000).toLocaleString())}${times} · ${esc(r.fingerprint.startsWith("yt:") ? "YouTube " + r.fingerprint.slice(3) : "file match")}</div></div>
          <span class="status ${esc(r.status)}">${esc(STATUS_TEXT[r.status] || r.status)}</span></a>`;
      })
      .join("");
  } catch (err) {
    $("lib-total").textContent = err.message;
  }
}

export function showAutopilot() {
  loadLibrary();
  stopAutopilot();
  formLoaded = false;
  refresh();
  timer = setInterval(refresh, POLL_MS);
}
