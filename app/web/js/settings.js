// Settings page.
import { api, esc, state, toast } from "./api.js";
import { updateEnginePill } from "./main.js";

const $ = (id) => document.getElementById(id);

function fillModels(models, current) {
  const list = models.length ? models : [current];
  $("set-model").innerHTML = list.map((m) => `<option ${m === current ? "selected" : ""}>${esc(m)}</option>`).join("");
}

function fillGroqModels(models, current) {
  const list = models.length ? models : [current];
  $("set-groq-model").innerHTML = list.map((m) => `<option ${m === current ? "selected" : ""}>${esc(m)}</option>`).join("");
}

export function initSettings() {
  $("set-ahead").addEventListener("input", () => ($("set-ahead-l").textContent = $("set-ahead").value));
  $("test-tg").addEventListener("click", async () => {
    const msg = $("tg-msg");
    msg.textContent = "Sending…";
    try {
      await api("/api/settings/telegram-test", {
        method: "POST",
        body: { telegram_bot_token: $("set-tg-token").value.trim(), telegram_chat_id: $("set-tg-chat").value.trim() },
      });
      msg.textContent = "Sent — check Telegram, then press Save.";
    } catch (err) {
      msg.textContent = err.message;
    }
  });
  $("test-groq").addEventListener("click", async () => {
    const msg = $("groq-msg");
    msg.textContent = "Checking…";
    try {
      const res = await api("/api/settings/groq-test", { method: "POST", body: { groq_api_key: $("set-groq-key").value.trim() } });
      const keep = res.models.includes(state.meta.settings.groq_model) ? state.meta.settings.groq_model : res.best;
      fillGroqModels(res.models, keep);
      msg.textContent = `Key works — ${res.models.length} models. Press Save.`;
    } catch (err) {
      msg.textContent = err.message;
    }
  });
  $("set-lang").innerHTML = state.meta.languages.map((l) => `<option value="${esc(l.code)}">${esc(l.name)}</option>`).join("");
  $("test-key").addEventListener("click", async () => {
    const msg = $("key-msg");
    msg.textContent = "Checking…";
    try {
      const res = await api("/api/settings/gemini-test", { method: "POST", body: { gemini_api_key: $("set-key").value.trim() } });
      const flash = res.models.filter((m) => m.includes("flash"));
      fillModels(res.models, flash.includes(state.meta.settings.gemini_model) ? state.meta.settings.gemini_model : flash[0] || res.models[0]);
      msg.textContent = `Key works — ${res.models.length} models available. Pick one and press Save.`;
    } catch (err) {
      msg.textContent = err.message;
    }
  });
  $("settings-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = {
      gemini_api_key: $("set-key").value.trim(),
      gemini_model: $("set-model").value,
      groq_api_key: $("set-groq-key").value.trim(),
      groq_model: $("set-groq-model").value,
      translator: $("set-translator").value,
      prep_ahead: Number($("set-ahead").value),
      transcribe_device: $("set-device").value,
      cleanup_after_done: $("set-cleanup").checked,
      telegram_bot_token: $("set-tg-token").value.trim(),
      telegram_chat_id: $("set-tg-chat").value.trim(),
      notify_done: $("set-tg-done").checked,
      notify_errors: $("set-tg-err").checked,
      library_dir: $("set-libdir").value.trim(),
      mymemory_email: $("set-email").value.trim(),
      whisper_model: $("set-whisper").value,
      default_lang: $("set-lang").value,
      default_style: $("set-style").value,
      review_script: $("set-review").checked,
    };
    try {
      state.meta.settings = await api("/api/settings", { method: "PUT", body });
      updateEnginePill();
      showSettings();
      toast("Settings saved");
    } catch (err) {
      toast(err.message, true);
    }
  });
}

export function showSettings() {
  const s = state.meta.settings;
  $("set-key").value = s.gemini_api_key;
  fillModels([], s.gemini_model);
  $("set-groq-key").value = s.groq_api_key;
  fillGroqModels([], s.groq_model);
  $("set-translator").value = s.translator;
  $("set-ahead").value = s.prep_ahead;
  $("set-ahead-l").textContent = s.prep_ahead;
  $("set-device").value = s.transcribe_device;
  $("set-cleanup").checked = s.cleanup_after_done;
  $("set-tg-token").value = s.telegram_bot_token;
  $("set-tg-chat").value = s.telegram_chat_id;
  $("set-tg-done").checked = s.notify_done;
  $("set-tg-err").checked = s.notify_errors;
  $("set-libdir").value = s.library_dir;
  $("set-email").value = s.mymemory_email;
  $("set-whisper").value = s.whisper_model;
  $("set-lang").value = s.default_lang;
  $("set-style").innerHTML = state.styles
    .map((st) => `<option value="${esc(st.id)}" ${st.id === s.default_style ? "selected" : ""}>${esc(st.name)}</option>`)
    .join("");
  $("set-review").checked = s.review_script;
  const keys = [s.groq_configured && "Groq", s.gemini_configured && "Gemini"].filter(Boolean);
  $("settings-msg").textContent = keys.length ? `Keys saved: ${keys.join(", ")}.` : "No API keys — free translators in use.";
}
