import sqlite3
from pathlib import Path

import pandas as pd

DB = Path("data/revenue_leak_audit.db")
OUT = Path("data/powerbi")
OUT.mkdir(parents=True, exist_ok=True)

LABELS = {
    "FAILED_PAYMENT_NO_RETRY": "Failed payments, no retry",
    "UNBILLED_ORDER": "Unbilled orders",
    "DISCOUNT_ABUSE": "Discounts above cap",
    "DUPLICATE_REFUND": "Duplicate refunds",
    "STALE_PRICE": "Stale marketplace prices",
}

con = sqlite3.connect(DB)

# One row per leak, enriched with date, channel, rep and city
leaks = pd.read_sql("""
    SELECT l.leak_type, l.order_id, l.record_id, l.leak_amount, l.detail,
           o.order_date,
           substr(o.order_date, 1, 7) || '-01' AS month,
           o.channel, o.rep_id, c.city, c.state
    FROM leak_register l
    JOIN orders o         ON o.order_id    = l.order_id
    LEFT JOIN customers c ON c.customer_id = o.customer_id
""", con)
leaks.insert(1, "leak_label", leaks["leak_type"].map(LABELS))
leaks.to_csv(OUT / "leaks.csv", index=False)

# Delivered order value per month (to turn leaks into a % of revenue)
revenue = pd.read_sql("""
    SELECT substr(order_date, 1, 7) || '-01' AS month, SUM(order_total) AS delivered_value
    FROM orders WHERE status = 'Delivered' GROUP BY 1 ORDER BY 1
""", con)
revenue.to_csv(OUT / "monthly_revenue.csv", index=False)

# Recovery plan with readable labels
plan = pd.read_csv("data/output/recovery_plan.csv")
plan.insert(1, "leak_label", plan["leak_type"].map(LABELS))
plan.to_csv(OUT / "recovery_plan.csv", index=False)

con.close()
print(f"leaks.csv           {len(leaks):,} rows")
print(f"monthly_revenue.csv {len(revenue)} rows")
print(f"recovery_plan.csv   {len(plan)} rows")
print("\nSaved in data/powerbi/ - import these 3 files into Power BI")