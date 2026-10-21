# MVP-2.7.0 — release presentation

| File | What it is |
|---|---|
| [`Agenticops-presentation-mvp-2.7.0.html`](Agenticops-presentation-mvp-2.7.0.html) | **The MVP-2.7.0 release presentation**: «AgenticOps — 项目、架构与功能分享», 12 slides in Chinese with speaker notes, written for the architect team: background, the seven-stage evolution, the architecture (overall, design principles, the auto-fix pipeline, Signal Gate, change management), features by maturity, four demo scenarios, the summary and Q&A. One self-contained file: open it in a browser, no network needed (the only outside link is the repository URL on the last slide). Keys: → / ↓ / Space / PageDown next, ← / ↑ / PageUp back, Home / End first / last, `F` full screen, `N` speaker notes, `O` or Esc thumbnail overview; `#n` in the URL opens slide n; printing gives one slide per page. |
| [`run-96fc9ec996f443af971f50b60b12857f-report.html`](run-96fc9ec996f443af971f50b60b12857f-report.html) | KiroCrew ON run report for the run that built the deck (2026-10-21): the requirement and outline, the plan, the four tasks (fact check and slide plan → build → static assertions → evaluator) with their rework round, usage and the recovery record. The deck was built from `origin/main` (`aef032d`). |

The deck is the run's `index.html`, taken byte for byte from the run's workspace. A copy saved from the browser
was not used: it also held the page's runtime state (the thumbnail overview cloned every slide, the notes panel) and
the UI and scripts that browser extensions had injected; the deck's own style and script are identical in both.

One correction since (owner, 2026-10-21): the run built the deck from `origin/main`, where 2.7.0 was still at S5,
so slides 1, 3 and 12 said «2.7.0 进行中». They now give the release as `docs/MVP-2.7.0-RELEASE.md` records it:
the cover tag «2.7.0 已发布 · v2.7.0»; the timeline «2026-10-05 → 10-08 · 已发布 · S1–S7 已验收 · A1–A4 移至 2.7.1»
and its speaker note; the Q&A slide no longer marks the release notes «进行中». Nothing else in the deck changed.

Archived on 2026-10-21 at the owner's request: the report as presentation material, the deck as the MVP-2.7.0
release presentation.
