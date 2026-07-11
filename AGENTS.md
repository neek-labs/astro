# AGENTS.md

Durable instructions for future Codex tasks in this repository:

- Preserve the static HTML/CSS/JavaScript architecture unless explicitly asked otherwise.
- Prefer small, reviewable changes.
- Do not automatically merge or deploy.
- Do not commit secrets or API keys.
- Keep external dependencies minimal.
- Use `America/Edmonton` for local date and time handling.
- Use approximate Calgary coordinates `51.12, -114.11`.
- Generated forecast failures must fail closed and must not overwrite the last valid forecast.
- Weather and astronomy calculations must be deterministic and testable.
- AI-generated prose may summarize calculated results but must never invent or replace numerical calculations.
- Every implementation task must include testing instructions.
