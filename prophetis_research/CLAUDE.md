# Prophetis Instructions For Claude Code

This repository is the `Prophetis` market-research workspace.

When working in Claude Code, follow the same project protocol as Codex.
Do not duplicate the rules manually; use the root files as the source of truth:

1. Read [AGENTS.md](AGENTS.md) for the operating rules.
2. Read [Prophetis.md](Prophetis.md) for the wake word, identity contract, persona boundary, and memory rules.
3. Read [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) for the one-screen lazy-loading contract.
4. Read [START_HERE.md](START_HERE.md) when the user asks how to start, what Prophetis covers, or wants prompt examples.
5. Read [AGENT_QUICKSTART.md](AGENT_QUICKSTART.md) for agent execution details, routing, output locations, and required evidence discipline.
6. When the user says `Prophetis`, enter Prophetis Mode.

Minimum execution rules:

- On an empty first prompt, `hi Prophetis`, `你好 Prophetis`, `Prophetis mode`, or an
  onboarding request, return a concise `START_HERE.md` summary before any
  research workflow.
- If the first prompt is already a concrete research task, do not block with
  onboarding; route the task and optionally mention `Prophetis help`.
- For `update Prophetis` / Prophetis self-update requests, run `scripts/Prophetis_update.sh`
  directly.
- For `Prophetis help`, `怎么�?Prophetis`, `Prophetis 能做什么` or `start here`, return the
  layered user-facing entry card from `START_HERE.md`.
- For `standard` / `deep_dive` research, run `scripts/check_updates.sh` once
  (local-first by default, with a 24h remote TTL); `quick_map` / 看一�?tasks
  skip it. A blocked fetch degrades to local refs and is reported �?never
  elevate sandbox permissions for a freshness check. Then route the task with
  `loops/analysis-routing.md`.
- Keep facts, inferences, judgments, evidence trails, and refresh conditions
  explicit.
- Use position, portfolio, instrument, and trade-action framing only within the
  gates named in `OPERATING_CONTRACT.md`.

Prophetis Mode is a research and documentation protocol, not a promise of background automation.
