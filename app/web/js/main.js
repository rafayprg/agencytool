// Router + app bootstrap.
import { api, state, toast } from "./api.js";
import { initCreate, refreshCreate } from "./create.js";
import { initAutopilot, showAutopilot, stopAutopilot } from "./autopilot.js";
import { showJob, showProjects, stopJobPolling } from "./projects.js";
import { initSettings, showSettings } from "./settings.js";
import { initStyles, showStyles } from "./styles-page.js";

const PAGES = ["create", "projects", "job", "autopilot", "styles", "settings"];

function route() {
  const hash = location.hash.replace(/^#/, "") || "create";
  const [page, arg] = hash.split("/");
  const name = PAGES.includes(page) ? page : "create";
  stopJobPolling();
  stopAutopilot();
  PAGES.forEach((p) => {
    document.getElementById(`page-${p}`).hidden = p !== name;
  });
  document.querySelectorAll(".tab").forEach((t) => {
    t.classList.toggle("active", t.dataset.page === name || (name === "job" && t.dataset.page === "projects"));
  });
  window.scrollTo({ top: 0 });
  if (name === "projects") showProjects();
  if (name === "job" && arg) showJob(arg);
  if (name === "autopilot") showAutopilot();
  if (name === "styles") showStyles();
  if (name === "settings") showSettings();
  if (name === "create") refreshCreate();
}

export function updateEnginePill() {
  const pill = document.getElementById("engine-pill");
  const s = state.meta?.settings || {};
  const order = s.translator === "free" ? [] : s.translator === "groq" ? ["groq"] : s.translator === "gemini" ? ["gemini"] : ["groq", "gemini"];
  const engine = order.find((e) => s[`${e}_configured`]);
  pill.textContent = engine ? `● ${engine === "groq" ? "Groq" : "Gemini"} translation` : "● Free translators";
  pill.classList.toggle("on", Boolean(engine));
}

async function pollRunning() {
  try {
    const jobs = await api("/api/jobs");
    const busy = jobs.filter((j) => ["running", "queued"].includes(j.status)).length;
    const badge = document.getElementById("running-count");
    badge.hidden = busy === 0;
    badge.textContent = String(busy);
    const ap = await api("/api/autopilot");
    document.getElementById("ap-dot").hidden = !ap.config.enabled;
  } catch {
    /* server restarting — try again next tick */
  }
}

async function boot() {
  try {
    state.meta = await api("/api/meta");
    state.styles = await api("/api/styles");
  } catch (err) {
    toast(err.message, true);
    return;
  }
  updateEnginePill();
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => (location.hash = t.dataset.page)));
  initCreate();
  initStyles();
  initSettings();
  initAutopilot();
  window.addEventListener("hashchange", route);
  route();
  pollRunning();
  setInterval(pollRunning, 4000);
}

boot();
