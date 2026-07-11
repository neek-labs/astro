# astro

Static astronomy content for `astro.nickhall.tech`.

## Calgary Astronomy Session Planner

The Session Planner will eventually help evaluate upcoming Calgary nights for visual astronomy and astrophotography. The planned version will combine live weather forecasts, night scoring, target visibility, equipment matching, and weekly update automation.

Stage 1 is a visual and structural proof of concept only. It adds a standalone `session-planner.html` page, scoped styling, client-side JSON rendering, and clearly labelled mock data in `data/session-planner.json`. It does not call live weather APIs, calculate Moon or target positions, run AI, schedule automation, or deploy anything.

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
3. Confirm the generated timestamp, data source, weekly summary, and seven nightly cards render.
4. Confirm the browser console has no errors.

To verify the error state, temporarily rename `data/session-planner.json` or make a malformed local copy while testing through the web server. Reload the page and confirm a visible error message appears. Restore the valid JSON file before committing.

## Planned Future Stages

- Live Open-Meteo integration
- Night scoring
- Target visibility
- Equipment matching
- Weekly pull-request automation
