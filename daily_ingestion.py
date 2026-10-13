import os
import sys
import time
import pandas as pd
from sqlalchemy import text
from dotenv import load_dotenv
from sqlalchemy import create_engine
from nba_api.stats.endpoints import leaguegamelog

# 1. Load the secret password
load_dotenv()
database_url = os.environ["DATABASE_URL"]

# =====================================================
# THE CONSULTANT'S UPGRADE: RETRY LOGIC & THE MASK
# =====================================================
def fetch_nba_data_with_retry(player_or_team_abbrev, max_retries=3):
    """
    Attempts to fetch data from the NBA API. Uses custom headers to bypass 
    firewall bot-detection, and implements exponential backoff on timeouts.
    """
    # The Mask: Disguise the Python script as a real web browser
    custom_headers = {
        "Host": "stats.nba.com",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://stats.nba.com/",
        "Origin": "https://stats.nba.com",
        "Connection": "keep-alive",
    }

    for attempt in range(1, max_retries + 1):
        try:
            print(f"      [Attempt {attempt}/{max_retries}] Pinging the NBA servers...")
            # We explicitly increase the timeout to 60 seconds and inject custom headers
            log = leaguegamelog.LeagueGameLog(
                season="2025-26", 
                player_or_team_abbreviation=player_or_team_abbrev,
                timeout=60,
                headers=custom_headers
            )
            return log.get_data_frames()[0]
        except Exception as e:
            print(f"      [!] Attempt {attempt} failed: {e}")
            if attempt < max_retries:
                sleep_time = 10 * attempt  # Waits 10s, then 20s...
                print(f"      Sleeping for {sleep_time} seconds before retrying...")
                time.sleep(sleep_time)
            else:
                print("      [!] CRITICAL: All API attempts failed. The NBA servers are blocking us or down.")
                raise e  # Pass the error up to trigger the hard exit

# =====================================================
# MAIN INGESTION PIPELINE
# =====================================================
def test_connection_and_upload():
    try:
        # Connect to Supabase
        print("1. Unlocking the Supabase database...")
        engine = create_engine(database_url)

        with engine.connect() as connection:
            # --- PART 1: TEAM DATA ---
            print("\n2. Waking up the NBA API for TEAM stats...")
            df_teams = fetch_nba_data_with_retry('T')
            
            # Format the dates so the computer can do math on them
            df_teams['GAME_DATE'] = pd.to_datetime(df_teams['GAME_DATE'])
            
            print("   Checking the drawer for the most recent Team game...")
            try:
                # Ask the database for the newest date it has saved
                result = connection.execute(text('SELECT MAX("GAME_DATE") FROM raw_team_box_scores'))
                max_team_date = result.scalar()
            except Exception:
                # If the drawer is completely empty, start from scratch
                max_team_date = None

            # The Filter: Cut out the old games
            if max_team_date:
                max_team_date = pd.to_datetime(max_team_date)
                new_teams_df = df_teams[df_teams['GAME_DATE'] > max_team_date]
            else:
                new_teams_df = df_teams
                
            # The Append: Save only the new games
            if not new_teams_df.empty:
                print(f"   Success! Found {len(new_teams_df)} NEW rows of Team data.")
                new_teams_df.to_sql('raw_team_box_scores', engine, if_exists='append', index=False)
                print("   New Team data neatly appended!")
            else:
                print("   Team drawer is already up to date! No new games to add.")


            # --- PART 2: PLAYER DATA ---
            print("\n3. Waking up the NBA API for PLAYER stats...")
            df_players = fetch_nba_data_with_retry('P')
            
            df_players['GAME_DATE'] = pd.to_datetime(df_players['GAME_DATE'])
            
            print("   Checking the drawer for the most recent Player game...")
            try:
                result = connection.execute(text('SELECT MAX("GAME_DATE") FROM raw_player_box_scores'))
                max_player_date = result.scalar()
            except Exception:
                max_player_date = None

            # The Filter: Cut out the old games
            if max_player_date:
                max_player_date = pd.to_datetime(max_player_date)
                new_players_df = df_players[df_players['GAME_DATE'] > max_player_date]
            else:
                new_players_df = df_players
                
            # The Append: Save only the new games
            if not new_players_df.empty:
                print(f"   Success! Found {len(new_players_df)} NEW rows of Player data.")
                new_players_df.to_sql('raw_player_box_scores', engine, if_exists='append', index=False)
                print("   New Player data neatly appended!")
            else:
                print("   Player drawer is already up to date! No new games to add.")

        print("\n*** ALL DATA SUCCESSFULLY UPLOADED TO THE CLOUD! ***")
        
    except Exception as e:
        print(f"\nOops, a fatal error occurred: {e}")
        print("Triggering a hard exit so GitHub Actions registers the failure!")
        sys.exit(1)  # THIS IS THE ALARM BELL

# The Trigger
if __name__ == "__main__":
    test_connection_and_upload()
