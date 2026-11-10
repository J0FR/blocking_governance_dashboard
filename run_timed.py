import time
from extract_data import query_hive, query_presto

SQL = """
with
product_dim AS (
    SELECT DISTINCT
        product_id,
        two_level_biz_cate AS vehicle_category
    FROM international_capital.dim_pub_product_category_df
    WHERE pt = date_format(date_sub(current_date(), 2), 'yyyyMMdd')
      AND country_code IN ('DO','PA','MX','PE','CO','EC','AR','CR','CL')
)
select *
from product_dim
"""

for name, fn in [("hive", query_hive), ("presto", query_presto)]:
    t = time.perf_counter()
    try:
        df = fn(SQL)
        print(f"{name}: {len(df)} rows in {time.perf_counter()-t:.1f}s")
    except Exception as e:
        print(f"{name}: FAILED after {time.perf_counter()-t:.1f}s -> {type(e).__name__}: {str(e)[:500]}")
