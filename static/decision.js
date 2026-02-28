const $ = (id) => document.getElementById(id);

let options = [];
let criteria = [];
let optionsSubmitted = false;
let criteriaSubmitted = false;

let modalMode = null; // "option" | "criteria"

function showToast(msg){
  $("toastText").textContent = msg;
  $("toast").style.display = "flex";
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => $("toast").style.display = "none", 1200);
}

function openModal(mode){
  modalMode = mode;
  $("modalTitle").textContent = mode === "option" ? "Add Option" : "Add Criterion";
  $("modalDesc").textContent = "Choose how you want to add.";
  $("modalBackdrop").style.display = "flex";
}

function closeModal(){
  $("modalBackdrop").style.display = "none";
}

function escapeHtml(str){
  return (str || "")
    .replaceAll("&","&amp;")
    .replaceAll("<","&lt;")
    .replaceAll(">","&gt;");
}

function renderPills(){
  $("optionsPills").innerHTML = options.map((t, idx) => `
    <div class="pill">
      ${escapeHtml(t)}
      <span class="x" data-type="option" data-idx="${idx}">×</span>
    </div>
  `).join("");

  $("criteriaPills").innerHTML = criteria.map((t, idx) => `
    <div class="pill">
      ${escapeHtml(t)}
      <span class="x" data-type="criteria" data-idx="${idx}">×</span>
    </div>
  `).join("");
}

function addManualItem(mode, value){
  const v = (value || "").trim();
  if(!v) return;

  if(mode === "option"){
    options.push(v);
    $("optionManualInput").value = "";
    $("optionManualInputWrap").style.display = "none";
    optionsSubmitted = false;
    $("optionsStatus").textContent = "Options updated (not submitted yet).";
  } else {
    criteria.push(v);
    $("criteriaManualInput").value = "";
    $("criteriaManualInputWrap").style.display = "none";
    criteriaSubmitted = false;
    $("criteriaStatus").textContent = "Criteria updated (not submitted yet).";
  }
  renderPills();
}

function addSystemSuggestions(mode){
  if(mode === "option"){
    const samples = ["Option A", "Option B", "Option C"];
    samples.forEach(s => options.push(s));
    optionsSubmitted = false;
    $("optionsStatus").textContent = "System suggested options added (prototype).";
  } else {
    const samples = ["Cost", "Performance", "Convenience"];
    samples.forEach(s => criteria.push(s));
    criteriaSubmitted = false;
    $("criteriaStatus").textContent = "System suggested criteria added (prototype).";
  }
  renderPills();
}

document.addEventListener("DOMContentLoaded", () => {
  // Decision lock
  $("lockDecisionBtn").addEventListener("click", () => {
    const text = $("decisionInput").value.trim();
    if(!text){
      showToast("Type a decision first");
      return;
    }

    $("decisionLockedText").innerHTML = `
      ${escapeHtml(text)}
      <button class="copyBtn" id="copyDecisionBtn" title="Copy">⧉</button>
    `;

    $("decisionInputWrap").style.display = "none";
    $("decisionLockedWrap").style.display = "block";

    setTimeout(() => {
      const btn = $("copyDecisionBtn");
      if(btn){
        btn.addEventListener("click", async (e) => {
          e.stopPropagation();
          try{
            await navigator.clipboard.writeText(text);
            showToast("Decision copied to clipboard");
          }catch{
            showToast("Copy failed");
          }
        });
      }
    }, 0);
  });

  // Modal open buttons
  $("addOptionBtn").addEventListener("click", () => openModal("option"));
  $("plusAddOptionBtn").addEventListener("click", () => openModal("option"));
  $("addCriteriaBtn").addEventListener("click", () => openModal("criteria"));
  $("plusAddCriteriaBtn").addEventListener("click", () => openModal("criteria"));

  // Modal choices
  $("chooseManual").addEventListener("click", () => {
    closeModal();
    if(modalMode === "option"){
      $("optionManualInputWrap").style.display = "block";
      $("optionManualInput").focus();
    } else {
      $("criteriaManualInputWrap").style.display = "block";
      $("criteriaManualInput").focus();
    }
  });

  $("chooseSystem").addEventListener("click", () => {
    closeModal();
    addSystemSuggestions(modalMode);
  });

  $("closeModalBtn").addEventListener("click", closeModal);
  $("modalBackdrop").addEventListener("click", (e) => {
    if(e.target === $("modalBackdrop")) closeModal();
  });

  // Manual add confirm
  $("optionAddConfirmBtn").addEventListener("click", () => addManualItem("option", $("optionManualInput").value));
  $("criteriaAddConfirmBtn").addEventListener("click", () => addManualItem("criteria", $("criteriaManualInput").value));

  // Enter key support
  $("optionManualInput").addEventListener("keydown", (e) => {
    if(e.key === "Enter"){
      e.preventDefault();
      addManualItem("option", $("optionManualInput").value);
    }
  });

  $("criteriaManualInput").addEventListener("keydown", (e) => {
    if(e.key === "Enter"){
      e.preventDefault();
      addManualItem("criteria", $("criteriaManualInput").value);
    }
  });

  // Delete pills
  document.addEventListener("click", (e) => {
    const x = e.target;
    if(x && x.classList && x.classList.contains("x")){
      const type = x.getAttribute("data-type");
      const idx = Number(x.getAttribute("data-idx"));
      if(type === "option"){
        options.splice(idx, 1);
        optionsSubmitted = false;
        $("optionsStatus").textContent = "Options updated (not submitted yet).";
      } else {
        criteria.splice(idx, 1);
        criteriaSubmitted = false;
        $("criteriaStatus").textContent = "Criteria updated (not submitted yet).";
      }
      renderPills();
    }
  });

  // Submit buttons
  $("submitOptionsBtn").addEventListener("click", () => {
    if(options.length < 1){
      showToast("Add at least 1 option");
      return;
    }
    optionsSubmitted = true;
    $("optionsStatus").textContent = `Options submitted ✅ (${options.length})`;
    showToast("Options submitted ✅");
  });

  $("submitCriteriaBtn").addEventListener("click", () => {
    if(criteria.length < 1){
      showToast("Add at least 1 criterion");
      return;
    }
    criteriaSubmitted = true;
    $("criteriaStatus").textContent = `Criteria submitted ✅ (${criteria.length})`;
    showToast("Criteria submitted ✅");
  });

  // Final submit (SAVES TO BACKEND)
  $("finalSubmitBtn").addEventListener("click", async () => {
    if ($("decisionLockedWrap").style.display === "none") {
      showToast("Lock the decision first");
      return;
    }
    if (!optionsSubmitted) {
      showToast("Submit options first");
      return;
    }
    if (!criteriaSubmitted) {
      showToast("Submit criteria first");
      return;
    }

    const question = $("decisionLockedText").textContent.replace("⧉", "").trim();
    const payload = { question, options, criteria };

    try {
      const res = await fetch("/decision/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const out = await res.json();

      if (!res.ok || !out.ok) {
        showToast(out.error || "Submit failed");
        return;
      }

      showToast("Saved ✅");
      $("finalHint").textContent = `Saved ✅ Decision ID: ${out.decision_id}`;
    } catch (err) {
      showToast("Network error");
    }
  });

  renderPills();
});