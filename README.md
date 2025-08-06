
# Fatal Fury ELO Bot

## Overview
This is a private Discord bot developed for internal company use. It implements a complete ELO rating and matchmaking system for "Fatal Fury" games within our Discord server. The bot handles challenges, match reporting, ELO calculations, and leaderboard management using slash commands.

## Features
- **Challenge System**: Players can challenge each other to a ranked match using the `/challenge` command.
- **Interactive Match Reporting**: A robust, button-based reporting system allows players to confirm match outcomes ("I Won" / "I Lost").
- **ELO Rating Calculation**: Automatically adjusts player ELO ratings based on match results using a standard K-factor.
- **Player Statistics**: View detailed player stats, including ELO, wins, losses, and win rate with `/stats`.
- **Dynamic Leaderboard**: Display the top-ranked players on the server with `/leaderboard`.
- **Match Management**: Players can view a list of their pending matches with `/my_matches`.
- **Automated Match Resolution**: Intelligently handles match timeouts and resolves matches where only one player reports a result.
- **Admin Tools**: Users with the "Administrador ELO" role can manually resolve disputed or problematic matches using the `/admin_resolve_match` command.

### Configure Environment Variables:
This project uses environment variables for sensitive data. Create a `.env` file or use your hosting platform's environment variable system to set the following:

- `BOT_TOKEN`: Your Discord bot's unique token.
- `GUILD_ID`: The ID of the Discord server (guild) where the bot will operate.

The bot will automatically initialize the `elo_bot.db` SQLite database file on its first run.

## Usage
Once the bot is running and has been invited to the Discord server, users can interact with it using the following slash commands:

- `/challenge @opponent`: Issue a match challenge to another user.
- `/stats [player]`: View your own stats or the stats of an optional specified player.
- `/leaderboard`: See the server's top players.
- `/my_matches`: View your active matches that are awaiting a result report.

## Database Schema
The bot uses a local SQLite database (`elo_bot.db`) for data persistence. The schema consists of two main tables:

- **players**: Stores user information, including `user_id`, `user_name`, `elo_rating`, `wins`, `losses`, and `games_played`.
- **matches**: Tracks active and completed matches, including the participants, status (`pending`, `confirmed`, `disputed`, `timed_out`), and reported results.

## Configuration
Key gameplay and behavior parameters can be adjusted directly in the global variables section of the Python script:

```python
INITIAL_ELO = 1000
K_FACTOR = 30
REPORT_TIMEOUT_HOURS = 1
CHALLENGE_TIMEOUT_SECONDS = 240
ADMIN_ROLE_NAME = "Administrador ELO"
```

## Deployment
This bot can be deployed on any Python-compatible hosting platform:

1. Clone this repository to your hosting platform
2. Configure the environment variables (`BOT_TOKEN` and `GUILD_ID`)
3. Install dependencies: `pip install -r requirements.txt`
4. Run the bot: `python main.py`
5. For production deployment, ensure your hosting platform supports 24/7 uptime

## Contact
For questions, issues, or suggestions regarding this bot, please contact: gerald@papercrowns.com
