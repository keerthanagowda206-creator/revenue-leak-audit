"""
Revenue Leak Audit - Step 3: plant KNOWN leaks into the clean dataset.

Run after generate_data.py:    python plant_leaks.py

Reads : data/clean/*.csv
Writes: data/leaky/*.csv                      the "company data" you will audit
        data/revenue_leak_audit.db            same data as a SQLite database (use this one!)
        data/ground_truth/ground_truth.csv    THE ANSWER KEY - do not open until Step 6

Five leak types are planted, plus "decoys": suspicious-looking events that are NOT
leaks (e.g. a payment that failed and was successfully retried). Decoys let you
measure false positives (precision) when you validate your audit in Step 6.
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

# ----------------------------- CONFIG ---------------------------------------
SEED = 7
rng = np.random.default_rng(SEED)

CLEAN, LEAKY, TRUTH = Path("data/clean"), Path("data/leaky"), Path("data/ground_truth")
LEAKY.mkdir(parents=True, exist_ok=True)
TRUTH.mkdir(parents=True, exist_ok=True)

FESTIVAL_WINDOWS = [("2025-10-01", "2025-11-10"), ("2026-01-22", "2026-01-28")]  # same as Step 2

PCT_UNBILLED = 0.03          # share of delivered orders that never get invoiced
PCT_FAILED_NO_RETRY = 0.04   # share of delivered orders whose payment failed, never retried
PCT_DUP_REFUNDS = 0.02       # share of refunds that get paid out twice
N_BAD_REPS = 6               # reps who give out-of-policy discounts
SHARE_ABUSED_ITEMS = 0.50    # share of a bad rep's items that get an out-of-policy discount
N_STALE_PRODUCTS = 8         # marketplace products listed at a stale, lower price
STALE_PRICE_CUT = 0.15       # stale listing is 15% below MRP
STALE_WINDOW = ("2025-08-01", "2026-02-28")
PCT_DECOY_RETRY = 0.05       # failed-then-retried payments (NOT leaks)

# ----------------------------- LOAD -----------------------------------------
NAMES = ["customers", "products", "sales_reps", "discount_policy", "orders",
         "order_items", "invoices", "payments", "refunds"]
t = {n: pd.read_csv(CLEAN / f"{n}.csv") for n in NAMES}
products, policy, reps = t["products"], t["discount_policy"], t["sales_reps"]
orders, items, invoices, payments, refunds = (t["orders"], t["order_items"], t["invoices"],
                                              t["payments"], t["refunds"])

n_delivered = int((orders["status"] == "Delivered").sum())
clean_delivered_value = orders.loc[orders["status"] == "Delivered", "order_total"].sum()

order_info = orders.set_index("order_id")
order_dt = pd.to_datetime(order_info["order_date"])
is_festival = pd.Series(False, index=order_info.index)
for a, b in FESTIVAL_WINDOWS:
    is_festival |= (order_dt >= pd.Timestamp(a)) & (order_dt <= pd.Timestamp(b))

truth_parts = []   # collects ground-truth rows


def record(leak_type, order_ids, record_ids, amounts, details, is_real=1):
    truth_parts.append(pd.DataFrame({
        "leak_type": leak_type, "order_id": list(order_ids), "record_id": list(record_ids),
        "leak_amount": np.round(np.asarray(amounts, dtype=float), 2),
        "is_real_leak": is_real, "detail": list(details)}))


# item-level helper columns (mapped, so row order never changes)
i_status = items["order_id"].map(order_info["status"])
i_channel = items["order_id"].map(order_info["channel"])
i_rep = items["order_id"].map(order_info["rep_id"])
i_date = items["order_id"].map(order_dt)
i_cat = items["product_id"].map(products.set_index("product_id")["category"])
i_cap = np.where(items["order_id"].map(is_festival),
                 i_cat.map(policy.set_index("category")["festival_max_discount_pct"]),
                 i_cat.map(policy.set_index("category")["max_discount_pct"])).astype(int)

# ----------------------------- LEAK 1: DISCOUNT ABUSE -----------------------
# A few WhatsApp reps give discounts ABOVE the approved cap on delivered orders.
bad_reps = rng.choice(reps["rep_id"], N_BAD_REPS, replace=False)
pick = (i_status == "Delivered") & i_rep.isin(bad_reps) & (rng.random(len(items)) < SHARE_ABUSED_ITEMS)
excess_pts = rng.choice([10, 15, 20], len(items))
new_disc = np.minimum(i_cap + excess_pts, 60)

leak_amt = items["quantity"] * items["unit_price"] * (new_disc - i_cap) / 100   # given away beyond policy
sel = pick.to_numpy()
record("DISCOUNT_ABUSE", items.loc[sel, "order_id"], items.loc[sel, "item_id"], leak_amt[sel],
       [f"{r}: {d}% given vs {c}% cap" for r, d, c in zip(i_rep[sel], new_disc[sel], i_cap[sel])])
items.loc[sel, "discount_pct"] = new_disc[sel]
items.loc[sel, "line_total"] = np.round(items.loc[sel, "quantity"] * items.loc[sel, "unit_price"]
                                        * (1 - new_disc[sel] / 100), 2)
used_orders = set(items.loc[sel, "order_id"])

# ----------------------------- LEAK 2: STALE PRICE LIST ---------------------
# Some products are sold on the Marketplace at an outdated price, below MRP, for months.
stale = rng.choice(products["product_id"], N_STALE_PRODUCTS, replace=False)
sel = ((i_status == "Delivered") & (i_channel == "Marketplace") & items["product_id"].isin(stale)
       & (i_date >= pd.Timestamp(STALE_WINDOW[0])) & (i_date <= pd.Timestamp(STALE_WINDOW[1]))).to_numpy()
old_line = items.loc[sel, "line_total"].copy()
items.loc[sel, "unit_price"] = np.round(items.loc[sel, "unit_price"] * (1 - STALE_PRICE_CUT), 2)
items.loc[sel, "line_total"] = np.round(items.loc[sel, "quantity"] * items.loc[sel, "unit_price"]
                                        * (1 - items.loc[sel, "discount_pct"] / 100), 2)
record("STALE_PRICE", items.loc[sel, "order_id"], items.loc[sel, "item_id"],
       old_line - items.loc[sel, "line_total"],
       [f"{p} sold {int(STALE_PRICE_CUT * 100)}% below MRP on Marketplace" for p in items.loc[sel, "product_id"]])
used_orders |= set(items.loc[sel, "order_id"])

# ----------------------------- RECOMPUTE TOTALS -----------------------------
order_total = items.groupby("order_id")["line_total"].sum().round(2)
orders["order_total"] = orders["order_id"].map(order_total)
inv_amount = invoices["order_id"].map(orders.set_index("order_id")["order_total"])
invoices["invoice_amount"] = inv_amount
payments["amount"] = payments["invoice_id"].map(invoices.set_index("invoice_id")["invoice_amount"])
refunds["refund_amount"] = refunds["order_id"].map(order_total)

inv_order = invoices.set_index("invoice_id")["order_id"]
inv_status = invoices["order_id"].map(orders.set_index("order_id")["status"])

# ----------------------------- LEAK 3: UNBILLED ORDERS ----------------------
cand = invoices[(inv_status == "Delivered") & ~invoices["order_id"].isin(used_orders)]
chosen = cand.loc[rng.choice(cand.index, int(PCT_UNBILLED * n_delivered), replace=False)]
record("UNBILLED_ORDER", chosen["order_id"], chosen["order_id"], chosen["invoice_amount"],
       ["delivered order never invoiced"] * len(chosen))
used_orders |= set(chosen["order_id"])
invoices = invoices[~invoices["invoice_id"].isin(chosen["invoice_id"])]
payments = payments[~payments["invoice_id"].isin(chosen["invoice_id"])]

# ----------------------------- LEAK 4: FAILED PAYMENT, NEVER RETRIED --------
inv_status = invoices["order_id"].map(orders.set_index("order_id")["status"])
cand = invoices[(inv_status == "Delivered") & ~invoices["order_id"].isin(used_orders)]
chosen = cand.loc[rng.choice(cand.index, int(PCT_FAILED_NO_RETRY * n_delivered), replace=False)]
record("FAILED_PAYMENT_NO_RETRY", chosen["order_id"], chosen["invoice_id"], chosen["invoice_amount"],
       ["payment failed, no successful retry"] * len(chosen))
used_orders |= set(chosen["order_id"])
payments.loc[payments["invoice_id"].isin(chosen["invoice_id"]), "payment_status"] = "Failed"

# ----------------------------- DECOYS: FAILED THEN RETRIED (not leaks) ------
inv_status = invoices["order_id"].map(orders.set_index("order_id")["status"])
cand = invoices[(inv_status == "Delivered") & ~invoices["order_id"].isin(used_orders)]
chosen = cand.loc[rng.choice(cand.index, int(PCT_DECOY_RETRY * n_delivered), replace=False)]
record("DECOY_RETRIED_PAYMENT", chosen["order_id"], chosen["invoice_id"], [0] * len(chosen),
       ["failed first, retry succeeded - NOT a leak"] * len(chosen), is_real=0)
mask = payments["invoice_id"].isin(chosen["invoice_id"])
retry = payments[mask].copy()
payments.loc[mask, "payment_status"] = "Failed"
next_id = len(t["payments"])
retry["payment_id"] = [f"PAY-{next_id + i:07d}" for i in range(1, len(retry) + 1)]
retry["payment_date"] = (pd.to_datetime(retry["payment_date"])
                         + pd.to_timedelta(rng.integers(1, 4, len(retry)), unit="D")).dt.strftime("%Y-%m-%d")
retry["payment_status"] = "Success"
payments = pd.concat([payments, retry]).sort_values(["payment_date", "payment_id"]).reset_index(drop=True)

# ----------------------------- LEAK 5: DUPLICATE REFUNDS --------------------
dups = refunds.loc[rng.choice(refunds.index, int(PCT_DUP_REFUNDS * len(refunds)), replace=False)].copy()
next_id = len(refunds)
dups["refund_id"] = [f"REF-{next_id + i:06d}" for i in range(1, len(dups) + 1)]
dups["refund_date"] = (pd.to_datetime(dups["refund_date"])
                       + pd.to_timedelta(rng.integers(2, 11, len(dups)), unit="D")).dt.strftime("%Y-%m-%d")
record("DUPLICATE_REFUND", dups["order_id"], dups["refund_id"], dups["refund_amount"],
       ["order refunded twice"] * len(dups))
refunds = pd.concat([refunds, dups]).sort_values(["refund_date", "refund_id"]).reset_index(drop=True)

# ----------------------------- SAVE DATA ------------------------------------
t.update(orders=orders, order_items=items, invoices=invoices, payments=payments, refunds=refunds)
for name, df in t.items():
    df.to_csv(LEAKY / f"{name}.csv", index=False)

db_path = Path("data/revenue_leak_audit.db")
if db_path.exists():
    db_path.unlink()
con = sqlite3.connect(db_path)
con.executescript(Path("schema.sql").read_text())
for name in NAMES:
    t[name].to_sql(name, con, if_exists="append", index=False)
con.commit()
con.close()

# ----------------------------- SAVE ANSWER KEY ------------------------------
truth = pd.concat(truth_parts, ignore_index=True)
truth.insert(0, "leak_id", [f"L{i:05d}" for i in range(1, len(truth) + 1)])
truth.to_csv(TRUTH / "ground_truth.csv", index=False)

# ----------------------------- SUMMARY --------------------------------------
real = truth[truth["is_real_leak"] == 1]
summary = real.groupby("leak_type").agg(cases=("leak_id", "count"), amount=("leak_amount", "sum"))
print("Planted leaks (answer key saved - don't peek until Step 6):\n")
print(summary.assign(amount=summary["amount"].map("Rs {:,.0f}".format)).to_string())
print(f"\nTotal planted leakage : Rs {real['leak_amount'].sum():,.0f} "
      f"({real['leak_amount'].sum() / clean_delivered_value:.1%} of delivered order value)")
print(f"Decoys (not leaks)    : {int((truth['is_real_leak'] == 0).sum()):,}")
print("\nAudit database ready: data/revenue_leak_audit.db")
