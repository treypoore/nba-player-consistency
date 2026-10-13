# =====================================================
# EXAMPLE CONFIG — PLACEHOLDER VALUES
# =====================================================
# These are NOT the values used to produce the published results.
# To run with your own settings, copy this file to config_private.py
# (which is git-ignored) and edit the numbers there.

# Eligibility thresholds
MIN_GAMES = 10
MIN_AVG_REB = 5.0
MIN_AVG_AST = 2.0
MIN_AVG_PTS = 8.0
MIN_AVG_FG3M = 1.0

# Scoring weights (should sum to 1.0)
SEASON_WEIGHT = 0.5
RECENT_WEIGHT = 0.5

# Number of most recent games used for the rolling CV
ROLLING_WINDOW = 10
