# astro

Static astronomy content for `astro.nickhall.tech`.

## Calgary Astronomy Session Planner

The Session Planner helps evaluate upcoming Calgary nights for visual astronomy and astrophotography. Stage 2 adds a deterministic Python forecast generator that combines Open-Meteo hourly weather, local solar twilight calculations, Moon context, configurable scoring, and atomic JSON publishing for the static frontend.

The Stage 2 generator writes `data/session-planner.json` for the static `session-planner.html` page. It does not run on a schedule, create pull requests, deploy, or use AI. Stage 4A/4B target geometry and lunar impact are generated separately as described below.

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

### Stage 4A Target Visibility and Stage 4B Lunar Impact

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

Stage 4B enriches those same nightly target records with objective lunar geometry:

- Moon illumination at the midpoint of the nightly darkness sample grid.
- Moon altitude and Moon-to-target angular separation at darkness start, the
  target's Stage 4A peak, and the nearest sample to the observable-window midpoint.
- The minimum separation and its UTC timestamp across the exact Stage 4A observable
  samples.
- Whether the Moon is above the geometric horizon at any observable sample.
- A preliminary 0–100 lunar-impact score and classification, where 100 means little
  or no expected Moon interference and 0 means severe expected interference.

Apparent topocentric Moon coordinates and altitudes are vectorized once per nightly
ten-minute grid and reused for every target. Each fixed ICRS target is transformed
to that lunar frame before using Astropy's coordinate separation rather than a
separate spherical-trigonometry implementation. Illumination uses the same
Sun-Moon elongation helper as the Stage 2 forecast, avoiding duplicate phase models.

The heuristic returns 100 when the Moon stays at or below 0 degrees for the whole
target window. Otherwise it uses:

```text
score = 0.50 × separation component
      + 0.30 × (100 - illumination percent)
      + 0.20 × Moon-altitude component
```

The separation component is linearly interpolated through `(0°, 0)`, `(30°, 20)`,
`(60°, 50)`, `(90°, 80)`, and `(120°, 100)`, clamping beyond the endpoints. The
Moon-altitude component is interpolated through `(0°, 100)`, `(15°, 75)`,
`(30°, 50)`, `(60°, 25)`, and `(90°, 0)`. The representative altitude is the
observable-midpoint sample. Ratings are `excellent` from 85, `good` from 70,
`moderate` from 50, `poor` from 25, and `severe` below 25.

This score is a transparent recommendation heuristic, not a scientifically
definitive sky-brightness model. It does not account for atmospheric extinction,
local obstructions, haze, wavelength, filters, target surface brightness, or
equipment. Targets without an observable window receive null window metrics, score,
and rating rather than a misleading value.

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

Use alternate paths when validating without replacing the checked-in generated
file:

```powershell
python scripts/calculate_target_visibility.py `
  --config config/session-planner.json `
  --catalogue data/astronomy-targets-master-stage3b-coordinates.json `
  --forecast data/session-planner.json `
  --output data/astronomy-target-visibility.json `
  --date 2026-08-15 --days 1
```

Run only the Stage 4 tests or the complete suite with:

```powershell
python -m pytest tests/test_target_visibility_stage4a.py tests/test_lunar_impact_stage4b.py
python -m pytest
```

The command prints a readable nightly summary and atomically writes schema `0.2`
JSON. Each night contains `moon.illumination_percent`; each existing Stage 4A target
record retains its fields and gains a nested snake_case `moon` object. Serialization
rejects non-finite values so generated output cannot contain `NaN`.

Stage 4B intentionally excludes weather combination, equipment matching, filter
selection, field-of-view suitability, and final ranking. Stage 4C should consume the
visibility and lunar-impact records as separate, explainable inputs to final target
recommendation scoring.

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

- Stage 4C: combine target visibility, lunar impact, and weather into final target
  recommendations before adding equipment and field-of-view suitability.
- Add scheduled GitHub automation and reviewable pull requests.
