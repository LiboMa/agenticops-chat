# AgenticOps UI integration contract · 2026-10-05

设计与接口交接文件；尚未实现。 / Design handoff; not implemented.

- existing-openapi.json: untouched running-service snapshot, 231 API operations plus six web routes.
- endpoint-catalog.json: full existing inventory with source locations.
- target-openapi.json: complete proposed target; x-delivery-status marks retained, extended and new operations.
- proposed-delta.openapi.json: 45 changed operations: 8 new and 37 extended (including four documentation-only repairs).
- API_CONTRACT.md: bilingual mapping, request/response rules, gaps and examples.
- change-register.json: operation-level phase mapping.
- state-mapping.json, design-tokens.json: state and visual design baseline.

Implementation starts with P0/P1 in ../../superpowers/plans/2026-10-05-blue-white-sre-workspace.md.
The interactive review remains in /Users/malibo/Documents/AgenticOps_BlueWhite_Implementation_20261005.

Do not infer customer runtime authentication, performance or successful cloud execution from this snapshot.
