from flask import Flask, request, jsonify, send_from_directory
from nba_api.stats.endpoints import (
    playergamelog, scoreboardv3, commonteamroster, teamgamelog
)
from nba_api.stats.static import players, teams
import anthropic
import os
import time
import pandas as pd
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from nba_api.stats.endpoints import scoreboardv3
import nba_api.library.http as nba_http

nba_http.HEADERS = {
    'Host': 'stats.nba.com',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Referer': 'https://www.nba.com/',
    'Origin': 'https://www.nba.com',
}

app = Flask(__name__, static_folder='public')
client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

def get_today_games():
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        scoreboard = scoreboardv3.ScoreboardV3(game_date=today)
        all_frames = scoreboard.get_data_frames()
        game_frame = all_frames[1]
        team_frame = all_frames[2]
        games = []
        for _, game in game_frame.iterrows():
            game_id = game['gameId']
            status = game['gameStatusText']
            teams_in_game = team_frame[team_frame['gameId'] == game_id]
            if len(teams_in_game) < 2:
                continue
            away = teams_in_game.iloc[0]
            home = teams_in_game.iloc[1]
            games.append({
                'gameId': game_id,
                'status': status,
                'homeTeam': f"{home['teamCity']} {home['teamName']}",
                'awayTeam': f"{away['teamCity']} {away['teamName']}",
                'homeTricode': home['teamTricode'],
                'awayTricode': away['teamTricode'],
                'matchup': f"{away['teamCity']} {away['teamName']} vs {home['teamCity']} {home['teamName']}"
            })
        return games
    except Exception as e:
        return []

def get_team_roster(team_name):
    try:
        all_teams = teams.get_teams()
        team = next((t for t in all_teams if
            team_name.lower() in t['full_name'].lower() or
            team_name.lower() in t['nickname'].lower() or
            team_name.lower() == t['abbreviation'].lower()), None)
        if not team:
            return []
        time.sleep(0.6)
        roster = commonteamroster.CommonTeamRoster(team_id=team['id'], season='2025-26')
        roster_df = roster.get_data_frames()[0]
        player_list = []
        for _, p in roster_df.iterrows():
            player_list.append({
                'name': p['PLAYER'],
                'number': p['NUM'],
                'position': p['POSITION'],
                'status': 'active'
            })
        return player_list
    except Exception as e:
        return []

def get_injury_report():
    try:
        from nba_api.stats.endpoints import leagueinjuryroster
        injuries = leagueinjuryroster.LeagueInjuryRoster()
        df = injuries.get_data_frames()[0]
        injury_map = {}
        for _, row in df.iterrows():
            injury_map[row['PLAYER_NAME']] = {
                'status': row['INJURY_STATUS'],
                'description': row['INJURY_DESCRIPTION']
            }
        return injury_map
    except:
        return {}

def get_odds(home_team, away_team):
    try:
        api_key = os.getenv('ODDS_API_KEY')
        url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/odds/?apiKey={api_key}&regions=us&markets=h2h,spreads,totals&oddsFormat=american"
        res = requests.get(url)
        data = res.json()
        for game in data:
            home = game.get('home_team', '')
            away = game.get('away_team', '')
            home_match = (home_team.lower() in home.lower() or home.lower() in home_team.lower() or
                          home_team.lower() in away.lower() or away.lower() in home_team.lower())
            away_match = (away_team.lower() in away.lower() or away.lower() in away_team.lower() or
                          away_team.lower() in home.lower() or home.lower() in away_team.lower())
            if home_match and away_match:
                odds_text = f"Betting lines for {away} vs {home}:\n"
                for bookmaker in game.get('bookmakers', [])[:2]:
                    odds_text += f"\n{bookmaker['title']}:\n"
                    for market in bookmaker.get('markets', []):
                        if market['key'] == 'h2h':
                            for outcome in market['outcomes']:
                                odds_text += f"  Moneyline {outcome['name']}: {outcome['price']}\n"
                        elif market['key'] == 'spreads':
                            for outcome in market['outcomes']:
                                odds_text += f"  Spread {outcome['name']}: {outcome['point']} ({outcome['price']})\n"
                        elif market['key'] == 'totals':
                            for outcome in market['outcomes']:
                                odds_text += f"  Total {outcome['name']}: {outcome['point']} ({outcome['price']})\n"
                return odds_text
        return "No odds found for this game."
    except Exception as e:
        return f"Could not fetch odds: {str(e)}"

def get_player_stats(player_name, opponent_tricode):
    try:
        player_list = players.find_players_by_full_name(player_name)
        if not player_list:
            return None
        player = player_list[0]
        player_id = player['id']
        time.sleep(0.6)
        try:
            playoff_log = playergamelog.PlayerGameLog(
                player_id=player_id,
                season='2025-26',
                season_type_all_star='Playoffs'
            )
            playoff_df = playoff_log.get_data_frames()[0]
            if playoff_df.empty:
                raise Exception("empty")
        except:
            try:
                playoff_log = playergamelog.PlayerGameLog(
                    player_id=player_id,
                    season='2025-26',
                    season_type_all_star='Playoff'
                )
                playoff_df = playoff_log.get_data_frames()[0]
            except:
                playoff_df = None
        time.sleep(0.6)
        reg_log = playergamelog.PlayerGameLog(
            player_id=player_id,
            season='2025-26',
            season_type_all_star='Regular Season'
        )
        reg_df = reg_log.get_data_frames()[0]
        if playoff_df is not None and not playoff_df.empty:
            combined = pd.concat([playoff_df, reg_df]).head(5)
            season_label = "Most Recent"
        else:
            combined = reg_df.head(5)
            season_label = "Regular Season"
        stats_text = f"Player: {player['full_name']}\n\nLast 5 games ({season_label}):\n"
        for _, game in combined.iterrows():
            stats_text += f"  {game['GAME_DATE']} vs {game['MATCHUP'].split()[-1]}: {game['PTS']}pts {game['REB']}reb {game['AST']}ast in {game['MIN']}min | {game['WL']}\n"
        if opponent_tricode:
            vs_games = reg_df[reg_df['MATCHUP'].str.contains(opponent_tricode, na=False)]
            if playoff_df is not None and not playoff_df.empty:
                vs_playoff = playoff_df[playoff_df['MATCHUP'].str.contains(opponent_tricode, na=False)]
                vs_games = pd.concat([vs_playoff, vs_games])
            if not vs_games.empty:
                stats_text += f"\nLast 3 matchups vs {opponent_tricode}:\n"
                for _, game in vs_games.head(3).iterrows():
                    stats_text += f"  {game['GAME_DATE']}: {game['PTS']}pts {game['REB']}reb {game['AST']}ast in {game['MIN']}min | {game['WL']}\n"
            else:
                stats_text += f"\nNo recent matchups found vs {opponent_tricode}\n"
        if not reg_df.empty:
            stats_text += f"\nSeason averages: {round(reg_df['PTS'].mean(),1)}pts {round(reg_df['REB'].mean(),1)}reb {round(reg_df['AST'].mean(),1)}ast over {len(reg_df)} games\n"
        return stats_text
    except Exception as e:
        return f"Error fetching stats: {str(e)}"

def get_team_recent(tricode):
    try:
        all_teams = teams.get_teams()
        team = next((t for t in all_teams if t['abbreviation'] == tricode), None)
        if not team:
            return f"Could not find team {tricode}"
        time.sleep(0.6)
        
        try:
            playoff_log = teamgamelog.TeamGameLog(team_id=team['id'], season='2025-26', season_type_all_star='Playoffs')
            playoff_df = playoff_log.get_data_frames()[0]
        except:
            playoff_df = None

        time.sleep(0.6)
        reg_log = teamgamelog.TeamGameLog(team_id=team['id'], season='2025-26')
        reg_df = reg_log.get_data_frames()[0]

        if playoff_df is not None and not playoff_df.empty:
            combined = pd.concat([playoff_df, reg_df]).head(5)
        else:
            combined = reg_df.head(5)

        if combined.empty:
            return f"No recent games found for {tricode}"

        text = f"{team['full_name']} last 5 games:\n"
        for _, game in combined.iterrows():
            text += f"  {game['GAME_DATE']} vs {game['MATCHUP'].split()[-1]}: {game['PTS']}pts | {game['WL']}\n"
        text += f"Record last 5: {combined['WL'].value_counts().get('W', 0)}W {combined['WL'].value_counts().get('L', 0)}L\n"
        return text
    except Exception as e:
        return f"Error fetching team stats: {str(e)}"

@app.route('/')
def index():
    return send_from_directory('public', 'index.html')

@app.route('/games', methods=['GET'])
def games():
    today_games = get_today_games()
    return jsonify({'games': today_games})

@app.route('/roster', methods=['GET'])
def roster():
    team_name = request.args.get('team', '')
    injury_map = get_injury_report()
    players_list = get_team_roster(team_name)
    for p in players_list:
        if p['name'] in injury_map:
            p['status'] = injury_map[p['name']]['status']
            p['injury'] = injury_map[p['name']]['description']
    return jsonify({'players': players_list})

@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.json
    player_name = data.get('player')
    opponent = data.get('opponent')
    opponent_tricode = data.get('opponentTricode', '')
    home_team = data.get('homeTeam', '')
    away_team = data.get('awayTeam', '')
    try:
        today = datetime.now().strftime('%A, %B %d, %Y')
        odds_text = get_odds(home_team, away_team)
        stats_text = get_player_stats(player_name, opponent_tricode)
        if not stats_text:
            return jsonify({'error': f'Player "{player_name}" not found'})
        opponent_roster = get_team_roster(opponent)
        roster_names = [p['name'] for p in opponent_roster]
        roster_text = f"Current {opponent} roster: {', '.join(roster_names)}"
        prompt = f"""You are a sharp NBA prop betting analyst. Today is {today}.

Player: {player_name}
Opponent: {opponent}

{roster_text}

{stats_text}

{odds_text}

Based on the current roster, stats, and betting lines provided:
1. Top 2-3 player prop bets with reasoning
2. Any props to avoid
3. Confidence level (low/medium/high) with one line summary

Be direct. Only reference players shown in the roster above."""
        message = client.messages.create(
            model='claude-sonnet-4-5',
            max_tokens=1000,
            messages=[{'role': 'user', 'content': prompt}]
        )
        return jsonify({
            'stats': stats_text,
            'analysis': message.content[0].text
        })
    except Exception as e:
        return jsonify({'error': f'Something went wrong: {str(e)}'})

@app.route('/analyze-team', methods=['POST'])
def analyze_team():
    data = request.json
    home_team = data.get('homeTeam')
    away_team = data.get('awayTeam')
    home_tricode = data.get('homeTricode')
    away_tricode = data.get('awayTricode')
    try:
        today = datetime.now().strftime('%A, %B %d, %Y')
        odds_text = get_odds(home_team, away_team)
        home_stats = get_team_recent(home_tricode)
        away_stats = get_team_recent(away_tricode)
        stats_text = f"{away_stats}\n{home_stats}"
        prompt = f"""You are a sharp NBA betting analyst. Today is {today}.

Matchup: {away_team} vs {home_team}

{odds_text}

{stats_text}

Give a team betting breakdown:
1. Moneyline value — which team has value and why
2. Spread analysis — is the line fair based on recent form
3. Total (over/under) — lean over or under based on both teams recent pace and scoring
4. Best bet of the three with confidence level (low/medium/high)

Be direct and specific. Base reasoning on the stats and odds provided."""
        message = client.messages.create(
            model='claude-sonnet-4-5',
            max_tokens=1000,
            messages=[{'role': 'user', 'content': prompt}]
        )
        return jsonify({
            'stats': stats_text,
            'analysis': message.content[0].text
        })
    except Exception as e:
        return jsonify({'error': f'Something went wrong: {str(e)}'})

@app.route('/debug-odds', methods=['GET'])
def debug_odds():
    try:
        api_key = os.getenv('ODDS_API_KEY')
        url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/odds/?apiKey={api_key}&regions=us&markets=h2h&oddsFormat=american"
        res = requests.get(url)
        data = res.json()
        games = [{'home': g.get('home_team'), 'away': g.get('away_team')} for g in data]
        return jsonify({'games': games})
    except Exception as e:
        return jsonify({'error': str(e)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    app.run(debug=False, host='0.0.0.0', port=port)