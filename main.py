import os
import re
import random
import asyncio
import threading
import requests
from flask import Flask
from discord.ext import commands
import discord
from datetime import datetime, timedelta
from discord import app_commands

# === DISCORD BOT SETUP ===
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

global_ban_list = set()

MODERATION_ROLES = {
    "Trial Moderator": ["kick", "mute", "voicemute"],
    "Moderator": ["kick", "mute", "voicemute"],
    "Head Moderator": ["kick", "mute", "voicemute"],
    "Trial Administrator": ["kick", "mute", "voicemute"],
    "Administrator": ["kick", "ban", "unban", "mute", "voicemute", "giverole"],
    "Head Administrator": ["kick", "ban", "unban", "mute", "gban", "voicemute", "giverole"],
    "Head Of Staff": ["kick", "ban", "unban", "mute", "gban", "voicemute", "giverole", "all"],
    "Trial Manager": ["all"],
    "Management": ["all"],
    "Head Of Management": ["all"],
    "Co Director": ["all"],
    "Director": ["all"],
}
def has_role_permission(interaction: discord.Interaction, command: str) -> bool:
    user_roles = [role.name for role in interaction.user.roles]

    for role in user_roles:
        if role in MODERATION_ROLES:
            perms = MODERATION_ROLES[role]
            if "all" in perms or command in perms:
                return True
    return False

LINK_PRIVILEGED_ROLES = [
    "Head Of Staff", "Trial Manager", "Management", "Head Of Management", "Co Director", "Director"
]
# === CONFIGURATION ===
ALERT_CHANNEL_ID = 1384717083652264056
STREAMER_CHANNEL_ID = 1207227502003757077
LOG_CHANNEL_ID = 1384882351678689431
STREAMER_ROLE = "Streamer"

# Helper to parse duration strings (e.g. "10m", "1h") into seconds
def parse_time(time_str: str):
    pattern = re.fullmatch(r"(\d+)([smhd])", time_str.lower())
    if not pattern:
        raise ValueError("Invalid time format! Use a number followed by s/m/h/d")
    amount, unit = pattern.groups()
    amount = int(amount)
    if unit == "s":
        return amount
    elif unit == "m":
        return amount * 60
    elif unit == "h":
        return amount * 3600
    elif unit == "d":
        return amount * 86400

# Scheduling helpers for timed unban/unmute

async def schedule_unban(guild: discord.Guild, user_id: int, unban_time: datetime):
    await discord.utils.sleep_until(unban_time)
    try:
        user = await bot.fetch_user(user_id)
        await guild.unban(user, reason="Temporary ban expired")
    except Exception:
        pass

async def schedule_unmute(guild: discord.Guild, member_id: int, unmute_time: datetime):
    await discord.utils.sleep_until(unmute_time)
    member = guild.get_member(member_id)
    if member:
        mute_role = discord.utils.get(guild.roles, name="Muted")
        if mute_role in member.roles:
            try:
                await member.remove_roles(mute_role, reason="Temporary mute expired")
            except Exception:
                pass

@bot.event
async def on_ready():
    await bot.wait_until_ready()
    await bot.tree.sync()
    print(f"Logged in as {bot.user} and synced commands.")

# -------- MODERATION COMMANDS --------

@bot.tree.command(name="kick", description="Kick a member")
@app_commands.describe(user="User to kick", reason="Reason for kicking")
async def kick(interaction: discord.Interaction, user: discord.User, reason: str):
    await interaction.response.defer()
    if not has_role_permission(interaction, "kick"):
        return await interaction.followup.send("❌ You do not have permission to use this command.", ephemeral=True)

    member = interaction.guild.get_member(user.id)
    if member:
        try:
            await member.kick(reason=f"{reason} - kicked by {interaction.user}")
            mod_history.setdefault(str(user.id), []).append({
                "type": "kick",
                "guild_id": interaction.guild.id,
                "moderator": interaction.user.name,
                "reason": reason
            })
            save_mod_history()
            await interaction.followup.send(f"👢 {member} has been kicked. Reason: {reason}")
            log_channel = bot.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                await log_channel.send(f"👢 {interaction.user} kicked {member} in {interaction.guild.name}. Reason: {reason}")
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to kick: {e}", ephemeral=True)
    else:
        await interaction.followup.send("❌ User not found in this server.", ephemeral=True)

@bot.tree.command(name="ban", description="Ban a member")
@app_commands.describe(member="Member to ban", reason="Reason for the ban", time="Optional duration (e.g., 10m, 1h, 1d)")
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str, time: str = None):
    await interaction.response.defer()
    if not has_role_permission(interaction, "ban"):
        return await interaction.followup.send("❌ You do not have permission to use this command.", ephemeral=True)

@bot.tree.command(name="gban", description="Globally ban a user across servers")
@app_commands.describe(user="User to globally ban", reason="Reason for the global ban", time="Optional duration (e.g., 10m, 2h, 1d)")
async def gban(interaction: discord.Interaction, user: discord.User, reason: str, time: str = None):
    await interaction.response.defer()
    if not has_role_permission(interaction, "gban"):
        return await interaction.followup.send("❌ You do not have permission to use this command.", ephemeral=True)


@bot.tree.command(name="mute", description="Mute a member in text channels")
@app_commands.describe(member="Member to mute", reason="Reason for the mute", time="Optional duration (e.g., 10m, 1h, 1d)")
async def mute(interaction: discord.Interaction, member: discord.Member, reason: str, time: str = None):
    await interaction.response.defer()
    if not has_role_permission(interaction, "mute"):
        return await interaction.followup.send("❌ You do not have permission to use this command.", ephemeral=True)

    mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
    if not mute_role:
        return await interaction.followup.send("❌ 'Muted' role does not exist. Please create it first.", ephemeral=True)

    try:
        await member.add_roles(mute_role, reason=f"{reason} - muted by {interaction.user}")
        await interaction.followup.send(f"🔇 {member} has been muted in text channels. Reason: {reason}")
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"🔇 {interaction.user} muted {member} in {interaction.guild.name}. Reason: {reason}")

        if time:
            seconds = parse_time(time)
            unmute_time = datetime.utcnow() + timedelta(seconds=seconds)
            asyncio.create_task(schedule_unmute(interaction.guild, member.id, unmute_time))
            await interaction.followup.send(f"⏲️ {member} will be unmuted in {time}.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to mute: {e}", ephemeral=True)

@bot.tree.command(name="unmute", description="Unmute a user in text channels")
@app_commands.describe(member="Member to unmute", reason="Reason for unmuting")
async def unmute(interaction: discord.Interaction, member: discord.Member, reason: str):
    await interaction.response.defer()
    if not has_role_permission(interaction, "mute"):
        return await interaction.followup.send("❌ You do not have permission to use this command.", ephemeral=True)

    mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
    if not mute_role:
        return await interaction.followup.send("❌ 'Muted' role does not exist.", ephemeral=True)

    try:
        await member.remove_roles(mute_role, reason=f"{reason} - unmuted by {interaction.user}")
        await interaction.followup.send(f"🔊 {member} has been unmuted in text channels. Reason: {reason}")
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"🔊 {interaction.user} unmuted {member} in {interaction.guild.name}. Reason: {reason}")
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to unmute: {e}", ephemeral=True)

@bot.tree.command(name="warn", description="Warn a member")
@app_commands.describe(member="Member to warn", reason="Reason for the warning")
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str):
    await interaction.response.defer()
    if not has_role_permission(interaction, "warn"):
        return await interaction.followup.send("❌ You do not have permission to use this command.", ephemeral=True)

@bot.tree.command(name="giverole", description="Give a role to a member")
@app_commands.describe(member="Member to give role to", role="Role to assign", reason="Reason for giving the role")
async def giverole(interaction: discord.Interaction, member: discord.Member, role: discord.Role, reason: str):
    if not has_role_permission(interaction, "giverole"):
        return await styled_response(interaction, "❌ You do not have permission to use this command.", discord.Color.red())

    try:
        await member.add_roles(role, reason=f"{reason} - given by {interaction.user}")
        await styled_response(interaction, f"✅ Gave role **{role.name}** to {member.mention}. Reason: {reason}")
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"✅ {interaction.user} gave role **{role.name}** to {member.mention}. Reason: {reason}")
    except Exception as e:
        await styled_response(interaction, f"❌ Failed to give role: {e}", discord.Color.red())

@bot.tree.command(name="takerole", description="Remove a role from a member")
@app_commands.describe(member="Member to remove role from", role="Role to remove", reason="Reason for removing the role")
async def takerole(interaction: discord.Interaction, member: discord.Member, role: discord.Role, reason: str):
    if not has_role_permission(interaction, "giverole"):  # Same permission as giverole
        return await styled_response(interaction, "❌ You do not have permission to use this command.", discord.Color.red())

    try:
        await member.remove_roles(role, reason=f"{reason} - removed by {interaction.user}")
        await styled_response(interaction, f"🗑️ Removed role **{role.name}** from {member.mention}. Reason: {reason}")
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"🗑️ {interaction.user} removed role **{role.name}** from {member.mention}. Reason: {reason}")
    except Exception as e:
        await styled_response(interaction, f"❌ Failed to remove role: {e}", discord.Color.red())

@bot.tree.command(name="ungban", description="Remove a user from the global ban list")
@app_commands.describe(user="User to un-global-ban")
async def ungban(interaction: discord.Interaction, user: discord.User):
    if not has_role_permission(interaction, "gban"):
        return await styled_response(interaction, "❌ You do not have permission to use this command.", discord.Color.red())

    user_id_str = str(user.id)
    if user_id_str in mod_history:
        mod_history[user_id_str] = [record for record in mod_history[user_id_str] if record["type"] != "gban"]
        save_mod_history()
        await styled_response(interaction, f"✅ {user} has been removed from the global ban list.")
    else:
        await styled_response(interaction, f"ℹ️ {user} was not found in the global ban list.")

from flask import Flask
from threading import Thread

app = Flask("")

# === FLASK KEEP-ALIVE SERVER ===
app = Flask(__name__)

@app.route('/')
def index():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

threading.Thread(target=run_flask).start()

bot.run(os.getenv("DISCORD_BOT_TOKEN"))

# Start the Discord bot
import os
bot.run(os.getenv("TOKEN"))
