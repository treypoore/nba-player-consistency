import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine

# =====================================================
# PATHS & GLOBAL SETTINGS
# =====================================================

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "Outputs"
PLOT_DIR = OUTPUT_DIR / "Plots"

# Load Database Password from .env
load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"]

# Algorithm Weights & Minimums
# The real values live in config_private.py (git-ignored). If it isn't
# present, the placeholder values in config_example.py are used instead.
try:
    import config_private as config
except ImportError:
    import config_example as config

MIN_GAMES = config.MIN_GAMES
MIN_AVG_REB = config.MIN_AVG_REB
MIN_AVG_AST = config.MIN_AVG_AST
MIN_AVG_PTS = config.MIN_AVG_PTS
MIN_AVG_FG3M = config.MIN_AVG_FG3M

SEASON_WEIGHT = config.SEASON_WEIGHT
RECENT_WEIGHT = config.RECENT_WEIGHT
ROLLING_WINDOW = config.ROLLING_WINDOW

# =====================================================
# STEP 1: PULL & CLEAN CLOUD DATA
# =====================================================

def pull_and_clean_data():
    print("1. Connecting to the Supabase cloud...")
    engine = create_engine(DATABASE_URL)
    
    print("2. Downloading live player data...")
    # Pull directly from the new cloud table
    query = "SELECT * FROM raw_player_box_scores"
    df = pd.read_sql(query, engine)

    # Standardize dates and numeric columns to NBA API specs
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"], errors="coerce", utc=True)
    df = df.dropna(subset=["GAME_DATE"])

    # Added PTS and FG3M to the mandatory numeric cleaning list
    numeric_cols = ["MIN", "REB", "AST", "PTS", "FG3M"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=numeric_cols)
    
    print(f"   Success! Cleaned {len(df)} rows for analysis.")
    return df

# =====================================================
# STEP 2: ROLLING CV (HOT / COLD STREAKS)
# =====================================================

def compute_recent_cv(df, stat_col):
    df_sorted = df.sort_values(["PLAYER_ID", "GAME_DATE"])

    rolling = (
        df_sorted
        .groupby("PLAYER_ID")[stat_col]
        .rolling(ROLLING_WINDOW, min_periods=ROLLING_WINDOW)
        .agg(["mean", "std"])
        .reset_index()
    )

    rolling["cv_recent"] = rolling["std"] / rolling["mean"]
    rolling.replace([np.inf, -np.inf], np.nan, inplace=True)

    return (
        rolling
        .dropna(subset=["cv_recent"])
        .groupby("PLAYER_ID")
        .tail(1)[["PLAYER_ID", "cv_recent"]]
    )

# =====================================================
# STEP 3: CONSISTENCY CALCULATOR (FULL MODEL)
# =====================================================

def calculate_consistency(df, stat_col, min_avg_required, label):
    # Filter out games where they didn't log minutes
    df = df[df["MIN"] > 0].copy()

    group_cols = ["PLAYER_ID", "PLAYER_NAME"]

    agg_df = (
        df
        .groupby(group_cols)
        .agg(
            games_used=("GAME_ID", "nunique"),
            avg_stat=(stat_col, "mean"),
            std_stat=(stat_col, lambda x: x.std(ddof=1))
        )
        .reset_index()
    )

    agg_df["cv_season"] = agg_df["std_stat"] / agg_df["avg_stat"]
    agg_df.replace([np.inf, -np.inf], np.nan, inplace=True)

    # Calculate and merge Rolling CV
    recent_cv = compute_recent_cv(df, stat_col)
    agg_df = agg_df.merge(recent_cv, on="PLAYER_ID", how="left")

    # Weighted Consistency Score (weights come from config)
    agg_df["weighted_cv"] = (
        SEASON_WEIGHT * agg_df["cv_season"] +
        RECENT_WEIGHT * agg_df["cv_recent"]
    )

    # Apply Guardrails
    eligible = agg_df[
        (agg_df["games_used"] >= MIN_GAMES) &
        (agg_df["avg_stat"] >= min_avg_required) &
        (agg_df["weighted_cv"].notna())
    ].copy()

    eligible = eligible.sort_values(
        by=["weighted_cv", "avg_stat"],
        ascending=[True, False]
    ).reset_index(drop=True)

    eligible["consistency_rank"] = (
        eligible["weighted_cv"]
        .rank(method="dense", ascending=True)
        .astype(int)
    )

    eligible = eligible.rename(columns={
        "avg_stat": f"avg_{label}",
        "std_stat": f"std_{label}",
        "cv_season": f"cv_season_{label}",
        "cv_recent": f"cv_recent_{label}",
        "weighted_cv": f"weighted_cv_{label}",
    })

    return eligible

# =====================================================
# STEP 4: VISUALIZATION — ARCHETYPE SCATTER
# =====================================================

def plot_archetypes_refined(df, label):
    PLOT_DIR.mkdir(parents=True, exist_ok=True)

    df_plot = (
        df.sort_values(by=f"weighted_cv_{label}", ascending=True)
          .head(50)
          .copy()
    )

    x = df_plot[f"cv_season_{label}"]
    y = df_plot[f"cv_recent_{label}"]

    plt.figure(figsize=(9, 7))
    plt.scatter(x, y, alpha=0.7)

    x_median = x.median()
    y_median = y.median()

    plt.axvline(x_median, linestyle="--", alpha=0.4)
    plt.axhline(y_median, linestyle="--", alpha=0.4)

    for _, row in df_plot.iterrows():
        player_name = row["PLAYER_NAME"]  
        plt.text(
            row[f"cv_season_{label}"] + 0.002,
            row[f"cv_recent_{label}"] + 0.002,
            player_name,
            fontsize=7,
            alpha=0.75
        )

    plt.xlabel("Season CV (Lower = More Consistent)")
    plt.ylabel(f"Last-{ROLLING_WINDOW} Games CV (Hot / Cold)")
    plt.title(f"{label.upper()} Consistency Archetypes — Top 50 Players")

    plt.text(0.01, 0.92, "Hot but Unstable", transform=plt.gca().transAxes, fontsize=9)
    plt.text(0.65, 0.02, "Consistent but Cold", transform=plt.gca().transAxes, fontsize=9)
    plt.text(0.01, 0.02, "Consistent + Hot", transform=plt.gca().transAxes, fontsize=9)

    plt.grid(alpha=0.2)

    plot_path = PLOT_DIR / f"{label}_consistency_archetypes_top50_cloud.png"
    plt.savefig(plot_path, bbox_inches="tight", dpi=200)
    plt.close()

    print(f"   Saved refined archetype plot to: {plot_path}")

# =====================================================
# STEP 5: MAIN PIPELINE
# =====================================================

def main():
    print("\n--- STARTING CLOUD CONSISTENCY MODEL ---")
    df = pull_and_clean_data()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("\n3. Calculating Rebounds Consistency...")
    reb_df = calculate_consistency(df, "REB", MIN_AVG_REB, "reb")
    reb_df.to_csv(OUTPUT_DIR / "rebounds_consistency_cloud.csv", index=False)
    plot_archetypes_refined(reb_df, "reb")

    print("\n4. Calculating Assists Consistency...")
    ast_df = calculate_consistency(df, "AST", MIN_AVG_AST, "ast")
    ast_df.to_csv(OUTPUT_DIR / "assists_consistency_cloud.csv", index=False)
    plot_archetypes_refined(ast_df, "ast")

    print("\n5. Calculating Points Consistency...")
    pts_df = calculate_consistency(df, "PTS", MIN_AVG_PTS, "pts")
    pts_df.to_csv(OUTPUT_DIR / "points_consistency_cloud.csv", index=False)
    plot_archetypes_refined(pts_df, "pts")

    print("\n6. Calculating 3-Pointers Consistency...")
    fg3m_df = calculate_consistency(df, "FG3M", MIN_AVG_FG3M, "fg3m")
    fg3m_df.to_csv(OUTPUT_DIR / "fg3m_consistency_cloud.csv", index=False)
    plot_archetypes_refined(fg3m_df, "fg3m")

    print("\n*** MODEL COMPLETE. OUTPUTS AND PLOTS SAVED. ***\n")

if __name__ == "__main__":
    main()