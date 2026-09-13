# Frozen synthetic replay cases

These two cases replay the complete offline fixture kits through the production
manager and workbench projection:

- `night-bus-rule`: rule change and transition arrangement.
- `water-billing-remedy`: billing basis, handling path, deadline and remedy commitment.

Each `index.json` entry freezes the request, expected subject/facet module,
structured fields, sources, components, search purposes and the targeted-update
field. `test_replay_cases.py` runs the manager end to end and asserts those
contracts, so a case cannot silently pull in the other event's materials or
collapse into a generic report.

Boundary: these are synthetic mechanism-replay cases. Passing them is not live
search quality, not a human 90%/95% assertion check, and does not change the
status of `tests/investigation/cases/registry.json`, whose ten real-material
slots stay `blocked` until genuine public snapshots and annotations exist.
