-- Driver segmentation, Presto dialect (grain: driver_id x country_code).
-- Placeholders filled by snapshot.py:
--   {dim_pt}   yyyyMMdd partition of dim tables (today - 2)
--   {dim_dt}   yyyy-MM-dd partition of city table (today - 2)
--   {start_pt} first day of the 28-day window (yyyyMMdd)
--   {end_pt}   last day of the 28-day window (yyyyMMdd)
-- Notes vs the original Hive query: integer divisions are cast to DOUBLE
-- (Presto truncates bigint/bigint), percentile_approx -> approx_percentile,
-- <=> -> IS NOT DISTINCT FROM, date arithmetic moved to Python.

WITH

product_dim AS (
    SELECT
        product_id,
        MAX(two_level_biz_cate) AS vehicle_category,
        MAX(two_level_biz_en)   AS two_level_biz_en,
        MAX(CASE WHEN LOWER(ssl_product_cluster) = 'ssl_moto' THEN 1 ELSE 0 END) AS is_moto
    FROM international_capital.dim_pub_product_category_df
    WHERE pt = '{dim_pt}'
      AND country_code IN ('DO','PA','MX','PE','CO','EC','AR','CR','CL')
    GROUP BY product_id
),

city_dim AS (
    SELECT
        city_id,
        MAX(city_name) AS city_name
    FROM international_capital.ods_ssl_city_captial_df
    WHERE dt = '{dim_dt}'
      AND country_code IN ('DO','PA','MX','PE','CO','EC','AR','CR','CL')
    GROUP BY city_id
),

order_metrics AS (
    SELECT
        t.driver_id,
        t.country_code,
        t.city_id,
        t.product_id,
        MAX(CASE WHEN COALESCE(pd.is_moto, 0) = 1 THEN '2-Wheels' ELSE '4-Wheels' END) AS vehicle_type,
        COUNT(DISTINCT CASE WHEN t.is_td_finish = 1 THEN t.order_id END) AS finished_orders,
        SUM(CASE WHEN t.is_td_finish = 1 AND t.charge_dur > 0 THEN t.charge_dur ELSE 0 END) / 3600.0 AS charging_hours
    FROM international_capital.view_dwm_trd_order_pro_core_anycar_base_di_ssl t
    LEFT JOIN product_dim pd
           ON t.product_id = pd.product_id
    WHERE t.pt BETWEEN '{start_pt}' AND '{end_pt}'
      AND t.country_code IN ('DO','PA','MX','PE','CO','EC','AR','CR','CL')
    GROUP BY t.driver_id, t.country_code, t.city_id, t.product_id
),

driver_active_days AS (
    SELECT
        t.driver_id,
        t.country_code,
        COUNT(DISTINCT t.pt) AS active_days
    FROM international_capital.view_dwm_trd_order_pro_core_anycar_base_di_ssl t
    WHERE t.pt BETWEEN '{start_pt}' AND '{end_pt}'
      AND t.country_code IN ('DO','PA','MX','PE','CO','EC','AR','CR','CL')
      AND t.is_td_finish = 1
    GROUP BY t.driver_id, t.country_code
),

driver_orders AS (
    SELECT
        driver_id,
        country_code,
        SUM(finished_orders) AS finished_orders,
        SUM(charging_hours)  AS charging_hours
    FROM order_metrics
    GROUP BY driver_id, country_code
),

main_vehicle AS (
    SELECT driver_id, country_code, vehicle_type, vehicle_orders
    FROM (
        SELECT
            driver_id, country_code, vehicle_type,
            SUM(finished_orders) AS vehicle_orders,
            ROW_NUMBER() OVER (
                PARTITION BY driver_id, country_code
                ORDER BY SUM(finished_orders) DESC,
                         SUM(charging_hours)  DESC,
                         CASE WHEN vehicle_type = '4-Wheels' THEN 0 ELSE 1 END
            ) AS rn
        FROM order_metrics
        WHERE finished_orders > 0
        GROUP BY driver_id, country_code, vehicle_type
    ) x
    WHERE rn = 1
),

top_product AS (
    SELECT driver_id, country_code, product_id, finished_orders AS top_product_orders
    FROM (
        SELECT
            om.driver_id, om.country_code, om.product_id,
            SUM(om.finished_orders) AS finished_orders,
            ROW_NUMBER() OVER (
                PARTITION BY om.driver_id, om.country_code
                ORDER BY SUM(om.finished_orders) DESC, om.product_id
            ) AS rn
        FROM order_metrics om
        JOIN main_vehicle mv
          ON om.driver_id    = mv.driver_id
         AND om.country_code = mv.country_code
         AND om.vehicle_type = mv.vehicle_type
        WHERE om.finished_orders > 0
        GROUP BY om.driver_id, om.country_code, om.product_id
    ) x
    WHERE rn = 1
),

main_city AS (
    SELECT driver_id, country_code, city_id
    FROM (
        SELECT
            h.driver_id, h.country_code, h.city_id,
            ROW_NUMBER() OVER (
                PARTITION BY h.driver_id, h.country_code
                ORDER BY h.city_online_seconds DESC,
                         COALESCE(c.city_orders, 0) DESC,
                         h.city_id
            ) AS rn
        FROM (
            SELECT
                d.driver_id, d.country_code, d.city_id,
                SUM(d.driver_online_seconds) AS city_online_seconds
            FROM international_capital.view_dwd_driver_listen_online_capital_di_ssl d
            WHERE d.pt BETWEEN '{start_pt}' AND '{end_pt}'
              AND d.country_code IN ('DO','PA','MX','PE','CO','EC','AR','CR','CL')
              AND d.driver_online_seconds > 0
            GROUP BY d.driver_id, d.country_code, d.city_id
        ) h
        LEFT JOIN (
            SELECT driver_id, country_code, city_id, SUM(finished_orders) AS city_orders
            FROM order_metrics
            GROUP BY driver_id, country_code, city_id
        ) c
          ON h.driver_id    = c.driver_id
         AND h.country_code = c.country_code
         AND h.city_id      = c.city_id
    ) x
    WHERE rn = 1
),

supply AS (
    SELECT
        d.driver_id,
        d.country_code,
        SUM(d.driver_online_seconds) / 3600.0                                  AS supply_hours,
        SUM(CASE WHEN d.state = 1 THEN d.driver_online_seconds ELSE 0 END) / 3600.0 AS idle_hours,
        SUM(CASE WHEN d.state = 2 THEN d.driver_online_seconds ELSE 0 END) / 3600.0 AS pickup_hours,
        SUM(CASE WHEN d.state = 3 THEN d.driver_online_seconds ELSE 0 END) / 3600.0 AS waiting_hours,
        SUM(CASE WHEN d.state = 4 THEN d.driver_online_seconds ELSE 0 END) / 3600.0 AS charging_hours,
        COUNT(DISTINCT CASE WHEN d.driver_online_seconds > 0 THEN d.pt END)    AS days_online
    FROM international_capital.view_dwd_driver_listen_online_capital_di_ssl d
    WHERE d.pt BETWEEN '{start_pt}' AND '{end_pt}'
      AND d.country_code IN ('DO','PA','MX','PE','CO','EC','AR','CR','CL')
    GROUP BY d.driver_id, d.country_code
),

finance AS (
    SELECT
        fp.driver_id,
        fp.country_code,
        SUM(fp.online_driver_divide) AS driver_income,
        SUM(fp.subsidy_b)            AS subsidy_b
    FROM g_caiwu.view_dwm_fin_order_report_capital_di_finance_table_ssl_eg fp
    WHERE fp.pt BETWEEN '{start_pt}' AND '{end_pt}'
      AND fp.country_code IN ('DO','PA','MX','PE','CO','EC','AR','CR','CL')
    GROUP BY fp.driver_id, fp.country_code
),

shor AS (
    SELECT
        driver_id,
        country_code,
        AVG(shor_rolling_current) AS shor
    FROM international_bi.driver_wh_shor_detail_bywk_v2
    WHERE concat(CAST(year AS VARCHAR),
                 lpad(CAST(month AS VARCHAR), 2, '0'),
                 lpad(CAST(day   AS VARCHAR), 2, '0'))
          BETWEEN '{start_pt}' AND '{end_pt}'
      AND country_code IN ('DO','PA','MX','PE','CO','EC','AR','CR','CL')
      AND shor_rolling_current >= 0
    GROUP BY driver_id, country_code
),

base AS (
    SELECT
        s.driver_id,
        s.country_code,
        mc.city_id                                   AS main_city_id,
        tp.product_id                                AS top_product_id,
        pd.vehicle_category,
        pd.two_level_biz_en,
        COALESCE(mv.vehicle_type, 'No Trips')        AS vehicle_type,
        mv.vehicle_orders                            AS main_vehicle_orders,
        CAST(mv.vehicle_orders AS DOUBLE) / NULLIF(CAST(o.finished_orders AS DOUBLE), 0) AS main_vehicle_share,

        s.supply_hours,
        s.days_online,
        COALESCE(ad.active_days, 0)                                  AS active_days,
        s.supply_hours / NULLIF(CAST(ad.active_days AS DOUBLE), 0)   AS daily_sh,

        COALESCE(o.finished_orders, 0)                               AS finished_orders,

        s.idle_hours,
        s.pickup_hours,
        s.waiting_hours,
        s.charging_hours,
        s.pickup_hours + s.waiting_hours + s.charging_hours          AS busy_hours,
        (s.pickup_hours + s.waiting_hours + s.charging_hours)
            / NULLIF(s.supply_hours, 0)                              AS occupancy_rate,

        CAST(COALESCE(f.driver_income, 0) AS DOUBLE)                 AS driver_income,
        CAST(f.driver_income AS DOUBLE) / NULLIF(CAST(o.finished_orders AS DOUBLE), 0) AS ipt,

        CAST(COALESCE(f.subsidy_b, 0) AS DOUBLE)                     AS subsidy_b,
        CASE WHEN COALESCE(f.subsidy_b, 0) > 0 THEN 1 ELSE 0 END     AS incentive_winner,

        sh.shor
    FROM supply s
    LEFT JOIN driver_orders o  ON s.driver_id = o.driver_id   AND s.country_code = o.country_code
    LEFT JOIN driver_active_days ad ON s.driver_id = ad.driver_id AND s.country_code = ad.country_code
    LEFT JOIN main_vehicle mv  ON s.driver_id = mv.driver_id  AND s.country_code = mv.country_code
    LEFT JOIN top_product tp   ON s.driver_id = tp.driver_id  AND s.country_code = tp.country_code
    LEFT JOIN main_city mc     ON s.driver_id = mc.driver_id  AND s.country_code = mc.country_code
    LEFT JOIN product_dim pd   ON tp.product_id = pd.product_id
    LEFT JOIN finance f        ON s.driver_id = f.driver_id   AND s.country_code = f.country_code
    LEFT JOIN shor sh          ON s.driver_id = sh.driver_id  AND s.country_code = sh.country_code
    WHERE s.supply_hours > 0
),

pctl AS (
    SELECT
        country_code,
        vehicle_type,
        approx_percentile(ipt, 0.80) AS ipt_p80
    FROM base
    WHERE finished_orders > 0
    GROUP BY country_code, vehicle_type
),

segmented AS (
    SELECT
        b.*,
        p.ipt_p80,

        CASE
            WHEN b.active_days = 0 THEN 'No Trips'
            WHEN b.daily_sh <= 4   THEN 'Hobby'
            WHEN b.daily_sh <= 8   THEN 'Part Time'
            ELSE 'WorkHorse'
        END AS seg_supply_hours,

        CASE
            WHEN b.finished_orders = 0  THEN 'No Trips'
            WHEN b.ipt <= p.ipt_p80     THEN 'Low IPT'
            ELSE 'High IPT'
        END AS seg_ipt,

        CASE WHEN b.incentive_winner = 1 THEN 'Incentive Winner' ELSE 'No Incentive' END AS seg_incentive,

        CASE
            WHEN b.shor IS NULL THEN 'No SHOR'
            WHEN b.shor >= 0.70 THEN 'High'
            ELSE 'Low'
        END AS seg_shor
    FROM base b
    LEFT JOIN pctl p
           ON b.country_code = p.country_code
          AND b.vehicle_type = p.vehicle_type
),

occ_group AS (
    SELECT
        country_code,
        main_city_id,
        seg_supply_hours,
        seg_ipt,
        seg_incentive,
        seg_shor,
        approx_percentile(occupancy_rate, 0.90)  AS max_occupancy_rate
    FROM segmented
    GROUP BY
        country_code,
        main_city_id,
        seg_supply_hours,
        seg_ipt,
        seg_incentive,
        seg_shor
)

SELECT
    sg.driver_id,
    sg.country_code,
    sg.main_city_id AS city_id,
    cd.city_name,
    sg.top_product_id,
    sg.vehicle_category,
    sg.two_level_biz_en,

    ROUND(sg.supply_hours, 2)     AS supply_hours,
    sg.days_online,
    sg.active_days,
    ROUND(sg.daily_sh, 2)         AS daily_sh,
    sg.finished_orders,
    ROUND(sg.idle_hours, 2)       AS idle_hours,
    ROUND(sg.pickup_hours, 2)     AS pickup_hours,
    ROUND(sg.waiting_hours, 2)    AS waiting_hours,
    ROUND(sg.charging_hours, 2)   AS charging_hours,
    ROUND(sg.busy_hours, 2)       AS busy_hours,
    ROUND(sg.occupancy_rate, 4)   AS occupancy_rate,
    ROUND(sg.driver_income, 2)    AS driver_income,
    ROUND(sg.ipt, 2)              AS ipt,
    ROUND(sg.subsidy_b, 2)        AS subsidy_b,
    sg.shor,

    sg.vehicle_type,
    sg.main_vehicle_orders,
    ROUND(sg.main_vehicle_share, 4) AS main_vehicle_share,
    sg.seg_supply_hours,
    sg.seg_ipt,
    sg.seg_incentive,
    sg.seg_shor,

    CONCAT_WS(' | ',
        sg.vehicle_type,
        sg.seg_supply_hours,
        sg.seg_ipt,
        sg.seg_incentive,
        CASE WHEN sg.seg_shor = 'No SHOR' THEN 'No SHOR' ELSE CONCAT('SHOR ', sg.seg_shor) END
    ) AS segment,

    ROUND(og.max_occupancy_rate, 4)                                          AS max_occupancy_rate,
    ROUND(sg.supply_hours
          * GREATEST(og.max_occupancy_rate - sg.occupancy_rate, 0), 2)       AS available_tsh,

    ROUND(sg.busy_hours / NULLIF(CAST(sg.finished_orders AS DOUBLE), 0) * 60, 1) AS avg_trip_minutes,

    COALESCE(FLOOR(
        sg.supply_hours * GREATEST(og.max_occupancy_rate - sg.occupancy_rate, 0)
        / NULLIF(sg.busy_hours / NULLIF(CAST(sg.finished_orders AS DOUBLE), 0), 0)
    ), 0)                                                                    AS available_trips
FROM segmented sg
LEFT JOIN city_dim cd
       ON sg.main_city_id = cd.city_id
LEFT JOIN occ_group og
       ON  sg.country_code        = og.country_code
      AND  sg.main_city_id        IS NOT DISTINCT FROM og.main_city_id
      AND  sg.seg_supply_hours    = og.seg_supply_hours
      AND  sg.seg_ipt             = og.seg_ipt
      AND  sg.seg_incentive       = og.seg_incentive
      AND  sg.seg_shor            = og.seg_shor
