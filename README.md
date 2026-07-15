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

The command prints a readable nightly summary and atomically writes schema `0.3`
JSON. Each night contains `moon.illumination_percent`; each existing Stage 4A target
record retains its fields and gains a nested snake_case `moon` object and compact
timestamped `altitude_samples` used by Stage 4C. Serialization rejects non-finite
values so generated output cannot contain `NaN`.

### Stage 4C Final Nightly Target Recommendations

Stage 4C joins these existing files without changing the static target catalogue:

- `data/session-planner.json`: Stage 2 weather qualification and structured best
  window timestamps.
- `data/astronomy-target-visibility.json`: Stage 4A visibility, altitude samples,
  and Stage 4B lunar impact.
- `data/astronomy-targets-master-stage3b-coordinates.json`: stable IDs, display
  metadata, object type, and imaging mode.
- `config/session-planner.json`: recommendation weights, result limit, overlap
  minimum, and class-adjustment limit.

The nightly weather score still answers whether the night is suitable for observing.
The separate target score assumes the night is usable and ranks which targets fit
the weather-qualified window. Poor weather returns no formal targets; visual weather
returns explicitly opportunistic visual candidates.

A candidate must be observable, have positive observable duration, a finite maximum
altitude, a Stage 4B lunar score, and at least 30 minutes of overlap with the
structured Stage 2 best window. The model is:

```text
base target score = 30% usable-window overlap
                  + 25% altitude quality
                  + 25% Stage 4B lunar impact
                  + 10% timing convenience
                  + 10% catalogue priority

final target score = clamp(base target score + target-class adjustment, 0, 100)
```

Overlap is interpolated through 0/0, 30/20, 60/50, 120/80, and 180/100
(minutes/component score). Altitude is interpolated through 25/0, 35/35, 45/65,
60/90, and 75/100 (degrees/component score), combining 60% maximum altitude and
40% usable-overlap midpoint altitude. Timing combines whether the target peaks in
the overlap (40%), coverage of the weather window (40%), and delay after the window
begins (20%). Catalogue priority is a neutral 50 because the catalogue has no
normalized priority field.

Validated target type and imaging mode can add or subtract at most five points in
the initial class model: narrowband emission targets receive +5, broadband galaxies
and reflection nebulae receive -5, and globular clusters or planetary nebulae receive
+3. This adjustment and its deterministic reason are stored separately.

Candidates are sorted by final score, overlap minutes, lunar score, maximum altitude,
display name, and stable target ID, in that order. At most three are stored. They are
not three equivalent choices: rank one is the compatibility `suggestedTarget` and
the primary UI recommendation; ranks two and three are alternatives.

Regenerate the inputs and recommendations in order:

```powershell
python scripts/generate_session_forecast.py
python scripts/calculate_target_visibility.py
python scripts/generate_target_recommendations.py
```

Explicit Stage 4C paths are supported, including the same forecast input/output path:

```powershell
python scripts/generate_target_recommendations.py `
  --config config/session-planner.json `
  --forecast data/session-planner.json `
  --visibility data/astronomy-target-visibility.json `
  --catalogue data/astronomy-targets-master-stage3b-coordinates.json `
  --output data/session-planner.json
```

Run targeted or complete tests with:

```powershell
python -m pytest tests/test_target_recommendations_stage4c.py tests/test_session_planner_frontend_stage4c.py
python -m pytest
```

The recommendation model is a practical heuristic. It does not yet include equipment
matching, detailed field-of-view suitability, exact exposure planning, local horizon
obstructions, seeing forecasts, atmospheric transparency beyond current weather
proxies, personal target history, completed-target avoidance, or filter-specific
exposure optimization. Stage 4D will automate the existing generation sequence and
reviewable publication; it should not redefine Stage 4C scoring.

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

- Stage 4D: add scheduled GitHub generation, validation, and reviewable publication.
