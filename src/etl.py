"""Layer 1: clean and join the MoJ data into one row per Crown Court per quarter.

Output: data/clean/court_quarter.parquet
"""
import pandas as pd

RAW = "data/raw/"
CLEAN = "data/clean/"
CLOSED = ["Blackfriars", "Dorchester", "Unknown"]  # closed courts + unassigned rows

# Ineffective-trial reason codes grouped into the levers we model
LEVERS = {
    "prosecution": [1, 2, 3, 4, 5, 6, 15, 16],  # prosecution / witness not ready
    "overlisting": [24],
    "defence_advocate": [19, 20, 21],
    "prisoner_not_produced": [14],
    "judge": [23],
}

# --- Step 1-2: load trials, keep Crown Court from 2016 (your start) ---
df = pd.read_csv(RAW + "trials_2026Q2.csv")
crown_df = df[(df["court_type"] == "Crown") & (df["year"] >= 2016)].copy()
# all-offences rows only, otherwise every offence group gets counted twice
crown_df = crown_df[crown_df["offence_group"] == "00: All offences"]
crown_df = crown_df.rename(columns={"crown_court_and_magistrates_lja": "court"})
crown_df["court"] = crown_df["court"].str.strip()
crown_df = crown_df[~crown_df["court"].isin(CLOSED)]
print("Crown rows:", len(crown_df))

# --- Step 3: trial counts by outcome per court-quarter ---
keys = ["court", "year", "quarter"]
outcome = crown_df["trial_effectiveness"].str.split(": ").str[1].str.split(" ").str[0].str.lower()
crown_df["outcome"] = outcome  # effective / cracked / ineffective / vacated
counts = crown_df.pivot_table(index=keys, columns="outcome", values="value",
                              aggfunc="sum", fill_value=0).reset_index()
counts.columns.name = None
counts["listed"] = counts[["effective", "cracked", "ineffective"]].sum(axis=1)
counts["ineffective_rate"] = counts["ineffective"] / counts["listed"]
counts["cracked_rate"] = counts["cracked"] / counts["listed"]

# --- Step 4: lever shares from ineffective reason codes ---
ineff = crown_df[crown_df["outcome"] == "ineffective"].copy()
ineff["code"] = ineff["reason"].str[:2].astype(int)
for lever, codes in LEVERS.items():
    part = ineff[ineff["code"].isin(codes)].groupby(keys)["value"].sum().rename(lever + "_n")
    counts = counts.merge(part, on=keys, how="left")
    counts[lever + "_n"] = counts[lever + "_n"].fillna(0)
    counts[lever + "_share"] = counts[lever + "_n"] / counts["ineffective"].where(counts["ineffective"] > 0)

# --- Step 5: receipts / disposals / open cases per court-quarter ---
r = pd.read_csv(RAW + "cc_rdos_2026Q2.csv")
r = r[r["offence_group"] == "00: All offences"].copy()
r = r.rename(columns={"crown_court": "court"})
r["court"] = r["court"].str.strip()
r["rdos"] = r["rdos"].str.split(". ").str[1].str.lower()  # receipts / disposals / open
rdos = r.pivot_table(index=keys, columns="rdos", values="value",
                     aggfunc="sum", fill_value=0).reset_index()
rdos.columns.name = None

# --- Step 6: join + map coordinates ---
panel = counts.merge(rdos, on=keys, how="left")
loc = pd.read_csv(CLEAN + "court_locations.csv")[["court", "lat", "lon"]]
panel = panel.merge(loc, on="court", how="left")
panel["period"] = pd.PeriodIndex(panel["year"].astype(str) + panel["quarter"], freq="Q")
panel = panel.sort_values(["court", "period"]).reset_index(drop=True)

# --- Step 7: checks ---
print("Courts:", panel["court"].nunique(), "| rows:", len(panel))
missing_loc = panel.loc[panel["lat"].isna(), "court"].unique()
print("Courts missing coordinates:", list(missing_loc))
latest = panel["period"].max()
print("Latest quarter:", latest, "| national open cases:", int(panel.loc[panel["period"] == latest, "open"].sum()))
nat = panel.groupby("year")[["ineffective", "listed"]].sum()
print("National ineffective rate by year:\n", (nat["ineffective"] / nat["listed"]).round(3))

panel["period"] = panel["period"].astype(str)
panel.to_parquet(CLEAN + "court_quarter.parquet", index=False)
print("Saved", CLEAN + "court_quarter.parquet")
