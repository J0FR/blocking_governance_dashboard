-- Retention: data_end_date (last day with complete data) already applied in the query.
--   (before: CURRENT_DATE() - 2)

WITH params_base AS (
    SELECT
        TO_DATE('${data_end_date}') AS data_end_date,
        DATE_FORMAT(
            TO_DATE('${data_end_date}'),
            'yyyyMMdd'
        ) AS data_end_pt,
        UNIX_TIMESTAMP(
            CONCAT(
                '${data_end_date}',
                ' 23:59:59'
            )
        ) AS data_end_ts
),
-- =========================================================
-- 0. DATE PARAMETERS
-- =========================================================
params_cutoff AS (
    SELECT
        data_end_date,
        data_end_pt,
        data_end_ts,
        DATE_SUB(
            data_end_date,
            84
        ) AS maturity_cutoff_date
    FROM params_base
),
params AS (
    SELECT
        data_end_date,
        data_end_pt,
        data_end_ts,
        maturity_cutoff_date,
        DATE_SUB(
            maturity_cutoff_date,
            PMOD(
                DATEDIFF(
                    maturity_cutoff_date,
                    '1970-01-04'
                ),
                7
            )
        ) AS cohort_end_date,
        DATE_SUB(
            DATE_SUB(
                maturity_cutoff_date,
                PMOD(
                    DATEDIFF(
                        maturity_cutoff_date,
                        '1970-01-04'
                    ),
                    7
                )
            ),
            83
        ) AS cohort_start_date
    FROM params_cutoff
),
-- =========================================================
-- 1. CALENDAR
-- =========================================================
dim_calendar AS (
    SELECT DISTINCT
        CAST(c.date_id AS STRING) AS pt,
        c.date_value,
        c.year_calendar_week
    FROM mx_ops.mx_date_value c
    CROSS JOIN params p
    WHERE c.date_value
          BETWEEN p.cohort_start_date
              AND p.cohort_end_date
),
-- =========================================================
-- 2. CITY DIMENSION (snapshot of data_end_date)
-- =========================================================
city_dim AS (
    SELECT DISTINCT
        country_code,
        city_id,
        city_name
    FROM international_capital.ods_ssl_city_captial_df
    WHERE dt = '${data_end_date}'
      AND country_code IN (
          'DO','PA','MX','PE','CO','EC','AR','CR','CL'
      )
),
-- =========================================================
-- 3. RULE DIMENSION (latest snapshot in the 12 days up to data_end_date)
-- =========================================================
dim_rule AS (
    SELECT
        country_code,
        rule_id,
        category_one_name,
        category_two_name,
        category_three_name,
        category_four_name
    FROM (
        SELECT
            country_code,
            rule_id,
            category_one_name,
            category_two_name,
            category_three_name,
            category_four_name,
            ROW_NUMBER() OVER (
                PARTITION BY
                    country_code,
                    rule_id
                ORDER BY pt DESC
            ) AS rn
        FROM international_capital.ods_saruman_rule_center_capital_df
        WHERE pt >= REGEXP_REPLACE(
            DATE_SUB('${data_end_date}', 12),
            '-',
            ''
        )
          AND pt <= DATE_FORMAT(TO_DATE('${data_end_date}'), 'yyyyMMdd')
          AND country_code IN (
              'DO','PA','MX','PE','CO','EC','AR','CR','CL'
          )
    ) r
    WHERE rn = 1
),
-- =========================================================
-- 4. RETENTION WINDOWS
-- INTERVAL / INDEPENDENT RETURN
-- =========================================================
retention_window_dim AS (
    SELECT 1 AS retention_order, '1-7 Days' AS retention_window_days, 'Week 1' AS retention_window_weeks
    UNION ALL SELECT 2, '8-14 Days', 'Week 2'
    UNION ALL SELECT 3, '15-21 Days', 'Week 3'
    UNION ALL SELECT 4, '22-28 Days', 'Week 4'
    UNION ALL SELECT 5, '29-35 Days', 'Week 5'
    UNION ALL SELECT 6, '36-42 Days', 'Week 6'
    UNION ALL SELECT 7, '43-49 Days', 'Week 7'
    UNION ALL SELECT 8, '50-56 Days', 'Week 8'
    UNION ALL SELECT 9, '57-63 Days', 'Week 9'
    UNION ALL SELECT 10, '64-70 Days', 'Week 10'
    UNION ALL SELECT 11, '71-77 Days', 'Week 11'
    UNION ALL SELECT 12, '78-84 Days', 'Week 12'
),
-- =========================================================
-- 5. RAW BLOCK MEASURES
-- =========================================================
block_measures_base AS (
    SELECT
        m.user_id AS driver_id,
        m.country_code,
        m.city_id,
        m.rule_id,
        m.action_type,
        m.level,
        m.measure_start_time,
        m.measure_expire_time,
        m.measure_time,
        r.category_one_name,
        r.category_two_name,
        r.category_three_name,
        r.category_four_name,
        CASE
            WHEN CAST(m.measure_start_time AS BIGINT) >= 100000000000
            THEN CAST(CAST(m.measure_start_time AS BIGINT) / 1000 AS BIGINT)
            ELSE CAST(m.measure_start_time AS BIGINT)
        END AS measure_start_ts,
        CASE
            WHEN m.measure_expire_time IS NULL THEN NULL
            WHEN CAST(m.measure_expire_time AS BIGINT) >= 100000000000
            THEN CAST(CAST(m.measure_expire_time AS BIGINT) / 1000 AS BIGINT)
            ELSE CAST(m.measure_expire_time AS BIGINT)
        END AS measure_expire_ts
    FROM pgi_alg_ibt.dwd_pgi_frodo_dispose_detail m
    LEFT JOIN dim_rule r
        ON m.country_code = r.country_code
       AND m.rule_id = r.rule_id
    CROSS JOIN params p
    WHERE CONCAT_WS('-', CAST(m.year AS STRING), LPAD(CAST(m.month AS STRING), 2, '0'), LPAD(CAST(m.day AS STRING), 2, '0'))
          BETWEEN CAST(DATE_SUB(p.cohort_start_date, 15) AS STRING) AND CAST(p.cohort_end_date AS STRING)
      AND m.country_code IN ('DO','PA','MX','PE','CO','EC','AR','CR','CL')
      AND (m.is_test = FALSE OR m.is_test IS NULL)
      AND (m.is_watch = TRUE OR m.is_watch IS NULL)
      AND (m.is_schedule = FALSE OR m.is_schedule IS NULL)
      AND m.role = 2
      AND m.measure_start_time IS NOT NULL
      AND (
            m.action_type IN (4, 14, 21, 23, 35, 37, 40, 78)
            OR r.category_four_name = 'Failed BGC Recheck'
          )
),
-- =========================================================
-- 6. ELIGIBLE BLOCKS + RETENTION ANCHOR + PERMANENT FLAG
-- =========================================================
block_measures_eligible AS (
    SELECT
        driver_id,
        country_code,
        city_id,
        rule_id,
        action_type,
        level,
        measure_start_time,
        measure_expire_time,
        measure_time,
        category_one_name,
        category_two_name,
        category_three_name,
        category_four_name,
        measure_start_ts,
        measure_expire_ts,
        CASE
            WHEN level IN (3, 6, 9)
              OR measure_time > 1296000
              OR measure_time IS NULL
            THEN 1
            ELSE 0
        END AS is_permanent_block,
        CASE
            WHEN level IN (3, 6, 9)
              OR measure_time > 1296000
              OR measure_time IS NULL
            THEN measure_start_ts
            ELSE measure_start_ts + CAST(measure_time AS BIGINT)
        END AS retention_anchor_ts
    FROM block_measures_base
    WHERE TO_DATE(FROM_UNIXTIME(measure_start_ts)) >= '2000-01-01'
),
-- =========================================================
-- 7. CLEAN 12-WEEK COHORT
-- =========================================================
block_cohort AS (
    SELECT DISTINCT
        cal.year_calendar_week AS iso_year_calendar_week,
        CONCAT_WS(
            '|',
            CAST(b.driver_id AS STRING),
            NVL(CAST(b.country_code AS STRING), 'NULL'),
            NVL(CAST(b.city_id AS STRING), 'NULL'),
            NVL(CAST(b.rule_id AS STRING), 'NULL'),
            NVL(CAST(b.action_type AS STRING), 'NULL'),
            NVL(CAST(b.measure_start_time AS STRING), 'NULL'),
            NVL(CAST(b.measure_expire_time AS STRING), 'NULL'),
            NVL(CAST(b.measure_time AS STRING), 'NULL')
        ) AS measure_event_id,
        b.driver_id,
        b.country_code,
        b.city_id,
        b.rule_id,
        b.action_type,
        b.category_one_name,
        b.category_two_name,
        b.category_three_name,
        b.category_four_name,
        b.measure_start_ts,
        b.measure_expire_ts,
        b.is_permanent_block,
        b.retention_anchor_ts,
        p.data_end_pt,
        p.data_end_ts
    FROM block_measures_eligible b
    INNER JOIN dim_calendar cal
        ON DATE_FORMAT(TO_DATE(FROM_UNIXTIME(b.retention_anchor_ts)), 'yyyyMMdd') = cal.pt
    CROSS JOIN params p
    WHERE TO_DATE(FROM_UNIXTIME(b.retention_anchor_ts)) BETWEEN p.cohort_start_date AND p.cohort_end_date
      AND p.data_end_ts - b.retention_anchor_ts >= 84 * 86400
),
-- =========================================================
-- 8. PRE-BLOCK ACTIVITY
-- =========================================================
pre_block_activity AS (
    SELECT
        b.measure_event_id,
        MAX(CASE WHEN t.order_id IS NOT NULL THEN 1 ELSE 0 END) AS is_pre_block_active_14d
    FROM block_cohort b
    CROSS JOIN params p
    LEFT JOIN international_capital.view_dwm_trd_order_pro_core_anycar_base_di_ssl t
        ON b.driver_id = t.driver_id
       AND b.country_code = t.country_code
       AND t.country_code IN ('DO','PA','MX','PE','CO','EC','AR','CR','CL')
       AND t.pt BETWEEN DATE_FORMAT(DATE_SUB(p.cohort_start_date, 29), 'yyyyMMdd') AND DATE_FORMAT(p.cohort_end_date, 'yyyyMMdd')
       AND t.pt >= DATE_FORMAT(DATE_SUB(TO_DATE(FROM_UNIXTIME(b.measure_start_ts)), 14), 'yyyyMMdd')
       AND t.pt <= DATE_FORMAT(TO_DATE(FROM_UNIXTIME(b.measure_start_ts)), 'yyyyMMdd')
       AND t.is_td_finish = 1
       AND t.finish_time IS NOT NULL
       AND TO_DATE(t.finish_time) >= '2000-01-01'
       AND UNIX_TIMESTAMP(CAST(t.finish_time AS STRING)) >= b.measure_start_ts - (14 * 86400)
       AND UNIX_TIMESTAMP(CAST(t.finish_time AS STRING)) < b.measure_start_ts
    GROUP BY b.measure_event_id
),
-- =========================================================
-- 9. ADD PRE-BLOCK ACTIVE FLAG
-- =========================================================
block_cohort_activity AS (
    SELECT
        b.iso_year_calendar_week,
        b.measure_event_id,
        b.driver_id,
        b.country_code,
        b.city_id,
        b.rule_id,
        b.action_type,
        b.category_one_name,
        b.category_two_name,
        b.category_three_name,
        b.category_four_name,
        b.measure_start_ts,
        b.measure_expire_ts,
        b.is_permanent_block,
        b.retention_anchor_ts,
        b.data_end_pt,
        b.data_end_ts,
        CASE WHEN NVL(pa.is_pre_block_active_14d, 0) = 1 THEN 1 ELSE 0 END AS is_pre_block_active_14d
    FROM block_cohort b
    LEFT JOIN pre_block_activity pa
        ON b.measure_event_id = pa.measure_event_id
),
-- =========================================================
-- 10. TRIPS BY RETENTION INTERVAL
-- =========================================================
trips_after_block AS (
    SELECT
        b.measure_event_id,
        CAST(CEIL((UNIX_TIMESTAMP(CAST(t.finish_time AS STRING)) - b.retention_anchor_ts) / (7 * 86400.0)) AS INT) AS retention_order
    FROM block_cohort_activity b
    CROSS JOIN params p
    INNER JOIN international_capital.view_dwm_trd_order_pro_core_anycar_base_di_ssl t
        ON b.driver_id = t.driver_id
       AND b.country_code = t.country_code
       AND t.country_code IN ('DO','PA','MX','PE','CO','EC','AR','CR','CL')
       AND t.pt BETWEEN DATE_FORMAT(p.cohort_start_date, 'yyyyMMdd') AND p.data_end_pt
       AND t.is_td_finish = 1
       AND t.finish_time IS NOT NULL
       AND TO_DATE(t.finish_time) >= '2000-01-01'
       AND UNIX_TIMESTAMP(CAST(t.finish_time AS STRING)) > b.retention_anchor_ts
       AND UNIX_TIMESTAMP(CAST(t.finish_time AS STRING)) <= b.retention_anchor_ts + (84 * 86400)
    GROUP BY
        b.measure_event_id,
        CAST(CEIL((UNIX_TIMESTAMP(CAST(t.finish_time AS STRING)) - b.retention_anchor_ts) / (7 * 86400.0)) AS INT)
),
-- =========================================================
-- 11. ADD CITY NAME
-- =========================================================
driver_enriched AS (
    SELECT
        r.iso_year_calendar_week,
        r.measure_event_id,
        r.driver_id,
        r.country_code,
        r.city_id,
        NVL(c.city_name, 'Unknown City') AS city_name,
        NVL(r.category_one_name, 'Unmapped Rule') AS category_one_name,
        NVL(r.category_two_name, 'Unmapped Rule') AS category_two_name,
        NVL(r.category_three_name, 'Unmapped Rule') AS category_three_name,
        NVL(r.category_four_name, 'Unmapped Rule') AS category_four_name,
        r.is_permanent_block,
        r.is_pre_block_active_14d
    FROM block_cohort_activity r
    LEFT JOIN city_dim c
        ON r.country_code = c.country_code
       AND r.city_id = c.city_id
),
-- =========================================================
-- 12. CREATE 12 INTERVAL RETENTION WINDOWS
-- =========================================================
retention_windows AS (
    SELECT
        d.iso_year_calendar_week,
        d.country_code,
        d.city_id,
        d.city_name,
        d.category_one_name,
        d.category_two_name,
        d.category_three_name,
        d.category_four_name,
        d.is_permanent_block,
        w.retention_order,
        w.retention_window_days,
        w.retention_window_weeks,
        d.driver_id AS eligible_driver_id_general,
        CASE WHEN t.measure_event_id IS NOT NULL THEN d.driver_id ELSE NULL END AS returned_driver_id_general,
        CASE WHEN d.is_pre_block_active_14d = 1 THEN d.driver_id ELSE NULL END AS eligible_driver_id_active_14d,
        CASE WHEN d.is_pre_block_active_14d = 1 AND t.measure_event_id IS NOT NULL THEN d.driver_id ELSE NULL END AS returned_driver_id_active_14d
    FROM driver_enriched d
    CROSS JOIN retention_window_dim w
    LEFT JOIN trips_after_block t
        ON d.measure_event_id = t.measure_event_id
       AND w.retention_order = t.retention_order
),
-- =========================================================
-- 13. DRIVER-LEVEL AGGREGATION
-- =========================================================
retention_agg AS (
    SELECT
        iso_year_calendar_week,
        country_code,
        city_id,
        city_name,
        category_one_name,
        category_two_name,
        category_three_name,
        category_four_name,
        is_permanent_block,
        retention_order,
        retention_window_days,
        retention_window_weeks,
        COUNT(DISTINCT eligible_driver_id_general) AS eligible_drivers_general,
        COUNT(DISTINCT returned_driver_id_general) AS returned_drivers_general,
        COUNT(DISTINCT eligible_driver_id_active_14d) AS eligible_drivers_active_14d,
        COUNT(DISTINCT returned_driver_id_active_14d) AS returned_drivers_active_14d
    FROM retention_windows
    GROUP BY
        iso_year_calendar_week,
        country_code,
        city_id,
        city_name,
        category_one_name,
        category_two_name,
        category_three_name,
        category_four_name,
        is_permanent_block,
        retention_order,
        retention_window_days,
        retention_window_weeks
)
-- =========================================================
-- 14. FINAL OUTPUT
-- =========================================================
SELECT
    iso_year_calendar_week,
    country_code,
    city_id,
    city_name,
    category_one_name,
    category_two_name,
    category_three_name,
    category_four_name,
    CASE WHEN is_permanent_block = 1 THEN 'Permanently Blocked' ELSE 'Temporary Blocked' END AS block_duration_type,
    retention_order,
    retention_window_days,
    retention_window_weeks,
    eligible_drivers_general,
    returned_drivers_general,
    eligible_drivers_active_14d,
    returned_drivers_active_14d
FROM retention_agg
ORDER BY
    iso_year_calendar_week ASC,
    country_code,
    city_id,
    category_one_name,
    category_two_name,
    category_three_name,
    category_four_name,
    block_duration_type,
    retention_order;
