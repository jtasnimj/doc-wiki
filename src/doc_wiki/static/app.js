"use strict";
const $ = (id) => document.getElementById(id);
let busy = false;
let lastResponse = null;
const emptyResults = $("results").firstElementChild.cloneNode(true);
const statusLabels = {answered: "Answered", partial: "Partial answer", not_found: "Not found", error: "Error"};

function controls() {
  $("batch").disabled = busy || !$("document").files.length || !$("questions").files.length;
  $("batch").textContent = busy ? "Answering…" : "Answer questions ↗";
  $("export").disabled = busy || !lastResponse;
  $("qa-form").setAttribute("aria-busy", String(busy));
  for (const id of ["document", "questions"]) $(id).disabled = busy;
}

function warnings(items) {
  $("warnings").replaceChildren();
  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = item;
    $("warnings").append(li);
  }
  $("warnings").hidden = !items.length;
}

function clearResults() {
  lastResponse = null;
  $("results").replaceChildren(emptyResults.cloneNode(true));
  $("result-summary").hidden = true;
  $("progress").textContent = "";
  $("error").hidden = true;
  warnings([]);
  controls();
}

function renderCitations(parent, citations) {
  for (const [index, source] of citations.entries()) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    const locations = source.locations.map(loc => loc.page ? `PDF page ${loc.page}` : `JSON ${loc.json_path}`).join(", ");
    summary.textContent = `Source ${index + 1} · ${locations}${source.derived ? " · Derived visual description" : ""}`;
    const excerpt = document.createElement("pre");
    excerpt.textContent = source.excerpt;
    details.append(summary, excerpt);
    parent.append(details);
  }
}

function render(data) {
  lastResponse = data;
  warnings(data.warnings || []);
  $("results").replaceChildren();
  const batchLabels = {completed: "Completed", partial_failure: "Some questions could not be answered", failed: "All questions failed"};
  $("result-summary").textContent = `${data.results.length} ${data.results.length === 1 ? "question" : "questions"} · ${batchLabels[data.batch_status]}`;
  $("result-summary").hidden = false;
  for (const [index, item] of data.results.entries()) {
    const article = document.createElement("article");
    article.className = "result";
    const top = document.createElement("div");
    top.className = "result-heading";
    const number = document.createElement("span");
    number.className = "question-number";
    number.textContent = `Question ${index + 1} · ${item.id}`;
    const badge = document.createElement("span");
    badge.className = "badge";
    if (Object.hasOwn(statusLabels, item.status)) badge.classList.add(item.status);
    badge.textContent = statusLabels[item.status] || item.status;
    top.append(number, badge);
    const heading = document.createElement("h3");
    heading.textContent = item.question;
    const answer = document.createElement("p");
    answer.className = "answer";
    answer.textContent = item.answer ?? item.error?.message ?? "Unable to answer.";
    article.append(top, heading, answer);
    renderCitations(article, item.citations);
    if (item.related_information?.length) {
      const section = document.createElement("section");
      section.className = "related-information";
      const title = document.createElement("h4");
      title.textContent = "Related information";
      const note = document.createElement("p");
      note.className = "hint";
      note.textContent = "These facts do not establish the requested answer.";
      section.append(title, note);
      for (const related of item.related_information) {
        const fact = document.createElement("div");
        const text = document.createElement("p");
        text.className = "answer";
        text.textContent = related.text;
        fact.append(text);
        renderCitations(fact, related.citations);
        section.append(fact);
      }
      article.append(section);
    }
    $("results").append(article);
  }
}

for (const id of ["document", "questions"]) $(id).addEventListener("change", clearResults);

$("qa-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy || !$("document").files.length || !$("questions").files.length) return;
  clearResults();
  busy = true;
  $("progress").textContent = "Reading the document and answering your questions…";
  controls();
  try {
    const form = new FormData();
    form.append("document_file", $("document").files[0]);
    form.append("questions_file", $("questions").files[0]);
    const response = await fetch("/api/qa", {method: "POST", body: form});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || `Request failed (${response.status}).`);
    render(data);
    $("progress").textContent = "Complete.";
  } catch (error) {
    $("progress").textContent = "";
    $("error").textContent = error.message;
    $("error").hidden = false;
  } finally {
    busy = false;
    controls();
  }
});

$("export").addEventListener("click", () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(lastResponse, null, 2)], {type: "application/json"}));
  const link = document.createElement("a");
  link.href = url;
  link.download = "doc-wiki-answers.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
controls();
