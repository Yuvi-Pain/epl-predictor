"""Seed data for the teams and team_aliases tables.

Canonical name -> other spellings seen in data sources. The canonical name is
added as an alias of itself automatically. When a loader reports an unknown
team name, add it here and rerun the loader.
"""

KNOWN_TEAMS: dict[str, list[str]] = {
    "Arsenal": [],
    "Aston Villa": [],
    "Bournemouth": ["AFC Bournemouth"],
    "Brentford": [],
    "Brighton & Hove Albion": ["Brighton", "Brighton and Hove Albion"],
    "Burnley": [],
    "Cardiff City": ["Cardiff"],
    "Chelsea": [],
    "Crystal Palace": [],
    "Everton": [],
    "Fulham": [],
    "Huddersfield Town": ["Huddersfield"],
    "Hull City": ["Hull"],
    "Ipswich Town": ["Ipswich"],
    "Leeds United": ["Leeds"],
    "Leicester City": ["Leicester"],
    "Liverpool": [],
    "Luton Town": ["Luton"],
    "Manchester City": ["Man City"],
    "Manchester United": ["Man United", "Man Utd"],
    "Middlesbrough": [],
    "Newcastle United": ["Newcastle"],
    "Norwich City": ["Norwich"],
    "Nottingham Forest": ["Nott'm Forest", "Nottm Forest"],
    "Sheffield United": ["Sheffield Utd", "Sheff Utd"],
    "Southampton": [],
    "Stoke City": ["Stoke"],
    "Sunderland": [],
    "Swansea City": ["Swansea"],
    "Tottenham Hotspur": ["Tottenham", "Spurs"],
    "Watford": [],
    "West Bromwich Albion": ["West Brom"],
    "West Ham United": ["West Ham"],
    "Wolverhampton Wanderers": ["Wolves", "Wolverhampton"],
}
