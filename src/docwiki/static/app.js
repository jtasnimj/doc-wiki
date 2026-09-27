"use strict";
const $ = (id) => document.getElementById(id);
let documentId = null;
let busy = false;
let lastResponse = null;

function controls() {
  $("upload").disabled = busy || !$("document").files.length;
  $("batch").disabled = busy || !$("document").files.length || !$("questions").files.length;
  $("ask").disabled = busy || !documentId || !$("question").value.trim();
  $("export").disabled = busy || !lastResponse;
  for (const id of ["document", "questions", "question"]) $(id).disabled = busy;
}
function warnings(items) {
  $("warnings").replaceChildren();
  for (const item of items) {
    const li = document.createElement("li"); li.textContent = item; $("warnings").append(li);
  }
  $("warnings").hidden = !items.length;
}
function render(data) {
  lastResponse = data;
  warnings(data.warnings || []);
  $("results").replaceChildren();
  for (const item of data.results) {
    const article = document.createElement("article"); article.className = "result";
    const badge = document.createElement("span"); badge.className = "badge";
    if (["answered", "partial", "not_found", "error"].includes(item.status)) badge.classList.add(item.status);
    badge.textContent = item.status.replaceAll("_", " ");
    const heading = document.createElement("h3"); heading.textContent = item.question;
    const answer = document.createElement("p"); answer.textContent = item.answer ?? item.error?.message ?? "Unable to answer.";
    article.append(badge, heading, answer);
    for (const source of item.citations) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      const locations = source.locations.map(loc => loc.page ? `PDF page ${loc.page}` : `JSON ${loc.json_path}`).join(", ");
      summary.textContent = `${locations}${source.derived ? " · Derived visual description" : " · Source excerpt"}`;
      const excerpt = document.createElement("pre"); excerpt.textContent = source.excerpt;
      details.append(summary, excerpt); article.append(details);
    }
    $("results").append(article);
  }
}
async function run(message, action) {
  busy = true; $("progress").textContent = message; $("error").hidden = true; controls();
  try { await action(); $("progress").textContent = "Complete."; }
  catch (error) { $("progress").textContent = ""; $("error").textContent = error.message; $("error").hidden = false; }
  finally { busy = false; controls(); }
}
async function api(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || `Request failed (${response.status}).`);
  return data;
}
$("document").addEventListener("change", () => {
  documentId = null; $("document-status").textContent = "Prepare this document or submit it with your questions."; controls();
});
$("questions").addEventListener("change", controls);
$("question").addEventListener("input", controls);
$("upload").addEventListener("click", () => run("Preparing document and its search index…", async () => {
  const form = new FormData(); form.append("document_file", $("document").files[0]);
  const data = await api("/api/documents", {method: "POST", body: form});
  documentId = data.document_id;
  $("document-status").textContent = `Ready · ${data.page_count ? data.page_count + " pages · " : ""}${data.chunk_count} passages${data.cache_hit ? " · Reused index" : ""}`;
  warnings(data.warnings);
}));
$("batch").addEventListener("click", () => run("Reading the document and answering your questions…", async () => {
  const form = new FormData(); form.append("document_file", $("document").files[0]); form.append("questions_file", $("questions").files[0]);
  const data = await api("/api/qa", {method: "POST", body: form});
  documentId = data.document_id; $("document-status").textContent = "Ready for more questions."; render(data);
}));
$("ask").addEventListener("click", () => run("Finding evidence for your question…", async () => {
  const data = await api(`/api/documents/${encodeURIComponent(documentId)}/questions`, {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({questions: [$("question").value]})
  });
  render(data);
}));
$("export").addEventListener("click", () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(lastResponse, null, 2)], {type: "application/json"}));
  const link = document.createElement("a"); link.href = url; link.download = "docwiki-answers.json"; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
controls();
