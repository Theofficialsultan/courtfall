import pandas as pd

df = pd.read_csv("data/raw/trials_2026Q2.csv")

print(df.head())

print(df.columns.tolist())

print(df["court_type"].unique())

print(df["year"].min())
print(df["year"].max())

crown_df = df[
    (df["court_type"] == "Crown") &
    (df["year"] >= 2016)
]

print(crown_df.head())
print("Filtered rows:", len(crown_df))