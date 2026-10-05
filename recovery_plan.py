from pathlib import Path

import pandas as pd

REGISTER = Path("data/output/leak_register.csv")
OUT_DIR = Path("data/output")
MONTHS_IN_DATA = 15          # Apr 2025 - Jun 2026

# ---------- YOUR ASSUMPTIONS (edit these; state them clearly in your report) ----------
# recovery rates = share of the leaked money the fix could realistically save
# effort = 1 (very easy) to 5 (very hard)
PLAN = {
    "FAILED_PAYMENT_NO_RETRY": dict(
        cons=0.40, exp=0.60, opt=0.80, effort=2,
        cause="Failed payments are never retried or followed up",
        fix="Automatic payment retry plus payment-link reminders for failed orders"),
    "UNBILLED_ORDER": dict(
        cons=0.50, exp=0.70, opt=0.90, effort=3,
        cause="No check that every delivered order gets an invoice",
        fix="Daily reconciliation of delivered orders vs invoices; raise missing invoices"),
    "DISCOUNT_ABUSE": dict(
        cons=0.30, exp=0.60, opt=0.90, effort=2,
        cause="Reps can give discounts above the approved cap",
        fix="Enforce the cap in the order system; manager approval above the limit"),
    "DUPLICATE_REFUND": dict(
        cons=0.30, exp=0.50, opt=0.70, effort=1,
        cause="Refund process allows the same order to be refunded twice",
        fix="Block a second refund per order; claw back existing duplicates"),
    "STALE_PRICE": dict(
        cons=0.70, exp=0.90, opt=1.00, effort=1,
        cause="Marketplace price list was not updated",
        fix="Sync Marketplace prices with the master price list automatically"),
}

leaks = (pd.read_csv(REGISTER).groupby("leak_type")
         .agg(cases=("record_id", "count"), leaked=("leak_amount", "sum")).reset_index())

for key in ["cons", "exp", "opt", "effort", "cause", "fix"]:
    leaks[key] = leaks["leak_type"].map(lambda t, k=key: PLAN[t][k])
leaks["recover_cons"] = leaks["leaked"] * leaks["cons"]
leaks["recover_exp"] = leaks["leaked"] * leaks["exp"]
leaks["recover_opt"] = leaks["leaked"] * leaks["opt"]

# priority = expected money saved per unit of effort (higher = do first)
leaks["priority_score"] = leaks["recover_exp"] / leaks["effort"]
leaks = leaks.sort_values("priority_score", ascending=False).reset_index(drop=True)
leaks.insert(0, "priority", leaks.index + 1)


def lakh(x):
    return f"{x / 1e5:,.2f}"


view = pd.DataFrame({
    "priority": leaks["priority"],
    "leak_type": leaks["leak_type"],
    "cases": leaks["cases"],
    "leaked_L": leaks["leaked"].map(lakh),
    "conservative_L": leaks["recover_cons"].map(lakh),
    "expected_L": leaks["recover_exp"].map(lakh),
    "optimistic_L": leaks["recover_opt"].map(lakh),
    "effort(1-5)": leaks["effort"],
})
print("RECOVERY PLAN (all amounts in Rs lakh)\n")
print(view.to_string(index=False))

tot = leaks[["leaked", "recover_cons", "recover_exp", "recover_opt"]].sum()
print(f"\nTotal leaked      : Rs {lakh(tot['leaked'])} lakh over {MONTHS_IN_DATA} months")
print(f"Realistically recoverable:")
print(f"  conservative    : Rs {lakh(tot['recover_cons'])} lakh")
print(f"  expected        : Rs {lakh(tot['recover_exp'])} lakh  ({tot['recover_exp'] / tot['leaked']:.0%} of leakage)")
print(f"  optimistic      : Rs {lakh(tot['recover_opt'])} lakh")
yearly = tot["leaked"] * 12 / MONTHS_IN_DATA
print(f"Yearly equivalent of the leakage: about Rs {lakh(yearly)} lakh per year")

print("\nFIX THESE IN THIS ORDER\n")
for _, r in leaks.iterrows():
    print(f"{r['priority']}. {r['leak_type']}")
    print(f"   Cause: {r['cause']}")
    print(f"   Fix  : {r['fix']}\n")

leaks.to_csv(OUT_DIR / "recovery_plan.csv", index=False)
print("Saved: data/output/recovery_plan.csv")