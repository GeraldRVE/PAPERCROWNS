# ==============================================================================
#           FATAL FURY ELO BOT - 
# ===============================================================================================================================================


import discord
from discord import app_commands, ui
from discord.ext import tasks
import sqlite3
import os
import uuid
import time
import math
from typing import Optional, Any

# --- INITIAL CONFIGURATION AND GLOBAL VARIABLES ---

BOT_TOKEN = os.getenv('BOT_TOKEN')
GUILD_ID_STR = os.getenv('GUILD_ID')
GUILD_ID = int(GUILD_ID_STR) if GUILD_ID_STR and GUILD_ID_STR.isdigit() else 0
CHANNEL_ID_STR = os.getenv('CHANNEL_ID')
CHANNEL_ID = int(CHANNEL_ID_STR) if CHANNEL_ID_STR and CHANNEL_ID_STR.isdigit() else 0

INITIAL_ELO = 1000
K_FACTOR = 30
REPORT_TIMEOUT_HOURS = 1
# New constant for the challenge acceptance phase
CHALLENGE_TIMEOUT_SECONDS = 240 # 4 minutes

ADMIN_ROLE_NAME = "Administrador ELO"
DATABASE_FILE = 'elo_bot.db'

# --- DATABASE MANAGEMENT MODULE ---
# All functions now accept a `db_conn` object to reuse the single connection.

def init_db(db_conn: sqlite3.Connection):
    """Initializes the database and creates tables if they don't exist."""
    print("Initializing database...")
    c = db_conn.cursor()
    c.execute(f'''
        CREATE TABLE IF NOT EXISTS players (
            user_id TEXT PRIMARY KEY,
            user_name TEXT NOT NULL,
            elo_rating INTEGER DEFAULT {INITIAL_ELO},
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            games_played INTEGER DEFAULT 0
        )
    ''')
    # A new column `original_challenge_msg_id` has been added to handle
    # the new two-step challenge process.
    c.execute('''
        CREATE TABLE IF NOT EXISTS matches (
            match_id TEXT PRIMARY KEY,
            player1_id TEXT NOT NULL,
            player2_id TEXT NOT NULL,
            message_id TEXT,
            channel_id TEXT,
            timestamp INTEGER NOT NULL,
            player1_report INTEGER,
            player2_report INTEGER,
            status TEXT DEFAULT 'pending'
        )
    ''')
    db_conn.commit()
    print("Database initialized successfully.")

def get_player(db_conn: sqlite3.Connection, user_id: int) -> Optional[sqlite3.Row]:
    """Gets a player's data by their ID. Returns None if not found."""
    c = db_conn.cursor()
    c.execute("SELECT * FROM players WHERE user_id = ?", (str(user_id),))
    return c.fetchone()

def add_player_if_not_exists(db_conn: sqlite3.Connection, user_id: int, user_name: str):
    """Adds a player to the database if they do not exist using a single, efficient query."""
    c = db_conn.cursor()
    c.execute("INSERT OR IGNORE INTO players (user_id, user_name, elo_rating) VALUES (?, ?, ?)",
              (str(user_id), user_name, INITIAL_ELO))
    db_conn.commit()

def create_match_record(db_conn: sqlite3.Connection, match_id: str, p1_id: int, p2_id: int, msg_id: int, ch_id: int):
    """Creates a new match record in the database."""
    c = db_conn.cursor()
    c.execute("INSERT INTO matches (match_id, player1_id, player2_id, message_id, channel_id, timestamp, status) VALUES (?, ?, ?, ?, ?, ?, 'pending')",
              (match_id, str(p1_id), str(p2_id), str(msg_id), str(ch_id), int(time.time())))
    db_conn.commit()

def get_match(db_conn: sqlite3.Connection, match_id: str) -> Optional[sqlite3.Row]:
    """Gets match data by its ID."""
    c = db_conn.cursor()
    c.execute("SELECT * FROM matches WHERE match_id = ?", (match_id,))
    return c.fetchone()

def update_match_report(db_conn: sqlite3.Connection, match_id: str, player_id: int, report_value: int):
    """Updates a player's report for a specific match safely."""
    match_data = get_match(db_conn, match_id)
    if not match_data: return

    c = db_conn.cursor()
    # Use explicit queries to avoid any chance of SQL injection
    if str(player_id) == match_data['player1_id']:
        c.execute("UPDATE matches SET player1_report = ? WHERE match_id = ?", (report_value, match_id))
    elif str(player_id) == match_data['player2_id']:
        c.execute("UPDATE matches SET player2_report = ? WHERE match_id = ?", (report_value, match_id))
    db_conn.commit()

def update_match_status(db_conn: sqlite3.Connection, match_id: str, status: str):
    """Updates the status of a match."""
    c = db_conn.cursor()
    c.execute("UPDATE matches SET status = ? WHERE match_id = ?", (status, match_id))
    db_conn.commit()

def get_leaderboard(db_conn: sqlite3.Connection, limit: int = 10) -> list:
    """Gets the top players by ELO rating."""
    c = db_conn.cursor()
    c.execute("SELECT user_name, elo_rating, wins, losses FROM players ORDER BY elo_rating DESC LIMIT ?", (limit,))
    return c.fetchall()

def get_pending_matches_for_user(db_conn: sqlite3.Connection, user_id: int) -> list:
    """Gets all pending matches for a specific user."""
    c = db_conn.cursor()
    c.execute("SELECT * FROM matches WHERE (player1_id = ? OR player2_id = ?) AND status = 'pending' ORDER BY timestamp DESC", (str(user_id), str(user_id)))
    return c.fetchall()

def get_stale_matches(db_conn: sqlite3.Connection) -> list:
    """Gets matches that are pending and older than the timeout period."""
    timeout_seconds = REPORT_TIMEOUT_HOURS * 3600
    stale_time = int(time.time()) - timeout_seconds
    c = db_conn.cursor()
    c.execute("SELECT * FROM matches WHERE status = 'pending' AND timestamp < ?", (stale_time,))
    return c.fetchall()

# --- ELO CALCULATION MODULE ---

def calculate_expected_score(rating1: int, rating2: int) -> float:
    """Calculates the expected score for player 1 against player 2."""
    return 1.0 / (1.0 + math.pow(10, (rating2 - rating1) / 400.0))

def update_elo_and_stats(db_conn: sqlite3.Connection, winner_id: int, loser_id: int) -> tuple[Optional[int], Optional[int]]:
    """Updates ELO and stats for both players after a confirmed match."""
    winner_data = get_player(db_conn, winner_id)
    loser_data = get_player(db_conn, loser_id)
    if not winner_data or not loser_data:
        print(f"Error: Player data not found for {winner_id} or {loser_id}.")
        return None, None

    r_winner, r_loser = winner_data['elo_rating'], loser_data['elo_rating']
    e_winner = calculate_expected_score(r_winner, r_loser)

    new_r_winner = r_winner + K_FACTOR * (1.0 - e_winner)
    new_r_loser = r_loser + K_FACTOR * (0.0 - (1.0 - e_winner))

    c = db_conn.cursor()
    c.execute("UPDATE players SET elo_rating = ?, wins = wins + 1, games_played = games_played + 1 WHERE user_id = ?", (round(new_r_winner), str(winner_id)))
    c.execute("UPDATE players SET elo_rating = ?, losses = losses + 1, games_played = games_played + 1 WHERE user_id = ?", (round(new_r_loser), str(loser_id)))
    db_conn.commit()

    return round(new_r_winner), round(new_r_loser)

# --- DISCORD CLIENT AND BOT LOGIC ---

class MyClient(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tree = app_commands.CommandTree(self)
        self.guild = discord.Object(id=GUILD_ID)

        # --- Centralized Database Connection ---
        self.db_conn = sqlite3.connect(DATABASE_FILE)
        self.db_conn.row_factory = sqlite3.Row
        init_db(self.db_conn)

    async def setup_hook(self):
        self.tree.copy_global_to(guild=self.guild)
        await self.tree.sync(guild=self.guild)
        print(f"Commands synced for guild: {GUILD_ID}")

    async def on_ready(self):
        check_stale_matches.start(self)  # Pass client instance to the task
        print(f'Bot connected as {self.user} (ID: {self.user.id})!')
        print('------')

    async def close(self):
        """Properly close resources when the bot is shutting down."""
        if self.db_conn:
            self.db_conn.close()
            print("Database connection closed.")
        await super().close()

intents = discord.Intents.default()
intents.members = True
client = MyClient(intents=intents)

# --- MATCH RESOLUTION HELPER ---
# This centralized function prevents code duplication.

async def _resolve_match_logic(client: MyClient, guild: discord.Guild, match_data: sqlite3.Row) -> tuple[str, Optional[discord.ui.View]]:
    """
    Handles all logic for resolving a match.
    Determines winner/loser, updates stats, and generates the result message.
    Returns the result message string and an optional View for disputed matches.
    """
    p1_id, p2_id = int(match_data['player1_id']), int(match_data['player2_id'])
    p1_report, p2_report = match_data['player1_report'], match_data['player2_report']
    match_id = match_data['match_id']

    try:
        player1 = await guild.fetch_member(p1_id)
        player2 = await guild.fetch_member(p2_id)
    except discord.NotFound:
        update_match_status(client.db_conn, match_id, "error_player_not_found")
        return f"Could not resolve match `{match_id}` because a player left the server.", None

    winner, loser = None, None
    result_message = ""
    final_view = None

    # Case 1: Both players reported
    if p1_report is not None and p2_report is not None:
        # Case 1a: Reports agree (win/loss)
        if p1_report != p2_report:
            winner = player1 if p1_report == 1 else player2
            loser = player2 if p1_report == 1 else player1
            result_message = f"✅ **Result Confirmed** for match `{match_id}`. "
        # Case 1b: Reports conflict (both claim win or both claim loss)
        else:
            update_match_status(client.db_conn, match_id, "disputed")
            admin_role = discord.utils.get(guild.roles, name=ADMIN_ROLE_NAME)
            admin_mention = f"<@&{admin_role.id}>" if admin_role else f"an **{ADMIN_ROLE_NAME}**"
            result_message = (f"🚨 **Report Conflict** in match `{match_id}` between "
                              f"{player1.mention} and {player2.mention}.\n"
                              f"An {admin_mention} needs to resolve it.")
            match_url = f"https://discord.com/channels/{guild.id}/{match_data['channel_id']}/{match_data['message_id']}"
            final_view = ui.View()
            final_view.add_item(ui.Button(label="Jump to Match", style=discord.ButtonStyle.link, url=match_url))
            return result_message, final_view

    # Case 2: Only one player reported before timeout
    elif p1_report is not None:
        winner = player1 if p1_report == 1 else player2
        loser = player2 if p1_report == 1 else player1
        result_message = f"⌛️ **Automatic Result** for match `{match_id}`. Only {player1.mention} reported. "
    elif p2_report is not None:
        winner = player2 if p2_report == 1 else player1
        loser = player1 if p2_report == 1 else player2
        result_message = f"⌛️ **Automatic Result** for match `{match_id}`. Only {player2.mention} reported. "

    # Case 3: Neither player reported before timeout
    else:
        update_match_status(client.db_conn, match_id, "timed_out")
        result_message = f"❌ **Match Expired** (`{match_id}`). Neither player reported in time."
        return result_message, None

    # If a winner was determined, update ELO and finalize the message
    if winner and loser:
        new_winner_elo, new_loser_elo = update_elo_and_stats(client.db_conn, winner.id, loser.id)
        update_match_status(client.db_conn, match_id, "confirmed")
        if new_winner_elo is not None:
            result_message += f"**{winner.mention} has defeated {loser.mention}!**\n"
            result_message += f"ELO: {winner.display_name} (`{new_winner_elo}`) | {loser.display_name} (`{new_loser_elo}`)"
        else:
            result_message = f"Could not update ELO for match `{match_id}` due to a data error."

    return result_message, final_view

# --- INTERACTIVE UI (VIEWS) ---

class MatchResultView(discord.ui.View):
    def __init__(self, client_instance: MyClient, player1: discord.Member, player2: discord.Member, match_id: str):
        super().__init__(timeout=REPORT_TIMEOUT_HOURS * 3600)
        self.client = client_instance
        self.player1 = player1
        self.player2 = player2
        self.match_id = match_id
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """
        Checks if the interacting user is allowed to use the buttons.
        Also checks if the match is still pending to prevent race conditions.
        """
        match_data = get_match(self.client.db_conn, self.match_id)
        if not match_data or match_data['status'] != 'pending':
            await interaction.response.send_message("This match has already been resolved or expired.", ephemeral=True)
            return False

        is_participant = interaction.user.id in [self.player1.id, self.player2.id]
        if not is_participant:
            await interaction.response.send_message("You are not a participant in this match.", ephemeral=True)
            return False

        voted_p1 = match_data['player1_report'] is not None
        voted_p2 = match_data['player2_report'] is not None

        has_voted = (interaction.user.id == self.player1.id and voted_p1) or \
                    (interaction.user.id == self.player2.id and voted_p2)
        if has_voted:
            await interaction.response.send_message("You have already reported a result for this match.", ephemeral=True)
            return False

        return True

    async def finalize_match(self, channel: discord.TextChannel):
        """Finalizes the match by calling the central logic helper."""
        match_data = get_match(self.client.db_conn, self.match_id)
        if not match_data or match_data['status'] != 'pending':
            return

        result_message, final_view = await _resolve_match_logic(self.client, channel.guild, match_data)

        if result_message:
            await channel.send(result_message, view=final_view)

        # Reliably disable buttons on the original message, with robust error handling
        if self.message:
            try:
                await self.message.edit(view=None)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                print(f"Could not edit message for match {self.match_id}. Error: {e}")

        self.stop()

    async def on_timeout(self):
        """Handles the case where the view times out before both players report."""
        if self.message:
            await self.finalize_match(self.message.channel)

    async def handle_report(self, interaction: discord.Interaction, won: bool):
        """Handles a win/loss report from a player."""
        report_value = 1 if won else 0
        update_match_report(self.client.db_conn, self.match_id, interaction.user.id, report_value)

        await interaction.response.send_message(f"You have reported a **{'win' if won else 'loss'}**. Waiting for the opponent...", ephemeral=True)

        # Check if both players have now voted
        match_data = get_match(self.client.db_conn, self.match_id)
        if match_data['player1_report'] is not None and match_data['player2_report'] is not None:
            await self.finalize_match(interaction.channel)

    @discord.ui.button(label="I Won!", style=discord.ButtonStyle.success, custom_id="i_won")
    async def i_won_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_report(interaction, won=True)

    @discord.ui.button(label="I Lost", style=discord.ButtonStyle.danger, custom_id="i_lost")
    async def i_lost_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_report(interaction, won=False)

class ChallengeView(discord.ui.View):
    """A view to handle the challenge acceptance phase."""
    def __init__(self, client_instance: MyClient, challenger: discord.Member, opponent: discord.Member):
        super().__init__(timeout=CHALLENGE_TIMEOUT_SECONDS)
        self.client = client_instance
        self.challenger = challenger
        self.opponent = opponent
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Only the opponent can interact with these buttons."""
        if interaction.user != self.opponent:
            await interaction.response.send_message("Only the challenged player can accept or decline this duel!", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        """Handles the case where the challenge invitation times out."""
        if self.message:
            embed = self.message.embeds[0]
            embed.color = discord.Color.dark_grey()
            embed.description = f"{self.challenger.mention}'s challenge to {self.opponent.mention} has expired."
            await self.message.edit(embed=embed, view=None)

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handles the challenge being accepted."""
        self.stop()
        match_id = uuid.uuid4().hex[:8]
        view = MatchResultView(self.client, self.challenger, self.opponent, match_id)

        # Edit the original message to show the challenge was accepted
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()
        embed.description = f"{self.opponent.mention} has accepted the challenge from {self.challenger.mention}!"
        embed.set_footer(text=f"Match ID: {match_id} | Both players have {REPORT_TIMEOUT_HOURS} hour(s) to report the result.")
        await interaction.response.edit_message(embed=embed, view=view)

        # Update the view instance with the new message
        message = await interaction.original_response()
        view.message = message

        # Create the match record in the database
        create_match_record(self.client.db_conn, match_id, self.challenger.id, self.opponent.id, message.id, message.channel.id)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handles the challenge being declined."""
        self.stop()
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        embed.description = f"{self.opponent.mention} has declined the challenge from {self.challenger.mention}."
        await interaction.response.edit_message(embed=embed, view=None)


# --- SLASH COMMANDS ---

@client.tree.command(name="challenge", description="Challenge another player to a ranked match.")
@app_commands.describe(opponent="The player you want to challenge.")
async def challenge_command(interaction: discord.Interaction, opponent: discord.Member):
    if interaction.channel_id != CHANNEL_ID:
        await interaction.response.send_message(f"This command can only be used in the designated ELO channel.", ephemeral=True)
        return

    if opponent.bot or opponent.id == interaction.user.id:
        await interaction.response.send_message("You cannot challenge a bot or yourself.", ephemeral=True)
        return

    add_player_if_not_exists(interaction.client.db_conn, interaction.user.id, interaction.user.display_name)
    add_player_if_not_exists(interaction.client.db_conn, opponent.id, opponent.display_name)

    # Use the new ChallengeView to handle acceptance
    view = ChallengeView(client, interaction.user, opponent)

    embed = discord.Embed(
        title="⚔️ A Challenge Has Been Issued! ⚔️",
        description=f"{interaction.user.mention} has challenged {opponent.mention}. Do you accept?",
        color=discord.Color.red()
    )
    embed.set_footer(text=f"The opponent has {CHALLENGE_TIMEOUT_SECONDS // 60} minutes to respond.")

    await interaction.response.send_message(opponent.mention, embed=embed, view=view)
    message = await interaction.original_response()
    view.message = message

@client.tree.command(name="stats", description="Show your stats or another player's stats.")
@app_commands.describe(player="The player whose stats you want to see (optional).")
async def stats_command(interaction: discord.Interaction, player: Optional[discord.Member] = None):
    if interaction.channel_id != CHANNEL_ID:
        await interaction.response.send_message(f"This command can only be used in the designated ELO channel.", ephemeral=True)
        return

    target_user = player or interaction.user
    player_data = get_player(interaction.client.db_conn, target_user.id)
    if not player_data:
        await interaction.response.send_message(f"{target_user.display_name} has not played any matches yet.", ephemeral=True)
        return

    embed = discord.Embed(title=f"📊 Stats for {player_data['user_name']}", color=discord.Color.blue())
    embed.set_thumbnail(url=target_user.display_avatar.url)
    embed.add_field(name="ELO Rating", value=f"**{player_data['elo_rating']}**", inline=False)
    embed.add_field(name="Wins", value=player_data['wins'], inline=True)
    embed.add_field(name="Losses", value=player_data['losses'], inline=True)
    win_rate = (player_data['wins'] / player_data['games_played'] * 100) if player_data['games_played'] > 0 else 0
    embed.add_field(name="Win Rate", value=f"{win_rate:.2f}%", inline=False)

    await interaction.response.send_message(embed=embed)

@client.tree.command(name="leaderboard", description="Displays the server's leaderboard.")
async def leaderboard_command(interaction: discord.Interaction):
    if interaction.channel_id != CHANNEL_ID:
        await interaction.response.send_message(f"This command can only be used in the designated ELO channel.", ephemeral=True)
        return

    leaderboard_data = get_leaderboard(interaction.client.db_conn, 10)
    if not leaderboard_data:
        await interaction.response.send_message("There is not enough data for a leaderboard yet.", ephemeral=True)
        return

    embed = discord.Embed(title="🏆 Fatal Fury Leaderboard 🏆", description="The top fighters on the server.", color=discord.Color.gold())
    leaderboard_text = ""
    medals = ["🥇", "🥈", "🥉"]
    for i, player in enumerate(leaderboard_data):
        rank = medals[i] if i < 3 else f"**#{i+1}**"
        leaderboard_text += f"{rank} **{player['user_name']}** - {player['elo_rating']} ELO (W:{player['wins']}/L:{player['losses']})\n"

    embed.add_field(name="Top Players", value=leaderboard_text, inline=False)
    await interaction.response.send_message(embed=embed)

@client.tree.command(name="my_matches", description="Shows a list of your pending matches.")
async def my_matches_command(interaction: discord.Interaction):
    if interaction.channel_id != CHANNEL_ID:
        await interaction.response.send_message(f"This command can only be used in the designated ELO channel.", ephemeral=True)
        return

    pending_matches = get_pending_matches_for_user(interaction.client.db_conn, interaction.user.id)
    if not pending_matches:
        await interaction.response.send_message("You have no pending matches!", ephemeral=True)
        return

    embed = discord.Embed(
        title="⚔️ Your Pending Matches",
        description="Here are your active matches. Click a button to jump directly to the challenge!",
        color=discord.Color.blue()
    )
    view = discord.ui.View()
    for match in pending_matches[:5]: # Limit to 5 to avoid clutter
        p1_id, p2_id = int(match['player1_id']), int(match['player2_id'])
        opponent_id = p2_id if interaction.user.id == p1_id else p1_id

        try:
            # Use fetch_member for reliability
            opponent = await interaction.guild.fetch_member(opponent_id)
            opponent_name = opponent.display_name
        except discord.NotFound:
            opponent_name = "an unknown player"

        match_url = f"https://discord.com/channels/{interaction.guild.id}/{match['channel_id']}/{match['message_id']}"
        button = discord.ui.Button(label=f"Match against {opponent_name}", style=discord.ButtonStyle.link, url=match_url)
        view.add_item(button)

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@client.tree.command(name="admin_resolve_match", description="[Admin] Manually resolve a match.")
@app_commands.describe(match_id="The ID of the match to resolve.", winner="The player who won the match.")
@app_commands.checks.has_role(ADMIN_ROLE_NAME)
async def admin_resolve_command(interaction: discord.Interaction, match_id: str, winner: discord.Member):
    if interaction.channel_id != CHANNEL_ID:
        await interaction.response.send_message(f"This command can only be used in the designated ELO channel.", ephemeral=True)
        return

    match_data = get_match(interaction.client.db_conn, match_id)
    if not match_data:
        await interaction.response.send_message(f"Match `{match_id}` was not found.", ephemeral=True)
        return
    if match_data['status'] not in ['pending', 'disputed']:
        await interaction.response.send_message(f"Match `{match_id}` has already been resolved.", ephemeral=True)
        return

    p1_id, p2_id = int(match_data['player1_id']), int(match_data['player2_id'])
    if winner.id not in [p1_id, p2_id]:
        await interaction.response.send_message("The specified winner is not a participant in this match.", ephemeral=True)
        return

    loser_id = p2_id if winner.id == p1_id else p1_id
    try:
        loser = await interaction.guild.fetch_member(loser_id)
    except discord.NotFound:
        await interaction.response.send_message(f"Could not find the loser of the match in the server.", ephemeral=True)
        return

    new_winner_elo, new_loser_elo = update_elo_and_stats(interaction.client.db_conn, winner.id, loser.id)
    update_match_status(interaction.client.db_conn, match_id, 'confirmed')

    embed = discord.Embed(title="⚖️ Match Resolution by Admin ⚖️", color=discord.Color.dark_orange())
    embed.description = f"Match `{match_id}` has been resolved by {interaction.user.mention}."
    embed.add_field(name="Result", value=f"**Winner:** {winner.mention}\n**Loser:** {loser.mention}", inline=False)
    if new_winner_elo is not None:
        embed.add_field(name="Updated ELO", value=f"{winner.display_name}: `{new_winner_elo}`\n{loser.display_name}: `{new_loser_elo}`", inline=False)

    await interaction.response.send_message(embed=embed)

@admin_resolve_command.error
async def admin_resolve_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.errors.MissingRole):
        await interaction.response.send_message(f"You need the `{ADMIN_ROLE_NAME}` role to use this command.", ephemeral=True)
    else:
        await interaction.response.send_message("An unexpected error occurred while running this command.", ephemeral=True)
        print(f"An error occurred in admin_resolve_match: {error}")


# --- BACKGROUND TASK ---

@tasks.loop(minutes=5)
async def check_stale_matches(client: MyClient):
    """Periodically checks for and resolves expired matches."""
    guild = client.get_guild(GUILD_ID)
    if not guild:
        print("Could not find the configured guild. Stale match check skipped.")
        return

    stale_matches = get_stale_matches(client.db_conn)
    if not stale_matches:
        return

    print(f"Found {len(stale_matches)} stale match(es) to clean up.")
    for match in stale_matches:
        # Check if the match is in the designated channel before processing it
        if int(match['channel_id']) != CHANNEL_ID:
            print(f"Skipping stale match {match['match_id']} as it is not in the designated channel.")
            continue

        channel = guild.get_channel(int(match['channel_id']))
        if not channel:
            print(f"Could not find channel for stale match {match['match_id']}. Skipping.")
            continue

        # Use the central logic handler to resolve the match
        result_message, _ = await _resolve_match_logic(client, guild, match)

        if result_message:
            await channel.send(result_message)

        # Reliably disable buttons on the original message
        try:
            message = await channel.fetch_message(int(match['message_id']))
            await message.edit(view=None)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            print(f"Could not edit original message for stale match {match['match_id']}.")


@check_stale_matches.before_loop
async def before_check_stale_matches():
    """Waits for the bot to be ready before starting the task loop."""
    await client.wait_until_ready()


# --- MAIN ENTRY POINT ---

if __name__ == "__main__":
    if not BOT_TOKEN or GUILD_ID == 0 or CHANNEL_ID == 0:
        print("CRITICAL ERROR: BOT_TOKEN, GUILD_ID, or CHANNEL_ID are not configured in Replit Secrets.")
    else:
        client.run(BOT_TOKEN)
