## Summary of Changes
<!-- Provide a concise description of what this PR does and why it is needed. -->

## Affected Subsystems
- [ ] `pedals_fw` (Accelerator & Brake Plausibility)
- [ ] `lights_fw` (Brakelights & Hazards)
- [ ] `components/can_driver` (Universal TWAI Driver)
- [ ] `sim/virtual_ecus` (Virtual Vehicle Simulation)
- [ ] `github-action/` (CI Engine & Runner Scripts)
- [ ] `docs/` or `README.md` (Documentation)

## Pre-Merge Verification Checklist
- [ ] Code compiles cleanly under ESP-IDF v5.1+ without errors.
- [ ] Cloud static analysis passes cleanly (`./github-action/static-check.sh`).
- [ ] No hardcoded GPIO pins or fake telemetry fallbacks are committed.
- [ ] FreeRTOS receive queues are drained prior to timeout assertions.
- [ ] Tested on physical silicon or verified via developer fork GitHub Actions.
- [ ] All new functions and manifests follow repository documentation standards.
