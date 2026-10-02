"use strict";
const $ = (selector) => document.querySelector(selector);
const node = (tag, className, text) => {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
};
const modelNames = {
  text_embedding: "Text embeddings",
  sentiment: "Sentiment",
  named_entities: "Named entities",
  summary: "Summarization",
  image_classification: "Image recognition",
  image_embedding: "Image embeddings",
  speech_to_text: "Speech to text",
};
let kind = "text";
let busy = false;
let libraryRequest = 0;
const previewURLs = {};

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error(
      "Couldn’t reach the app. Check your connection and try again.",
    );
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((item) => item.msg).join(". ")
          : `The request couldn’t finish (${response.status}). Please try again.`,
    );
  }
  return data;
}
const post = (path, data) =>
  request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
function showError(message) {
  $("#form-error").textContent = message;
  $("#form-error").hidden = !message;
}
function selectKind(next) {
  if (busy) return;
  kind = next;
  document.querySelectorAll("[data-kind]").forEach((tab) => {
    const selected = tab.dataset.kind === kind;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    $(`#${tab.dataset.kind}-panel`).hidden = !selected;
  });
  $("#text-input").required = kind === "text";
  const file = kind === "text" ? null : $(`#${kind}-input`).files[0];
  $("#file-name").textContent = file?.name || "";
  $("#file-name").hidden = !file;
  showError("");
}
document.querySelectorAll("[data-kind]").forEach((tab, index, tabs) => {
  tab.addEventListener("click", () => selectKind(tab.dataset.kind));
  tab.addEventListener("keydown", (event) => {
    const offsets = {
      ArrowRight: 1,
      ArrowLeft: -1,
      Home: -index,
      End: tabs.length - 1 - index,
    };
    if (!(event.key in offsets) || busy) return;
    event.preventDefault();
    const next = tabs[(index + offsets[event.key] + tabs.length) % tabs.length];
    selectKind(next.dataset.kind);
    next.focus();
  });
});
$("#text-input").addEventListener("input", () => {
  $("#char-count").textContent =
    `${$("#text-input").value.length.toLocaleString()} / 20,000`;
});
$("#load-example").addEventListener("click", () => {
  $("#asset-title").value = "A weekend in Lisbon";
  $("#text-input").value =
    "I absolutely loved our weekend in Lisbon. Sofia showed us the beautiful gardens at the Gulbenkian Museum, and we watched the sunset over the Tagus River. The city felt welcoming, creative, and full of life. I can’t wait to visit Portugal again.";
  $("#text-input").dispatchEvent(new Event("input"));
  $("#text-input").focus();
});
for (const mediaKind of ["image", "audio"]) {
  const input = $(`#${mediaKind}-input`);
  input.addEventListener("change", () => {
    const file = input.files[0];
    const preview = $(`#${mediaKind}-preview`);
    if (previewURLs[mediaKind]) URL.revokeObjectURL(previewURLs[mediaKind]);
    preview.removeAttribute("src");
    preview.hidden = true;
    $("#file-name").hidden = !file;
    $("#file-name").textContent = file?.name || "";
    showError("");
    if (!file) return;
    if (file.size > 25 * 1024 * 1024) {
      input.value = "";
      showError("Choose a file smaller than 25 MB.");
      return;
    }
    previewURLs[mediaKind] = URL.createObjectURL(file);
    preview.src = previewURLs[mediaKind];
    preview.hidden = false;
  });
  const zone = input.closest(".upload-zone");
  for (const event of ["dragenter", "dragover"])
    zone.addEventListener(event, () => zone.classList.add("dragging"));
  for (const event of ["dragleave", "drop"])
    zone.addEventListener(event, () => zone.classList.remove("dragging"));
}
function insight(label, content) {
  const section = node("section", "insight");
  section.append(
    node("div", "insight-label", label),
    typeof content === "string" ? node("p", "", content) : content,
  );
  return section;
}
function renderTextInsights(container, analysis) {
  if (analysis.sentiment) {
    const row = node("div", "sentiment-row");
    const label = analysis.sentiment.label.toLowerCase();
    row.append(
      node(
        "span",
        `sentiment-badge ${label === "negative" ? "negative" : ""}`,
        label,
      ),
      node(
        "span",
        "confidence",
        `${(analysis.sentiment.score * 100).toFixed(1)}% confidence`,
      ),
    );
    container.append(insight("Overall sentiment", row));
  }
  if (analysis.summary)
    container.append(insight("In a few words", analysis.summary.text));
  if (analysis.entities) {
    const entities = node("div", "entity-list");
    analysis.entities.entities.forEach((item) => {
      const chip = node("span", "entity", item.text);
      chip.append(node("small", "", item.label));
      entities.append(chip);
    });
    if (!entities.childNodes.length)
      entities.append(node("p", "", "No named entities found."));
    container.append(insight("People, places & things", entities));
  }
  if (analysis.embedding) {
    const wrap = node("div");
    wrap.append(
      node("p", "", `${analysis.embedding.dimensions} dimensions · normalized`),
    );
    const bars = node("div", "embedding");
    bars.setAttribute("aria-hidden", "true");
    analysis.embedding.vector.slice(0, 32).forEach((value) => {
      const bar = node("i");
      bar.style.height = `${Math.min(100, Math.max(7, Math.abs(value) * 800))}%`;
      bars.append(bar);
    });
    wrap.append(
      bars,
      node("small", "input-note", "Embedding preview · first 32 dimensions"),
    );
    container.append(insight("A fingerprint for meaning", wrap));
  }
}
function renderAsset(asset) {
  const container = node("div", "result-content");
  const meta = node("div", "result-meta");
  meta.append(
    node("span", `kind-tag ${asset.kind}`, asset.kind),
    node("span", "", "Saved to your library ✓"),
  );
  container.append(
    meta,
    node("h3", "", asset.title || `Untitled ${asset.kind}`),
  );
  const analysis = asset.analysis;
  if (analysis.transcription) {
    container.append(
      insight(
        "What we heard",
        analysis.transcription.text || "No speech detected.",
      ),
    );
    container.append(
      node(
        "p",
        "input-note",
        `${analysis.transcription.duration_seconds.toFixed(1)} seconds · English transcription`,
      ),
    );
    if (analysis.text) renderTextInsights(container, analysis.text);
  } else if (analysis.classification) {
    const predictions = node("div");
    analysis.classification.predictions.forEach((prediction) => {
      const row = node("div", "prediction");
      row.append(
        node("span", "", prediction.label),
        node("span", "", `${(prediction.score * 100).toFixed(1)}%`),
      );
      const track = node("div", "prediction-track"),
        fill = node("div", "prediction-fill");
      fill.style.width = `${Math.max(0, Math.min(100, prediction.score * 100))}%`;
      track.append(fill);
      row.append(track);
      predictions.append(row);
    });
    container.append(insight("What’s in the picture", predictions));
    renderTextInsights(container, { embedding: analysis.embedding });
  } else renderTextInsights(container, analysis);
  const details = node("details", "result-details");
  details.append(
    node("summary", "", "View full result"),
    node("pre", "", JSON.stringify(asset, null, 2)),
  );
  container.append(details);
  $("#results").replaceChildren(container);
}
$("#analyze-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  showError("");
  const title = $("#asset-title").value.trim() || null;
  const text = $("#text-input").value.trim();
  const file = kind === "text" ? null : $(`#${kind}-input`).files[0];
  if (kind === "text" && !text) {
    showError("Add some text to get started.");
    return;
  }
  if (kind !== "text" && !file) {
    showError(`Choose an ${kind} file to get started.`);
    return;
  }
  busy = true;
  const controls = [
    ...document.querySelectorAll(
      "#analyze-form input, #analyze-form textarea, #analyze-form button, [data-kind]",
    ),
  ];
  controls.forEach((control) => (control.disabled = true));
  $(".result-card").setAttribute("aria-busy", "true");
  const previous = [...$("#results").childNodes];
  const processing = node("div", "processing");
  processing.append(
    node("div", "spinner"),
    node("h3", "", "Finding the interesting bits…"),
    node(
      "p",
      "",
      "The first analysis can take a little longer while the models get ready.",
    ),
  );
  $("#results").replaceChildren(processing);
  try {
    let asset;
    if (kind === "text") asset = await post("/v1/assets/text", { text, title });
    else {
      const data = new FormData();
      data.append("file", file);
      if (title) data.append("title", title);
      asset = await request(`/v1/assets/${kind}`, {
        method: "POST",
        body: data,
      });
    }
    renderAsset(asset);
    $("#search-input").value = "";
    await loadLibrary();
    await loadModels();
  } catch (error) {
    showError(error.message);
    $("#results").replaceChildren(...previous);
  } finally {
    busy = false;
    controls.forEach((control) => (control.disabled = false));
    $(".result-card").setAttribute("aria-busy", "false");
  }
});
async function loadLibrary() {
  const sequence = ++libraryRequest;
  const query = $("#search-input").value.trim();
  $("#library-status").textContent = query
    ? "Finding connections…"
    : "Loading your library…";
  try {
    const data = query
      ? (await post("/v1/search", { text: query, limit: 20 })).hits
      : await request("/v1/assets?limit=20");
    if (sequence !== libraryRequest) return;
    const cards = data.map((asset) => {
      const card = node("button", "asset-tile");
      card.type = "button";
      card.append(
        node("span", `kind-tag ${asset.kind}`, asset.kind),
        node("h3", "", asset.title || `Untitled ${asset.kind}`),
        node("p", "", asset.content_text || "No speech detected."),
        node("small", "", "Open insights ↗"),
      );
      card.addEventListener("click", async () => {
        if (busy) return;
        card.disabled = true;
        try {
          renderAsset(await request(`/v1/assets/${asset.id}`));
          $("#studio").scrollIntoView({ behavior: "smooth" });
        } catch (error) {
          $("#library-status").textContent = error.message;
        } finally {
          card.disabled = false;
        }
      });
      return card;
    });
    $("#asset-list").replaceChildren(
      ...(cards.length
        ? cards
        : [
            node(
              "div",
              "library-empty",
              query
                ? "No matches yet. Try another phrase."
                : "Your next discovery starts above. Analyze something to begin your library.",
            ),
          ]),
    );
    $("#library-status").textContent = query
      ? `${data.length} search result${data.length === 1 ? "" : "s"}`
      : `Showing ${data.length} recent asset${data.length === 1 ? "" : "s"}`;
  } catch (error) {
    if (sequence === libraryRequest)
      $("#library-status").textContent = error.message;
  }
}
$("#search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  loadLibrary();
});
$("#refresh-library").addEventListener("click", () => {
  $("#search-input").value = "";
  loadLibrary();
});
async function loadModels() {
  try {
    const models = await request("/v1/models");
    $("#model-count").textContent =
      `${models.filter((model) => model.available).length} of ${models.length} available`;
    $("#model-list").replaceChildren(
      ...models.map((model) => {
        const card = node("div", "model-tile");
        card.append(
          node("h3", "", modelNames[model.key] || model.key),
          node("p", "", model.repo_id),
          node(
            "small",
            model.available ? "" : "unavailable",
            model.loaded
              ? "● In use"
              : model.available
                ? "● Ready when you are"
                : "○ Unavailable",
          ),
        );
        return card;
      }),
    );
  } catch {
    $("#model-count").textContent = "Models unavailable";
  }
}
async function loadHealth() {
  try {
    await request("/health/ready");
    $("#health-status").className = "status ready";
    $("#health-status").replaceChildren(
      node("i"),
      document.createTextNode("All systems ready"),
    );
  } catch {
    $("#health-status").className = "status unavailable";
    $("#health-status").replaceChildren(
      node("i"),
      document.createTextNode("Services unavailable"),
    );
  }
}
function updateNavigation() {
  document
    .querySelectorAll(".nav-link")
    .forEach((link) =>
      link.classList.toggle(
        "active",
        link.hash === (location.hash || "#studio"),
      ),
    );
}
window.addEventListener("hashchange", updateNavigation);
updateNavigation();
loadHealth();
loadModels();
loadLibrary();
setInterval(loadHealth, 30000);
