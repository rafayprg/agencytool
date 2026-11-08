// Projects list + single project (job) page.
import { api, esc, fmtTime, rateString, renderVoices, state, toast } from "./api.js";
import { renderScript } from "./script-editor.js";

const POLL_MS = 2000;
let listTimer = null;
let jobTimer = null;
let currentId = null;
const sig = {};

export function stopJobPolling() {
  clearInterval(listTimer);
  clearInterval(jobTimer);
  listTimer = jobTimer = null;
  currentId = null;
}

function agentState(job, stage) {
  if (job.done?.includes(stage)) return "done";
  if (job.stage === stage) {
    if (job.status === "error") return "err";
    if (job.status === "review") return "wait";
    if (job.status === "running") return "run";
  }
  return "";
}

const STATUS_TEXT = { queued: "queued", running: "working", waiting: "waiting", review: "needs you", done: "ready", error: "failed", cancelled: "stopped" };

function chips(job) {
  return state.meta.agents
    .filter((a) => a.stage !== "review" || job.options?.review)
    .map((a) => `<i class="chip ${agentState(job, a.stage)}" title="${esc(a.name)}"></i>`)
    .join("");
}

function currentAgentName(job) {
  return state.meta.agents.find((a) => a.stage === job.stage)?.name || "";
}

// ---------------- list ----------------
async function loadList() {
  let jobs;
  try {
    jobs = await api("/api/jobs");
  } catch (err) {
    toast(err.message, true);
    return;
  }
  const list = document.getElementById("job-list");
  document.getElementById("jobs-empty").hidden = jobs.length > 0;
  list.innerHTML = jobs
    .map((j) => {
      const lang = state.meta.languages.find((l) => l.code === j.options?.lang)?.name || j.options?.lang || "";
      const where = j.status === "running" ? `${currentAgentName(j)} ${Math.round((j.progress || 0) * 100)}%` : "";
      const thumb = j.files.thumbnail || j.files.full_frame;
      return `<a class="job" href="#job/${esc(j.id)}">
        ${thumb ? `<img class="thumb" src="${esc(thumb)}" alt="" loading="lazy" />` : `<span class="thumb"></span>`}
        <div style="min-width:0">
          <div class="title">${esc(j.title || "Untitled")}</div>
          <div class="sub">→ ${esc(lang)} · ${esc(j.options?.voice || "")}${j.duration ? " · " + fmtTime(j.duration) : ""}${where ? " · " + esc(where) : ""}</div>
          <div class="chips">${chips(j)}</div>
        </div>
        <span class="status ${esc(j.status)}">${esc(STATUS_TEXT[j.status] || j.status)}</span>
      </a>`;
    })
    .join("");
}

export function showProjects() {
  stopJobPolling();
  loadList();
  listTimer = setInterval(loadList, POLL_MS);
}

// ---------------- detail ----------------
function skeleton(id) {
  document.getElementById("job-detail").innerHTML = `
    <div class="detail-head"><div><h1 id="jd-title">Loading…</h1><p class="sub" id="jd-sub"></p></div><div class="row wrap" id="jd-actions"></div></div>
    <div class="detail-grid">
      <aside class="card pipeline" id="jd-pipe" aria-label="Agents"></aside>
      <div>
        <div id="jd-alert" class="panel"></div>
        <div id="jd-outputs" class="panel"></div>
        <div id="jd-script" class="panel"></div>
        <div id="jd-rerun" class="panel"></div>
        <div id="jd-crop" class="panel"></div>
        <div class="panel"><h2>Agent log</h2><div id="jd-log" class="log"></div></div>
      </div>
    </div>`;
  Object.keys(sig).forEach((k) => delete sig[k]);
  sig.id = id;
}

function once(key, value, fn) {
  const s = JSON.stringify(value);
  if (sig[key] === s) return;
  sig[key] = s;
  fn();
}

function renderHead(job) {
  const lang = state.meta.languages.find((l) => l.code === job.options.lang)?.name || job.options.lang;
  document.getElementById("jd-title").textContent = job.title || "Untitled";
  document.getElementById("jd-sub").textContent =
    `${job.channel ? job.channel + " · " : ""}${job.duration ? fmtTime(job.duration) + " · " : ""}→ ${lang} · ${job.options.voice} · style ${job.options.style}`;
  once("actions", job.status, () => {
    const busy = ["running", "queued", "waiting"].includes(job.status);
    document.getElementById("jd-actions").innerHTML =
      `<span class="status ${esc(job.status)}">${esc(STATUS_TEXT[job.status] || job.status)}</span>` +
      (busy ? `<button class="btn small" data-act="cancel">Stop</button>` : `<button class="btn small danger" data-act="delete">Delete</button>`);
    document.querySelector('[data-act="cancel"]')?.addEventListener("click", () => act(job.id, "cancel"));
    document.querySelector('[data-act="delete"]')?.addEventListener("click", () => act(job.id, "delete"));
  });
}

function renderPipeline(job) {
  document.getElementById("jd-pipe").innerHTML = state.meta.agents
    .filter((a) => a.stage !== "review" || job.options.review)
    .map((a, i) => {
      const st = agentState(job, a.stage);
      const icon = st === "done" ? "✓" : st === "err" ? "!" : String(i + 1);
      const bar = st === "run" ? `<div class="bar"><i style="width:${Math.round((job.progress || 0) * 100)}%"></i></div>` : "";
      return `<div class="agent ${st}"><span class="dot">${icon}</span><div><b>${esc(a.name)}</b><small>${esc(a.role)}</small>${bar}</div></div>`;
    })
    .join("");
}

function renderAlert(job) {
  once("alert", [job.status, job.error, job.stage], () => {
    const box = document.getElementById("jd-alert");
    if (job.status === "error") {
      const cropFix = job.stage === "crop"
        ? `<input id="fix-crop" type="text" placeholder="W:H:X:Y e.g. 460:1044:1235:18" value="${esc(job.options.crop || "")}" style="max-width:260px" />`
        : "";
      box.innerHTML = `<div class="callout-box err"><div><b>${esc(job.error)}</b><p class="hint">Fix the cause, then retry — finished agents are not repeated.</p></div>
        <div class="row">${cropFix}<button class="btn primary" id="retry">Retry</button></div></div>`;
      document.getElementById("retry").addEventListener("click", () => {
        const crop = document.getElementById("fix-crop");
        run(job.id, crop ? { crop: crop.value.trim() } : {});
      });
    } else if (job.status === "review") {
      box.innerHTML = `<div class="callout-box"><div><b>The translated script is ready.</b><p class="hint">Check the lines below, edit anything, then record the voice.</p></div></div>`;
    } else if (job.status === "cancelled") {
      box.innerHTML = `<div class="callout-box"><div><b>Stopped.</b></div><button class="btn" id="resume">Resume</button></div>`;
      document.getElementById("resume").addEventListener("click", () => run(job.id, {}));
    } else {
      box.innerHTML = "";
    }
  });
}

function renderOutputs(job) {
  const f = job.files;
  once("outputs", [f.video_16x9, f.video_9x16, f.upload_txt, f.thumb_new], async () => {
    const box = document.getElementById("jd-outputs");
    if (!f.video_16x9 && !f.video_9x16) {
      box.innerHTML = "";
      return;
    }
    const fig = (src, label, name) =>
      src ? `<figure><video src="${esc(src)}" controls preload="metadata"></video>
        <figcaption><span>${label}</span><a class="btn small" href="${esc(src)}" download="${esc(name)}">Download</a></figcaption></figure>` : "";
    let upload = "";
    if (f.upload_txt) {
      try {
        upload = await (await fetch(f.upload_txt)).text();
      } catch {
        upload = "";
      }
    }
    box.innerHTML = `<h2>Your video</h2>
      <div class="videos">${fig(f.video_16x9, "YouTube 16:9", "video_16x9.mp4")}${fig(f.video_9x16, "Shorts / Reels 9:16", "video_9x16.mp4")}</div>
      ${f.thumb_new || f.thumb_original ? `<div class="thumbs">
        ${f.thumb_new ? `<figure><img src="${esc(f.thumb_new)}" alt="New thumbnail" /><figcaption><span>New thumbnail</span><a class="btn small" href="${esc(f.thumb_new)}" download="thumbnail.jpg">Download</a></figcaption></figure>` : ""}
        ${f.thumb_original ? `<figure><img src="${esc(f.thumb_original)}" alt="Original thumbnail" /><figcaption><span>Original creator's thumbnail</span><a class="btn small" href="${esc(f.thumb_original)}" download="original_thumbnail.jpg">Download</a></figcaption></figure>` : ""}
      </div>` : ""}
      <div class="downloads">
        ${f.captions ? `<a class="btn small" href="${esc(f.captions)}" download="captions.srt">Captions .srt</a>` : ""}
        ${f.metadata ? `<a class="btn small" href="${esc(f.metadata)}" download="metadata.json">metadata.json</a>` : ""}
        ${f.upload_txt ? `<button class="btn small" id="copy-upload">Copy title + description</button>` : ""}
      </div>
      ${upload ? `<pre class="upload">${esc(upload)}</pre>` : ""}`;
    document.getElementById("copy-upload")?.addEventListener("click", async () => {
      await navigator.clipboard.writeText(upload);
      toast("Copied");
    });
  });
}

function renderCrop(job) {
  once("crop", [job.crop, job.files.full_frame, job.status === "running", job.cleaned], () => {
    const box = document.getElementById("jd-crop");
    if (!job.crop || !job.files.full_frame) {
      box.innerHTML = "";
      return;
    }
    const c = job.crop;
    const pct = (v, total) => `${((v / total) * 100).toFixed(2)}%`;
    const busy = ["running", "queued", "waiting"].includes(job.status) || Boolean(job.cleaned);
    box.innerHTML = `<h2>Phone screen <span class="hint">(${esc(c.source)})</span></h2>
      <div class="crop-view">
        <div class="crop-frame"><img src="${esc(job.files.full_frame)}" alt="Source frame" />
          <span class="crop-rect" style="left:${pct(c.x, job.width)};top:${pct(c.y, job.height)};width:${pct(c.w, job.width)};height:${pct(c.h, job.height)}"></span></div>
        ${job.files.crop_preview ? `<img src="${esc(job.files.crop_preview)}" alt="Cropped phone" />` : ""}
      </div>
      <div class="row wrap"><label class="field"><span>Wrong box? Set W:H:X:Y (video is ${job.width}×${job.height})</span>
        <input id="crop-input" type="text" value="${c.w}:${c.h}:${c.x}:${c.y}" /></label>
        <button class="btn" id="recrop" ${busy ? "disabled" : ""}>Re-crop &amp; re-render</button></div>`;
    document.getElementById("recrop").addEventListener("click", () =>
      run(job.id, { from_stage: "crop", crop: document.getElementById("crop-input").value.trim() }),
    );
  });
}

function renderRerun(job) {
  const ready = job.done.includes("voice") || job.done.includes("translate");
  once("rerun", [ready, job.status, job.options, job.cleaned], () => {
    const box = document.getElementById("jd-rerun");
    const busy = ["running", "queued"].includes(job.status);
    if (!ready || busy || job.status === "review") {
      box.innerHTML = "";
      return;
    }
    if (job.cleaned) {
      box.innerHTML = `<div class="callout-box"><div><b>Working files were removed by the disk saver.</b>
        <p class="hint">The finished package is kept${job.exported_only ? " in your output folder" : ""}. To change style or voice, make it again from New video (tick "make it again").</p></div></div>`;
      return;
    }
    const styleOpts = state.styles
      .map((s) => `<option value="${esc(s.id)}" ${s.id === job.options.style ? "selected" : ""}>${esc(s.name)}</option>`)
      .join("");
    const rateNum = parseInt(job.options.rate, 10) || 0;
    box.innerHTML = `<h2>Change and re-make</h2>
      <div class="rerun">
        <label class="field"><span>Editing style</span><select id="rr-style">${styleOpts}</select></label>
        <label class="field"><span>Speed <b id="rr-rate-l">${esc(rateString(rateNum))}</b></span><input id="rr-rate" type="range" min="-20" max="30" step="2" value="${rateNum}" /></label>
        <div class="row wrap"><button class="btn" id="rr-render">Re-render with style</button>
        <button class="btn" id="rr-thumb">Re-make thumbnail</button></div>
      </div>
      <div id="rr-voices" class="voice-list"></div>
      <div class="row"><button class="btn primary" id="rr-voice">Re-record voice + render</button></div>`;
    let voice = job.options.voice;
    const rr = () => rateString(document.getElementById("rr-rate").value);
    document.getElementById("rr-rate").addEventListener("input", () => (document.getElementById("rr-rate-l").textContent = rr()));
    renderVoices(document.getElementById("rr-voices"), job.options.lang, voice, rr, (id) => (voice = id));
    document.getElementById("rr-thumb").addEventListener("click", () =>
      run(job.id, { from_stage: "thumbnail", style: document.getElementById("rr-style").value }),
    );
    document.getElementById("rr-render").addEventListener("click", () =>
      run(job.id, { from_stage: "render", style: document.getElementById("rr-style").value }),
    );
    document.getElementById("rr-voice").addEventListener("click", () =>
      run(job.id, { from_stage: "voice", voice, rate: rr(), style: document.getElementById("rr-style").value }),
    );
  });
}

function renderLog(job) {
  once("log", job.log.length, () => {
    const box = document.getElementById("jd-log");
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 30;
    box.innerHTML = job.log
      .map((l) => `<div><span class="t">${new Date(l.t * 1000).toLocaleTimeString()}</span><span class="a">${esc(l.agent)}</span><span class="${l.level === "error" ? "error" : ""}">${esc(l.msg)}</span></div>`)
      .join("");
    if (atBottom) box.scrollTop = box.scrollHeight;
  });
}

async function loadJob() {
  const id = currentId;
  let job;
  try {
    job = await api(`/api/jobs/${encodeURIComponent(id)}`);
  } catch (err) {
    if (id === currentId) document.getElementById("jd-title").textContent = err.message;
    return;
  }
  if (id !== currentId) return;
  renderHead(job);
  renderPipeline(job);
  renderAlert(job);
  renderOutputs(job);
  renderRerun(job);
  renderCrop(job);
  renderLog(job);
  once("script", [job.done.includes("translate") || job.status === "review", job.status], () =>
    renderScript(document.getElementById("jd-script"), job, run),
  );
}

export function showJob(id) {
  stopJobPolling();
  currentId = id;
  skeleton(id);
  loadJob();
  jobTimer = setInterval(loadJob, POLL_MS);
}

export async function run(id, body) {
  try {
    await api(`/api/jobs/${encodeURIComponent(id)}/run`, { method: "POST", body });
    toast("Agents working…");
    Object.keys(sig).forEach((k) => k !== "id" && delete sig[k]);
    loadJob();
  } catch (err) {
    toast(err.message, true);
  }
}

async function act(id, what) {
  if (what === "delete" && !confirm("Delete this project and all its files? This cannot be undone.")) return;
  try {
    if (what === "delete") {
      await api(`/api/jobs/${encodeURIComponent(id)}`, { method: "DELETE" });
      toast("Deleted");
      location.hash = "projects";
    } else {
      await api(`/api/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" });
      toast("Stopping…");
    }
  } catch (err) {
    toast(err.message, true);
  }
}
