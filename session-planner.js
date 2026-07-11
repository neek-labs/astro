(function () {
  const dataUrl = "data/session-planner.json";
  const levelRank = {
    poor: 0,
    visual: 1,
    possible: 2,
    strong: 3,
    exceptional: 4
  };

  document.addEventListener("DOMContentLoaded", () => {
    loadPlannerData();
  });

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
    setText("session-planner-location", `${data.location.name} (${data.location.latitude}, ${data.location.longitude})`);
    setText("session-planner-generated", `Generated: ${formatGeneratedAt(data.generatedAt, data.location.timezone)}`);
    setText("session-planner-source", `Data source: ${data.dataSource}`);
    setText(
      "session-planner-sample-note",
      data.sampleData ? "Sample data is being displayed for Stage 1. Do not use it for real observing decisions." : ""
    );

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
        .map((night) => `${night.weekday}, ${night.date}: ${night.recommendation.label}`)
        .join(" | ");
    } else {
      copy.textContent = "No strong imaging nights appear in this sample week.";
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
      confidence.textContent = `Confidence: ${text(night.recommendation && night.recommendation.confidence)}`;
      title.append(date, confidence);

      const badge = document.createElement("div");
      badge.className = "session-planner-recommendation";
      badge.textContent = `${levelSymbol(getLevel(night))} ${text(night.recommendation && night.recommendation.label)}`;

      header.append(title, badge);

      const details = document.createElement("dl");
      details.className = "session-planner-detail-grid";
      addDetail(details, "Best window", night.conditions && night.conditions.bestWindow);
      addDetail(details, "Usable hours", formatHours(night.conditions && night.conditions.usableHours));
      addDetail(details, "Cloud cover", formatPercent(night.conditions && night.conditions.averageCloudCoverPercent));
      addDetail(details, "Precipitation", formatPercent(night.conditions && night.conditions.precipitationProbabilityPercent));
      addDetail(details, "Wind", formatWind(night.conditions && night.conditions.wind));
      addDetail(details, "Temp/dew spread", formatTemperature(night.conditions && night.conditions.temperature));
      addDetail(details, "Moon", formatPercent(night.conditions && night.conditions.moon && night.conditions.moon.illuminationPercent));
      addDetail(details, "Target", night.suggestedTarget);
      addDetail(details, "Equipment", night.suggestedEquipment);

      const explanation = document.createElement("p");
      explanation.className = "session-planner-explanation";
      explanation.textContent = text(night.explanation);

      card.append(header, details, explanation);

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
    message.textContent = "The Session Planner is unavailable because the sample JSON file is missing or malformed. Please try again after the data file is restored.";

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
