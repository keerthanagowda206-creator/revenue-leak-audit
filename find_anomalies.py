import sqlite3
from pathlib import Path

import pandas as pd
from sklearn.ensemble import IsolationForest

DB = Path("data/revenue_leak_audit.db")
OUT_DIR = Path("data/output")
OUT_DIR.mkdir(parents=True, exist_ok=True)

con = sqlite3.connect(DB)

# 1) Every item sold in a delivered order, with its price compared to the list price (MRP)
items = pd.read_sql("""
    SELECT oi.item_id, oi.product_id, oi.quantity, oi.discount_pct,
           o.channel, o.order_date,
           oi.unit_price / p.mrp AS price_ratio
    FROM order_items oi
    JOIN orders   o ON o.order_id   = oi.order_id
    JOIN products p ON p.product_id = oi.product_id
    WHERE o.status = 'Delivered'
""", con)

# 2) Remove items the 4 rules already caught: we are hunting for NEW kinds of leaks
known = pd.read_sql("SELECT record_id FROM leak_register", con)["record_id"]
items = items[~items["item_id"].isin(known)]

# 3) Build a "behaviour profile" for every product x channel combination
items["below_mrp"] = items["price_ratio"] < 0.999
profile = (items.groupby(["product_id", "channel"])
           .agg(items_sold=("item_id", "count"),
                avg_price_ratio=("price_ratio", "mean"),
                avg_discount=("discount_pct", "mean"),
                avg_qty=("quantity", "mean"),
                items_below_mrp=("below_mrp", "sum"))
           .reset_index())
print(f"Product x channel combinations scanned: {len(profile)}")

# 4) Isolation Forest: flag the combinations that behave least like the others
features = ["avg_price_ratio", "avg_discount", "avg_qty"]
model = IsolationForest(n_estimators=300, contamination=0.02, random_state=42)
profile["unusual"] = model.fit_predict(profile[features]) == -1
profile["score"] = -model.score_samples(profile[features])      # higher = more unusual

# 5) For the investigator: when did the below-MRP sales happen?
dates = (items[items["below_mrp"]].groupby(["product_id", "channel"])["order_date"]
         .agg(first_below_mrp="min", last_below_mrp="max").reset_index())
flagged = (profile[profile["unusual"]]
           .merge(dates, on=["product_id", "channel"], how="left")
           .sort_values("score", ascending=False))

print(f"Combinations flagged as unusual: {len(flagged)}\n")
show = flagged[["product_id", "channel", "items_sold", "avg_price_ratio", "avg_discount",
                "items_below_mrp", "first_below_mrp", "last_below_mrp"]].round(2)
print(show.to_string(index=False))

flagged.to_csv(OUT_DIR / "anomalies.csv", index=False)
print("\nSaved: data/output/anomalies.csv")
print("\nYOUR JOB: look at the table. What do the flagged rows have in common?")
con.close()