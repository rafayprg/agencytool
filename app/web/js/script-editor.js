// Translated script editor (shown while the job waits for review, and after it is done).
import { api, esc, fmtTime, toast } from "./api.js";

export async function renderScript(box, job, run) {
  const ready = job.done.includes("translate") || job.status === "review";
  if (!ready) {
    box.innerHTML = "";
    return;
  }
  let spec;
  try {
    spec = await api(`/api/jobs/${encodeURIComponent(job.id)}/script`);
  } catch {
    box.innerHTML = "";
    return;
  }
  const review = job.status === "review";
  const busy = ["running", "queued"].includes(job.status);
  const open = review ? "open" : "";
  box.innerHTML = `<details class="card" ${open}>
    <summary><h2 style="display:inline">Script</h2> <span class="hint">· ${spec.scenes.length} lines · translated by ${esc(spec.engine)}${spec.reviewed ? " · edited by you" : ""}</span></summary>
    <form id="script-form" style="display:grid;gap:12px;margin-top:14px">
      <div class="script-meta">
        <label class="field"><span>Video title</span><input name="title" maxlength="100" value="${esc(spec.title)}" required /></label>
        <label class="field"><span>"Tap" badge word</span><input name="tap" maxlength="12" value="${esc(spec.labels?.tap || "TAP")}" /></label>
      </div>
      <label class="field"><span>Thumbnail text (2–5 words)</span><input name="thumb" maxlength="60" value="${esc(spec.thumb_text || "")}" /></label>
      <label class="field"><span>Tags (comma separated)</span><input name="tags" value="${esc((spec.tags || []).join(", "))}" /></label>
      <div>${spec.scenes
        .map(
          (s) => `<div class="scene-row" data-id="${s.id}">
          <span class="sid">${s.id}</span>
          <div class="orig"><small>${fmtTime(s.src[0])}–${fmtTime(s.src[1])}</small>${esc(s.original)}</div>
          <div class="scene-fields">
            <textarea name="text" rows="3" required>${esc(s.text)}</textarea>
            <div class="mini-row">
              <input name="chapter" maxlength="60" placeholder="Chapter pill" value="${esc(s.chapter)}" />
              <input name="sub" maxlength="120" placeholder="Big heading" value="${esc(s.sub)}" />
              <input name="callout" maxlength="80" placeholder="Button to tap" value="${esc(s.callout)}" />
            </div>
          </div></div>`,
        )
        .join("")}</div>
      <div class="submit-bar">
        <button class="btn" type="submit" data-mode="save" ${busy ? "disabled" : ""}>Save</button>
        <button class="btn primary" type="submit" data-mode="go" ${busy ? "disabled" : ""}>${review ? "Save &amp; record voice →" : "Save &amp; re-make video"}</button>
      </div>
    </form></details>`;
  const form = box.querySelector("#script-form");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const mode = e.submitter?.dataset.mode || "save";
    const body = {
      title: form.title.value.trim(),
      tap_label: form.tap.value.trim() || "TAP",
      thumb_text: form.thumb.value.trim(),
      tags: form.tags.value.split(",").map((t) => t.trim()).filter(Boolean),
      scenes: [...form.querySelectorAll(".scene-row")].map((row) => ({
        id: Number(row.dataset.id),
        text: row.querySelector('[name="text"]').value.trim(),
        chapter: row.querySelector('[name="chapter"]').value.trim(),
        sub: row.querySelector('[name="sub"]').value.trim(),
        callout: row.querySelector('[name="callout"]').value.trim(),
      })),
    };
    if (body.scenes.some((s) => !s.text)) return toast("Every line needs text", true);
    try {
      await api(`/api/jobs/${encodeURIComponent(job.id)}/script`, { method: "PUT", body });
      toast("Script saved");
      if (mode === "go") await run(job.id, review ? {} : { from_stage: "voice" });
    } catch (err) {
      toast(err.message, true);
    }
  });
}
