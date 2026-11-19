# nyc-trip-planner

Claude Code skill for managing the 纽约旅行 Notion trip planner.

- Skill: `.claude/skills/nyc-trip/` (instructions in `SKILL.md`, helper in `scripts/trip.py`)
- No secrets are stored here. The Notion connection token lives in the Claude Code cloud
  environment's network secrets and is injected by its proxy for `api.notion.com`.

Start a Claude Code cloud session with this repository on the environment that holds the
Notion secret, then send a Google Takeout zip, screenshots, brochures or a list of places,
or ask Claude to plan a day or week.
