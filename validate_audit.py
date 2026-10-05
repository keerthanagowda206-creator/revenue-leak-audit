import sqlite3
from pathlib import Path

import pandas as pd

DB = Path("data/revenue_leak_audit.db")
REGISTER = Path("data/output/leak_register.csv")
TRUTH = Path("data/ground_truth/ground_truth.csv")
OUT_DIR = Path("data/output")

found = pd.read_csv(REGISTER)           # what YOUR audit flagged
truth = pd.read_csv(TRUTH)              # the hidden answer key
real = truth[truth["is_real_leak"] == 1]
decoys = truth[truth["is_real_leak"] == 0]


def pct(x):
    return f"{x:.1%}"


# ---------- PART 1: score your audit, leak type by leak type ----------
rows = []
for leak_type, planted in real.groupby("leak_type"):
    flagged = found[found["leak_type"] == leak_type]
    correct_ids = set(flagged["record_id"]) & set(planted["record_id"])
    n_flagged, n_planted, n_correct = len(flagged), len(planted), len(correct_ids)
    rows.append({
        "leak_type": leak_type,
        "planted": n_planted,
        "flagged": n_flagged,
        "correct": n_correct,
        "false_alarms": n_flagged - n_correct,
        "missed": n_planted - n_correct,
        "precision": n_correct / n_flagged if n_flagged else 0,
        "recall": n_correct / n_planted,
        "rs_planted": planted["leak_amount"].sum(),
        "rs_found": flagged[flagged["record_id"].isin(correct_ids)]["leak_amount"].sum(),
    })
report = pd.DataFrame(rows)

total = {"leak_type": "ALL TYPES"}
for col in ["planted", "flagged", "correct", "false_alarms", "missed", "rs_planted", "rs_found"]:
    total[col] = report[col].sum()
total["precision"] = total["correct"] / total["flagged"]
total["recall"] = total["correct"] / total["planted"]
report = pd.concat([report, pd.DataFrame([total])], ignore_index=True)

show = report.copy()
show["precision"] = show["precision"].map(pct)
show["recall"] = show["recall"].map(pct)
show["rs_planted"] = show["rs_planted"].map("{:,.0f}".format)
show["rs_found"] = show["rs_found"].map("{:,.0f}".format)
print("YOUR AUDIT vs THE ANSWER KEY\n")
print(show.to_string(index=False))
print("\nprecision = of everything you flagged, how much was a real leak")
print("recall    = of all real leaks, how many you caught")

# ---------- PART 2: did the decoys fool you? ----------
decoy_ids = set(decoys["record_id"])
fooled = decoy_ids & set(found["record_id"])
print(f"\nDECOYS (payments that failed but were retried successfully): "
      f"{len(decoy_ids):,}  ->  wrongly flagged by your audit: {len(fooled)}")

# ---------- PART 3: why careful rules matter (naive rules for comparison) ----------
con = sqlite3.connect(DB)
naive_fail = set(pd.read_sql(
    "SELECT DISTINCT invoice_id FROM payments WHERE payment_status = 'Failed'", con)["invoice_id"])
naive_disc = set(pd.read_sql("""
    SELECT oi.item_id
    FROM order_items oi
    JOIN orders o          ON o.order_id   = oi.order_id
    JOIN products p        ON p.product_id = oi.product_id
    JOIN discount_policy d ON d.category   = p.category
    WHERE o.status = 'Delivered' AND oi.discount_pct > d.max_discount_pct
""", con)["item_id"])
con.close()

naive_rows = []
for name, flagged_ids, leak_type in [
        ("Naive: 'any failed payment' (ignores retries)", naive_fail, "FAILED_PAYMENT_NO_RETRY"),
        ("Naive: 'discount above normal cap' (ignores festivals)", naive_disc, "DISCOUNT_ABUSE")]:
    planted_ids = set(real[real["leak_type"] == leak_type]["record_id"])
    correct = len(flagged_ids & planted_ids)
    naive_rows.append({"rule": name, "flagged": len(flagged_ids), "correct": correct,
                       "false_alarms": len(flagged_ids) - correct,
                       "precision": pct(correct / len(flagged_ids)),
                       "recall": pct(correct / len(planted_ids))})
print("\nNAIVE RULES FOR COMPARISON (what happens if you skip the careful logic)\n")
print(pd.DataFrame(naive_rows).to_string(index=False))

report.to_csv(OUT_DIR / "validation_report.csv", index=False)
print("\nSaved: data/output/validation_report.csv")