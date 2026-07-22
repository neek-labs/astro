(function () {
  const dataUrl = "data/session-planner.json";
  const astrosphericScriptUrl = "https://astrosphericcloudstorage.blob.core.windows.net/embed/astrosphericembed.js";
  const astrosphericLocations = {
    calgary: {
      label: "Calgary",
      lat: 51.0486,
      lon: -114.0708
    },
    darksky: {
      label: "Starland Recreation Area",
      lat: 51.6630,
      lon: -112.9081
    },
    stones: {
      label: "Stones Throw Camp",
      lat: 50.5974,
      lon: -112.8299
    }
  };
  const levelRank = {
    poor: 0,
    visual: 1,
    possible: 2,
    strong: 3,
    exceptional: 4
  };
  let astrosphericScriptPromise = null;
  let astrosphericInitialized = false;
  let selectedAstrosphericLocationKey = "calgary";
  let clearDarkSkyLoaded = false;

  document.addEventListener("DOMContentLoaded", () => {
    initializeDetailedForecastPanels();
    loadPlannerData();
  });

  function initializeDetailedForecastPanels() {
    const astrosphericPanel = document.getElementById("astrospheric-forecast");
    const clearDarkSkyPanel = document.getElementById("clear-dark-sky-forecast");

    if (astrosphericPanel) {
      astrosphericPanel.addEventListener("toggle", () => {
        if (astrosphericPanel.open) {
          openAstrosphericPanel();
        }
      });

      document.querySelectorAll("[data-astrospheric-location]").forEach((button) => {
        button.addEventListener("click", () => {
          changeAstrosphericLocation(button.dataset.astrosphericLocation);
        });
      });
    }

    if (clearDarkSkyPanel) {
      clearDarkSkyPanel.addEventListener("toggle", () => {
        if (clearDarkSkyPanel.open) {
          loadClearDarkSkyChart();
        }
      });
    }
  }

  async function openAstrosphericPanel() {
    setAstrosphericControlsDisabled(true);
    setForecastStatus("astrospheric-status", "Loading the Astropheric forecast...");

    try {
      await loadAstrospheric();
      initializeAstrosphericEmbed();
      setAstrosphericControlsDisabled(false);
      updateAstrosphericButtonState();
    } catch (error) {
      console.error("Astropheric forecast error:", error);
      setForecastStatus(
        "astrospheric-status",
        "The Astropheric forecast could not be loaded. Please use the Session Planner recommendations or try again after reloading the page.",
        true
      );
    }
  }

  function loadAstrospheric() {
    if (astrosphericScriptPromise) {
      return astrosphericScriptPromise;
    }

    astrosphericScriptPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = astrosphericScriptUrl;
      script.async = true;
      script.addEventListener("load", resolve, { once: true });
      script.addEventListener("error", () => {
        reject(new Error("The Astropheric script request failed."));
      }, { once: true });
      document.head.appendChild(script);
    });

    return astrosphericScriptPromise;
  }

  function initializeAstrosphericEmbed() {
    if (astrosphericInitialized) {
      setAstrosphericReadyStatus();
      return;
    }

    const embed = window.m_AstrosphericEmbed;
    if (!embed || typeof embed.Create !== "function" || typeof embed.ChangeLocation !== "function") {
      throw new Error("The Astropheric embed API is unavailable after loading.");
    }

    const location = astrosphericLocations[selectedAstrosphericLocationKey];
    embed.Create("astrospheric-embed", location.lat, location.lon);
    astrosphericInitialized = true;
    setAstrosphericReadyStatus();
  }

  function changeAstrosphericLocation(locationKey) {
    const location = astrosphericLocations[locationKey];
    if (!location || !astrosphericInitialized) {
      return;
    }

    try {
      window.m_AstrosphericEmbed.ChangeLocation(location.lat, location.lon);
      selectedAstrosphericLocationKey = locationKey;
      updateAstrosphericButtonState();
      setAstrosphericReadyStatus();
    } catch (error) {
      console.error("Astropheric location error:", error);
      setForecastStatus("astrospheric-status", "The Astropheric location could not be changed. Please try another location.", true);
    }
  }

  function setAstrosphericControlsDisabled(disabled) {
    document.querySelectorAll("[data-astrospheric-location]").forEach((button) => {
      button.disabled = disabled;
    });
  }

  function updateAstrosphericButtonState() {
    document.querySelectorAll("[data-astrospheric-location]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.astrosphericLocation === selectedAstrosphericLocationKey));
    });
  }

  function setAstrosphericReadyStatus() {
    const location = astrosphericLocations[selectedAstrosphericLocationKey];
    setForecastStatus("astrospheric-status", `Showing the Astropheric forecast for ${location.label}.`);
  }

  function loadClearDarkSkyChart() {
    if (clearDarkSkyLoaded) {
      return;
    }

    const chart = document.getElementById("clear-dark-sky-chart");
    const source = chart && chart.dataset.src;
    if (!chart || !source) {
      setForecastStatus("clear-dark-sky-status", "The Clear Dark Sky chart is unavailable.", true);
      return;
    }

    clearDarkSkyLoaded = true;
    setForecastStatus("clear-dark-sky-status", "Loading the Clear Dark Sky chart...");
    chart.addEventListener("load", () => {
      chart.hidden = false;
      setForecastStatus("clear-dark-sky-status", "Clear Dark Sky chart loaded for Calgary.");
    }, { once: true });
    chart.addEventListener("error", () => {
      setForecastStatus("clear-dark-sky-status", "The Clear Dark Sky chart could not be loaded. Use the link below to open its forecast page.", true);
    }, { once: true });
    chart.src = source;
    chart.removeAttribute("data-src");
  }

  function setForecastStatus(id, message, isError) {
    const status = document.getElementById(id);
    if (!status) {
      return;
    }

    status.textContent = message;
    status.classList.toggle("detailed-forecast-status--error", Boolean(isError));
  }

  async function loadPlannerData() {
    const summary = document.getElementById("session-planner-summary");
    const cards = document.getElementById("session-planner-cards");

    try {
      const response = await fetch(dataUrl, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`Forecast data returned ${response.status}`);
      }

      const data = await response.json();
      validateData(data);
      renderPlanner(data);
    } catch (error) {
      console.error("Session Planner data error:", error);
      renderError(summary, cards);
    }
  }

  function validateData(data) {
    if (!data || typeof data !== "object") {
      throw new Error("Data is not an object.");
    }

    if (!data.location || typeof data.location !== "object") {
      throw new Error("Missing location.");
    }

    const locationFields = ["name", "latitude", "longitude", "timezone"];
    locationFields.forEach((field) => {
      if (data.location[field] === undefined || data.location[field] === null || data.location[field] === "") {
        throw new Error(`Missing location.${field}.`);
      }
    });

    if (!data.generatedAt || !data.dataSource || !Array.isArray(data.nights)) {
      throw new Error("Missing generatedAt, dataSource, or nights.");
    }

    if (data.nights.length !== 7) {
      throw new Error("Expected exactly seven nightly forecasts.");
    }
  }

  function renderPlanner(data) {
    setText("session-planner-location", `Forecasted location: ${data.location.name} (${data.location.latitude}, ${data.location.longitude})`);
    setText("session-planner-generated", `Generated: ${formatGeneratedAt(data.generatedAt, data.location.timezone)}`);
    setText("session-planner-source", `Data source: ${data.dataSource}`);

    renderSummary(data.nights, data.location.timezone);
    renderCards(data.nights, data.location.timezone);
  }

  function renderSummary(nights, timezone) {
    const summary = document.getElementById("session-planner-summary");
    summary.replaceChildren();

    const bestNights = nights
      .filter((night) => levelRank[getLevel(night)] >= levelRank.strong)
      .sort((a, b) => levelRank[getLevel(b)] - levelRank[getLevel(a)]);

    const heading = document.createElement("h2");
    heading.textContent = "Best nights this week";

    const copy = document.createElement("p");
    if (bestNights.length > 0) {
      copy.textContent = bestNights
        .map((night) => `${formatDisplayDate(night.date, night.weekday, timezone)}: ${night.recommendation.label} (${formatScore(night.recommendation.score)})`)
        .join(" | ");
    } else {
      copy.textContent = "No strong imaging nights appear in this forecast window.";
    }

    const disclaimer = document.createElement("p");
    disclaimer.className = "session-planner-disclaimer";
    disclaimer.textContent = "Forecast confidence drops further into the week, so treat later cards as planning hints only.";

    summary.append(heading, copy, disclaimer);
  }

  function renderCards(nights, timezone) {
    const container = document.getElementById("session-planner-cards");
    container.replaceChildren();

    nights.forEach((night) => {
      container.appendChild(renderNightCard(night, timezone));
    });
  }

  function renderNightCard(night, timezone) {
    const card = document.createElement("article");
    card.className = `session-planner-card session-planner-card--${getLevel(night)}`;

    const disclosure = document.createElement("details");
    disclosure.className = "session-planner-night-details";
    const validTargets = getValidTargetRecommendations(night);
    disclosure.append(
      renderNightSummary(night, timezone, validTargets),
      renderExpandedNightDetails(night, timezone, validTargets)
    );
    card.appendChild(disclosure);
    return card;
  }

  function renderNightSummary(night, timezone, validTargets) {
    const conditions = night && night.conditions ? night.conditions : {};
    const recommendation = night && night.recommendation ? night.recommendation : {};
    const summary = document.createElement("summary");
    summary.className = "session-planner-night-summary";

    const header = document.createElement("div");
    header.className = "session-planner-night-summary-header";
    const date = document.createElement("h3");
    date.textContent = formatDisplayDate(night.date, night.weekday, timezone);
    const badge = document.createElement("span");
    badge.className = "session-planner-recommendation";
    badge.textContent = text(recommendation.label);
    header.append(date, badge);

    const score = document.createElement("p");
    score.className = "session-planner-score-confidence";
    score.textContent = `${formatScore(recommendation.score)} · ${text(recommendation.confidence)} confidence`;

    const window = document.createElement("p");
    window.className = "session-planner-summary-window";
    window.textContent = formatTimeRange(
      conditions.bestWindowStart,
      conditions.bestWindowEnd,
      timezone,
      conditions.bestWindow
    );

    const weather = document.createElement("div");
    weather.className = "session-planner-compact-conditions";
    appendCompactMetric(weather, "Clouds", formatPercent(conditions.averageCloudCoverPercent));
    appendCompactMetric(weather, "Wind", formatWindSummary(conditions.wind));
    appendCompactMetric(weather, "Moon", formatMoonIllumination(conditions.moon));

    summary.append(header, score, window, weather);

    if (validTargets.length > 0) {
      const target = document.createElement("p");
      target.className = "session-planner-summary-target";
      const label = document.createElement("strong");
      label.textContent = "Suggested target: ";
      target.append(label, validTargets[0].displayName);
      summary.appendChild(target);
    }

    const priorityWarning = selectPriorityWarning(night, validTargets[0]);
    if (priorityWarning) {
      const warning = document.createElement("p");
      warning.className = "session-planner-summary-warning";
      const label = document.createElement("strong");
      label.textContent = `${priorityWarning.label}: `;
      warning.append(label, priorityWarning.message);
      summary.appendChild(warning);
    }

    const affordance = document.createElement("span");
    affordance.className = "session-planner-expand-affordance";
    affordance.textContent = formatExpandAffordance(validTargets.length);
    summary.appendChild(affordance);
    return summary;
  }

  function appendCompactMetric(parent, label, value) {
    const metric = document.createElement("span");
    const name = document.createElement("strong");
    name.textContent = `${label} `;
    metric.append(name, text(value));
    parent.appendChild(metric);
  }

  function renderExpandedNightDetails(night, timezone, validTargets) {
    const expanded = document.createElement("div");
    expanded.className = "session-planner-night-expanded";
    expanded.append(
      renderConditionsSection(night, timezone),
      renderTargetRecommendations(night, timezone, validTargets),
      renderPlanningNotes(night)
    );
    return expanded;
  }

  function renderConditionsSection(night, timezone) {
    const conditions = night && night.conditions ? night.conditions : {};
    const section = createExpandedSection("Conditions", "session-planner-conditions");
    const groups = document.createElement("div");
    groups.className = "session-planner-condition-groups";

    const observingEntries = [
      ["Best window", formatTimeRange(conditions.bestWindowStart, conditions.bestWindowEnd, timezone, conditions.bestWindow)]
    ];
    if (hasDistinctUsableHours(conditions)) {
      observingEntries.push(["Qualified window", formatHours(conditions.usableHours)]);
    }
    observingEntries.push(
      ["Visual window", formatHours(conditions.visualUsableHours)],
      ["Imaging window", formatHours(conditions.imagingUsableHours)],
      ["Astronomical night", formatBoolean(conditions.astronomicalNightOccurs)]
    );

    groups.append(
      createConditionGroup("Observing window", observingEntries),
      createConditionGroup("Weather", [
        ["Cloud cover", formatPercent(conditions.averageCloudCoverPercent)],
        ["Low cloud", formatPercent(conditions.averageLowCloudCoverPercent)],
        ["Precipitation", formatPercent(conditions.precipitationProbabilityPercent)],
        ["Wind and gusts", formatWind(conditions.wind)]
      ]),
      createConditionGroup("Environment", [
        ["Temperature", formatTemperatureC(conditions.temperature && conditions.temperature.expectedC)],
        ["Dew margin", formatTemperatureC(conditions.temperature && conditions.temperature.dewPointSpreadC)],
        ["Moon", formatMoonSummary(conditions.moon)]
      ])
    );
    section.appendChild(groups);
    return section;
  }

  function createExpandedSection(title, className) {
    const section = document.createElement("section");
    section.className = `session-planner-expanded-section ${className}`;
    const heading = document.createElement("h4");
    heading.textContent = title;
    section.appendChild(heading);
    return section;
  }

  function createConditionGroup(title, entries) {
    const group = document.createElement("section");
    group.className = "session-planner-condition-group";
    const heading = document.createElement("h5");
    heading.textContent = title;
    const details = document.createElement("dl");
    details.className = "session-planner-condition-list";
    entries.forEach(([label, value]) => addDetail(details, label, value));
    group.append(heading, details);
    return group;
  }

  function renderTargetRecommendations(night, timezone, validTargets) {
    const section = createExpandedSection("Target recommendations", "session-planner-targets");
    const recommendations = night && night.targetRecommendations;
    if (validTargets.length === 0) {
      const unavailable = document.createElement("p");
      unavailable.className = "session-planner-targets-unavailable";
      unavailable.textContent = recommendations && typeof recommendations.message === "string"
        ? recommendations.message
        : "Detailed target recommendations are unavailable for this forecast.";
      section.appendChild(unavailable);
      return section;
    }

    const primary = validTargets[0];
    const primaryCard = document.createElement("div");
    primaryCard.className = "session-planner-primary-target";

    const title = document.createElement("div");
    title.className = "session-planner-target-title";
    const name = document.createElement("h5");
    name.textContent = primary.displayName;
    const metadata = document.createElement("p");
    metadata.textContent = [
      primary.primaryCatalogId && primary.primaryCatalogId !== primary.displayName ? primary.primaryCatalogId : null,
      capitalize(primary.recommendationRating),
      formatDecimalScore(primary.recommendationScore)
    ].filter(Boolean).join(" · ");
    title.append(name, metadata);

    const metrics = document.createElement("dl");
    metrics.className = "session-planner-target-metrics";
    addDetail(metrics, "Type", primary.targetType);
    addDetail(metrics, "Observing window", formatTimeRange(primary.usableWindowOverlapStart, primary.usableWindowOverlapEnd, timezone));
    addDetail(metrics, "Usable overlap", formatMinutes(primary.usableWindowOverlapMinutes));
    addDetail(metrics, "Peak altitude", formatAltitude(primary.maximumAltitudeDeg));
    addDetail(metrics, "Peak time", formatLocalTime(primary.maximumAltitudeTime, timezone));
    addDetail(metrics, "Lunar impact", capitalize(primary.lunarImpactRating));
    primaryCard.append(title, metrics);

    const reasoning = renderTargetReasoning(primary);
    if (reasoning) {
      primaryCard.appendChild(reasoning);
    }
    section.appendChild(primaryCard);

    if (validTargets.length > 1) {
      const alternatives = document.createElement("div");
      alternatives.className = "session-planner-target-alternatives";
      const alternativesHeading = document.createElement("h5");
      alternativesHeading.textContent = "Also recommended";
      alternatives.appendChild(alternativesHeading);

      validTargets.slice(1).forEach((target) => {
        const item = document.createElement("div");
        item.className = "session-planner-alternative-target";
        const itemName = document.createElement("strong");
        itemName.textContent = `#${target.rank} ${target.displayName}`;
        const itemIdentity = document.createElement("p");
        itemIdentity.className = "session-planner-alternative-identity";
        itemIdentity.textContent = [
          target.primaryCatalogId && target.primaryCatalogId !== target.displayName ? target.primaryCatalogId : null,
          target.targetType
        ].filter(Boolean).join(" · ");
        const itemMetrics = document.createElement("p");
        itemMetrics.textContent = [
          capitalize(target.recommendationRating),
          formatDecimalScore(target.recommendationScore),
          formatCompactMinutes(target.usableWindowOverlapMinutes),
          `${formatAltitude(target.maximumAltitudeDeg)} peak at ${formatLocalTime(target.maximumAltitudeTime, timezone)}`,
          `${capitalize(target.lunarImpactRating)} Moon impact`
        ].join(" · ");
        item.append(itemName);
        if (itemIdentity.textContent) {
          item.appendChild(itemIdentity);
        }
        item.appendChild(itemMetrics);
        alternatives.appendChild(item);
      });
      section.appendChild(alternatives);
    }

    return section;
  }

  function renderTargetReasoning(target) {
    const hasReasons = hasTextValues(target.reasons);
    const hasWarnings = hasTextValues(target.warnings);
    if (!hasReasons && !hasWarnings) {
      return null;
    }

    const disclosure = document.createElement("details");
    disclosure.className = "session-planner-target-reasoning";
    const summary = document.createElement("summary");
    summary.textContent = "Why this target?";
    const content = document.createElement("div");
    content.className = "session-planner-target-reasoning-content";

    if (hasReasons) {
      const label = document.createElement("p");
      label.className = "session-planner-target-reasoning-label";
      label.textContent = "Why it ranks well";
      content.appendChild(label);
      appendTextList(content, target.reasons, "session-planner-target-reasons");
    }
    if (hasWarnings) {
      const label = document.createElement("p");
      label.className = "session-planner-target-reasoning-label";
      label.textContent = "Target considerations";
      content.appendChild(label);
      appendTextList(content, target.warnings, "session-planner-target-warnings");
    }

    disclosure.append(summary, content);
    return disclosure;
  }

  function renderPlanningNotes(night) {
    const section = createExpandedSection("Planning notes", "session-planner-planning-notes");
    const warnings = Array.isArray(night && night.warnings) ? night.warnings : [];
    const messages = deduplicateMessages([
      ...(Array.isArray(night && night.reasons) ? night.reasons : []),
      ...splitMessageSentences(night && night.explanation),
      ...warnings
    ]);

    if (messages.length === 0) {
      const unavailable = document.createElement("p");
      unavailable.textContent = "No additional planning notes are available.";
      section.appendChild(unavailable);
      return section;
    }

    const list = document.createElement("ul");
    list.className = "session-planner-planning-list";
    messages.forEach((message) => {
      const item = document.createElement("li");
      if (warnings.some((warning) => messagesOverlap(message, warning))) {
        item.className = "session-planner-planning-warning";
        const label = document.createElement("strong");
        label.textContent = "Warning: ";
        item.append(label, message);
      } else {
        item.textContent = message;
      }
      list.appendChild(item);
    });
    section.appendChild(list);
    return section;
  }

  function hasDistinctUsableHours(conditions) {
    const usable = conditions && conditions.usableHours;
    return typeof usable === "number" &&
      usable !== conditions.visualUsableHours &&
      usable !== conditions.imagingUsableHours;
  }

  function hasTextValues(values) {
    return Array.isArray(values) && values.some((value) => typeof value === "string" && value.trim());
  }

  function formatExpandAffordance(targetCount) {
    if (targetCount === 1) {
      return "View full forecast and 1 target";
    }
    if (targetCount > 1) {
      return `View full forecast and ${targetCount} targets`;
    }
    return "View full forecast";
  }

  function selectPriorityWarning(night, primaryTarget) {
    const messages = deduplicateMessages([
      ...(Array.isArray(night && night.warnings) ? night.warnings : []),
      ...(Array.isArray(primaryTarget && primaryTarget.warnings) ? primaryTarget.warnings : [])
    ]);
    if (messages.length === 0) {
      return null;
    }

    const ranked = messages.map((message, index) => ({
      message,
      index,
      priority: warningPriority(message)
    })).sort((left, right) => left.priority - right.priority || left.index - right.index);
    const selected = ranked[0];
    return {
      label: selected.priority >= 3 && selected.priority <= 6 ? "Note" : "Warning",
      message: selected.message
    };
  }

  function warningPriority(message) {
    const normalized = normalizeMessage(message);
    if (/safety|cloud|precip|rain|snow|storm|wind|gust|weather|visibility/.test(normalized)) {
      return 1;
    }
    if (/dew/.test(normalized)) {
      return 2;
    }
    if (/imaging|visual observing/.test(normalized)) {
      return 3;
    }
    if (/target|available|overlap|altitude|timing/.test(normalized)) {
      return 4;
    }
    if (/confidence/.test(normalized)) {
      return 5;
    }
    if (/weekday|schedule|fatigue|after midnight/.test(normalized)) {
      return 6;
    }
    return 7;
  }

  function splitMessageSentences(value) {
    if (typeof value !== "string" || !value.trim()) {
      return [];
    }
    return value.match(/[^.!?]+[.!?]+|[^.!?]+$/g) || [];
  }

  function deduplicateMessages(values) {
    const messages = [];
    values.filter((value) => typeof value === "string" && value.trim()).forEach((value) => {
      const candidate = value.trim();
      const duplicateIndex = messages.findIndex((message) => messagesOverlap(message, candidate));
      if (duplicateIndex === -1) {
        messages.push(candidate);
      } else if (candidate.length < messages[duplicateIndex].length) {
        messages[duplicateIndex] = candidate;
      }
    });
    return messages;
  }

  function messagesOverlap(left, right) {
    const normalizedLeft = normalizeMessage(left);
    const normalizedRight = normalizeMessage(right);
    return normalizedLeft === normalizedRight ||
      (Math.min(normalizedLeft.length, normalizedRight.length) >= 24 &&
        (normalizedLeft.includes(normalizedRight) || normalizedRight.includes(normalizedLeft)));
  }

  function normalizeMessage(value) {
    return String(value || "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  }

  function getValidTargetRecommendations(night) {
    const recommendations = night && night.targetRecommendations;
    if (!recommendations || !Array.isArray(recommendations.topTargets)) {
      return [];
    }

    return recommendations.topTargets.filter(isValidTargetRecommendation).slice(0, 3);
  }

  function isValidTargetRecommendation(target) {
    return Boolean(
      target &&
      typeof target === "object" &&
      typeof target.displayName === "string" &&
      target.displayName.length > 0 &&
      typeof target.rank === "number" &&
      Number.isFinite(target.recommendationScore) &&
      target.recommendationScore >= 0 &&
      target.recommendationScore <= 100 &&
      Number.isFinite(target.usableWindowOverlapMinutes) &&
      Number.isFinite(target.maximumAltitudeDeg) &&
      typeof target.lunarImpactRating === "string"
    );
  }

  function appendTextList(parent, values, className, maximumItems) {
    if (!Array.isArray(values) || values.length === 0) {
      return;
    }
    const list = document.createElement("ul");
    list.className = className;
    const validValues = values.filter((value) => typeof value === "string" && value);
    const displayedValues = typeof maximumItems === "number"
      ? validValues.slice(0, maximumItems)
      : validValues;
    displayedValues.forEach((value) => {
      const item = document.createElement("li");
      item.textContent = value;
      list.appendChild(item);
    });
    if (list.children.length > 0) {
      parent.appendChild(list);
    }
  }

  function addDetail(list, label, value) {
    const term = document.createElement("dt");
    term.textContent = label;

    const description = document.createElement("dd");
    description.textContent = text(value);

    list.append(term, description);
  }

  function renderError(summary, cards) {
    const box = document.createElement("div");
    box.className = "session-planner-error";

    const heading = document.createElement("h2");
    heading.textContent = "Forecast data could not be loaded";

    const message = document.createElement("p");
    message.textContent = "The Session Planner is unavailable because the forecast JSON file is missing or malformed. Please try again after the data file is restored.";

    box.append(heading, message);
    summary.replaceChildren(box);
    cards.replaceChildren();
  }

  function getLevel(night) {
    const level = night && night.recommendation && night.recommendation.level;
    return Object.prototype.hasOwnProperty.call(levelRank, level) ? level : "poor";
  }

  function formatGeneratedAt(value, timezone) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return text(value);
    }

    return new Intl.DateTimeFormat("en-CA", {
      dateStyle: "medium",
      timeStyle: "short",
      hour12: true,
      timeZone: timezone || "America/Edmonton"
    }).format(date);
  }

  function formatDisplayDate(value, fallbackWeekday, timezone) {
    const match = typeof value === "string" && value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) {
      return [fallbackWeekday, value].filter(Boolean).join(", ") || "Date unavailable";
    }

    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    const date = new Date(Date.UTC(year, month - 1, day, 18));
    if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) {
      return [fallbackWeekday, value].filter(Boolean).join(", ");
    }

    try {
      return new Intl.DateTimeFormat("en-US", {
        weekday: "long",
        month: "long",
        day: "numeric",
        timeZone: timezone || "America/Edmonton"
      }).format(date);
    } catch (error) {
      console.error("Session Planner date formatting error:", error);
      return [fallbackWeekday, value].filter(Boolean).join(", ");
    }
  }

  function formatTimeRange(startValue, endValue, timezone, fallback) {
    const start = formatZonedTime(startValue, timezone);
    const end = formatZonedTime(endValue, timezone);
    if (!start || !end) {
      return text(fallback);
    }

    if (start.zone && end.zone && start.zone !== end.zone) {
      return `${start.time} ${start.zone}–${end.time} ${end.zone}`;
    }
    const zone = end.zone || start.zone;
    return `${start.time}–${end.time}${zone ? ` ${zone}` : ""}`;
  }

  function formatZonedTime(value, timezone) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return null;
    }

    try {
      const options = {
        hour: "numeric",
        minute: "2-digit",
        hour12: true,
        timeZone: timezone || "America/Edmonton"
      };
      const time = new Intl.DateTimeFormat("en-US", options).format(date);
      const zoneParts = new Intl.DateTimeFormat("en-US", {
        ...options,
        timeZoneName: "short"
      }).formatToParts(date);
      const zonePart = zoneParts.find((part) => part.type === "timeZoneName");
      return {
        time,
        zone: zonePart ? zonePart.value : ""
      };
    } catch (error) {
      console.error("Session Planner time formatting error:", error);
      return null;
    }
  }

  function formatHours(value) {
    if (typeof value !== "number") {
      return value;
    }
    if (value === 0) {
      return "None";
    }
    const formatted = value.toFixed(value % 1 === 0 ? 0 : 1);
    return `${formatted} ${value === 1 ? "hour" : "hours"}`;
  }

  function formatPercent(value) {
    return typeof value === "number" ? `${value}%` : value;
  }

  function formatScore(value) {
    return typeof value === "number" ? `${Math.round(value)}/100` : text(value);
  }

  function formatDecimalScore(value) {
    return typeof value === "number" ? `${value.toFixed(1)}/100` : text(value);
  }

  function formatMinutes(value) {
    if (typeof value !== "number") {
      return text(value);
    }
    const rounded = Math.round(value);
    return `${rounded} ${rounded === 1 ? "minute" : "minutes"}`;
  }

  function formatCompactMinutes(value) {
    return typeof value === "number" ? `${Math.round(value)} min` : text(value);
  }

  function formatAltitude(value) {
    return typeof value === "number" ? `${value.toFixed(1)}°` : text(value);
  }

  function formatLocalTime(value, timezone) {
    const formatted = formatZonedTime(value, timezone);
    return formatted ? `${formatted.time}${formatted.zone ? ` ${formatted.zone}` : ""}` : text(value);
  }

  function capitalize(value) {
    if (typeof value !== "string" || value.length === 0) {
      return text(value);
    }
    return value.charAt(0).toUpperCase() + value.slice(1);
  }

  function formatBoolean(value) {
    if (typeof value !== "boolean") {
      return value;
    }

    return value ? "Yes" : "No";
  }

  function formatWind(wind) {
    if (!wind) {
      return "Wind data unavailable";
    }

    return `${text(wind.sustainedKph)} km/h, gusts ${text(wind.gustKph)} km/h`;
  }

  function formatWindSummary(wind) {
    if (!wind) {
      return "unavailable";
    }
    return `${text(wind.sustainedKph)} km/h`;
  }

  function formatTemperatureC(value) {
    return typeof value === "number" ? `${value}°C` : text(value);
  }

  function formatMoonIllumination(moon) {
    if (!moon || typeof moon.illuminationPercent !== "number") {
      return "unavailable";
    }
    return `${Math.round(moon.illuminationPercent)}%`;
  }

  function formatMoonSummary(moon) {
    if (!moon || typeof moon.illuminationPercent !== "number") {
      return "Moon data unavailable";
    }

    const illumination = `${Math.round(moon.illuminationPercent)}% illuminated`;
    if (moon.aboveHorizon === false) {
      return `${illumination} · below horizon`;
    }
    if (typeof moon.altitudeDegrees === "number") {
      return `${illumination} · ${Math.round(moon.altitudeDegrees)}° high`;
    }
    if (moon.aboveHorizon === true) {
      return `${illumination} · above horizon`;
    }

    return illumination;
  }

  function setText(id, value) {
    const element = document.getElementById(id);
    if (element) {
      element.textContent = text(value);
    }
  }

  function text(value) {
    if (value === undefined || value === null || value === "") {
      return "Unavailable";
    }

    return String(value);
  }
})();
