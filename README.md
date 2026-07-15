# astro

Static astronomy content for `astro.nickhall.tech`.

## Calgary Astronomy Session Planner

The Session Planner helps evaluate upcoming Calgary nights for visual astronomy and astrophotography. Stage 2 adds a deterministic Python forecast generator that combines Open-Meteo hourly weather, local solar twilight calculations, Moon context, configurable scoring, and atomic JSON publishing for the static frontend.

The Stage 2 generator writes `data/session-planner.json` for the static `session-planner.html` page. It does not run on a schedule, create pull requests, deploy, or use AI. Stage 4A target visibility is generated separately as described below.

### Stage 2 Capabilities

- Fetches live hourly forecast data from the Open-Meteo Forecast API for Calgary, Alberta.
- Evaluates seven observing nights using the local evening date in `America/Edmonton`.
- Calculates visual-usable darkness when the Sun is below -6 degrees and imaging-usable darkness when the Sun is below -12 degrees.
- Indicates whether true astronomical night occurs when the Sun drops below -18 degrees.
- Handles Calgary summer nights normally, including periods where astronomical darkness never occurs.
- Finds the strongest contiguous observing window instead of relying on whole-night averages.
- Scores nights from 0 to 100 and classifies them as `poor`, `visual`, `possible`, `strong`, or `exceptional`.
- Preserves the last valid JSON forecast if generation fails.

### Scoring Overview

Scoring values are configured in `config/session-planner.json` rather than buried in code. The initial weights are:

- 35% cloud and low-cloud conditions
- 15% precipitation risk
- 15% contiguous usable duration
- 10% wind and gusts
- 10% dew-point spread and humidity
- 5% visibility
- 5% darkness quality
- 5% scheduling convenience

Weather and astronomy dominate the score. Scheduling convenience only applies a small configurable penalty to Sunday-through-Thursday windows that run substantially after midnight, and it should not turn excellent conditions into a poor recommendation.

Thresholds, location, forecast length, weather limits, minimum window lengths, and scoring weights can be adjusted in `config/session-planner.json`.

### Forecast Generation

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m pytest
python scripts/generate_session_forecast.py
python -m http.server 8000
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m pytest
python scripts/generate_session_forecast.py
python -m http.server 8000
```

Then open:

```text
http://localhost:8000/session-planner.html
```

The generator validates configuration, weather responses, generated night records, and the final frontend schema. It writes to a temporary file next to `data/session-planner.json`, flushes it, and atomically replaces the forecast only after every validation step succeeds. If any step fails, the command exits non-zero and leaves the previous forecast file unchanged.

### Stage 4A Target Visibility

Stage 4A calculates geometry-only visibility for every target in
`data/astronomy-targets-master-stage3b-coordinates.json` and writes the next seven
observing nights to `data/astronomy-target-visibility.json`. The master catalogue
remains unchanged; generated records join back to it with `target_id`.

The calculation uses the shared Calgary location, timezone-aware local timestamps,
ICRS/J2000 coordinates, and Astropy AltAz transformations sampled every ten minutes.
It prefers astronomical darkness (Sun below -18 degrees), then falls back to the
planner's existing imaging (-12 degrees) or visual (-6 degrees) useful-darkness
definitions when Calgary summer nights require it. A target is observable when it
reaches the configured 25-degree minimum altitude; that threshold avoids the most
obstructed and atmosphere-heavy part of the horizon.

Install and test with the same project environment:

```powershell
pip install -r requirements.txt
python -m pytest
python scripts/calculate_target_visibility.py
```

Run a deterministic one-night geometry check with:

```powershell
python scripts/calculate_target_visibility.py --date 2026-08-15 --days 1
```

The command prints a readable nightly summary and atomically writes the JSON output.
Stage 4A intentionally excludes weather, Moon conditions, filter suitability, and
field-of-view scoring so target geometry can be validated independently.

## Running Locally

Because the Session Planner fetches JSON, test it through a local web server instead of opening the page with `file://`.

```bash
python -m http.server 8000
```

Then open:

```text
http://localhost:8000/session-planner.html
```

## Testing JSON Loading

To verify normal loading:

1. Start the local server with `python -m http.server 8000`.
2. Open `http://localhost:8000/session-planner.html`.
3. Confirm the generated timestamp, data source, weekly summary, score, darkness details, and seven nightly cards render.
4. Confirm the browser console has no errors.

To verify the error state, temporarily rename `data/session-planner.json` or make a malformed local copy while testing through the web server. Reload the page and confirm a visible error message appears. Restore the valid JSON file before committing.

## Planned Future Stages

- Combine Stage 4A target geometry with weather and Moon constraints in a later stage.
- Add scheduled GitHub automation and reviewable pull requests.
