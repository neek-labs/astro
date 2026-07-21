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

    renderSummary(data.nights);
    renderCards(data.nights);
  }

  function renderSummary(nights) {
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
        .map((night) => `${night.weekday}, ${night.date}: ${night.recommendation.label} (${formatScore(night.recommendation.score)})`)
        .join(" | ");
    } else {
      copy.textContent = "No strong imaging nights appear in this forecast window.";
    }

    const disclaimer = document.createElement("p");
    disclaimer.className = "session-planner-disclaimer";
    disclaimer.textContent = "Forecast confidence drops further into the week, so treat later cards as planning hints only.";

    summary.append(heading, copy, disclaimer);
  }

  function renderCards(nights) {
    const container = document.getElementById("session-planner-cards");
    container.replaceChildren();

    nights.forEach((night) => {
      const card = document.createElement("article");
      card.className = `session-planner-card session-planner-card--${getLevel(night)}`;

      const header = document.createElement("div");
      header.className = "session-planner-card-header";

      const title = document.createElement("div");
      const date = document.createElement("h3");
      date.textContent = `${night.weekday}, ${night.date}`;
      const confidence = document.createElement("p");
      confidence.textContent = `Confidence: ${text(night.recommendation && night.recommendation.confidence)} | Score: ${formatScore(night.recommendation && night.recommendation.score)}`;
      title.append(date, confidence);

      const badge = document.createElement("div");
      badge.className = "session-planner-recommendation";
      badge.textContent = `${levelSymbol(getLevel(night))} ${text(night.recommendation && night.recommendation.label)}`;

      header.append(title, badge);

      const details = document.createElement("dl");
      details.className = "session-planner-detail-grid";
      addDetail(details, "Best window", night.conditions && night.conditions.bestWindow);
      addDetail(details, "Usable hours", formatHours(night.conditions && night.conditions.usableHours));
      addDetail(details, "Visual usable", formatHours(night.conditions && night.conditions.visualUsableHours));
      addDetail(details, "Imaging usable", formatHours(night.conditions && night.conditions.imagingUsableHours));
      addDetail(details, "Astronomical night", formatBoolean(night.conditions && night.conditions.astronomicalNightOccurs));
      addDetail(details, "Cloud cover", formatPercent(night.conditions && night.conditions.averageCloudCoverPercent));
      addDetail(details, "Low cloud", formatPercent(night.conditions && night.conditions.averageLowCloudCoverPercent));
      addDetail(details, "Precipitation", formatPercent(night.conditions && night.conditions.precipitationProbabilityPercent));
      addDetail(details, "Wind", formatWind(night.conditions && night.conditions.wind));
      addDetail(details, "Temp/dew spread", formatTemperature(night.conditions && night.conditions.temperature));
      addDetail(details, "Moon", formatMoon(night.conditions && night.conditions.moon));

      const explanation = document.createElement("p");
      explanation.className = "session-planner-explanation";
      explanation.textContent = text(night.explanation);

      card.append(header, details);
      renderTargetRecommendations(card, night);
      card.append(explanation);

      if (Array.isArray(night.warnings) && night.warnings.length > 0) {
        const warnings = document.createElement("ul");
        warnings.className = "session-planner-warnings";
        night.warnings.forEach((warning) => {
          const item = document.createElement("li");
          item.textContent = warning;
          warnings.appendChild(item);
        });
        card.appendChild(warnings);
      }

      container.appendChild(card);
    });
  }

  function renderTargetRecommendations(card, night) {
    const section = document.createElement("section");
    section.className = "session-planner-targets";

    const heading = document.createElement("h4");
    heading.textContent = "Target recommendations";
    section.appendChild(heading);

    const recommendations = night && night.targetRecommendations;
    const validTargets = getValidTargetRecommendations(night);
    if (validTargets.length === 0) {
      const unavailable = document.createElement("p");
      unavailable.className = "session-planner-targets-unavailable";
      unavailable.textContent = recommendations && typeof recommendations.message === "string"
        ? recommendations.message
        : "Detailed target recommendations are unavailable for this forecast.";
      section.appendChild(unavailable);
      card.appendChild(section);
      return;
    }

    const primary = validTargets[0];
    const primaryCard = document.createElement("div");
    primaryCard.className = "session-planner-primary-target";

    const title = document.createElement("div");
    title.className = "session-planner-target-title";
    const name = document.createElement("h5");
    name.textContent = primary.displayName;
    const catalogueId = document.createElement("p");
    catalogueId.textContent = primary.primaryCatalogId && primary.primaryCatalogId !== primary.displayName
      ? primary.primaryCatalogId
      : "Primary recommendation";
    const score = document.createElement("strong");
    score.textContent = `${formatDecimalScore(primary.recommendationScore)} · ${capitalize(primary.recommendationRating)}`;
    title.append(name, catalogueId, score);

    const metrics = document.createElement("dl");
    metrics.className = "session-planner-target-metrics";
    addDetail(metrics, "Type", primary.targetType);
    addDetail(metrics, "Usable overlap", formatMinutes(primary.usableWindowOverlapMinutes));
    addDetail(metrics, "Maximum altitude", formatAltitude(primary.maximumAltitudeDeg));
    addDetail(metrics, "Peak", formatLocalTime(primary.maximumAltitudeTime));
    addDetail(metrics, "Lunar impact", capitalize(primary.lunarImpactRating));
    primaryCard.append(title, metrics);

    appendTextList(primaryCard, primary.reasons, "session-planner-target-reasons", 3);
    appendTextList(primaryCard, primary.warnings, "session-planner-target-warnings", 3);
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
        const itemMetrics = document.createElement("p");
        itemMetrics.textContent = [
          formatDecimalScore(target.recommendationScore),
          formatMinutes(target.usableWindowOverlapMinutes),
          formatAltitude(target.maximumAltitudeDeg),
          `${capitalize(target.lunarImpactRating)} lunar rating`
        ].join(" · ");
        item.append(itemName, itemMetrics);
        alternatives.appendChild(item);
      });
      section.appendChild(alternatives);
    }

    card.appendChild(section);
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
    values.filter((value) => typeof value === "string" && value).slice(0, maximumItems).forEach((value) => {
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

  function levelSymbol(level) {
    const symbols = {
      poor: "Stop",
      visual: "Eye",
      possible: "Check",
      strong: "Camera",
      exceptional: "Star"
    };

    return symbols[level] || "Info";
  }

  function formatGeneratedAt(value, timezone) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return text(value);
    }

    return new Intl.DateTimeFormat("en-CA", {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: timezone || "America/Edmonton"
    }).format(date);
  }

  function formatHours(value) {
    return typeof value === "number" ? `${value.toFixed(value % 1 === 0 ? 0 : 1)} hours` : value;
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
    return typeof value === "number" ? `${Math.round(value)} minutes` : text(value);
  }

  function formatAltitude(value) {
    return typeof value === "number" ? `${value.toFixed(1)}°` : text(value);
  }

  function formatLocalTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return text(value);
    }
    return new Intl.DateTimeFormat("en-CA", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: "America/Edmonton",
      timeZoneName: "short"
    }).format(date);
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
      return "";
    }

    return `${text(wind.sustainedKph)} kph, gusts ${text(wind.gustKph)} kph`;
  }

  function formatTemperature(temperature) {
    if (!temperature) {
      return "";
    }

    return `${text(temperature.expectedC)} C, dew spread ${text(temperature.dewPointSpreadC)} C`;
  }

  function formatMoon(moon) {
    if (!moon) {
      return "";
    }

    const parts = [formatPercent(moon.illuminationPercent)];
    if (typeof moon.aboveHorizon === "boolean") {
      parts.push(moon.aboveHorizon ? "above horizon" : "below horizon");
    }
    if (typeof moon.altitudeDegrees === "number") {
      parts.push(`${moon.altitudeDegrees} deg alt`);
    }

    return parts.filter(Boolean).join(", ");
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
