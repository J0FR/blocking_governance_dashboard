-- =====================================================================
-- Block impact: ventana de fechas (yyyy-MM-dd) ya aplicada en el query.
-- =====================================================================

WITH dim_calendar AS (
    SELECT DISTINCT
        CAST(date_id AS STRING) AS pt,
        year_calendar_week
    FROM mx_ops.mx_date_value
    WHERE date_value BETWEEN '${start_date}' AND '${end_date}'
),

city_dim AS (
    SELECT DISTINCT
        country_code,
        city_id,
        city_name
    FROM international_capital.ods_ssl_city_captial_df
    WHERE dt = DATE_FORMAT(DATE_SUB(CURRENT_DATE(), 2), 'yyyy-MM-dd')
      AND country_code IN ('DO','PA','MX','PE','CO','EC','AR','CR','CL')
),

product_dim AS (
    SELECT DISTINCT
        product_id,
        two_level_biz_cate AS vehicle_category
    FROM international_capital.dim_pub_product_category_df
    WHERE pt = DATE_FORMAT(DATE_SUB(CURRENT_DATE(), 2), 'yyyyMMdd')
      AND country_code IN ('DO','PA','MX','PE','CO','EC','AR','CR','CL')
),

-- 1. Raw disposal measures
raw_measures AS (
    SELECT
        cal.year_calendar_week,
        m.user_id AS driver_id,
        m.country_code,
        m.city_id,
        m.rule_id,
        m.action_type,
        m.level,
        m.measure_time,

        -- > 30 days = Permanent
        CASE
            WHEN m.level IN (3, 6, 9)
              OR m.measure_time > 2592000
            THEN 'Permanently Blocked'
            ELSE 'Temporary Blocked'
        END AS block_duration_type

    FROM pgi_alg_ibt.dwd_pgi_frodo_dispose_detail m

    INNER JOIN dim_calendar cal
        ON REGEXP_REPLACE(
            CAST(TO_DATE(m.create_time) AS STRING),
            '-',
            ''
        ) = cal.pt

    WHERE CONCAT(m.year, '-', m.month, '-', m.day)
            BETWEEN '${start_date}' AND '${end_date}'

      AND TO_DATE(m.create_time)
            BETWEEN '${start_date}' AND '${end_date}'

      AND (m.is_test = FALSE OR m.is_test IS NULL)
      AND (m.is_watch = TRUE OR m.is_watch IS NULL)
      AND (m.is_schedule = FALSE OR m.is_schedule IS NULL)

      AND m.country_code IN (
          'DO','PA','MX','PE','CO','EC','AR','CR','CL'
      )

      AND m.action_type IN (
          4, 14, 21, 23, 35, 37, 40, 78
      )

      AND m.role = 2
),

target_drivers AS (
    SELECT DISTINCT
        driver_id
    FROM raw_measures
),

-- 2. Consolidate measures per driver + week + rule
-- Maximum weekly impact = 168 hours
driver_week_measures AS (
    SELECT
        year_calendar_week,
        driver_id,
        country_code,
        city_id,
        rule_id,
        block_duration_type,

        COUNT(*) AS total_measures_applied,

        CASE
            WHEN block_duration_type = 'Permanently Blocked'
                THEN 168.0
            ELSE LEAST(
                168.0,
                SUM(NVL(measure_time, 0)) / 3600.0
            )
        END AS measure_time_hours

    FROM raw_measures

    GROUP BY
        year_calendar_week,
        driver_id,
        country_code,
        city_id,
        rule_id,
        block_duration_type
),

-- 3. Drivers active at least once across full timeframe
overall_active_drivers AS (
    SELECT DISTINCT
        t.driver_id

    FROM international_capital.view_dwm_trd_order_pro_core_anycar_base_di_ssl t

    INNER JOIN target_drivers td
        ON t.driver_id = td.driver_id

    WHERE t.pt BETWEEN REGEXP_REPLACE('${start_date}', '-', '')
                   AND REGEXP_REPLACE('${end_date}', '-', '')
      AND t.country_code IN (
          'DO','PA','MX','PE','CO','EC','AR','CR','CL'
      )
      AND t.is_td_finish = 1
),

-- 4. Weekly order metrics assigning Primary Vehicle Category
weekly_order_metrics AS (
    SELECT
        year_calendar_week,
        driver_id,
        country_code,
        city_id,
        vehicle_category,
        weekly_finished_orders

    FROM (
        SELECT
            cal.year_calendar_week,
            t.driver_id,
            t.country_code,
            t.city_id,

            NVL(
                p.vehicle_category,
                'Unassigned Category'
            ) AS vehicle_category,

            COUNT(
                DISTINCT CASE
                    WHEN t.is_td_finish = 1
                    THEN t.order_id
                END
            ) AS weekly_finished_orders,

            ROW_NUMBER() OVER (
                PARTITION BY
                    cal.year_calendar_week,
                    t.driver_id,
                    t.country_code,
                    t.city_id

                ORDER BY
                    COUNT(
                        DISTINCT CASE
                            WHEN t.is_td_finish = 1
                            THEN t.order_id
                        END
                    ) DESC
            ) AS cat_rnk

        FROM international_capital.view_dwm_trd_order_pro_core_anycar_base_di_ssl t

        INNER JOIN target_drivers td
            ON t.driver_id = td.driver_id

        INNER JOIN dim_calendar cal
            ON t.pt = cal.pt

        LEFT JOIN product_dim p
            ON t.product_id = p.product_id

        WHERE t.pt BETWEEN REGEXP_REPLACE('${start_date}', '-', '')
                       AND REGEXP_REPLACE('${end_date}', '-', '')

          AND t.country_code IN (
              'DO','PA','MX','PE','CO','EC','AR','CR','CL'
          )

        GROUP BY
            cal.year_calendar_week,
            t.driver_id,
            t.country_code,
            t.city_id,
            NVL(
                p.vehicle_category,
                'Unassigned Category'
            )
    ) sub_ord

    WHERE cat_rnk = 1
),

-- 5. Weekly online supply hours
weekly_platform_metrics AS (
    SELECT
        cal.year_calendar_week,
        d.driver_id,
        d.country_code,
        d.city_id,

        SUM(d.driver_online_seconds) / 3600.0 AS weekly_sh

    FROM international_capital.view_dwd_driver_listen_online_capital_di_ssl d

    INNER JOIN target_drivers td
        ON d.driver_id = td.driver_id

    INNER JOIN dim_calendar cal
        ON d.pt = cal.pt

    WHERE d.country_code IN (
        'DO','PA','MX','PE','CO','EC','AR','CR','CL'
    )

      AND d.pt BETWEEN REGEXP_REPLACE('${start_date}', '-', '')
                   AND REGEXP_REPLACE('${end_date}', '-', '')

    GROUP BY
        cal.year_calendar_week,
        d.driver_id,
        d.country_code,
        d.city_id
),

-- 6. Strict 1-to-1 weekly driver activity join
weekly_driver_activity AS (
    SELECT
        COALESCE(o.year_calendar_week, p.year_calendar_week) AS year_calendar_week,
        COALESCE(o.driver_id, p.driver_id)                   AS driver_id,
        COALESCE(o.country_code, p.country_code)             AS country_code,
        COALESCE(o.city_id, p.city_id)                       AS city_id,

        NVL(o.vehicle_category, 'Unassigned Category')       AS vehicle_category,
        NVL(o.weekly_finished_orders, 0)                     AS weekly_finished_orders,
        NVL(p.weekly_sh, 0)                                  AS weekly_tsh

    FROM weekly_order_metrics o

    FULL OUTER JOIN weekly_platform_metrics p
        ON o.driver_id = p.driver_id
       AND o.country_code = p.country_code
       AND o.city_id = p.city_id
       AND o.year_calendar_week = p.year_calendar_week
),

-- Marketplace segmentation
drv_segm AS (
    SELECT
        t1.country_code,
        t1.city_id,
        t1.driver_id,
        t1.final_cluster AS market_place_cohort

    FROM (
        SELECT
            t0.*,

            ROW_NUMBER() OVER (
                PARTITION BY
                    t0.country_code,
                    t0.city_id,
                    t0.driver_id
                ORDER BY
                    t0.frequency DESC
            ) AS rank

        FROM (
            SELECT
                c.country_code,
                c.city_id,
                c.driver_id,
                c.final_cluster,
                COUNT(1) AS frequency

            FROM mx_ops.ssl_drv_incentives_clusters_wi c

            INNER JOIN target_drivers td
                ON c.driver_id = td.driver_id

            WHERE c.pt BETWEEN REGEXP_REPLACE('${start_date}', '-', '')
                           AND REGEXP_REPLACE('${end_date}', '-', '')

              AND c.country_code IN (
                  'DO','PA','MX','PE','CO','EC','AR','CR','CL'
              )

            GROUP BY
                c.country_code,
                c.city_id,
                c.driver_id,
                c.final_cluster
        ) t0
    ) t1

    WHERE t1.rank = 1
),

-- Rule dimension
dim_rule AS (
    SELECT
        rule_id,
        category_one_name,
        category_two_name,
        category_three_name,
        category_four_name

    FROM (
        SELECT
            rule_id,
            category_one_name,
            category_two_name,
            category_three_name,
            category_four_name,

            ROW_NUMBER() OVER (
                PARTITION BY rule_id
                ORDER BY pt DESC
            ) AS rn

        FROM international_capital.ods_saruman_rule_center_capital_df

        WHERE pt >= REGEXP_REPLACE(
            DATE_SUB(CURRENT_DATE(), 14),
            '-',
            ''
        )
    ) t

    WHERE rn = 1
)

SELECT
    m.year_calendar_week,
    m.country_code,
    m.city_id,

    NVL(c.city_name, 'Unknown City')                    AS city_name,
    NVL(da.vehicle_category, 'Unassigned Category')     AS vehicle_category,
    NVL(s.market_place_cohort, 'Unassigned Cohort')     AS market_place_cohort,

    m.block_duration_type,

    NVL(r.category_one_name,   'Unmapped Rule')         AS category_one_name,
    NVL(r.category_two_name,   'Unmapped Rule')         AS category_two_name,
    NVL(r.category_three_name, 'Unmapped Rule')         AS category_three_name,
    NVL(r.category_four_name,  'Unmapped Rule')         AS category_four_name,

    COUNT(DISTINCT m.driver_id)                         AS total_impacted_drivers,

    COUNT(
        DISTINCT CASE
            WHEN act.driver_id IS NOT NULL
            THEN m.driver_id
        END
    )                                                   AS active_impacted_drivers,

    SUM(m.total_measures_applied)                       AS total_measures_applied,
    SUM(NVL(da.weekly_finished_orders, 0))              AS total_finished_trips,
    ROUND(SUM(NVL(da.weekly_tsh, 0)), 2)                AS total_supply_hours,
    ROUND(SUM(m.measure_time_hours), 2)                 AS total_measure_time_hours

FROM driver_week_measures m

LEFT JOIN overall_active_drivers act
    ON m.driver_id = act.driver_id

LEFT JOIN weekly_driver_activity da
    ON m.driver_id = da.driver_id
   AND m.country_code = da.country_code
   AND m.city_id = da.city_id
   AND m.year_calendar_week = da.year_calendar_week

LEFT JOIN city_dim c
    ON m.country_code = c.country_code
   AND m.city_id = c.city_id

LEFT JOIN drv_segm s
    ON m.country_code = s.country_code
   AND m.city_id = s.city_id
   AND m.driver_id = s.driver_id

LEFT JOIN dim_rule r
    ON m.rule_id = r.rule_id

GROUP BY
    m.year_calendar_week,
    m.country_code,
    m.city_id,
    NVL(c.city_name, 'Unknown City'),
    NVL(da.vehicle_category, 'Unassigned Category'),
    NVL(s.market_place_cohort, 'Unassigned Cohort'),
    m.block_duration_type,
    NVL(r.category_one_name,   'Unmapped Rule'),
    NVL(r.category_two_name,   'Unmapped Rule'),
    NVL(r.category_three_name, 'Unmapped Rule'),
    NVL(r.category_four_name,  'Unmapped Rule')

ORDER BY
    m.year_calendar_week ASC,
    m.country_code,
    total_impacted_drivers DESC;
