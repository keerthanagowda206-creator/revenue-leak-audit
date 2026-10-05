"""
Revenue Leak Audit - Step 2: generate a CLEAN synthetic D2C e-commerce dataset.

Run from the project folder:   python generate_data.py
Outputs:
    data/clean/*.csv          one CSV per table
    data/revenue_leak.db      SQLite database built from schema.sql

The data is deliberately leak-free. Leaks get planted in Step 3 (plant_leaks.py),
so you always know the ground truth.
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

# ----------------------------- CONFIG ---------------------------------------
SEED = 42
N_CUSTOMERS, N_PRODUCTS, N_REPS, N_ORDERS = 8000, 150, 25, 50000
START, END = pd.Timestamp("2025-04-01"), pd.Timestamp("2026-06-30")  # 15 months
FESTIVAL_WINDOWS = [("2025-10-01", "2025-11-10"),   # Diwali sale
                    ("2026-01-22", "2026-01-28")]   # Republic Day sale
FESTIVAL_EXTRA_DISCOUNT = 10                         # extra % allowed in festival windows

CATEGORIES = {   # price range (INR), cost as share of MRP, max approved discount %
    "Skincare":    dict(price=(249, 1499), cost=(0.30, 0.45), max_disc=15),
    "Haircare":    dict(price=(199, 1199), cost=(0.30, 0.45), max_disc=15),
    "Apparel":     dict(price=(499, 2999), cost=(0.45, 0.60), max_disc=25),
    "Home Decor":  dict(price=(399, 3499), cost=(0.40, 0.55), max_disc=20),
    "Accessories": dict(price=(299, 1999), cost=(0.35, 0.50), max_disc=25),
    "Wellness":    dict(price=(349, 1799), cost=(0.35, 0.50), max_disc=10),
}
FIRST = ["Aarav", "Vihaan", "Aditya", "Arjun", "Rohan", "Karan", "Ishaan", "Rahul", "Ananya",
         "Diya", "Priya", "Neha", "Sneha", "Kavya", "Isha", "Meera", "Pooja", "Riya", "Sanjay", "Vikram"]
LAST = ["Sharma", "Verma", "Iyer", "Reddy", "Nair", "Patel", "Gupta", "Singh", "Mehta", "Das",
        "Kumar", "Joshi", "Rao", "Banerjee", "Shah"]
CITIES = [("Bengaluru", "Karnataka", 14), ("Mumbai", "Maharashtra", 13), ("Delhi", "Delhi", 13),
          ("Hyderabad", "Telangana", 9), ("Chennai", "Tamil Nadu", 8), ("Pune", "Maharashtra", 8),
          ("Kolkata", "West Bengal", 6), ("Ahmedabad", "Gujarat", 5), ("Jaipur", "Rajasthan", 4),
          ("Lucknow", "Uttar Pradesh", 3), ("Kochi", "Kerala", 3), ("Chandigarh", "Chandigarh", 2)]
REGIONS = ["North", "South", "East", "West"]

rng = np.random.default_rng(SEED)
CSV_DIR = Path("data/clean")
CSV_DIR.mkdir(parents=True, exist_ok=True)

# ----------------------------- CUSTOMERS ------------------------------------
city_p = np.array([c[2] for c in CITIES], dtype=float)
city_p /= city_p.sum()
city_idx = rng.choice(len(CITIES), N_CUSTOMERS, p=city_p)
customers = pd.DataFrame({
    "customer_id": [f"C{i:05d}" for i in range(1, N_CUSTOMERS + 1)],
    "customer_name": [f"{a} {b}" for a, b in zip(rng.choice(FIRST, N_CUSTOMERS),
                                                 rng.choice(LAST, N_CUSTOMERS))],
    "city": [CITIES[i][0] for i in city_idx],
    "state": [CITIES[i][1] for i in city_idx],
    "acquisition_channel": rng.choice(
        ["Instagram", "Google Ads", "Organic", "Referral", "Influencer"], N_CUSTOMERS,
        p=[0.30, 0.25, 0.20, 0.15, 0.10]),
})

# ----------------------------- SALES REPS -----------------------------------
reps = pd.DataFrame({
    "rep_id": [f"R{i:02d}" for i in range(1, N_REPS + 1)],
    "rep_name": [f"{a} {b}" for a, b in zip(rng.choice(FIRST, N_REPS), rng.choice(LAST, N_REPS))],
    "region": [REGIONS[i % 4] for i in range(N_REPS)],
    "hire_date": START - pd.to_timedelta(rng.integers(30, 900, N_REPS), unit="D"),
})

# ----------------------------- PRODUCTS + POLICY ----------------------------
cat_names = list(CATEGORIES)
prod_cat = [cat_names[i % len(cat_names)] for i in range(N_PRODUCTS)]
raw_price = np.array([rng.uniform(*CATEGORIES[c]["price"]) for c in prod_cat])
mrp = np.round(raw_price / 10) * 10 - 1                       # prices like 499, 1299
cost_ratio = np.array([rng.uniform(*CATEGORIES[c]["cost"]) for c in prod_cat])
products = pd.DataFrame({
    "product_id": [f"P{i:03d}" for i in range(1, N_PRODUCTS + 1)],
    "product_name": [f"{c} Product {i:03d}" for i, c in enumerate(prod_cat, start=1)],
    "category": prod_cat,
    "mrp": mrp,
    "cost_price": np.round(mrp * cost_ratio, 2),
})
discount_policy = pd.DataFrame({
    "category": cat_names,
    "max_discount_pct": [CATEGORIES[c]["max_disc"] for c in cat_names],
    "festival_max_discount_pct": [CATEGORIES[c]["max_disc"] + FESTIVAL_EXTRA_DISCOUNT for c in cat_names],
})

# ----------------------------- ORDERS ---------------------------------------
days = pd.date_range(START, END)
day_w = np.where(days.dayofweek >= 5, 1.25, 1.0)              # weekend bump
for a, b in FESTIVAL_WINDOWS:                                 # festival bump
    in_window = (days >= pd.Timestamp(a)) & (days <= pd.Timestamp(b))
    day_w = day_w * np.where(in_window, 2.2, 1.0)
day_w = day_w / day_w.sum()
order_dates = days[rng.choice(len(days), N_ORDERS, p=day_w)].sort_values()

order_is_fest = np.zeros(N_ORDERS, dtype=bool)
for a, b in FESTIVAL_WINDOWS:
    order_is_fest |= np.asarray((order_dates >= pd.Timestamp(a)) & (order_dates <= pd.Timestamp(b)))

cust_w = rng.lognormal(0, 1, N_CUSTOMERS)                     # a few loyal, many occasional
cust_w /= cust_w.sum()
channel = rng.choice(["Website", "App", "Marketplace", "WhatsApp"], N_ORDERS, p=[0.40, 0.30, 0.15, 0.15])

orders = pd.DataFrame({
    "order_id": [f"O{i:06d}" for i in range(1, N_ORDERS + 1)],
    "customer_id": customers["customer_id"].values[rng.choice(N_CUSTOMERS, N_ORDERS, p=cust_w)],
    "rep_id": np.where(channel == "WhatsApp", rng.choice(reps["rep_id"], N_ORDERS), None),
    "channel": channel,
    "order_date": order_dates,
    "status": rng.choice(["Delivered", "Cancelled", "Returned"], N_ORDERS, p=[0.88, 0.05, 0.07]),
    "payment_method": rng.choice(["UPI", "Card", "COD", "NetBanking"], N_ORDERS, p=[0.45, 0.20, 0.28, 0.07]),
})

# ----------------------------- ORDER ITEMS ----------------------------------
n_items = rng.choice([1, 2, 3, 4], N_ORDERS, p=[0.60, 0.25, 0.10, 0.05])
item_order_idx = np.repeat(np.arange(N_ORDERS), n_items)
prod_w = rng.lognormal(0, 0.8, N_PRODUCTS)
prod_w /= prod_w.sum()
item_prod_idx = rng.choice(N_PRODUCTS, len(item_order_idx), p=prod_w)
qty = rng.choice([1, 2, 3], len(item_order_idx), p=[0.80, 0.15, 0.05])

cat_max = np.array([CATEGORIES[c]["max_disc"] for c in prod_cat])
item_fest = order_is_fest[item_order_idx]
max_disc = cat_max[item_prod_idx] + FESTIVAL_EXTRA_DISCOUNT * item_fest
levels = max_disc // 5                                        # discounts in steps of 5%
skew = np.where(item_fest, 1.0, 1.6)                          # festival = deeper discounts
disc = (np.floor(rng.random(len(max_disc)) ** skew * (levels + 1)) * 5).astype(int)
assert (disc <= max_disc).all(), "clean data must respect the discount policy"

unit_price = mrp[item_prod_idx]
line_total = np.round(qty * unit_price * (1 - disc / 100), 2)
order_items = pd.DataFrame({
    "item_id": [f"I{i:06d}" for i in range(1, len(item_order_idx) + 1)],
    "order_id": orders["order_id"].values[item_order_idx],
    "product_id": products["product_id"].values[item_prod_idx],
    "quantity": qty,
    "unit_price": unit_price,
    "discount_pct": disc,
    "line_total": line_total,
})
orders["order_total"] = np.round(np.bincount(item_order_idx, weights=line_total), 2)

# signup date = shortly before first order (or random for customers who never ordered)
first_order = customers["customer_id"].map(orders.groupby("customer_id")["order_date"].min())
signup = first_order - pd.to_timedelta(rng.integers(0, 31, N_CUSTOMERS), unit="D")
random_signup = pd.Series(START + pd.to_timedelta(rng.integers(0, (END - START).days, N_CUSTOMERS), unit="D"))
customers["signup_date"] = signup.where(signup.notna(), random_signup)

# ----------------------------- INVOICES (delivered + returned orders) -------
billable = orders[orders["status"].isin(["Delivered", "Returned"])].reset_index(drop=True)
invoices = pd.DataFrame({
    "invoice_id": [f"INV-{i:07d}" for i in range(1, len(billable) + 1)],
    "order_id": billable["order_id"],
    "invoice_date": billable["order_date"] + pd.to_timedelta(rng.integers(1, 4, len(billable)), unit="D"),
    "invoice_amount": billable["order_total"],
})

# ----------------------------- PAYMENTS -------------------------------------
pay_method = billable["payment_method"].values
delay = np.where(pay_method == "COD", rng.integers(3, 9, len(invoices)), 0)   # COD pays later
payments = pd.DataFrame({
    "payment_id": [f"PAY-{i:07d}" for i in range(1, len(invoices) + 1)],
    "invoice_id": invoices["invoice_id"],
    "payment_date": invoices["invoice_date"] + pd.to_timedelta(delay, unit="D"),
    "amount": invoices["invoice_amount"],
    "payment_status": "Success",
})

# ----------------------------- REFUNDS (returned orders) --------------------
returned = invoices[billable["status"].values == "Returned"].reset_index(drop=True)
refunds = pd.DataFrame({
    "refund_id": [f"REF-{i:06d}" for i in range(1, len(returned) + 1)],
    "order_id": returned["order_id"],
    "refund_date": returned["invoice_date"] + pd.to_timedelta(rng.integers(5, 16, len(returned)), unit="D"),
    "refund_amount": returned["invoice_amount"],
    "reason": rng.choice(["Size/Fit issue", "Damaged product", "Not as described", "Changed mind",
                          "Late delivery"], len(returned), p=[0.30, 0.20, 0.20, 0.20, 0.10]),
})

# ----------------------------- SAVE -----------------------------------------
tables = {"customers": customers, "products": products, "sales_reps": reps,
          "discount_policy": discount_policy, "orders": orders, "order_items": order_items,
          "invoices": invoices, "payments": payments, "refunds": refunds}

for name, df in tables.items():
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%d")
    df.to_csv(CSV_DIR / f"{name}.csv", index=False)

db_path = Path("data/revenue_leak.db")
if db_path.exists():
    db_path.unlink()
con = sqlite3.connect(db_path)
con.executescript(Path("schema.sql").read_text())
for name, df in tables.items():
    df.to_sql(name, con, if_exists="append", index=False)
con.commit()
con.close()

# ----------------------------- SANITY CHECKS --------------------------------
print("Rows per table:")
for name, df in tables.items():
    print(f"  {name:<16}{len(df):>8,}")
print(f"\nTotal invoiced revenue : Rs {invoices['invoice_amount'].sum():,.0f}")
print(f"Total refunded         : Rs {refunds['refund_amount'].sum():,.0f}")
print(f"Avg discount           : {order_items['discount_pct'].mean():.1f}%")
print(f"Orders in festival sale: {order_is_fest.mean():.1%}")
print("\nDone. Clean data saved to data/clean/ and data/revenue_leak.db")
