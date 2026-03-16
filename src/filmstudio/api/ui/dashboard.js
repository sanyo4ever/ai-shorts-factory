const state = {
  presetCatalog: null,
  quickStartCatalog: null,
  overviews: [],
  queue: null,
  campaignOverview: null,
  campaigns: [],
  selectedCampaignName: null,
  campaignDetails: new Map(),
  selectedProjectId: null,
  selectedTarget: null,
  projectDetails: new Map(),
  campaignReleaseNoteDirty: false,
  campaignReleaseNoteKey: null,
  statusTimer: null,
};

const elements = {};

document.addEventListener("DOMContentLoaded", () => {
  cacheElements();
  bindEvents();
  refreshStudio({ forceProjectRefresh: true }).catch(handleError);
});

function cacheElements() {
  const byId = (id) => document.getElementById(id);
  elements.refreshButton = byId("refresh-button");
  elements.projectCountBadge = byId("project-count-badge");
  elements.queueCountBadge = byId("queue-count-badge");
  elements.campaignCountBadge = byId("campaign-count-badge");
  elements.globalMetrics = byId("global-metrics");
  elements.campaignSummary = byId("campaign-summary");
  elements.campaignList = byId("campaign-list");
  elements.campaignSelectionHint = byId("campaign-selection-hint");
  elements.campaignEmpty = byId("campaign-empty");
  elements.campaignDetail = byId("campaign-detail");
  elements.campaignHero = byId("campaign-hero");
  elements.campaignReleaseSummary = byId("campaign-release-summary");
  elements.campaignCompareTarget = byId("campaign-compare-target");
  elements.campaignReleaseNote = byId("campaign-release-note");
  elements.campaignReleaseBlockers = byId("campaign-release-blockers");
  elements.campaignMarkCandidateButton = byId("campaign-mark-candidate-button");
  elements.campaignMarkCanonicalButton = byId("campaign-mark-canonical-button");
  elements.campaignMarkSupersededButton = byId("campaign-mark-superseded-button");
  elements.campaignComparison = byId("campaign-comparison");
  elements.campaignReleaseDesk = byId("campaign-release-desk");
  elements.campaignReleaseHandoff = byId("campaign-release-handoff");
  elements.campaignCases = byId("campaign-cases");
  elements.queueSummary = byId("queue-summary");
  elements.queueList = byId("queue-list");
  elements.projectList = byId("project-list");
  elements.selectionHint = byId("selection-hint");
  elements.projectEmpty = byId("project-empty");
  elements.projectDetail = byId("project-detail");
  elements.projectHero = byId("project-hero");
  elements.videoPreview = byId("video-preview");
  elements.semanticQuality = byId("semantic-quality");
  elements.deliverablesList = byId("deliverables-list");
  elements.reviewSummary = byId("review-summary");
  elements.reviewScenes = byId("review-scenes");
  elements.reviewModeSelect = byId("review-mode-select");
  elements.reviewWorkspaceSummary = byId("review-workspace-summary");
  elements.reviewFocus = byId("review-focus");
  elements.reviewerInput = byId("reviewer-input");
  elements.reviewReasonCode = byId("review-reason-code");
  elements.reviewNoteInput = byId("review-note-input");
  elements.reviewCompareTarget = byId("review-compare-target");
  elements.reviewComparePanel = byId("review-compare-panel");
  elements.rerenderStageSelect = byId("rerender-stage-select");
  elements.approveFocusButton = byId("approve-focus-button");
  elements.markRerenderButton = byId("mark-rerender-button");
  elements.rerenderFocusButton = byId("rerender-focus-button");
  elements.runProjectButton = byId("run-project-button");
  elements.refreshProjectButton = byId("refresh-project-button");
  elements.quickGenerateForm = byId("quick-generate-form");
  elements.quickExampleSelect = byId("quick-example-select");
  elements.quickStackProfile = byId("quick-stack-profile");
  elements.quickTitle = byId("quick-title");
  elements.quickCharacters = byId("quick-characters");
  elements.quickLanguage = byId("quick-language");
  elements.quickDuration = byId("quick-duration");
  elements.quickPrompt = byId("quick-prompt");
  elements.quickRunImmediately = byId("quick-run-immediately");
  elements.quickProfilePreview = byId("quick-profile-preview");
  elements.createProjectForm = byId("create-project-form");
  elements.createTitle = byId("create-title");
  elements.createLanguage = byId("create-language");
  elements.createScript = byId("create-script");
  elements.createStylePreset = byId("create-style-preset");
  elements.createVoiceCastPreset = byId("create-voice-cast-preset");
  elements.createMusicPreset = byId("create-music-preset");
  elements.createShortArchetype = byId("create-short-archetype");
  elements.createRunImmediately = byId("create-run-immediately");
  elements.presetPreview = byId("preset-preview");
  elements.statusBanner = byId("status-banner");
}

function bindEvents() {
  elements.refreshButton.addEventListener("click", () => {
    refreshStudio({ forceProjectRefresh: true }).catch(handleError);
  });
  elements.refreshProjectButton.addEventListener("click", () => {
    if (!state.selectedProjectId) {
      return;
    }
    loadProjectDetail(state.selectedProjectId, { force: true }).catch(handleError);
  });
  elements.runProjectButton.addEventListener("click", () => {
    if (!state.selectedProjectId) {
      return;
    }
    runProject(state.selectedProjectId).catch(handleError);
  });
  elements.quickGenerateForm.addEventListener("submit", (event) => {
    event.preventDefault();
    quickGenerateProjectFromForm().catch(handleError);
  });
  elements.quickExampleSelect.addEventListener("change", applyQuickExampleSelection);
  elements.quickStackProfile.addEventListener("change", renderQuickProfilePreview);
  elements.campaignList.addEventListener("click", (event) => {
    const campaignButton = event.target.closest("[data-campaign-name]");
    if (!campaignButton) {
      return;
    }
    selectCampaign(campaignButton.dataset.campaignName).catch(handleError);
  });
  elements.campaignCompareTarget.addEventListener("change", () => {
    if (!state.selectedCampaignName) {
      return;
    }
    loadCampaignDetail(state.selectedCampaignName, {
      force: true,
      compareTo: elements.campaignCompareTarget.value || null,
    }).catch(handleError);
  });
  elements.campaignReleaseNote.addEventListener("input", () => {
    state.campaignReleaseNoteDirty = true;
  });
  elements.campaignMarkCandidateButton.addEventListener("click", () => {
    updateCampaignReleaseStatus("candidate").catch(handleError);
  });
  elements.campaignMarkCanonicalButton.addEventListener("click", () => {
    updateCampaignReleaseStatus("canonical").catch(handleError);
  });
  elements.campaignMarkSupersededButton.addEventListener("click", () => {
    updateCampaignReleaseStatus("superseded").catch(handleError);
  });
  elements.approveFocusButton.addEventListener("click", () => {
    applyFocusedReview({ status: "approved" }).catch(handleError);
  });
  elements.markRerenderButton.addEventListener("click", () => {
    applyFocusedReview({ status: "needs_rerender" }).catch(handleError);
  });
  elements.rerenderFocusButton.addEventListener("click", () => {
    applyFocusedReview({
      status: "needs_rerender",
      requestRerender: true,
      runImmediately: true,
    }).catch(handleError);
  });
  elements.projectList.addEventListener("click", (event) => {
    const projectCard = event.target.closest("[data-project-id]");
    if (!projectCard) {
      return;
    }
    selectProject(projectCard.dataset.projectId).catch(handleError);
  });
  elements.queueList.addEventListener("click", (event) => {
    const queueButton = event.target.closest("[data-queue-project-id]");
    if (!queueButton) {
      return;
    }
    const targetKind = queueButton.dataset.targetKind || null;
    const targetId = queueButton.dataset.targetId || null;
    selectProject(
      queueButton.dataset.queueProjectId,
      targetKind && targetId ? { kind: targetKind, id: targetId, sceneId: queueButton.dataset.sceneId || null } : null,
    ).catch(handleError);
  });
  elements.reviewScenes.addEventListener("click", (event) => {
    const focusButton = event.target.closest("[data-review-focus-kind]");
    if (!focusButton) {
      return;
    }
    setFocusedTarget({
      kind: focusButton.dataset.reviewFocusKind,
      id: focusButton.dataset.reviewFocusId,
      sceneId: focusButton.dataset.reviewSceneId || null,
      title: focusButton.dataset.reviewTitle || null,
    }).catch(handleError);
  });
  elements.reviewCompareTarget.addEventListener("change", () => {
    if (!state.selectedProjectId || !state.selectedTarget) {
      return;
    }
    loadFocusedCompare(state.selectedProjectId, { force: true }).catch(handleError);
  });
  elements.reviewModeSelect.addEventListener("change", () => {
    if (!state.selectedProjectId) {
      return;
    }
    const detail = getSelectedDetail();
    if (!detail) {
      return;
    }
    primeFocusedTarget(detail.review);
    renderReviewWorkspaceSummary(detail.review);
    renderReviewFocus(detail.review);
    renderReviewScenes(detail.review);
    loadFocusedCompare(state.selectedProjectId, { force: true }).catch(handleError);
  });
  elements.createProjectForm.addEventListener("submit", (event) => {
    event.preventDefault();
    createProjectFromForm().catch(handleError);
  });
  [
    elements.createStylePreset,
    elements.createVoiceCastPreset,
    elements.createMusicPreset,
    elements.createShortArchetype,
  ].forEach((select) => {
    select.addEventListener("change", renderPresetPreview);
  });
}

async function refreshStudio({ forceProjectRefresh = false } = {}) {
  setStatus("Syncing studio state...", "info");
  const [presetCatalog, quickStartCatalog, overviews, queue, campaignOverview, campaigns] = await Promise.all([
    fetchJson("/api/v1/projects/preset-catalog"),
    fetchJson("/api/v1/projects/quick-start"),
    fetchJson("/api/v1/projects/overviews"),
    fetchJson("/api/v1/projects/operator-queue"),
    fetchJson("/api/v1/campaigns/overview"),
    fetchJson("/api/v1/campaigns?limit=8"),
  ]);
  state.presetCatalog = presetCatalog;
  state.quickStartCatalog = quickStartCatalog;
  state.overviews = Array.isArray(overviews) ? overviews : [];
  state.queue = queue || { summary: {}, items: [] };
  state.campaignOverview = campaignOverview || { summary: {}, highlights: {}, campaigns: [] };
  state.campaigns = Array.isArray(campaigns) ? campaigns : [];
  populatePresetForm();
  populateQuickGenerateForm();
  chooseCampaignSelection();
  chooseProjectSelection();
  renderChrome();
  if (state.selectedCampaignName) {
    await loadCampaignDetail(state.selectedCampaignName, { force: forceProjectRefresh });
  } else {
    renderCampaignDetail();
  }
  if (state.selectedProjectId) {
    await loadProjectDetail(state.selectedProjectId, { force: forceProjectRefresh });
  } else {
    renderProjectDetail();
  }
  setStatus("Studio state is current.", "success", 1800);
}

function populatePresetForm() {
  if (!state.presetCatalog) {
    return;
  }
  const defaults = state.presetCatalog.defaults || {};
  populateSelect(elements.createStylePreset, state.presetCatalog.style_presets, defaults.style_preset);
  populateSelect(
    elements.createVoiceCastPreset,
    state.presetCatalog.voice_cast_presets,
    defaults.voice_cast_preset,
  );
  populateSelect(elements.createMusicPreset, state.presetCatalog.music_presets, defaults.music_preset);
  populateSelect(
    elements.createShortArchetype,
    state.presetCatalog.short_archetypes,
    defaults.short_archetype,
  );
  renderPresetPreview();
}

function populateQuickGenerateForm() {
  if (!state.quickStartCatalog) {
    elements.quickProfilePreview.innerHTML = `<div class="muted-copy">Quick generate catalog not loaded yet.</div>`;
    return;
  }
  const defaults = state.quickStartCatalog.defaults || {};
  const examples = Array.isArray(state.quickStartCatalog.examples) ? state.quickStartCatalog.examples : [];
  const profiles = state.quickStartCatalog.profiles || {};
  const currentExample = elements.quickExampleSelect.value || defaults.example_slug || "";
  const currentProfile = elements.quickStackProfile.value || defaults.stack_profile || "production_vertical";

  elements.quickExampleSelect.innerHTML = [
    `<option value="">Custom idea</option>`,
    ...examples.map((example) => {
      const selected = example.slug === currentExample ? " selected" : "";
      return `<option value="${escapeHtml(example.slug)}"${selected}>${escapeHtml(example.title)}</option>`;
    }),
  ].join("");
  elements.quickStackProfile.innerHTML = Object.entries(profiles)
    .map(([key, profile]) => {
      const selected = key === currentProfile ? " selected" : "";
      return `<option value="${escapeHtml(key)}"${selected}>${escapeHtml(profile.label || key)}</option>`;
    })
    .join("");
  if (!elements.quickLanguage.value) {
    elements.quickLanguage.value = defaults.language || "uk";
  }
  if (!elements.quickDuration.value) {
    elements.quickDuration.value = String(defaults.target_duration_sec || 8);
  }
  elements.quickRunImmediately.checked = Boolean(defaults.run_immediately ?? true);
  if (!elements.quickPrompt.value.trim() && !elements.quickTitle.value.trim()) {
    applyQuickExampleSelection();
  } else {
    renderQuickProfilePreview();
  }
}

function applyQuickExampleSelection() {
  const catalog = state.quickStartCatalog || {};
  const examples = Array.isArray(catalog.examples) ? catalog.examples : [];
  const example = examples.find((entry) => entry.slug === elements.quickExampleSelect.value) || null;
  if (!example) {
    renderQuickProfilePreview();
    return;
  }
  elements.quickTitle.value = example.title || "";
  elements.quickCharacters.value = Array.isArray(example.character_names)
    ? example.character_names.join(", ")
    : "";
  elements.quickLanguage.value = example.language || elements.quickLanguage.value || "uk";
  elements.quickDuration.value = String(example.target_duration_sec || elements.quickDuration.value || 8);
  elements.quickPrompt.value = example.prompt || "";
  if (example.stack_profile) {
    elements.quickStackProfile.value = example.stack_profile;
  }
  renderQuickProfilePreview();
}

function renderQuickProfilePreview() {
  if (!state.quickStartCatalog) {
    elements.quickProfilePreview.innerHTML = `<div class="muted-copy">Quick generate catalog not loaded yet.</div>`;
    return;
  }
  const profiles = state.quickStartCatalog.profiles || {};
  const examples = Array.isArray(state.quickStartCatalog.examples) ? state.quickStartCatalog.examples : [];
  const profileKey =
    elements.quickStackProfile.value ||
    state.quickStartCatalog.defaults?.stack_profile ||
    "production_vertical";
  const profile = profiles[profileKey] || {};
  const example = examples.find((entry) => entry.slug === elements.quickExampleSelect.value) || null;
  const backendProfile = profile.backend_profile || {};
  const exampleSummary = example
    ? `
      <article class="preset-card">
        <p class="eyebrow">Example</p>
        <h3>${escapeHtml(example.title || example.slug || "Quick example")}</h3>
        <p>${escapeHtml(example.description || "Curated starter scenario.")}</p>
      </article>
    `
    : "";
  elements.quickProfilePreview.innerHTML = `
    ${exampleSummary}
    <article class="preset-card">
      <p class="eyebrow">Stack</p>
      <h3>${escapeHtml(profile.label || profileKey)}</h3>
      <p>${escapeHtml(profile.description || "")}</p>
      <p class="muted-copy">
        visual ${escapeHtml(backendProfile.visual_backend || "deterministic")} ·
        video ${escapeHtml(backendProfile.video_backend || "deterministic")} ·
        tts ${escapeHtml(backendProfile.tts_backend || "deterministic")} ·
        music ${escapeHtml(backendProfile.music_backend || "deterministic")} ·
        lipsync ${escapeHtml(backendProfile.lipsync_backend || "deterministic")}
      </p>
    </article>
  `;
}

function populateSelect(select, catalog, selectedKey) {
  const currentValue = select.value || selectedKey;
  const entries = Object.entries(catalog || {});
  select.innerHTML = entries
    .map(([key, value]) => {
      const label = escapeHtml(String(value.label || key));
      const selected = key === currentValue ? " selected" : "";
      return `<option value="${escapeHtml(key)}"${selected}>${label}</option>`;
    })
    .join("");
  if (!select.value && selectedKey) {
    select.value = selectedKey;
  }
}

function chooseProjectSelection() {
  const knownIds = new Set(state.overviews.map((overview) => overview.project_id));
  if (state.selectedProjectId && knownIds.has(state.selectedProjectId)) {
    return;
  }
  state.selectedProjectId = state.overviews[0]?.project_id || null;
  state.selectedTarget = null;
}

function chooseCampaignSelection() {
  const knownNames = new Set(state.campaigns.map((campaign) => campaign.campaign_name));
  if (state.selectedCampaignName && knownNames.has(state.selectedCampaignName)) {
    return;
  }
  const currentCanonical =
    state.campaignOverview?.release_management?.current_canonical?.campaign_name || null;
  state.selectedCampaignName =
    (currentCanonical && knownNames.has(currentCanonical) ? currentCanonical : null) ||
    state.campaigns[0]?.campaign_name ||
    null;
}

async function loadCampaignDetail(campaignName, { force = false, compareTo = null } = {}) {
  if (!campaignName) {
    renderCampaignDetail();
    return;
  }
  const cacheKey = `${campaignName}::${compareTo || ""}`;
  if (!force && state.campaignDetails.has(cacheKey)) {
    renderCampaignDetail();
    return;
  }
  setStatus(`Loading campaign ${campaignName}...`, "info");
  const query = compareTo ? `?compare_to=${encodeURIComponent(compareTo)}` : "";
  const detail = await fetchJson(`/api/v1/campaigns/${encodeURIComponent(campaignName)}${query}`);
  detail.selected_compare_target =
    compareTo || detail.comparison?.right?.campaign_name || detail.summary?.release?.compared_to || "";
  state.campaignDetails.set(cacheKey, detail);
  state.campaignDetails.set(campaignName, detail);
  renderChrome();
  renderCampaignDetail();
}

async function selectCampaign(campaignName) {
  if (state.selectedCampaignName !== campaignName) {
    state.campaignReleaseNoteDirty = false;
    state.campaignReleaseNoteKey = null;
  }
  state.selectedCampaignName = campaignName;
  renderChrome();
  await loadCampaignDetail(campaignName, { force: false });
}

async function loadProjectDetail(projectId, { force = false } = {}) {
  if (!projectId) {
    renderProjectDetail();
    return;
  }
  if (!force && state.projectDetails.has(projectId)) {
    renderProjectDetail();
    return;
  }
  setStatus(`Loading project ${projectId}...`, "info");
  const [overview, review, deliverables] = await Promise.all([
    fetchJson(`/api/v1/projects/${projectId}/overview`),
    fetchJson(`/api/v1/projects/${projectId}/review`),
    fetchJson(`/api/v1/projects/${projectId}/deliverables`),
  ]);
  state.projectDetails.set(projectId, { overview, review, deliverables, reviewCompare: null });
  primeFocusedTarget(review);
  await loadFocusedCompare(projectId, { force: true });
  renderChrome();
  renderProjectDetail();
}

function primeFocusedTarget(review) {
  const resolved = resolveFocusedTarget(review);
  if (!resolved) {
    state.selectedTarget = null;
    return;
  }
  state.selectedTarget = {
    kind: resolved.kind,
    id: resolved.id,
    sceneId: resolved.sceneId || null,
    title: resolved.title || null,
  };
}

function getReviewWorkspace(review) {
  return review?.workspace || {};
}

function getSemanticRegressionWorkspace(review) {
  return getReviewWorkspace(review).semantic_regression || {};
}

function effectiveReviewMode(review) {
  const requested = elements.reviewModeSelect?.value || "auto";
  if (requested !== "auto") {
    return requested;
  }
  return getReviewWorkspace(review).default_mode || "all_targets";
}

function isSemanticRegressionScene(review, scene) {
  const semantic = getSemanticRegressionWorkspace(review);
  return new Set(semantic.changed_scene_ids || []).has(scene.scene_id);
}

function isSemanticRegressionShot(review, shot) {
  const semantic = getSemanticRegressionWorkspace(review);
  return new Set(semantic.changed_shot_ids || []).has(shot.shot_id);
}

function defaultReviewCompareTarget(target) {
  return target?.kind === "scene" ? "approved" : "previous";
}

function allowedReviewCompareTargets(target) {
  return target?.kind === "scene"
    ? ["approved", "current"]
    : ["previous", "approved", "current"];
}

function normalizeReviewCompareTarget(target, selector) {
  const allowed = allowedReviewCompareTargets(target);
  return allowed.includes(selector) ? selector : defaultReviewCompareTarget(target);
}

function syncReviewCompareTargetOptions(target, selectedValue = null) {
  const allowed = allowedReviewCompareTargets(target);
  const labels = {
    previous: "previous revision",
    approved: "approved revision",
    current: "current revision",
  };
  elements.reviewCompareTarget.innerHTML = allowed
    .map((value) => {
      const selected = value === selectedValue ? " selected" : "";
      return `<option value="${escapeHtml(value)}"${selected}>${escapeHtml(labels[value] || value)}</option>`;
    })
    .join("");
  elements.reviewCompareTarget.value = normalizeReviewCompareTarget(target, selectedValue || allowed[0]);
}

async function loadFocusedCompare(projectId, { force = false } = {}) {
  const target = state.selectedTarget;
  const detail = state.projectDetails.get(projectId);
  if (!detail || !target) {
    renderReviewCompare(null);
    return;
  }
  const right = normalizeReviewCompareTarget(target, elements.reviewCompareTarget?.value || "");
  syncReviewCompareTargetOptions(target, right);
  const cacheKey = `${target.kind}:${target.id}:${right}`;
  if (!force && detail.reviewCompare?.cacheKey === cacheKey) {
    renderReviewCompare(detail.reviewCompare.payload);
    return;
  }
  const baseUrl =
    target.kind === "shot"
      ? `/api/v1/projects/${projectId}/shots/${target.id}/compare`
      : `/api/v1/projects/${projectId}/scenes/${target.id}/compare`;
  const payload = await fetchJson(`${baseUrl}?left=current&right=${encodeURIComponent(right)}`);
  detail.reviewCompare = { cacheKey, payload };
  state.projectDetails.set(projectId, detail);
  renderReviewCompare(payload);
}

async function selectProject(projectId, target = null) {
  const projectChanged = state.selectedProjectId !== projectId;
  state.selectedProjectId = projectId;
  if (target) {
    state.selectedTarget = target;
  } else if (projectChanged) {
    state.selectedTarget = null;
  }
  if (projectChanged && elements.reviewModeSelect) {
    elements.reviewModeSelect.value = "auto";
  }
  renderChrome();
  await loadProjectDetail(projectId, { force: false });
}

function renderChrome() {
  renderGlobalMetrics();
  renderCampaignCenter();
  renderCampaignDetail();
  renderQueue();
  renderProjectList();
  renderPresetPreview();
  renderQuickProfilePreview();
}

function renderGlobalMetrics() {
  const summary = state.queue?.summary || {};
  const metrics = [
    { label: "Needs Attention", value: summary.projects_needing_attention || 0 },
    { label: "Queue Items", value: summary.queue_item_count || 0 },
    { label: "Deliverables Ready", value: summary.deliverables_ready_project_count || 0 },
    { label: "Quality Gate Fails", value: summary.quality_gate_failed_project_count || 0 },
  ];
  elements.projectCountBadge.textContent = `${state.overviews.length} projects`;
  elements.queueCountBadge.textContent = `${summary.queue_item_count || 0} items`;
  elements.globalMetrics.innerHTML = metrics
    .map(
      (metric) => `
        <article class="metric-card">
          <strong>${escapeHtml(String(metric.value))}</strong>
          <span>${escapeHtml(metric.label)}</span>
        </article>
      `,
    )
    .join("");
}

function renderCampaignCenter() {
  const overview = state.campaignOverview || { summary: {}, highlights: {} };
  const summary = overview.summary || {};
  const latestReadiness = overview.highlights?.latest_product_readiness || null;
  const readinessRate = latestReadiness?.rates?.product_ready_rate;
  const releaseManagement = overview.release_management || {};
  const currentCanonical = releaseManagement.current_canonical || null;
  elements.campaignCountBadge.textContent = `${summary.campaign_count || 0} campaigns`;
  elements.campaignSummary.innerHTML = `
    <span>${escapeHtml(String(summary.green_campaign_count || 0))} green</span>
    <span>${escapeHtml(String(summary.family_count || 0))} families</span>
    <span>${readinessRate == null ? "no release gate" : `release gate ${escapeHtml(formatRate(readinessRate))}`}</span>
    <span>${currentCanonical ? `canonical ${escapeHtml(currentCanonical.campaign_name)}` : "no canonical baseline"}</span>
  `;
  if (!state.campaigns.length) {
    elements.campaignList.innerHTML = `<div class="muted-copy">No campaign reports found.</div>`;
    return;
  }
  elements.campaignList.innerHTML = state.campaigns
    .map((campaign) => {
      const primaryRate =
        campaign.rates?.product_ready_rate ??
        campaign.rates?.all_requirements_met_rate ??
        campaign.rates?.semantic_quality_gate_rate ??
        campaign.rates?.expected_lane_visible_rate ??
        campaign.rates?.duration_alignment_rate ??
        0;
      const openUrl = `/api/v1/campaigns/${encodeURIComponent(campaign.campaign_name)}`;
      const selected = campaign.campaign_name === state.selectedCampaignName;
      const releaseStatus = campaign.release?.status || "untracked";
      return `
        <article class="queue-item${selected ? " is-focused" : ""}">
          <div class="card-topline">
            <div>
              <strong class="card-title">${escapeHtml(campaign.campaign_name)}</strong>
              <p>${escapeHtml(campaign.family || "campaign")} / ${escapeHtml(String(campaign.completed_runs || 0))}/${escapeHtml(String(campaign.total_runs || 0))} runs</p>
            </div>
            <span class="badge ${campaign.is_green ? "quality-pass" : "quality-fail"}">${escapeHtml(campaign.status || "unknown")}</span>
          </div>
          <div class="meta-row">
            <span>${escapeHtml(campaign.generated_at || "unknown time")}</span>
            <span>${escapeHtml(formatRate(primaryRate))}</span>
          </div>
          <div class="chip-row">
            <span class="chip">${escapeHtml(releaseStatus)}</span>
            ${
              campaign.release?.is_current_canonical
                ? '<span class="quality-chip quality-pass">current canonical</span>'
                : ""
            }
          </div>
          ${Array.isArray(campaign.categories) && campaign.categories.length
            ? `<div class="chip-row">${campaign.categories
                .slice(0, 4)
                .map((category) => `<span class="chip">${escapeHtml(category)}</span>`)
                .join("")}</div>`
            : ""}
          <div class="card-actions">
            <button class="button button-primary" type="button" data-campaign-name="${escapeHtml(campaign.campaign_name)}">Inspect</button>
            <a class="button button-ghost" href="${escapeHtml(openUrl)}" target="_blank" rel="noreferrer">Open Report</a>
          </div>
        </article>
      `;
    })
    .join("");
}

function getSelectedCampaignDetail() {
  if (!state.selectedCampaignName) {
    return null;
  }
  const selectedCompareTarget = elements.campaignCompareTarget?.value || "";
  return (
    state.campaignDetails.get(`${state.selectedCampaignName}::${selectedCompareTarget}`) ||
    state.campaignDetails.get(state.selectedCampaignName) ||
    null
  );
}

function renderCampaignDetail() {
  elements.campaignSelectionHint.textContent = state.selectedCampaignName
    ? `Focused campaign: ${state.selectedCampaignName}`
    : "Select a campaign to inspect";
  const detail = getSelectedCampaignDetail();
  if (!detail) {
    elements.campaignEmpty.hidden = false;
    elements.campaignDetail.hidden = true;
    return;
  }
  elements.campaignEmpty.hidden = true;
  elements.campaignDetail.hidden = false;
  renderCampaignHero(detail);
  renderCampaignReleaseSummary(detail);
  renderCampaignCompareTarget(detail);
  renderCampaignPromotionState(detail);
  renderCampaignComparison(detail);
  renderCampaignReleaseDesk(detail);
  renderCampaignReleaseHandoff(detail);
  renderCampaignCases(detail);
}

function renderCampaignHero(detail) {
  const summary = detail.summary || {};
  const release = summary.release || {};
  const comparison = detail.comparison || null;
  elements.campaignHero.innerHTML = `
    <div class="card-topline">
      <div>
        <strong class="card-title">${escapeHtml(summary.campaign_name || "campaign")}</strong>
        <p>${escapeHtml(summary.family || "campaign")} / ${escapeHtml(summary.generated_at || "unknown time")}</p>
      </div>
      <span class="badge ${summary.is_green ? "quality-pass" : "quality-fail"}">${escapeHtml(summary.status || "unknown")}</span>
    </div>
    <div class="chip-row">
      <span class="chip">${escapeHtml(release.status || "untracked")}</span>
      ${
        release.is_current_canonical
          ? '<span class="quality-chip quality-pass">current canonical</span>'
          : ""
      }
      ${
        comparison?.status
          ? `<span class="chip">comparison ${escapeHtml(comparison.status)}</span>`
          : ""
      }
    </div>
    <div class="meta-row">
      <span>${escapeHtml(String(summary.completed_runs || 0))}/${escapeHtml(String(summary.total_runs || 0))} runs</span>
      <span>${escapeHtml(String(summary.qc_finding_count || 0))} QC findings</span>
      <span>${escapeHtml(formatRate(summary.rates?.product_ready_rate ?? summary.rates?.all_requirements_met_rate ?? 0))}</span>
    </div>
  `;
}

function renderCampaignReleaseSummary(detail) {
  const releaseSummary = detail.release_summary || {};
  const summary = detail.summary || {};
  const release = summary.release || {};
  const promotion = detail.promotion || {};
  const bullets = Array.isArray(releaseSummary.bullets) ? releaseSummary.bullets : [];
  elements.campaignReleaseSummary.innerHTML = `
    <article class="queue-item">
      <div class="card-topline">
        <div>
          <strong class="card-title">${escapeHtml(releaseSummary.headline || "Release summary unavailable.")}</strong>
          <p>${escapeHtml(summary.campaign_name || "")}</p>
        </div>
        <span class="badge ${badgeClass(release.status || "untracked")}">${escapeHtml(release.status || "untracked")}</span>
      </div>
      <div class="meta-row">
        <span>${escapeHtml(release.explicit ? "explicit registry state" : "derived release state")}</span>
        ${
          release.compared_to
            ? `<span>compared to ${escapeHtml(release.compared_to)}</span>`
            : ""
        }
        ${
          promotion.canonical_blocked
            ? `<span>canonical blocked</span>`
            : `<span>canonical ready</span>`
        }
      </div>
      <div class="queue-list">
        ${
          bullets.length
            ? bullets.map((bullet) => `<div class="muted-copy">${escapeHtml(bullet)}</div>`).join("")
            : '<div class="muted-copy">No release summary bullets available.</div>'
        }
      </div>
    </article>
  `;
}

function renderCampaignCompareTarget(detail) {
  const options = [
    '<option value="">Auto compare target</option>',
    ...state.campaigns
      .filter((campaign) => campaign.campaign_name !== state.selectedCampaignName)
      .map((campaign) => {
        const selected =
          campaign.campaign_name === (detail.selected_compare_target || "") ? " selected" : "";
        return `<option value="${escapeHtml(campaign.campaign_name)}"${selected}>${escapeHtml(campaign.campaign_name)}</option>`;
      }),
  ];
  elements.campaignCompareTarget.innerHTML = options.join("");
}

function campaignReleaseNoteKey(detail) {
  return `${detail.summary?.campaign_name || ""}::${detail.selected_compare_target || ""}`;
}

function renderCampaignPromotionState(detail) {
  const promotion = detail.promotion || {};
  const blocked = Boolean(promotion.canonical_blocked);
  const suggestedNote = promotion.suggested_note || "";
  const releaseNoteKey = campaignReleaseNoteKey(detail);
  if (!state.campaignReleaseNoteDirty || state.campaignReleaseNoteKey !== releaseNoteKey) {
    elements.campaignReleaseNote.value = suggestedNote;
    state.campaignReleaseNoteDirty = false;
    state.campaignReleaseNoteKey = releaseNoteKey;
  }
  elements.campaignMarkCanonicalButton.disabled = blocked;
  elements.campaignMarkCanonicalButton.title = blocked
    ? "Resolve review_quality_regression targets before canonical promotion."
    : "";
  elements.campaignReleaseBlockers.innerHTML = blocked
    ? `
      <span class="quality-chip quality-fail">canonical blocked</span>
      <span>${escapeHtml(String(promotion.blocked_case_count || 0))} blocked cases</span>
      ${
        Array.isArray(promotion.blocked_regressed_metrics) && promotion.blocked_regressed_metrics.length
          ? `<span>${escapeHtml(promotion.blocked_regressed_metrics.join(", "))}</span>`
          : `<span>review_quality_regression open</span>`
      }
    `
    : `
      <span class="quality-chip quality-pass">canonical ready</span>
      <span>${escapeHtml(String((detail.case_table || []).length))} cases reviewed</span>
      <span>suggested note hydrated</span>
    `;
}

function renderCampaignComparison(detail) {
  const comparison = detail.comparison || null;
  if (!comparison) {
    elements.campaignComparison.innerHTML = `<div class="muted-copy">No comparison target selected for this campaign.</div>`;
    return;
  }
  const compareUrl = `/api/v1/campaigns/compare?left=${encodeURIComponent(
    comparison.left?.campaign_name || "",
  )}&right=${encodeURIComponent(comparison.right?.campaign_name || "")}`;
  const changedCases = comparison.case_diff?.changed || [];
  const regressions = comparison.case_diff?.regressed || [];
  const improvements = comparison.case_diff?.improved || [];
  const semanticRegressions = comparison.case_diff?.semantic_regressed || [];
  const revisionSemanticRegressions = comparison.case_diff?.revision_semantic_regressed || [];
  const revisionReleaseRegressions = comparison.case_diff?.revision_release_regressed || [];
  const deliverableRegressions = comparison.case_diff?.deliverables_regressed || [];
  const operatorRegressions = comparison.case_diff?.operator_attention_regressed || [];
  const backendChanges = comparison.backend_changes || [];
  const presetChanges = comparison.preset_changes || [];
  const metricDeltas = (comparison.metric_deltas || [])
    .filter((item) => Math.abs(Number(item.delta || 0)) > 0)
    .slice(0, 6);
  elements.campaignComparison.innerHTML = `
    <article class="queue-item">
      <div class="card-topline">
        <div>
          <strong class="card-title">${escapeHtml(comparison.left?.campaign_name || "")}</strong>
          <p>vs ${escapeHtml(comparison.right?.campaign_name || "")}</p>
        </div>
        <span class="badge ${badgeClass(comparison.status || "unchanged")}">${escapeHtml(comparison.status || "unchanged")}</span>
      </div>
      <div class="meta-row">
        <span>${escapeHtml(String(regressions.length))} regressions</span>
        <span>${escapeHtml(String(improvements.length))} improvements</span>
        <span>${escapeHtml(String(backendChanges.length))} backend changes</span>
        <span>${escapeHtml(String(semanticRegressions.length))} semantic regressions</span>
      </div>
      <div class="chip-row">
        <span class="chip">semantic baseline regressions ${escapeHtml(String(revisionSemanticRegressions.length))}</span>
        <span class="chip">revision regressions ${escapeHtml(String(revisionReleaseRegressions.length))}</span>
        <span class="chip">deliverable regressions ${escapeHtml(String(deliverableRegressions.length))}</span>
        <span class="chip">operator regressions ${escapeHtml(String(operatorRegressions.length))}</span>
        <span class="chip">preset changes ${escapeHtml(String(presetChanges.length))}</span>
      </div>
      ${
        metricDeltas.length
          ? `<div class="chip-row">${metricDeltas
              .map(
                (item) =>
                  `<span class="chip">${escapeHtml(item.metric)} ${item.delta > 0 ? "+" : ""}${escapeHtml(item.delta.toFixed(2))}</span>`,
              )
              .join("")}</div>`
          : '<div class="muted-copy">No metric deltas across release gates.</div>'
      }
      ${
        changedCases.length
          ? `<div class="queue-list">${changedCases
              .slice(0, 8)
              .map(
                (item) => `
                  <article class="queue-item">
                    <div class="card-topline">
                      <strong class="card-title">${escapeHtml(item.title || item.slug)}</strong>
                      <span class="badge ${item.left_status === "passed" ? "quality-pass" : "quality-fail"}">${escapeHtml(item.right_status)} → ${escapeHtml(item.left_status)}</span>
                    </div>
                    <div class="meta-row">
                      <span>${escapeHtml(item.slug)}</span>
                      ${
                        item.semantic_failures_added?.length
                          ? `<span>semantic +${escapeHtml(item.semantic_failures_added.join(", "))}</span>`
                          : ""
                      }
                      ${
                        item.revision_semantic_failures_added?.length
                          ? `<span>semantic baseline +${escapeHtml(item.revision_semantic_failures_added.join(", "))}</span>`
                          : ""
                      }
                      ${
                        item.revision_release_failures_added?.length
                          ? `<span>revision +${escapeHtml(item.revision_release_failures_added.join(", "))}</span>`
                          : ""
                      }
                      ${item.deliverables_regressed ? "<span>deliverables regressed</span>" : ""}
                      ${item.operator_attention_regressed ? "<span>operator attention added</span>" : ""}
                      ${item.qc_finding_delta ? `<span>QC Δ ${escapeHtml(String(item.qc_finding_delta))}</span>` : ""}
                    </div>
                  </article>
                `,
              )
              .join("")}</div>`
          : '<div class="muted-copy">No per-case regressions or improvements.</div>'
      }
      <div class="card-actions">
        <a class="button button-ghost" href="${escapeHtml(compareUrl)}" target="_blank" rel="noreferrer">Open Raw Compare</a>
      </div>
    </article>
  `;
}

function renderCampaignReleaseDesk(detail) {
  const releaseManagement = state.campaignOverview?.release_management || {};
  const currentCanonical = releaseManagement.current_canonical || null;
  const previousCanonical = releaseManagement.previous_canonical || null;
  const recommended = releaseManagement.recommended_canonical || null;
  const candidates = Array.isArray(releaseManagement.candidates) ? releaseManagement.candidates : [];
  const baselineManifest = releaseManagement.baseline_manifest || null;
  const releaseHandoff = releaseManagement.release_handoff || null;
  const baselineSummary = baselineManifest?.comparison?.summary || {};
  const promotion = detail?.promotion || {};
  elements.campaignReleaseDesk.innerHTML = `
    <article class="queue-item">
      <div class="meta-row">
        <span>${currentCanonical ? `canonical ${escapeHtml(currentCanonical.campaign_name)}` : "no canonical baseline"}</span>
        <span>${previousCanonical ? `previous ${escapeHtml(previousCanonical.campaign_name)}` : "no previous baseline"}</span>
      </div>
      ${
        baselineManifest
          ? `
            <div class="chip-row">
              <span class="chip">baseline ${escapeHtml(baselineManifest.current_canonical?.campaign_name || "canonical")}</span>
              <span class="chip">comparison ${escapeHtml(baselineManifest.comparison?.status || "none")}</span>
              <span class="chip">case deltas ${escapeHtml(String(baselineSummary.case_detail_change_count || 0))}</span>
            </div>
            <div class="meta-row">
              <span>semantic regressions ${escapeHtml(String(baselineSummary.semantic_regression_count || 0))}</span>
              <span>semantic baseline regressions ${escapeHtml(String(baselineSummary.revision_semantic_regression_count || 0))}</span>
              <span>revision regressions ${escapeHtml(String(baselineSummary.revision_release_regression_count || 0))}</span>
              <span>deliverable regressions ${escapeHtml(String(baselineSummary.deliverable_regression_count || 0))}</span>
              <span>operator regressions ${escapeHtml(String(baselineSummary.operator_attention_regression_count || 0))}</span>
            </div>
            <div class="card-actions">
              <a class="button button-ghost" href="/api/v1/campaigns/release/baseline" target="_blank" rel="noreferrer">Open Baseline Manifest</a>
              ${
                releaseHandoff?.summary?.package_ready
                  ? '<a class="button button-ghost" href="/api/v1/campaigns/release/handoff" target="_blank" rel="noreferrer">Open Release Handoff</a>'
                  : ""
              }
            </div>
          `
          : '<div class="muted-copy">No canonical baseline manifest has been written yet.</div>'
      }
      ${
        recommended
          ? `<div class="muted-copy">Recommended canonical: ${escapeHtml(recommended.campaign_name)}</div>`
          : '<div class="muted-copy">No recommended canonical campaign available.</div>'
      }
      ${
        promotion.canonical_blocked
          ? `<div class="chip-row">
              <span class="quality-chip quality-fail">promotion blocked</span>
              ${(promotion.blocked_case_slugs || [])
                .slice(0, 6)
                .map((slug) => `<span class="chip">${escapeHtml(slug)}</span>`)
                .join("")}
            </div>`
          : ""
      }
      ${
        candidates.length
          ? `<div class="chip-row">${candidates
              .slice(0, 6)
              .map((candidate) => `<span class="chip">${escapeHtml(candidate.campaign_name)}</span>`)
              .join("")}</div>`
          : '<div class="muted-copy">No candidate campaigns in registry.</div>'
      }
    </article>
  `;
}

function renderCampaignReleaseHandoff(detail) {
  const selectedSummary = detail.summary || {};
  const selectedRelease = selectedSummary.release || {};
  const releaseManagement = state.campaignOverview?.release_management || {};
  const currentCanonicalHandoff = releaseManagement.release_handoff || null;
  const handoff = selectedRelease.is_current_canonical
    ? currentCanonicalHandoff || detail.handoff || null
    : detail.handoff || null;
  if (!handoff) {
    elements.campaignReleaseHandoff.innerHTML =
      '<div class="muted-copy">Release handoff is not available yet for this campaign.</div>';
    return;
  }
  const summary = handoff.summary || {};
  const comparison = handoff.comparison || {};
  const comparisonSummary = comparison.summary || {};
  const releaseNote = handoff.release_note || {};
  const packageContents = Array.isArray(handoff.package_contents) ? handoff.package_contents : [];
  const isCurrentCanonical = Boolean(selectedRelease.is_current_canonical);
  const contentChips = packageContents.length
    ? packageContents
        .slice(0, 6)
        .map((item) => `<span class="chip">${escapeHtml(String(item).split("/").slice(-1)[0])}</span>`)
        .join("")
    : '<span class="muted-copy">No package contents declared.</span>';
  elements.campaignReleaseHandoff.innerHTML = `
    <article class="queue-item">
      <div class="card-topline">
        <div>
          <strong class="card-title">${escapeHtml(handoff.campaign_name || selectedSummary.campaign_name || "campaign")}</strong>
          <p>${isCurrentCanonical ? "current canonical release handoff" : "candidate handoff preview"}</p>
        </div>
        <span class="badge ${handoff.status === "ready" ? "quality-pass" : "badge-status-candidate"}">${escapeHtml(handoff.status || "preview")}</span>
      </div>
      <div class="meta-row">
        <span>${escapeHtml(String(summary.case_count || 0))} cases</span>
        <span>${escapeHtml(String(summary.regression_count || 0))} regressions</span>
        <span>${escapeHtml(String(summary.improvement_count || 0))} improvements</span>
        <span>${summary.package_ready ? "package ready" : "preview only"}</span>
      </div>
      <div class="chip-row">
        <span class="chip">semantic regressions ${escapeHtml(String(summary.semantic_regression_count || 0))}</span>
        <span class="chip">semantic baseline regressions ${escapeHtml(String(summary.revision_semantic_regression_count || 0))}</span>
        <span class="chip">revision regressions ${escapeHtml(String(summary.revision_release_regression_count || 0))}</span>
        <span class="chip">deliverable regressions ${escapeHtml(String(summary.deliverable_regression_count || 0))}</span>
      </div>
      <div class="queue-list">
        <article class="queue-item">
          <div class="card-topline">
            <strong class="card-title">Release Note</strong>
            <span class="badge ${releaseNote.source === "registry_note" ? "quality-pass" : "badge-status-candidate"}">${escapeHtml(releaseNote.source || "none")}</span>
          </div>
          <div class="muted-copy">${formatMultilineText(releaseNote.text || "No release note recorded yet.")}</div>
        </article>
        <article class="queue-item">
          <div class="card-topline">
            <strong class="card-title">Package Contents</strong>
            <span class="badge ${summary.package_ready ? "quality-pass" : "badge-status-candidate"}">${summary.package_ready ? "downloadable" : "not promoted"}</span>
          </div>
          <div class="chip-row">${contentChips}</div>
        </article>
      </div>
      <div class="meta-row">
        <span>comparison ${escapeHtml(comparison.status || "none")}</span>
        <span>case deltas ${escapeHtml(String(comparisonSummary.case_detail_change_count || 0))}</span>
        <span>operator regressions ${escapeHtml(String(comparisonSummary.operator_attention_regression_count || 0))}</span>
      </div>
      <div class="card-actions">
        ${
          isCurrentCanonical && handoff.manifest_url
            ? `<a class="button button-ghost" href="${escapeHtml(handoff.manifest_url)}" target="_blank" rel="noreferrer">Open Handoff Manifest</a>`
            : ""
        }
        ${
          isCurrentCanonical && handoff.download_url
            ? `<a class="button button-primary" href="${escapeHtml(handoff.download_url)}">Download Handoff Package</a>`
            : ""
        }
        ${
          !isCurrentCanonical
            ? '<span class="muted-copy">Promote this campaign to canonical to materialize the handoff package.</span>'
            : ""
        }
      </div>
    </article>
  `;
}

function renderCampaignCases(detail) {
  const rows = Array.isArray(detail.case_table) ? detail.case_table : [];
  if (!rows.length) {
    elements.campaignCases.innerHTML = `<div class="muted-copy">No case rows available for this campaign.</div>`;
    return;
  }
  elements.campaignCases.innerHTML = rows
    .map((row) => {
      const backendProfile = row.backend_profile || {};
      const preset = row.product_preset || {};
      const revisionSemanticPassed = row.revision_semantic?.gate_passed;
      const revisionReleasePassed = row.revision_release?.gate_passed;
      const nextAction = row.operator_overview?.action?.next_action || "ship";
      return `
        <article class="queue-item${revisionSemanticPassed ? "" : " is-regression-target"}">
          <div class="card-topline">
            <div>
              <strong class="card-title">${escapeHtml(row.title || row.slug)}</strong>
              <p>${escapeHtml(row.slug || "case")}</p>
            </div>
            <span class="badge ${badgeClass(row.status || "unknown")}">${escapeHtml(row.status || "unknown")}</span>
          </div>
          <div class="meta-row">
            <span>${escapeHtml(row.category || "uncategorized")}</span>
            <span>${escapeHtml(backendProfile.visual_backend || "visual")} / ${escapeHtml(backendProfile.video_backend || "video")} / ${escapeHtml(backendProfile.tts_backend || "tts")}</span>
          </div>
          <div class="chip-row">
            ${
              preset.style_preset
                ? `<span class="chip">${escapeHtml(preset.style_preset)}</span>`
                : ""
            }
            ${
              preset.short_archetype
                ? `<span class="chip">${escapeHtml(preset.short_archetype)}</span>`
                : ""
            }
            ${
              row.project_id
                ? `<span class="chip">${escapeHtml(row.project_id)}</span>`
                : ""
            }
            <span class="chip">${revisionSemanticPassed ? "semantic baseline clear" : "semantic baseline review"}</span>
            <span class="chip">${revisionReleasePassed ? "revision release ready" : "revision release review"}</span>
            <span class="chip">${escapeHtml(nextAction)}</span>
          </div>
          <div class="card-actions">
            ${
              row.project_url
                ? `<a class="button button-ghost" href="${escapeHtml(row.project_url)}" target="_blank" rel="noreferrer">Open Project</a>`
                : ""
            }
            <a class="button button-ghost" href="${escapeHtml(row.campaign_url)}" target="_blank" rel="noreferrer">Open Campaign</a>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderQueue() {
  const summary = state.queue?.summary || {};
  const items = Array.isArray(state.queue?.items) ? state.queue.items : [];
  elements.queueSummary.innerHTML = `
    <span>${escapeHtml(String(summary.pending_review_shot_count || 0))} pending review</span>
    <span>${escapeHtml(String(summary.needs_rerender_shot_count || 0))} need rerender</span>
    <span>${escapeHtml(String(summary.failed_qc_project_count || 0))} QC failures</span>
    <span>${escapeHtml(String(summary.quality_regression_failed_project_count || 0))} semantic baseline</span>
    <span>${escapeHtml(String(summary.revision_release_failed_project_count || 0))} revision release</span>
  `;
  if (!items.length) {
    elements.queueList.innerHTML = `<div class="muted-copy">Queue is clear.</div>`;
    return;
  }
  elements.queueList.innerHTML = items
    .map((item) => {
      const isFocused =
        item.project_id === state.selectedProjectId &&
        item.target_kind === state.selectedTarget?.kind &&
        item.target_id === state.selectedTarget?.id;
      const title =
        item.target_kind === "shot"
          ? item.shot_title || item.target_id
          : item.target_kind === "scene"
            ? item.scene_title || item.target_id
            : item.project_title;
      return `
        <article class="queue-item${isFocused ? " is-focused" : ""}">
          <div class="card-topline">
            <div>
              <strong class="card-title">${escapeHtml(title || item.project_title || item.target_id || "Queue item")}</strong>
              <p>${escapeHtml(item.project_title || "")}</p>
            </div>
            <span class="badge ${badgeClass(item.review_status || item.action)}">${escapeHtml(item.action)}</span>
          </div>
          <div class="meta-row">
            <span>${escapeHtml(item.target_kind || "project")}</span>
            <span>${escapeHtml(item.reason || "operator")}</span>
          </div>
          ${renderFailedGates(item.failed_gates)}
          <div class="card-actions">
            <button
              class="button button-ghost"
              type="button"
              data-queue-project-id="${escapeHtml(item.project_id)}"
              data-target-kind="${escapeHtml(item.target_kind || "")}"
              data-target-id="${escapeHtml(item.target_id || "")}"
              data-scene-id="${escapeHtml(item.scene_id || "")}"
            >Focus</button>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderProjectList() {
  elements.selectionHint.textContent = state.selectedProjectId
    ? `Focused project: ${state.selectedProjectId}`
    : "Select a project to inspect";
  if (!state.overviews.length) {
    elements.projectList.innerHTML = `<div class="muted-copy">No projects yet.</div>`;
    return;
  }
  elements.projectList.innerHTML = state.overviews
    .map((overview) => {
      const selected = overview.project_id === state.selectedProjectId;
      const preset = overview.product_preset || {};
      const nextAction = overview.action?.next_action || "inspect";
      const semanticPassed = overview.semantic_quality?.gate_passed;
      const revisionSemanticPassed = overview.revision_semantic?.gate_passed;
      const revisionReleasePassed = overview.revision_release?.gate_passed;
      return `
        <article class="project-card${selected ? " is-selected" : ""}" data-project-id="${escapeHtml(overview.project_id)}">
          <div class="card-headline">
            <div>
              <strong class="card-title">${escapeHtml(overview.title)}</strong>
              <p>${escapeHtml(overview.project_id)}</p>
            </div>
            <span class="badge ${badgeClass(overview.status)}">${escapeHtml(overview.status)}</span>
          </div>
          <div class="chip-row">
            <span class="chip">${escapeHtml(preset.style_preset || "style")}</span>
            <span class="chip">${escapeHtml(preset.short_archetype || "archetype")}</span>
            <span class="chip">${escapeHtml(overview.language || "lang")}</span>
          </div>
          <div class="meta-row">
            <span>${escapeHtml(String(overview.summary?.scene_count || 0))} scenes</span>
            <span>${escapeHtml(String(overview.summary?.shot_count || 0))} shots</span>
            <span>${escapeHtml(String(overview.summary?.speaker_count || 0))} speakers</span>
          </div>
          <div class="badge-row">
            <span class="badge ${badgeClass(nextAction)}">${escapeHtml(nextAction)}</span>
            <span class="badge ${semanticPassed ? "quality-pass" : "quality-fail"}">
              semantic ${semanticPassed ? "green" : "review"}
            </span>
            <span class="badge ${revisionSemanticPassed ? "quality-pass" : "quality-fail"}">
              semantic baseline ${revisionSemanticPassed ? "clear" : "review"}
            </span>
            <span class="badge ${revisionReleasePassed ? "quality-pass" : "quality-fail"}">
              revision ${revisionReleasePassed ? "ready" : "review"}
            </span>
            <span class="badge ${overview.deliverables?.ready ? "quality-pass" : "quality-fail"}">
              ${overview.deliverables?.ready ? "deliverables ready" : "deliverables pending"}
            </span>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderProjectDetail() {
  const detail = getSelectedDetail();
  if (!detail) {
    elements.projectEmpty.hidden = false;
    elements.projectDetail.hidden = true;
    return;
  }
  elements.projectEmpty.hidden = true;
  elements.projectDetail.hidden = false;
  renderProjectHero(detail.overview);
  renderVideoPanel(detail.overview, detail.deliverables);
  renderSemanticQuality(
    detail.overview.semantic_quality || {},
    detail.overview.revision_semantic || {},
  );
  renderDeliverables(detail.deliverables);
  renderReviewSummary(
    detail.review,
    detail.overview.revision_release || {},
    detail.overview.revision_semantic || {},
  );
  renderReviewWorkspaceSummary(detail.review);
  renderReviewFocus(detail.review);
  renderReviewCompare(detail.reviewCompare?.payload || null);
  renderReviewScenes(detail.review);
}

function getSelectedDetail() {
  if (!state.selectedProjectId) {
    return null;
  }
  return state.projectDetails.get(state.selectedProjectId) || null;
}

function renderProjectHero(overview) {
  const preset = overview.product_preset || {};
  const backends = overview.backend_profile || {};
  const summary = overview.summary || {};
  const revisionSemantic = overview.revision_semantic || {};
  const revisionRelease = overview.revision_release || {};
  elements.projectHero.innerHTML = `
    <div class="hero-layout">
      <div class="hero-copy">
        <p class="eyebrow">Focused Project</p>
        <h2>${escapeHtml(overview.title)}</h2>
        <p class="lead">
          ${escapeHtml(overview.project_id)} · next action <strong>${escapeHtml(overview.action?.next_action || "inspect")}</strong>
        </p>
        <div class="chip-row">
          <span class="chip">${escapeHtml(preset.style_preset || "style")}</span>
          <span class="chip">${escapeHtml(preset.voice_cast_preset || "voice cast")}</span>
          <span class="chip">${escapeHtml(preset.music_preset || "music")}</span>
          <span class="chip">${escapeHtml(preset.short_archetype || "archetype")}</span>
        </div>
        <div class="hero-meta">
          <span class="badge ${badgeClass(overview.status)}">${escapeHtml(overview.status)}</span>
          <span class="badge ${overview.deliverables?.ready ? "quality-pass" : "quality-fail"}">
            ${overview.deliverables?.ready ? "deliverables ready" : "deliverables pending"}
          </span>
          <span class="badge ${overview.semantic_quality?.gate_passed ? "quality-pass" : "quality-fail"}">
            semantic ${overview.semantic_quality?.gate_passed ? "passed" : "review"}
          </span>
          <span class="badge ${revisionSemantic?.gate_passed ? "quality-pass" : "quality-fail"}">
            semantic baseline ${revisionSemantic?.gate_passed ? "clear" : "review"}
          </span>
          <span class="badge ${revisionRelease?.gate_passed ? "quality-pass" : "quality-fail"}">
            revision ${revisionRelease?.gate_passed ? "ready" : "review"}
          </span>
        </div>
      </div>
      <div class="hero-side">
        <div class="hero-stat">
          <strong>${escapeHtml(String(summary.scene_count || 0))} scenes</strong>
          <span>${escapeHtml(String(summary.shot_count || 0))} shots · ${escapeHtml(String(summary.speaker_count || 0))} speakers</span>
        </div>
        <div class="hero-stat">
          <strong>${escapeHtml(String(overview.estimated_duration_sec || 0))} sec</strong>
          <span>expected duration · ${escapeHtml(overview.language || "uk")} dialogue</span>
        </div>
        <div class="hero-stat">
          <strong>${escapeHtml(backends.visual_backend || "visual")}</strong>
          <span>visual · ${escapeHtml(backends.video_backend || "video")} video · ${escapeHtml(backends.tts_backend || "tts")} voice</span>
        </div>
      </div>
    </div>
  `;
}

function renderVideoPanel(overview, deliverables) {
  const finalVideo = deliverables?.named?.final_video || null;
  const poster = deliverables?.named?.poster || null;
  if (!finalVideo?.exists) {
    elements.videoPreview.innerHTML = `<div class="muted-copy">No final video has been produced yet.</div>`;
    return;
  }
  elements.videoPreview.innerHTML = `
    <div class="video-shell">
      <video controls preload="metadata" poster="${escapeHtml(poster?.download_url || "")}">
        <source src="${escapeHtml(finalVideo.download_url)}" type="video/mp4">
      </video>
    </div>
    <div class="chip-row">
      <a class="button button-primary" href="${escapeHtml(finalVideo.download_url)}" download>Download Final MP4</a>
      ${
        deliverables?.named?.deliverables_package?.download_url
          ? `<a class="button button-ghost" href="${escapeHtml(deliverables.named.deliverables_package.download_url)}" download>Download Package</a>`
          : ""
      }
      ${
        deliverables?.named?.poster?.download_url
          ? `<a class="button button-ghost" href="${escapeHtml(deliverables.named.poster.download_url)}" download>Poster</a>`
          : ""
      }
    </div>
    <div class="meta-row">
      <span>${escapeHtml(overview.status)}</span>
      <span>${escapeHtml(overview.qc?.status || "not_run")} QC</span>
      <span>${escapeHtml(String(overview.qc?.finding_count || 0))} findings</span>
    </div>
  `;
}

function renderSemanticQuality(semanticQuality, revisionSemantic) {
  const metrics = semanticQuality.metrics || {};
  const order = [
    ["subtitle_readability", "Subtitle Readability"],
    ["script_coverage", "Script Coverage"],
    ["shot_variety", "Shot Variety"],
    ["portrait_identity_consistency", "Portrait Identity"],
    ["audio_mix_clean", "Audio Mix"],
    ["archetype_payoff", "Archetype Payoff"],
  ];
  const baselineSummary = revisionSemantic || {};
  const baselineCard = `
    <article class="quality-card">
      <strong>Revision Semantic</strong>
      <span class="metric-value">${escapeHtml(formatRate(baselineSummary.current_overall_rate ?? semanticQuality.overall_rate ?? 0))}</span>
      <div class="quality-meta">
        <span class="badge ${baselineSummary.gate_passed ? "quality-pass" : "quality-fail"}">
          ${
            baselineSummary.baseline_available
              ? baselineSummary.gate_passed
                ? "baseline clear"
                : "regression review"
              : "no baseline yet"
          }
        </span>
        <span class="muted-copy">
          ${
            baselineSummary.baseline_available
              ? `changed ${escapeHtml(String(baselineSummary.changed_shot_count || 0))} shots · regressed ${escapeHtml(String(baselineSummary.regressed_metric_count || 0))} metrics`
              : "baseline will materialize after release-ready approval"
          }
        </span>
      </div>
      ${
        Array.isArray(baselineSummary.regressed_metrics) && baselineSummary.regressed_metrics.length
          ? `<div class="chip-row">${baselineSummary.regressed_metrics
              .map((metric) => `<span class="chip">${escapeHtml(metric)}</span>`)
              .join("")}</div>`
          : ""
      }
    </article>
  `;
  elements.semanticQuality.innerHTML = baselineCard + order
    .map(([key, label]) => {
      const metric = metrics[key] || {};
      return `
        <article class="quality-card">
          <strong>${escapeHtml(label)}</strong>
          <span class="metric-value">${escapeHtml(formatRate(metric.rate))}</span>
          <div class="quality-meta">
            <span class="badge ${metric.passed ? "quality-pass" : "quality-fail"}">
              ${metric.passed ? "passed" : "review"}
            </span>
            ${
              Array.isArray(metric.missing_beats) && metric.missing_beats.length
                ? `<span class="muted-copy">${escapeHtml(metric.missing_beats.join(", "))}</span>`
                : `<span class="muted-copy">${escapeHtml(key.replaceAll("_", " "))}</span>`
            }
          </div>
        </article>
      `;
    })
    .join("");
}

function renderDeliverables(deliverables) {
  const items = Array.isArray(deliverables?.items) ? deliverables.items : [];
  if (!items.length) {
    elements.deliverablesList.innerHTML = `<div class="muted-copy">No deliverables tracked yet.</div>`;
    return;
  }
  elements.deliverablesList.innerHTML = items
    .map((item) => {
      const stage = item.stage || "unknown";
      const action = item.download_url
        ? `<a href="${escapeHtml(item.download_url)}" download>Open</a>`
        : `<span class="muted-copy">Unavailable</span>`;
      return `
        <article class="deliverable-card">
          <div class="card-topline">
            <h3>${escapeHtml(item.kind)}</h3>
            <span class="badge ${item.exists ? "quality-pass" : "quality-fail"}">${item.exists ? "ready" : "missing"}</span>
          </div>
          <p class="mono">${escapeHtml(item.path || "")}</p>
          <div class="meta-row">
            <span>stage ${escapeHtml(stage)}</span>
            <span>${action}</span>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderReviewSummary(review, revisionRelease, revisionSemantic) {
  const summary = review?.summary || {};
  const releaseSummary = revisionRelease || {};
  const semanticBaseline = revisionSemantic || {};
  elements.reviewSummary.innerHTML = `
    <span>${escapeHtml(String(summary.pending_review_shot_count || 0))} pending shots</span>
    <span>${escapeHtml(String(summary.needs_rerender_shot_count || 0))} rerender shots</span>
    <span>${escapeHtml(String(summary.approved_shot_count || 0))} approved shots</span>
    <span>${escapeHtml(String(releaseSummary.release_ready_shot_count || 0))} release-ready shots</span>
    <span>${semanticBaseline.gate_passed ? "semantic baseline clear" : "semantic regression review"}</span>
    <span>${releaseSummary.gate_passed ? "revision release ready" : "revision release review"}</span>
  `;
}

function renderReviewWorkspaceSummary(review) {
  const workspace = getReviewWorkspace(review);
  const semantic = getSemanticRegressionWorkspace(review);
  if (!semantic.available && elements.reviewModeSelect?.value === "semantic_regressions") {
    elements.reviewModeSelect.value = "auto";
  }
  const activeMode = effectiveReviewMode(review);
  const focusTarget = semantic.focus_target || null;
  if (!semantic.available) {
    elements.reviewWorkspaceSummary.innerHTML = `
      <span>mode ${escapeHtml(activeMode)}</span>
      <span>review all targets</span>
      <span>no semantic regression baseline changes</span>
    `;
    return;
  }
  elements.reviewWorkspaceSummary.innerHTML = `
    <span>mode ${escapeHtml(activeMode)}</span>
    <span>${escapeHtml(String(semantic.changed_shot_count || 0))} changed shots</span>
    <span>${escapeHtml(String(semantic.changed_scene_count || 0))} changed scenes</span>
    <span>${escapeHtml(String((semantic.regressed_metrics || []).length))} regressed metrics</span>
    ${
      focusTarget
        ? `<span>focus ${escapeHtml(focusTarget.kind)} ${escapeHtml(focusTarget.id)}</span>`
        : `<span>no recommended focus target</span>`
    }
  `;
}

function renderReviewFocus(review) {
  const target = resolveFocusedTarget(review);
  if (!target) {
    elements.reviewFocus.className = "focus-card";
    elements.reviewFocus.innerHTML = `<div class="muted-copy">Select a scene or shot from the review stack.</div>`;
    elements.reviewComparePanel.innerHTML = `<div class="muted-copy">Revision compare becomes available after you focus a scene or shot.</div>`;
    return;
  }
  state.selectedTarget = target;
  elements.reviewReasonCode.value = target.review?.reason_code || "general";
  syncReviewCompareTargetOptions(
    target,
    normalizeReviewCompareTarget(target, elements.reviewCompareTarget?.value || ""),
  );
  const status = target.review?.status || "pending_review";
  const semantic = getSemanticRegressionWorkspace(review);
  const isRegressionTarget =
    target.kind === "shot"
      ? new Set(semantic.changed_shot_ids || []).has(target.id)
      : new Set(semantic.changed_scene_ids || []).has(target.id);
  elements.reviewFocus.className = `focus-card${isRegressionTarget ? " is-regression-target" : ""}`;
  elements.reviewFocus.innerHTML = `
    <div class="card-topline">
      <div>
        <strong class="card-title">${escapeHtml(target.title)}</strong>
        <p>${escapeHtml(target.kind)} · ${escapeHtml(target.id)}</p>
      </div>
      <span class="badge ${badgeClass(status)}">${escapeHtml(status)}</span>
    </div>
    <div class="meta-row">
      ${target.kind === "shot" ? `<span>scene ${escapeHtml(target.sceneId || "")}</span>` : ""}
      <span>revision ${escapeHtml(String(target.review?.output_revision || 0))}</span>
      <span>approved ${escapeHtml(String(target.review?.approved_revision ?? "none"))}</span>
      <span>reason ${escapeHtml(target.review?.reason_code || "general")}</span>
      <span>${escapeHtml(target.review?.reviewer || "operator")}</span>
    </div>
    ${
      isRegressionTarget
        ? `<div class="chip-row">
            <span class="quality-chip quality-fail">semantic regression target</span>
            ${(semantic.regressed_metrics || [])
              .map((metric) => `<span class="chip">${escapeHtml(metric)}</span>`)
              .join("")}
          </div>`
        : ""
    }
    ${
      target.review?.note
        ? `<p>${escapeHtml(target.review.note)}</p>`
        : `<p class="muted-copy">Use the buttons below to approve or rerender this target.</p>`
    }
  `;
}

function resolveFocusedTarget(review) {
  const scenes = Array.isArray(review?.scenes) ? review.scenes : [];
  const reviewMode = effectiveReviewMode(review);
  const semantic = getSemanticRegressionWorkspace(review);
  const semanticShotIds = new Set(semantic.changed_shot_ids || []);
  const semanticSceneIds = new Set(semantic.changed_scene_ids || []);
  if (!scenes.length) {
    return null;
  }
  if (state.selectedTarget) {
    for (const scene of scenes) {
      if (state.selectedTarget.kind === "scene" && scene.scene_id === state.selectedTarget.id) {
        if (reviewMode === "semantic_regressions" && !semanticSceneIds.has(scene.scene_id)) {
          break;
        }
        return {
          kind: "scene",
          id: scene.scene_id,
          sceneId: scene.scene_id,
          title: scene.title,
          review: scene.review,
        };
      }
      if (state.selectedTarget.kind === "shot") {
        for (const shot of scene.shots || []) {
          if (shot.shot_id === state.selectedTarget.id) {
            if (reviewMode === "semantic_regressions" && !semanticShotIds.has(shot.shot_id)) {
              break;
            }
            return {
              kind: "shot",
              id: shot.shot_id,
              sceneId: shot.scene_id,
              title: shot.title,
              review: shot.review,
            };
          }
        }
      }
    }
  }
  if (reviewMode === "semantic_regressions" && semantic.focus_target) {
    return {
      kind: semantic.focus_target.kind,
      id: semantic.focus_target.id,
      sceneId: semantic.focus_target.scene_id || semantic.focus_target.id,
      title: semantic.focus_target.title,
      review: findReviewStateForTarget(review, semantic.focus_target.kind, semantic.focus_target.id),
    };
  }
  const firstScene = scenes[0];
  const firstShot = firstScene.shots?.[0];
  if (firstShot) {
    return {
      kind: "shot",
      id: firstShot.shot_id,
      sceneId: firstShot.scene_id,
      title: firstShot.title,
      review: firstShot.review,
    };
  }
  return {
    kind: "scene",
    id: firstScene.scene_id,
    sceneId: firstScene.scene_id,
    title: firstScene.title,
    review: firstScene.review,
  };
}

function findReviewStateForTarget(review, kind, id) {
  const scenes = Array.isArray(review?.scenes) ? review.scenes : [];
  for (const scene of scenes) {
    if (kind === "scene" && scene.scene_id === id) {
      return scene.review;
    }
    for (const shot of scene.shots || []) {
      if (kind === "shot" && shot.shot_id === id) {
        return shot.review;
      }
    }
  }
  return null;
}

function renderReviewScenes(review) {
  const scenes = Array.isArray(review?.scenes) ? review.scenes : [];
  const reviewMode = effectiveReviewMode(review);
  if (!scenes.length) {
    elements.reviewScenes.innerHTML = `<div class="muted-copy">No scenes available.</div>`;
    return;
  }
  const visibleScenes =
    reviewMode === "semantic_regressions"
      ? scenes.filter((scene) => {
          if (isSemanticRegressionScene(review, scene)) {
            return true;
          }
          return (scene.shots || []).some((shot) => isSemanticRegressionShot(review, shot));
        })
      : scenes;
  if (!visibleScenes.length) {
    elements.reviewScenes.innerHTML = `<div class="muted-copy">No semantic-regression targets are available.</div>`;
    return;
  }
  elements.reviewScenes.innerHTML = visibleScenes
    .map((scene) => {
      const isSceneFocused = state.selectedTarget?.kind === "scene" && state.selectedTarget.id === scene.scene_id;
      const isRegressionScene = isSemanticRegressionScene(review, scene);
      const shots = (
        reviewMode === "semantic_regressions"
          ? (scene.shots || []).filter((shot) => isSemanticRegressionShot(review, shot))
          : Array.isArray(scene.shots)
            ? scene.shots
            : []
      );
      return `
        <article class="scene-card${isSceneFocused ? " is-focused" : ""}${isRegressionScene ? " is-regression-target" : ""}">
          <details open>
            <summary>
              <div class="card-topline">
                <div>
                  <h3>${escapeHtml(scene.title)}</h3>
                  <p>${escapeHtml(scene.scene_id)} · ${escapeHtml(String(scene.duration_sec || 0))} sec</p>
                </div>
                <span class="badge ${badgeClass(scene.review?.status || "pending_review")}">
                  ${escapeHtml(scene.review?.status || "pending_review")}
                </span>
              </div>
            </summary>
            ${
              isRegressionScene || shots.some((shot) => isSemanticRegressionShot(review, shot))
                ? `<div class="chip-row">
                    ${isRegressionScene ? '<span class="quality-chip quality-fail">semantic regression scene</span>' : ""}
                    <span class="chip">${escapeHtml(String(shots.length))} focused shots</span>
                  </div>`
                : ""
            }
            <div class="card-actions">
              <button
                class="button button-ghost"
                type="button"
                data-review-focus-kind="scene"
                data-review-focus-id="${escapeHtml(scene.scene_id)}"
                data-review-scene-id="${escapeHtml(scene.scene_id)}"
                data-review-title="${escapeHtml(scene.title)}"
              >Focus Scene</button>
            </div>
            <div class="shot-grid">
              ${shots
                .map((shot) => {
                  const focused = state.selectedTarget?.kind === "shot" && state.selectedTarget.id === shot.shot_id;
                  const isRegressionShot = isSemanticRegressionShot(review, shot);
                  return `
                    <article class="shot-card${focused ? " is-focused" : ""}${isRegressionShot ? " is-regression-target" : ""}">
                      <div class="card-topline">
                        <div>
                          <h4>${escapeHtml(shot.title)}</h4>
                          <p>${escapeHtml(shot.shot_id)} · ${escapeHtml(shot.strategy || "shot")} · ${escapeHtml(
                            String(shot.duration_sec || 0),
                          )} sec</p>
                        </div>
                        <span class="badge ${badgeClass(shot.review?.status || "pending_review")}">
                          ${escapeHtml(shot.review?.status || "pending_review")}
                        </span>
                      </div>
                      <div class="meta-row">
                        <span>revision ${escapeHtml(String(shot.review?.output_revision || 0))}</span>
                        <span>${escapeHtml(shot.review?.reason || "review_loop")}</span>
                      </div>
                      ${
                        isRegressionShot
                          ? `<div class="chip-row"><span class="quality-chip quality-fail">semantic regression target</span></div>`
                          : ""
                      }
                      <div class="card-actions">
                        <button
                          class="button button-ghost"
                          type="button"
                          data-review-focus-kind="shot"
                          data-review-focus-id="${escapeHtml(shot.shot_id)}"
                          data-review-scene-id="${escapeHtml(shot.scene_id)}"
                          data-review-title="${escapeHtml(shot.title)}"
                        >Focus Shot</button>
                      </div>
                    </article>
                  `;
                })
                .join("")}
            </div>
          </details>
        </article>
      `;
    })
    .join("");
}

function renderPresetPreview() {
  if (!state.presetCatalog) {
    elements.presetPreview.innerHTML = `<div class="muted-copy">Preset catalog not loaded yet.</div>`;
    return;
  }
  const styleKey = elements.createStylePreset.value || state.presetCatalog.defaults?.style_preset;
  const voiceKey = elements.createVoiceCastPreset.value || state.presetCatalog.defaults?.voice_cast_preset;
  const musicKey = elements.createMusicPreset.value || state.presetCatalog.defaults?.music_preset;
  const archetypeKey = elements.createShortArchetype.value || state.presetCatalog.defaults?.short_archetype;
  elements.presetPreview.innerHTML = [
    renderPresetCard("Style", styleKey, state.presetCatalog.style_presets?.[styleKey]),
    renderPresetCard("Voice Cast", voiceKey, state.presetCatalog.voice_cast_presets?.[voiceKey]),
    renderPresetCard("Music", musicKey, state.presetCatalog.music_presets?.[musicKey]),
    renderPresetCard("Archetype", archetypeKey, state.presetCatalog.short_archetypes?.[archetypeKey]),
  ].join("");
}

function renderPresetCard(label, key, payload) {
  const details = payload || {};
  const summary =
    details.visual_direction ||
    details.delivery ||
    details.cue_direction ||
    details.planning_bias ||
    "";
  const secondary = details.palette_hint || details.instrumentation?.join(", ") || details.beats?.join(", ") || "";
  return `
    <article class="preset-card">
      <p class="eyebrow">${escapeHtml(label)}</p>
      <h3>${escapeHtml(details.label || key || label)}</h3>
      <p>${escapeHtml(summary)}</p>
      ${secondary ? `<p class="muted-copy">${escapeHtml(secondary)}</p>` : ""}
    </article>
  `;
}

function renderFailedGates(failedGates) {
  if (!Array.isArray(failedGates) || !failedGates.length) {
    return "";
  }
  return `<div class="chip-row">${failedGates
    .map((gate) => `<span class="quality-chip quality-fail">${escapeHtml(gate)}</span>`)
    .join("")}</div>`;
}

function renderReviewCompare(compare) {
  if (!compare) {
    elements.reviewComparePanel.innerHTML = `<div class="muted-copy">Revision compare not loaded yet.</div>`;
    return;
  }
  if (compare.target_kind === "scene") {
    const summary = compare.summary || {};
    const shots = Array.isArray(compare.shots) ? compare.shots : [];
    elements.reviewComparePanel.innerHTML = `
      <div class="card-topline">
        <div>
          <strong class="card-title">Scene Compare</strong>
          <p>${escapeHtml(compare.title || compare.scene_id || "scene")}</p>
        </div>
        <span class="badge ${summary.compare_ready ? "quality-pass" : "quality-fail"}">
          ${summary.compare_ready ? "compare ready" : "single revision"}
        </span>
      </div>
      <div class="mini-summary">
        <span>${escapeHtml(String(summary.comparable_shot_count || 0))} comparable shots</span>
        <span>${escapeHtml(String(summary.revision_delta_shot_count || 0))} changed shots</span>
        <span>${escapeHtml(String(summary.approved_revision_locked_shot_count || 0))} locked approvals</span>
      </div>
      <div class="scene-stack">
        ${shots
          .map((shotCompare) => {
            const comparison = shotCompare.comparison || {};
            return `
              <article class="compare-card">
                <div class="card-topline">
                  <div>
                    <strong class="card-title">${escapeHtml(shotCompare.title || shotCompare.shot_id)}</strong>
                    <p>${escapeHtml(shotCompare.shot_id || "")}</p>
                  </div>
                  <span class="badge ${comparison.available ? "quality-pass" : "quality-fail"}">
                    ${comparison.available ? "comparable" : "single revision"}
                  </span>
                </div>
                <div class="meta-row">
                  <span>current ${escapeHtml(String(shotCompare.review?.output_revision || 0))}</span>
                  <span>approved ${escapeHtml(String(shotCompare.review?.approved_revision ?? "none"))}</span>
                </div>
                <div class="chip-row">
                  ${(comparison.changed_artifact_kinds || [])
                    .map((kind) => `<span class="chip">${escapeHtml(kind)}</span>`)
                    .join("") || `<span class="muted-copy">No artifact delta.</span>`}
                </div>
              </article>
            `;
          })
          .join("")}
      </div>
    `;
    return;
  }
  const comparison = compare.comparison || {};
  const left = compare.left_revision || null;
  const right = compare.right_revision || null;
  elements.reviewComparePanel.innerHTML = `
    <div class="card-topline">
      <div>
        <strong class="card-title">Revision Compare</strong>
        <p>${escapeHtml(compare.title || compare.shot_id || "shot")}</p>
      </div>
      <span class="badge ${comparison.available ? "quality-pass" : "quality-fail"}">
        ${comparison.available ? "side by side" : "single revision"}
      </span>
    </div>
    <div class="mini-summary">
      <span>left ${escapeHtml(compare.left_alias || "current")} · r${escapeHtml(String(left?.revision ?? "none"))}</span>
      <span>right ${escapeHtml(compare.right_alias || "previous")} · r${escapeHtml(String(right?.revision ?? "none"))}</span>
      <span>${escapeHtml(String((comparison.changed_artifact_kinds || []).length))} artifact deltas</span>
    </div>
    <div class="chip-row">
      ${(comparison.changed_artifact_kinds || [])
        .map((kind) => `<span class="chip">${escapeHtml(kind)}</span>`)
        .join("") || `<span class="muted-copy">No changed artifact kinds detected.</span>`}
    </div>
    <div class="compare-grid">
      ${renderRevisionCard(compare.left_alias || "left", left)}
      ${renderRevisionCard(compare.right_alias || "right", right)}
    </div>
  `;
}

function renderRevisionCard(label, revision) {
  if (!revision) {
    return `
      <article class="compare-card">
        <div class="card-topline">
          <strong class="card-title">${escapeHtml(label)}</strong>
          <span class="badge quality-fail">missing</span>
        </div>
        <p class="muted-copy">No revision is available for this selector.</p>
      </article>
    `;
  }
  const primaryVideo = revision.primary_video || null;
  const reviewEvents = Array.isArray(revision.review_events) ? revision.review_events : [];
  return `
    <article class="compare-card">
      <div class="card-topline">
        <div>
          <strong class="card-title">${escapeHtml(label)}</strong>
          <p>revision ${escapeHtml(String(revision.revision))}</p>
        </div>
        <span class="badge ${revision.status === "approved" ? "quality-pass" : "badge-status-review"}">
          ${escapeHtml(revision.status || "historical")}
        </span>
      </div>
      ${
        primaryVideo?.download_url
          ? `
            <div class="compare-video">
              <video controls preload="metadata">
                <source src="${escapeHtml(primaryVideo.download_url)}" type="video/mp4">
              </video>
            </div>
          `
          : `<p class="muted-copy">No canonical video artifact stored for this revision.</p>`
      }
      <div class="meta-row">
        <span>${escapeHtml(String(revision.artifact_count || 0))} artifacts</span>
        <span>${escapeHtml(String(revision.review_event_count || 0))} review events</span>
        <span>${escapeHtml(String(revision.created_at || ""))}</span>
      </div>
      <div class="chip-row">
        ${(revision.artifacts || [])
          .map((artifact) =>
            artifact.download_url
              ? `<a class="chip" href="${escapeHtml(artifact.download_url)}" target="_blank" rel="noreferrer">${escapeHtml(artifact.kind)}</a>`
              : `<span class="chip">${escapeHtml(artifact.kind)}</span>`,
          )
          .join("") || `<span class="muted-copy">No stored artifacts.</span>`}
      </div>
      ${
        reviewEvents.length
          ? `
            <div class="meta-row">
              ${reviewEvents
                .slice(-2)
                .map(
                  (event) =>
                    `<span>${escapeHtml(event.status || "review")} · ${escapeHtml(
                      event.reason_code || event.reason || "general",
                    )} · r${escapeHtml(String(event.reviewed_revision ?? event.output_revision ?? "n/a"))}</span>`,
                )
                .join("")}
            </div>
          `
          : ""
      }
    </article>
  `;
}

async function setFocusedTarget(target) {
  state.selectedTarget = target;
  const detail = getSelectedDetail();
  renderReviewFocus(detail?.review);
  await loadFocusedCompare(state.selectedProjectId, { force: true });
  renderReviewScenes(detail?.review);
}

async function applyFocusedReview({ status, requestRerender = false, runImmediately = false }) {
  if (!state.selectedProjectId || !state.selectedTarget) {
    setStatus("Select a scene or shot before applying a review action.", "warning", 2200);
    return;
  }
  const note = elements.reviewNoteInput.value.trim();
  const reviewer = elements.reviewerInput.value.trim() || "operator";
  const reasonCode = elements.reviewReasonCode.value || "general";
  const startStage = elements.rerenderStageSelect.value;
  const target = state.selectedTarget;
  const detail = getSelectedDetail();
  const comparePayload = detail?.reviewCompare?.payload || null;
  const targetRevision =
    comparePayload?.left_revision?.revision ??
    target.review?.output_revision ??
    0;
  const url =
    target.kind === "shot"
      ? `/api/v1/projects/${state.selectedProjectId}/shots/${target.id}/review`
      : `/api/v1/projects/${state.selectedProjectId}/scenes/${target.id}/review`;
  setStatus(`${status} on ${target.kind} ${target.id}...`, "info");
  const reviewResponse = await fetchJson(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      status,
      note,
      reason: note || status,
      reason_code: reasonCode,
      reviewer,
      target_revision: targetRevision,
      request_rerender: requestRerender,
      run_immediately: runImmediately,
      start_stage: startStage,
    }),
  });
  const existingDetail = state.projectDetails.get(state.selectedProjectId) || {};
  state.projectDetails.set(state.selectedProjectId, { ...existingDetail, review: reviewResponse });
  await loadProjectDetail(state.selectedProjectId, { force: true });
  elements.reviewNoteInput.value = "";
  setStatus(`Updated ${target.kind} ${target.id}.`, "success", 1800);
}

async function runProject(projectId) {
  setStatus(`Running project ${projectId}. This can take a while...`, "info");
  await fetchJson(`/api/v1/projects/${projectId}/run`, { method: "POST" });
  state.projectDetails.delete(projectId);
  await refreshStudio({ forceProjectRefresh: true });
}

async function updateCampaignReleaseStatus(status) {
  if (!state.selectedCampaignName) {
    setStatus("Select a campaign before changing release state.", "warning", 2200);
    return;
  }
  const detail = getSelectedCampaignDetail();
  if (status === "canonical" && detail?.promotion?.canonical_blocked) {
    setStatus(
      "Canonical promotion is blocked until review_quality_regression targets are resolved.",
      "warning",
      2600,
    );
    return;
  }
  const compareTo = elements.campaignCompareTarget.value || null;
  const note = elements.campaignReleaseNote.value.trim();
  setStatus(`${status} on ${state.selectedCampaignName}...`, "info");
  const updatedDetail = await fetchJson(
    `/api/v1/campaigns/${encodeURIComponent(state.selectedCampaignName)}/release`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status,
        note,
        compared_to: compareTo,
      }),
    },
  );
  updatedDetail.selected_compare_target =
    compareTo || updatedDetail.comparison?.right?.campaign_name || updatedDetail.summary?.release?.compared_to || "";
  state.campaignDetails.set(state.selectedCampaignName, updatedDetail);
  state.campaignDetails.set(
    `${state.selectedCampaignName}::${updatedDetail.selected_compare_target || ""}`,
    updatedDetail,
  );
  state.campaignReleaseNoteDirty = false;
  state.campaignReleaseNoteKey = null;
  await refreshStudio({ forceProjectRefresh: false });
  setStatus(`Updated release state for ${state.selectedCampaignName}.`, "success", 1800);
}

async function createProjectFromForm() {
  const payload = {
    title: elements.createTitle.value.trim(),
    script: elements.createScript.value.trim(),
    language: elements.createLanguage.value,
    style_preset: elements.createStylePreset.value,
    voice_cast_preset: elements.createVoiceCastPreset.value,
    music_preset: elements.createMusicPreset.value,
    short_archetype: elements.createShortArchetype.value,
  };
  if (!payload.title || !payload.script) {
    setStatus("Title and script are required.", "warning", 2000);
    return;
  }
  setStatus("Creating project...", "info");
  const snapshot = await fetchJson("/api/v1/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const projectId = snapshot.project.project_id;
  state.projectDetails.delete(projectId);
  state.selectedProjectId = projectId;
  state.selectedTarget = null;
  if (elements.createRunImmediately.checked) {
    await runProject(projectId);
    return;
  }
  await refreshStudio({ forceProjectRefresh: true });
  setStatus(`Project ${projectId} created.`, "success", 1800);
}

async function quickGenerateProjectFromForm() {
  const payload = {
    prompt: elements.quickPrompt.value.trim(),
    title: elements.quickTitle.value.trim() || null,
    language: elements.quickLanguage.value,
    target_duration_sec: Number.parseInt(elements.quickDuration.value || "8", 10) || 8,
    character_names: elements.quickCharacters.value
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean),
    stack_profile: elements.quickStackProfile.value || "production_vertical",
    example_slug: elements.quickExampleSelect.value || null,
    run_immediately: Boolean(elements.quickRunImmediately.checked),
  };
  if (!payload.prompt && !payload.example_slug) {
    setStatus("Add an idea or choose a quick example.", "warning", 2200);
    return;
  }
  setStatus("Quick generate is building the project...", "info");
  const snapshot = await fetchJson("/api/v1/projects/quick-generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const projectId = snapshot.project.project_id;
  state.projectDetails.delete(projectId);
  state.selectedProjectId = projectId;
  state.selectedTarget = null;
  await refreshStudio({ forceProjectRefresh: true });
  setStatus(
    payload.run_immediately
      ? `Quick project ${projectId} generated.`
      : `Quick project ${projectId} created.`,
    "success",
    2200,
  );
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { Accept: "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      if (payload?.detail) {
        message = String(payload.detail);
      }
    } catch {
      // no-op
    }
    throw new Error(message);
  }
  return response.json();
}

function handleError(error) {
  console.error(error);
  setStatus(error instanceof Error ? error.message : "Unexpected dashboard error.", "error");
}

function setStatus(message, tone = "idle", timeoutMs = 0) {
  if (state.statusTimer) {
    clearTimeout(state.statusTimer);
    state.statusTimer = null;
  }
  elements.statusBanner.textContent = message;
  elements.statusBanner.className = `status-banner status-${tone}`;
  if (timeoutMs > 0) {
    state.statusTimer = window.setTimeout(() => {
      elements.statusBanner.textContent = "Studio idle.";
      elements.statusBanner.className = "status-banner status-idle";
    }, timeoutMs);
  }
}

function badgeClass(value) {
  return `badge-status-${String(value || "unknown").replaceAll(" ", "_")}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatRate(value) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function formatMultilineText(value) {
  return escapeHtml(value).replaceAll("\n", "<br>");
}
