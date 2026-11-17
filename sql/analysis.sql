-- ============================================================================
-- CAN Log Analyser - saved analysis queries
-- ============================================================================
-- Each query is tagged with "-- name: <id>" so run_step3.py can run them by
-- name. They assume one capture is loaded as log_id = 1 (change as needed).
-- Techniques on show: aggregation, GROUP BY/HAVING, window functions (LAG,
-- bucketing), set operations (EXCEPT), and joins.
-- ============================================================================

-- name: overview
-- One-line summary of the capture: size, unique IDs, duration, bus rate.
SELECT lf.filename,
       lf.vehicle_make, lf.vehicle_model, lf.capture_type,
       count(*)                                   AS frames,
       count(DISTINCT cf.can_id)                  AS unique_ids,
       round((max(cf.ts) - min(cf.ts))::numeric, 1)            AS duration_s,
       round((count(*) / (max(cf.ts) - min(cf.ts)))::numeric, 0) AS frames_per_s
FROM can_frame cf
JOIN log_file lf USING (log_id)
WHERE cf.log_id = 1
GROUP BY lf.log_id, lf.filename, lf.vehicle_make, lf.vehicle_model, lf.capture_type;

-- name: busiest_ids
-- The highest-rate IDs (the periodic "heartbeat" traffic).
SELECT can_id,
       frame_count,
       round(freq_hz::numeric, 1)              AS freq_hz,
       round((median_period * 1000)::numeric, 2) AS median_ms,
       round((period_iqr * 1000)::numeric, 2)    AS iqr_ms
FROM id_profile
WHERE log_id = 1
ORDER BY frame_count DESC
LIMIT 10;

-- name: rare_ids
-- The rarest IDs - few frames, often event-driven rather than periodic.
SELECT can_id,
       frame_count,
       round(freq_hz::numeric, 3) AS freq_hz
FROM id_profile
WHERE log_id = 1
ORDER BY frame_count ASC
LIMIT 10;

-- name: longest_gaps
-- Biggest silences on any ID, using LAG() to measure the gap to the previous
-- frame of the same ID. These are the raw candidates for "dropout".
WITH gaps AS (
    SELECT can_id,
           ts,
           ts - lag(ts) OVER (PARTITION BY can_id ORDER BY ts) AS gap_s
    FROM can_frame
    WHERE log_id = 1
)
SELECT can_id,
       round(gap_s::numeric, 4) AS gap_s,
       round(ts::numeric, 3)    AS ends_at_ts
FROM gaps
WHERE gap_s IS NOT NULL
ORDER BY gap_s DESC
LIMIT 10;

-- name: per_5s_rate
-- Total bus traffic in 5-second buckets - is the load steady over the capture?
SELECT floor((ts - (SELECT min(ts) FROM can_frame WHERE log_id = 1)) / 5)::int AS bucket_5s,
       count(*) AS frames
FROM can_frame
WHERE log_id = 1
GROUP BY bucket_5s
ORDER BY bucket_5s;

-- name: dlc_distribution
-- How many data bytes frames carry (data length code).
SELECT dlc,
       count(*)                                        AS frames,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct
FROM can_frame
WHERE log_id = 1
GROUP BY dlc
ORDER BY dlc;

-- name: constant_payload_ids
-- IDs whose 8-byte payload NEVER changes across the whole capture - likely
-- static status/config messages (a useful "normal" signature).
SELECT can_id,
       count(*)              AS frames,
       count(DISTINCT data)  AS distinct_payloads
FROM can_frame
WHERE log_id = 1
GROUP BY can_id
HAVING count(DISTINCT data) = 1
ORDER BY frames DESC
LIMIT 10;

-- name: most_variable_ids
-- The opposite: IDs whose payload changes the most - the "live" signals
-- (sensor values, wheel speeds, etc.).
SELECT can_id,
       count(*)              AS frames,
       count(DISTINCT data)  AS distinct_payloads,
       round(100.0 * count(DISTINCT data) / count(*), 1) AS pct_unique
FROM can_frame
WHERE log_id = 1
GROUP BY can_id
HAVING count(*) > 100
ORDER BY distinct_payloads DESC
LIMIT 10;

-- name: ids_only_in_log_a
-- Which IDs appear in one capture but not another (fill in the two log_ids).
-- Needs a second capture loaded; the "missing ID" idea behind Step 4/5.
SELECT DISTINCT can_id FROM can_frame WHERE log_id = 1
EXCEPT
SELECT DISTINCT can_id FROM can_frame WHERE log_id = 2
ORDER BY can_id;
