// Small helpers shared by every page.

export async function api(path, { method = "GET", body, form } = {}) {
  const opts = { method, headers: {} };
  if (form) {
    opts.body = form;
  } else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch {
    throw new Error("Studio server is not reachable — is start.bat still running?");
  }
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail = data && data.detail;
    const msg = Array.isArray(detail) ? detail.map((d) => d.msg).join(", ") : detail || `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

/** Escape text for safe use inside innerHTML templates. */
export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

let toastTimer;
export function toast(message, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.classList.toggle("err", isError);
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), isError ? 6000 : 3000);
}

export const state = { meta: null, styles: [] };

export function styleMini(style) {
  const c = style.colors;
  const vars = `--s-bg1:${c.bg1};--s-bg2:${c.bg2};--s-accent:${c.accent};--s-accent2:${c.accent2};--s-text:${c.text}`;
  const side = style.layout === "phone-left" ? "left" : "right";
  return `<div class="mini ${side}" style="${esc(vars)}"><i class="m-phone"></i><i class="m-pill"></i><i class="m-head"></i><i class="m-call"></i><i class="m-cap"></i></div>`;
}

export function fmtTime(sec) {
  if (!sec && sec !== 0) return "";
  const s = Math.round(sec);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function rateString(value) {
  const n = Number(value);
  return `${n >= 0 ? "+" : ""}${n}%`;
}

let currentAudio = null;
/** Play a voice sample; clicking the same button again stops it. */
export function playPreview(button, voice, rate) {
  if (currentAudio) {
    currentAudio.pause();
    document.querySelectorAll(".play.playing").forEach((b) => {
      b.classList.remove("playing");
      b.textContent = "▶";
    });
    if (currentAudio.dataset.voice === voice + rate) {
      currentAudio = null;
      return;
    }
  }
  const audio = new Audio(`/api/voices/preview?voice=${encodeURIComponent(voice)}&rate=${encodeURIComponent(rate)}`);
  audio.dataset.voice = voice + rate;
  currentAudio = audio;
  button.classList.add("playing");
  button.textContent = "■";
  const reset = () => {
    button.classList.remove("playing");
    button.textContent = "▶";
  };
  audio.addEventListener("ended", reset);
  audio.addEventListener("error", () => {
    reset();
    toast("Voice preview failed (internet needed for voices)", true);
  });
  audio.play().catch(reset);
}

/** Render a voice picker into `container`; calls onPick(voiceId). */
export async function renderVoices(container, lang, selected, getRate, onPick) {
  container.innerHTML = `<p class="hint">Loading voices…</p>`;
  let voices;
  try {
    voices = await api(`/api/voices?lang=${encodeURIComponent(lang)}`);
  } catch (err) {
    container.innerHTML = `<p class="error">${esc(err.message)}</p>`;
    return null;
  }
  if (!voices.length) {
    container.innerHTML = `<p class="error">No voices for this language.</p>`;
    return null;
  }
  const pick = voices.some((v) => v.id === selected) ? selected : voices[0].id;
  // the chosen voice first, then the rest
  const ordered = [...voices.filter((v) => v.id === pick), ...voices.filter((v) => v.id !== pick)];
  container.innerHTML = ordered
    .map(
      (v) => `<label class="voice ${v.id === pick ? "selected" : ""}" data-voice="${esc(v.id)}">
        <input type="radio" name="voice" value="${esc(v.id)}" ${v.id === pick ? "checked" : ""} />
        <span class="meta"><b>${esc(v.name)}</b><small>${esc(v.gender)} · ${esc(v.locale)}</small></span>
        <button type="button" class="play" aria-label="Play ${esc(v.name)} sample">▶</button>
      </label>`,
    )
    .join("");
  container.querySelectorAll(".voice").forEach((el) => {
    el.addEventListener("click", (e) => {
      const id = el.dataset.voice;
      if (e.target.closest(".play")) {
        e.preventDefault();
        playPreview(e.target.closest(".play"), id, getRate());
        return;
      }
      container.querySelectorAll(".voice").forEach((x) => x.classList.toggle("selected", x === el));
      el.querySelector("input").checked = true;
      onPick(id);
    });
  });
  onPick(pick);
  return pick;
}

/** Language checkboxes (all languages except `exclude`), keeping `checked` codes ticked. */
export function renderLangChips(container, exclude, checked = []) {
  container.innerHTML = state.meta.languages
    .filter((l) => l.code !== exclude)
    .map((l) => `<label><input type="checkbox" value="${esc(l.code)}" ${checked.includes(l.code) ? "checked" : ""} /> ${esc(l.name)}</label>`)
    .join("");
}

export function readLangChips(container) {
  return [...container.querySelectorAll("input:checked")].map((i) => i.value);
}
