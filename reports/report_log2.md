# CAN Bus Test Report — DRAFT - review before use

**Capture:** 2_brakes_INJECTED_demo.log — Mazda CX-3 Maxx Sport (Brakes (injected faults - demo))  
*Clean brakes capture with 24 synthetic dropouts injected*

## Method
Loaded 183,839 CAN frames (93 unique IDs, 81.2 s, ~2264 frames/s) into PostgreSQL. Each ID's normal timing was profiled (median period and 99th-percentile gap). Dropouts were flagged where an inter-frame gap exceeded `gap > max(k_med * median_period, k_p99 * p99_period)` (k_med=3, k_p99=1.5).

## Results
- Total anomalies: **24** (dropout: 24)
- Largest dropouts:
    - ID `4DA`: 1247 ms gap at 49.70 s
    - ID `45A`: 1228 ms gap at 62.53 s
    - ID `079`: 1220 ms gap at 54.58 s
    - ID `215`: 1211 ms gap at 69.07 s
    - ID `40A`: 848 ms gap at 74.94 s

## Validation
Detector validated by 24 known dropouts injected into a clean capture: at k=3, **precision 1.00, recall 1.00** (a naive median-only rule scored precision 0.11 on the same test).

## Analysis
24 timing anomalies were detected. The flagged IDs stopped transmitting for far longer than their own normal worst-case gap, which is consistent with a dropout (ECU reset, loose connector, or bus error) rather than normal bursty traffic.

## Conclusion
The capture shows **24 dropout-type anomalies** that warrant investigation.

## Next checks
- Inspect wiring and the transmitting ECU for any flagged IDs.
- Compare against a known-good capture of the same vehicle/scenario.
- Re-run against labelled real-fault data (e.g. the ROAD dataset) for independent confirmation.

_Generated from computed values only. DRAFT - review before use._