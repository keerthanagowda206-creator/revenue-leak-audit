import sqlite3
from pathlib import Path

import pandas as pd

DB = Path("data/revenue_leak_audit.db")
OUT_DIR = Path("data/output")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------- SETUP: festival calendar + empty leak register ----------
SETUP = """
DROP TABLE IF EXISTS festival_calendar;
CREATE TABLE festival_calendar (sale_name TEXT, start_date TEXT, end_date TEXT);
INSERT INTO festival_calendar VALUES
    ('Diwali Sale',       '2025-10-01', '2025-11-10'),
    ('Republic Day Sale', '2026-01-22', '2026-01-28');

DROP TABLE IF EXISTS leak_register;
CREATE TABLE leak_register (
    leak_type TEXT, order_id TEXT, record_id TEXT, leak_amount REAL, detail TEXT
);
"""

# ---------- RULE 1: delivered orders that were never invoiced ----------
RULE_1 = """
INSERT INTO leak_register
SELECT 'UNBILLED_ORDER', o.order_id, o.order_id, o.order_total,
       'delivered order has no invoice'
FROM orders o
LEFT JOIN invoices i ON i.order_id = o.order_id
WHERE o.status = 'Delivered' AND i.invoice_id IS NULL;
"""

# ---------- RULE 2: invoices with no successful payment ----------
RULE_2 = """
INSERT INTO leak_register
SELECT 'FAILED_PAYMENT_NO_RETRY', i.order_id, i.invoice_id, i.invoice_amount,
       'no successful payment on this invoice'
FROM invoices i
WHERE NOT EXISTS (
    SELECT 1 FROM payments p
    WHERE p.invoice_id = i.invoice_id AND p.payment_status = 'Success'
);
"""

# ---------- RULE 3: orders refunded more than once ----------
RULE_3 = """
INSERT INTO leak_register
SELECT 'DUPLICATE_REFUND', order_id, refund_id, refund_amount,
       'refund #' || rn || ' paid for the same order'
FROM (
    SELECT refund_id, order_id, refund_amount,
           ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY refund_date, refund_id) AS rn
    FROM refunds
)
WHERE rn > 1;
"""

# ---------- RULE 4: discounts above the approved cap (festival-aware) ----------
RULE_4 = """
WITH item_cap AS (
    SELECT oi.item_id, oi.order_id, oi.quantity, oi.unit_price, oi.discount_pct, o.rep_id,
           CASE
               WHEN EXISTS (SELECT 1 FROM festival_calendar f
                            WHERE o.order_date BETWEEN f.start_date AND f.end_date)
                   THEN d.festival_max_discount_pct
               ELSE d.max_discount_pct
           END AS cap_pct
    FROM order_items oi
    JOIN orders          o ON o.order_id   = oi.order_id
    JOIN products        p ON p.product_id = oi.product_id
    JOIN discount_policy d ON d.category   = p.category
    WHERE o.status = 'Delivered'
)
INSERT INTO leak_register
SELECT 'DISCOUNT_ABUSE', order_id, item_id,
       ROUND(quantity * unit_price * (discount_pct - cap_pct) / 100.0, 2),
       COALESCE(rep_id, 'no rep') || ': ' || discount_pct || '% given vs ' || cap_pct || '% cap'
FROM item_cap
WHERE discount_pct > cap_pct;
"""
# ---------- RULE 5: items sold below the list price (found by the anomaly model) ----------
RULE_5 = """
INSERT INTO leak_register
SELECT 'STALE_PRICE', oi.order_id, oi.item_id,
       ROUND(oi.quantity * (p.mrp - oi.unit_price) * (1 - oi.discount_pct / 100.0), 2),
       oi.product_id || ' sold at ' || oi.unit_price || ' vs list price ' || p.mrp
           || ' on ' || o.channel
FROM order_items oi
JOIN orders   o ON o.order_id   = oi.order_id
JOIN products p ON p.product_id = oi.product_id
WHERE o.status = 'Delivered'
  AND oi.unit_price < p.mrp - 0.005;
"""
# ---------- RUN EVERYTHING ----------
con = sqlite3.connect(DB)
for name, sql in [("setup", SETUP), ("rule 1", RULE_1), ("rule 2", RULE_2),
                                    ("rule 3", RULE_3), ("rule 4", RULE_4), ("rule 5", RULE_5)]:
    con.executescript(sql)
    print(f"ran {name}")
con.commit()

register = pd.read_sql("SELECT * FROM leak_register", con)
delivered_value = pd.read_sql(
    "SELECT SUM(order_total) AS v FROM orders WHERE status = 'Delivered'", con)["v"][0]
con.close()

summary = (register.groupby("leak_type")
           .agg(cases=("record_id", "count"), amount=("leak_amount", "sum"))
           .sort_values("amount", ascending=False))
summary["share_of_delivered_value"] = summary["amount"] / delivered_value

print("\nLEAKS FOUND BY THE RULE ENGINE\n")
view = summary.copy()
view["amount"] = view["amount"].map("Rs {:,.0f}".format)
view["share_of_delivered_value"] = view["share_of_delivered_value"].map("{:.2%}".format)
print(view.to_string())

total = register["leak_amount"].sum()
print(f"\nTotal flagged : Rs {total:,.0f}  ({total / delivered_value:.2%} of delivered order value)")
print(f"Rows flagged  : {len(register):,}")

register.to_csv(OUT_DIR / "leak_register.csv", index=False)
print("\nSaved: data/output/leak_register.csv")