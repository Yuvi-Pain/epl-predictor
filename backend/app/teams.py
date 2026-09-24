"""Seed data for the teams and team_aliases tables.

Canonical name -> other spellings seen in data sources: football-data.co.uk's
short names ("Man United") and football-data.org's full names ("Manchester
United FC"). The canonical name is added as an alias of itself automatically.
When a loader or the fixture refresh reports an unknown team name, add it here
and rerun it.
"""

KNOWN_TEAMS: dict[str, list[str]] = {
    "Arsenal": ["Arsenal FC"],
    "Aston Villa": ["Aston Villa FC"],
    "Bournemouth": ["AFC Bournemouth"],
    "Brentford": ["Brentford FC"],
    "Brighton & Hove Albion": ["Brighton", "Brighton and Hove Albion", "Brighton & Hove Albion FC"],
    "Burnley": ["Burnley FC"],
    "Cardiff City": ["Cardiff", "Cardiff City FC"],
    "Chelsea": ["Chelsea FC"],
    "Coventry City": ["Coventry", "Coventry City FC"],
    "Crystal Palace": ["Crystal Palace FC"],
    "Everton": ["Everton FC"],
    "Fulham": ["Fulham FC"],
    "Huddersfield Town": ["Huddersfield", "Huddersfield Town AFC"],
    "Hull City": ["Hull", "Hull City AFC"],
    "Ipswich Town": ["Ipswich", "Ipswich Town FC"],
    "Leeds United": ["Leeds", "Leeds United FC"],
    "Leicester City": ["Leicester", "Leicester City FC"],
    "Liverpool": ["Liverpool FC"],
    "Luton Town": ["Luton", "Luton Town FC"],
    "Manchester City": ["Man City", "Manchester City FC"],
    "Manchester United": ["Man United", "Man Utd", "Manchester United FC"],
    "Middlesbrough": ["Middlesbrough FC"],
    "Newcastle United": ["Newcastle", "Newcastle United FC"],
    "Norwich City": ["Norwich", "Norwich City FC"],
    "Nottingham Forest": ["Nott'm Forest", "Nottm Forest", "Nottingham Forest FC"],
    "Sheffield United": ["Sheffield Utd", "Sheff Utd", "Sheffield United FC"],
    "Southampton": ["Southampton FC"],
    "Stoke City": ["Stoke", "Stoke City FC"],
    "Sunderland": ["Sunderland AFC"],
    "Swansea City": ["Swansea", "Swansea City AFC"],
    "Tottenham Hotspur": ["Tottenham", "Spurs", "Tottenham Hotspur FC"],
    "Watford": ["Watford FC"],
    "West Bromwich Albion": ["West Brom", "West Bromwich Albion FC"],
    "West Ham United": ["West Ham", "West Ham United FC"],
    "Wolverhampton Wanderers": ["Wolves", "Wolverhampton", "Wolverhampton Wanderers FC"],
}
