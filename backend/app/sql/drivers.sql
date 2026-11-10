-- =====================================================================
-- Driver segmentation (grain: driver_id x country_code)
-- Criteria: 4W/2W, Daily SH, Occupancy Rate, IPT, Incentive Winner, SHOR
--
-- PARAMETER: ${run_date} in 'yyyy-MM-dd' format
-- Period:    from run_date - 28 days to run_date - 1 day (28 full days)
--            e.g. run_date = 2026-11-05  ->  2026-10-08 to 2026-11-04
-- Tickets: all categories are counted (no cr_lv4_id filter)
--
-- Occupancy Rate = (pickup + waiting + charging hours) / TSH,
-- all from listen_online by driver state (1 idle, 2 pickup, 3 waiting, 4 charging)
--
-- SSL tables first:
--   orders    -> international_capital.view_dwm_trd_order_pro_core_anycar_base_di_ssl
--   hours     -> international_capital.view_dwd_driver_listen_online_capital_di_ssl
--   finance   -> g_caiwu.view_dwm_fin_order_report_capital_di_finance_table_ssl_eg
--   cities    -> international_capital.ods_ssl_city_captial_df
-- Non-SSL (no SSL alternative available):
--   product   -> international_capital.dim_pub_product_category_df (uses ssl_product_cluster)
--   SHOR      -> international_bi.driver_wh_shor_detail_bywk_v2
-- =====================================================================

WITH

-- ---------------------------------------------------------------------
-- Dimensions
-- ---------------------------------------------------------------------
product_dim AS (
    -- Grouped by product_id to avoid duplicating rows on join
    SELECT
        product_id,
        MAX(two_level_biz_cate) AS vehicle_category,
        MAX(two_level_biz_en)   AS two_level_biz_en,
        MAX(CASE WHEN LOWER(ssl_product_cluster) = 'ssl_moto' THEN 1 ELSE 0 END) AS is_moto
    FROM international_capital.dim_pub_product_category_df
    WHERE pt = date_format(date_sub(current_date(), 2), 'yyyyMMdd')
      AND country_code IN ('DO','PA','MX','PE','CO','EC','AR','CR','CL')
    GROUP BY product_id
),

city_dim AS (
    -- Grouped by city_id to guarantee one row per city (no duplicated drivers)
    SELECT
        city_id,
        MAX(city_name) AS city_name
    FROM international_capital.ods_ssl_city_captial_df
    WHERE dt = date_format(date_sub(current_date(), 2), 'yyyy-MM-dd')
      AND country_code IN ('DO','PA','MX','PE','CO','EC','AR','CR','CL')
    GROUP BY city_id
),

-- ---------------------------------------------------------------------
-- Currency: local -> USD (same logic as the finance report query)
-- ---------------------------------------------------------------------
country_currency AS (
    SELECT 'DO' AS country_code, 'DOP' AS currency UNION ALL
    SELECT 'PA', 'USD' UNION ALL
    SELECT 'MX', 'MXN' UNION ALL
    SELECT 'PE', 'PEN' UNION ALL
    SELECT 'CO', 'COP' UNION ALL
    SELECT 'EC', 'USD' UNION ALL
    SELECT 'AR', 'ARS' UNION ALL
    SELECT 'CR', 'CRC' UNION ALL
    SELECT 'CL', 'CLP'
),

currency_dim AS (
    SELECT
        cc.country_code,
        CASE
            WHEN cc.currency = 'USD' THEN 1
            ELSE cr.inverse_con_rate_last_month_avg
        END AS local_to_usd_rate
    FROM country_currency cc
    LEFT JOIN g_caiwu.dim_currency_rate_di cr
           ON cr.from_currency = 'USD'
          AND cr.to_currency   = cc.currency
          AND CONCAT(cr.year, cr.month, cr.day) = date_format(date_sub(current_date(), 2), 'yyyyMMdd')
),

-- ---------------------------------------------------------------------
-- Orders (SSL)
-- ---------------------------------------------------------------------
order_metrics AS (
    SELECT
        t.driver_id,
        t.country_code,
        t.city_id,
        t.product_id,
        -- Products missing from product_dim default to 4-Wheels
        MAX(CASE WHEN COALESCE(pd.is_moto, 0) = 1 THEN '2-Wheels' ELSE '4-Wheels' END) AS vehicle_type,
        COUNT(DISTINCT CASE WHEN t.is_td_finish = 1 THEN t.order_id END) AS finished_orders,
        SUM(CASE WHEN t.is_td_finish = 1 AND t.charge_dur > 0 THEN t.charge_dur ELSE 0 END) / 3600.0 AS charging_hours
    FROM international_capital.view_dwm_trd_order_pro_core_anycar_base_di_ssl t
    LEFT JOIN product_dim pd
           ON t.product_id = pd.product_id
    WHERE t.pt BETWEEN date_format(date_sub('${run_date}', 28), 'yyyyMMdd') AND date_format(date_sub('${run_date}', 1), 'yyyyMMdd')
      AND t.country_code IN ('DO','PA','MX','PE','CO','EC','AR','CR','CL')
    GROUP BY t.driver_id, t.country_code, t.city_id, t.product_id
),

-- Active days = days with at least one finished trip
-- (separate CTE: counting distinct days can't be re-summed from order_metrics)
driver_active_days AS (
    SELECT
        t.driver_id,
        t.country_code,
        COUNT(DISTINCT t.pt) AS active_days
    FROM international_capital.view_dwm_trd_order_pro_core_anycar_base_di_ssl t
    WHERE t.pt BETWEEN date_format(date_sub('${run_date}', 28), 'yyyyMMdd') AND date_format(date_sub('${run_date}', 1), 'yyyyMMdd')
      AND t.country_code IN ('DO','PA','MX','PE','CO','EC','AR','CR','CL')
      AND t.is_td_finish = 1
    GROUP BY t.driver_id, t.country_code
),

-- Driver totals across ALL products and cities
driver_orders AS (
    SELECT
        driver_id,
        country_code,
        SUM(finished_orders) AS finished_orders,
        SUM(charging_hours)  AS charging_hours
    FROM order_metrics
    GROUP BY driver_id, country_code
),

-- Main vehicle type: 4-Wheels or 2-Wheels, whichever has MORE finished trips
-- (summing all products of each type). One row per driver -> no duplicates.
-- Tie-break: more charging hours, then 4-Wheels.
main_vehicle AS (
    SELECT driver_id, country_code, vehicle_type, vehicle_orders
    FROM (
        SELECT
            driver_id, country_code, vehicle_type,
            vehicle_orders,
            ROW_NUMBER() OVER (
                PARTITION BY driver_id, country_code
                ORDER BY vehicle_orders DESC, veh_charging DESC,
                         CASE WHEN vehicle_type = '4-Wheels' THEN 0 ELSE 1 END
            ) AS rn
        FROM (
            SELECT driver_id, country_code, vehicle_type,
                   SUM(finished_orders) AS vehicle_orders,
                   SUM(charging_hours)  AS veh_charging
            FROM order_metrics
            WHERE finished_orders > 0
            GROUP BY driver_id, country_code, vehicle_type
        ) v
    ) x
    WHERE rn = 1
),

-- Main product: the one with most trips WITHIN the main vehicle type
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

-- Main city: the city where the driver operates the most
-- (most online hours; tie-break: most finished trips, then city_id).
-- Uses online hours so drivers without trips also get a city.
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
            WHERE d.pt BETWEEN date_format(date_sub('${run_date}', 28), 'yyyyMMdd') AND date_format(date_sub('${run_date}', 1), 'yyyyMMdd')
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

-- ---------------------------------------------------------------------
-- Online hours (SSL)
-- ---------------------------------------------------------------------
-- state: 1 = idle, 2 = pickup, 3 = waiting, 4 = charging (on trip)
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
    WHERE d.pt BETWEEN date_format(date_sub('${run_date}', 28), 'yyyyMMdd') AND date_format(date_sub('${run_date}', 1), 'yyyyMMdd')
      AND d.country_code IN ('DO','PA','MX','PE','CO','EC','AR','CR','CL')
    GROUP BY d.driver_id, d.country_code
),

-- ---------------------------------------------------------------------
-- Finance (SSL): driver income and incentives
-- ---------------------------------------------------------------------
finance AS (
    SELECT
        fp.driver_id,
        fp.country_code,
        SUM(fp.online_driver_divide) AS driver_income,
        SUM(fp.subsidy_b)            AS subsidy_b
    FROM g_caiwu.view_dwm_fin_order_report_capital_di_finance_table_ssl_eg fp
    WHERE fp.pt BETWEEN date_format(date_sub('${run_date}', 28), 'yyyyMMdd') AND date_format(date_sub('${run_date}', 1), 'yyyyMMdd')
      AND fp.country_code IN ('DO','PA','MX','PE','CO','EC','AR','CR','CL')
    GROUP BY fp.driver_id, fp.country_code
),

-- ---------------------------------------------------------------------
-- SHOR (non-SSL): same 28-day period as the rest of the query
-- ---------------------------------------------------------------------
shor AS (
    SELECT
        driver_id,
        country_code,
        AVG(shor_rolling_current) AS shor
    FROM international_bi.driver_wh_shor_detail_bywk_v2
    WHERE concat(CAST(year AS STRING),
                 lpad(CAST(month AS STRING), 2, '0'),
                 lpad(CAST(day   AS STRING), 2, '0'))
          BETWEEN date_format(date_sub('${run_date}', 28), 'yyyyMMdd')
              AND date_format(date_sub('${run_date}', 1), 'yyyyMMdd')
      AND country_code IN ('DO','PA','MX','PE','CO','EC','AR','CR','CL')
      AND shor_rolling_current >= 0
    GROUP BY driver_id, country_code
),

-- ---------------------------------------------------------------------
-- Tickets and compensations (from the CRM ticket query)
-- Same 28-day window as the rest of the query
-- ---------------------------------------------------------------------

-- Tickets created in the period, latest version of each ticket
TICKET AS (
    SELECT *
    FROM (
        SELECT
            t.ticketid,
            t.order_id,
            t.country_code,
            ROW_NUMBER() OVER (PARTITION BY t.requester_id, t.ticketid
                               ORDER BY t.local_update_time DESC) AS rn_tickets
        FROM international_capital.dwd_crm_ticket_capital_di t
        WHERE t.country_code IN ('DO','PA','MX','PE','CO','EC','AR','CR','CL')
          AND t.pt BETWEEN date_format(date_sub('${run_date}', 28), 'yyyyMMdd')
                       AND date_format(date_sub('${run_date}', 1),  'yyyyMMdd')
          AND to_date(t.local_create_time) BETWEEN date_sub('${run_date}', 28)
                                               AND date_sub('${run_date}', 1)
          AND to_date(t.local_update_time) BETWEEN date_sub('${run_date}', 28)
                                               AND date_sub('${run_date}', 1)
    ) x
    WHERE x.rn_tickets = 1
),

-- Driver of each ticketed order. Wider window (40 days before, 5 after)
-- because the ticket can be created days after the trip
TRIP AS (
    SELECT
        order_id,
        driver_id,
        ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY pt) AS rn_trip
    -- NOTE: was dwd_trd_anycar_order_base_capital_di (no SELECT privilege for this user);
    -- the SSL order view has order_id / driver_id / pt / country_code too.
    FROM international_capital.view_dwm_trd_order_pro_core_anycar_base_di_ssl
    WHERE country_code IN ('DO','PA','MX','PE','CO','EC','AR','CR','CL')
      AND order_id IN (SELECT order_id FROM TICKET)
      AND pt BETWEEN date_format(date_sub('${run_date}', 68), 'yyyyMMdd')
                 AND date_format(date_add('${run_date}', 4),  'yyyyMMdd')
),

-- Compensations of those tickets (status 2 = Compensation successful)
COMP AS (
    SELECT
        c.ticketid AS comptkt,
        c.price    AS price_d,
        c.status
    FROM g_caiwu.dwd_fin_compensate_info_global_capital_di c
    WHERE c.country_code IN ('DO','PA','MX','PE','CO','EC','AR','CR','CL')
      AND c.pt BETWEEN date_format(date_sub('${run_date}', 28), 'yyyyMMdd')
                   AND date_format(date_sub('${run_date}', 1),  'yyyyMMdd')
      AND c.ticketid IN (SELECT ticketid FROM TICKET)
      AND c.organization_id = 1
),

-- Tickets per driver (unique ticket ids) and successful compensation in USD
driver_tickets AS (
    SELECT
        tp.driver_id,
        t.country_code,
        COUNT(DISTINCT t.ticketid)                                         AS tickets,
        SUM(CASE WHEN c.status = 2 THEN COALESCE(c.price_d, 0) ELSE 0 END)
            * MAX(COALESCE(cd.local_to_usd_rate, 1))                       AS compensated_usd
    FROM TICKET t
    JOIN TRIP tp
      ON t.order_id = tp.order_id
     AND tp.rn_trip = 1
    LEFT JOIN COMP c
      ON t.ticketid = c.comptkt
    LEFT JOIN currency_dim cd
      ON t.country_code = cd.country_code
    WHERE t.rn_tickets = 1
      AND tp.driver_id IS NOT NULL
    GROUP BY tp.driver_id, t.country_code
),

-- ---------------------------------------------------------------------
-- Driver-level metrics
-- ---------------------------------------------------------------------
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
        mv.vehicle_orders / NULLIF(o.finished_orders, 0) AS main_vehicle_share,

        s.supply_hours,
        s.days_online,
        COALESCE(ad.active_days, 0)                                  AS active_days,
        -- Daily SH = TSH / active days (days with at least one finished trip)
        s.supply_hours / NULLIF(ad.active_days, 0)                   AS daily_sh,

        COALESCE(o.finished_orders, 0)                               AS finished_orders,

        -- Time by state, all from listen_online (same source as TSH)
        s.idle_hours,
        s.pickup_hours,
        s.waiting_hours,
        s.charging_hours,
        s.pickup_hours + s.waiting_hours + s.charging_hours          AS busy_hours,
        -- OR = (pickup + waiting + charging) / TSH
        (s.pickup_hours + s.waiting_hours + s.charging_hours)
            / NULLIF(s.supply_hours, 0)                              AS occupancy_rate,

        COALESCE(f.driver_income, 0)                                 AS driver_income,
        f.driver_income / NULLIF(o.finished_orders, 0)               AS ipt,

        COALESCE(f.subsidy_b, 0)                                     AS subsidy_b,
        CASE WHEN COALESCE(f.subsidy_b, 0) > 0 THEN 1 ELSE 0 END     AS incentive_winner,

        sh.shor,

        -- Tickets and compensations
        COALESCE(dt.tickets, 0)                                      AS tickets,
        COALESCE(dt.tickets, 0) / NULLIF(o.finished_orders, 0)       AS tickets_per_order,
        COALESCE(dt.compensated_usd, 0)                              AS compensated_usd
    FROM supply s
    LEFT JOIN driver_orders o  ON s.driver_id = o.driver_id   AND s.country_code = o.country_code
    LEFT JOIN driver_active_days ad ON s.driver_id = ad.driver_id AND s.country_code = ad.country_code
    LEFT JOIN main_vehicle mv  ON s.driver_id = mv.driver_id  AND s.country_code = mv.country_code
    LEFT JOIN top_product tp   ON s.driver_id = tp.driver_id  AND s.country_code = tp.country_code
    LEFT JOIN main_city mc     ON s.driver_id = mc.driver_id  AND s.country_code = mc.country_code
    LEFT JOIN product_dim pd   ON tp.product_id = pd.product_id
    LEFT JOIN finance f        ON s.driver_id = f.driver_id   AND s.country_code = f.country_code
    LEFT JOIN shor sh          ON s.driver_id = sh.driver_id  AND s.country_code = sh.country_code
    LEFT JOIN driver_tickets dt ON s.driver_id = dt.driver_id AND s.country_code = dt.country_code
    WHERE s.supply_hours > 0
),

-- IPT percentile by country and vehicle type, drivers with trips only
pctl AS (
    SELECT
        country_code,
        vehicle_type,
        percentile_approx(ipt, 0.80) AS ipt_p80
    FROM base
    WHERE finished_orders > 0
    GROUP BY country_code, vehicle_type
),

segmented AS (
    SELECT
        b.*,
        p.ipt_p80,

        CASE
            WHEN b.active_days = 0 THEN 'No Trips'   -- online but no finished trips
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

        -- SHOR: >= 70% is High, < 70% is Low
        -- Assumes SHOR is a ratio (0-1). If it comes as 0-100, change 0.70 to 70.
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

-- ---------------------------------------------------------------------
-- Max occupancy per group = P90 of occupancy_rate among drivers with the
-- same country, city and segment combination
-- ---------------------------------------------------------------------
occ_group AS (
    SELECT
        country_code,
        main_city_id,
        seg_supply_hours,
        seg_ipt,
        seg_incentive,
        seg_shor,
        percentile_approx(occupancy_rate, 0.90)  AS max_occupancy_rate
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
    ROUND(sg.driver_income, 2)    AS driver_income,
    ROUND(sg.ipt, 2)              AS ipt,
    ROUND(sg.subsidy_b, 2)        AS subsidy_b,
    sg.tickets,
    ROUND(sg.tickets_per_order, 4) AS tickets_per_order,
    ROUND(sg.compensated_usd, 2)  AS compensated_usd,
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

    -- Available supply: how many more hours of the driver's TSH could be
    -- filled with trips if he reached the P90 occupancy of his group
    ROUND(sg.occupancy_rate, 4)                                              AS occupancy_rate,
    ROUND(og.max_occupancy_rate, 4)                                          AS max_occupancy_rate,
    ROUND(sg.supply_hours
          * GREATEST(og.max_occupancy_rate - sg.occupancy_rate, CAST(0 AS DOUBLE)), 2)       AS available_tsh,

    -- Average trip cycle = (pickup + waiting + charging) / finished trips
    ROUND(sg.busy_hours / NULLIF(sg.finished_orders, 0) * 60, 1)             AS avg_trip_minutes,

    -- Extra trips the driver could do with his available TSH
    COALESCE(FLOOR(
        sg.supply_hours * GREATEST(og.max_occupancy_rate - sg.occupancy_rate, CAST(0 AS DOUBLE))
        / NULLIF(sg.busy_hours / NULLIF(sg.finished_orders, 0), 0)
    ), 0)                                                                    AS available_trips
FROM segmented sg
LEFT JOIN city_dim cd
       ON sg.main_city_id = cd.city_id
LEFT JOIN occ_group og
       ON  sg.country_code        = og.country_code
      AND  sg.main_city_id       <=> og.main_city_id
      AND  sg.seg_supply_hours    = og.seg_supply_hours
      AND  sg.seg_ipt             = og.seg_ipt
      AND  sg.seg_incentive       = og.seg_incentive
      AND  sg.seg_shor            = og.seg_shor
ORDER BY sg.country_code, sg.driver_id;
