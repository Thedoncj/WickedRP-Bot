import os
import re
import random
import asyncio
import threading
import signal
import json
from datetime import datetime, timedelta, timezone
from flask import Flask
import discord
from discord import app_commands
from discord.ext import commands

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

MODERATION_ROLES = {
    "Trial Moderator": ["kick", "mute", "voicemute"],
    "Moderator": ["kick", "mute", "voicemute"],
    "Head Moderator": ["kick", "mute", "voicemute"],
    "Trial Administrator": ["kick", "mute", "voicemute", "giverole"],
    "Administrator": ["kick", "ban", "unban", "mute", "voicemute", "giverole"],
    "Head Administrator": ["kick", "ban", "unban", "mute", "gban", "voicemute", "giverole"],
    "Head Of Staff": ["all"],
    "Trial Manager": ["all"],
    "Management": ["all"],
    "Head Of Management": ["all"],
    "Co Director": ["all"],
    "Director": ["all"],
}

# === CONFIGURATION ===
ALERT_CHANNEL_ID = 1384717083652264056
STREAMER_CHANNEL_ID = 1207227502003757077
LOG_CHANNEL_ID = 1384882351678689431
STREAMER_ROLE = "Streamer"

kick_list = set(["Trial Moderator", "Moderator", "Head Moderator", "Trial Administrator", "Administrator", "Head Administrator", "Head Of Staff", "Trial Manager", "Management", "Head Of Management", "Co Director", "Director"])
ban_list = set(["Trial Moderator", "Moderator", "Head Moderator", "Trial Administrator", "Administrator", "Head Administrator", "Head Of Staff", "Trial Manager", "Management", "Head Of Management", "Co Director", "Director"])
warn_list = set(["Trial Moderator", "Moderator", "Head Moderator", "Trial Administrator", "Administrator", "Head Administrator", "Head Of Staff", "Trial Manager", "Management", "Head Of Management", "Co Director", "Director"])
gban_list = set(["Trial Moderator", "Moderator", "Head Moderator", "Trial Administrator", "Administrator", "Head Administrator", "Head Of Staff", "Trial Manager", "Management", "Head Of Management", "Co Director", "Director"])

mod_history = {}
MOD_HISTORY_FILE = "mod_history.json"
if os.path.exists(MOD_HISTORY_FILE):
    with open(MOD_HISTORY_FILE, "r") as f:
        mod_history = json.load(f)
else:
    mod_history = {}

def save_mod_history():
    with open(MOD_HISTORY_FILE, "w") as f:
        json.dump(mod_history, f, indent=4)

def has_role_permission(interaction: discord.Interaction, command_name: str):
    for role in interaction.user.roles:
        perms = MODERATION_ROLES.get(role.name)
        if perms:
            if "all" in perms or command_name in perms:
                return True
    return False

async def styled_response(interaction, message, color=discord.Color.blurple()):
    embed = discord.Embed(description=message, color=color)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.event
async def on_ready():
    await bot.wait_until_ready()
    await bot.tree.sync()
    print(f"Logged in as {bot.user} and synced commands.")

@bot.event
async def on_member_join(member: discord.Member):
    alert_channel = bot.get_channel(ALERT_CHANNEL_ID)
    if not alert_channel:
        return

    user_id = member.id
    embed_needed = False
    embed = discord.Embed(
        title="🔍 New Member Alert",
        description=f"User: {member.mention} (`{member.id}`) has joined.",
        color=discord.Color.orange()
    )

    if member.avatar is None:
        embed.add_field(name="⚠️ No Profile Picture", value="This user has the default avatar.", inline=False)
        embed_needed = True

    account_age = datetime.now(timezone.utc) - member.created_at
    if account_age < timedelta(days=7):
        embed.add_field(name="⚠️ New Account", value=f"Account is only `{account_age.days}` days old.", inline=False)
        embed_needed = True

    user_id_str = str(user_id)
    if user_id_str in mod_history:
        embed.title = "🚨 Member with Prior Moderation History Joined"
        embed.color = discord.Color.red()
        for record in mod_history[user_id_str]:
            guild = bot.get_guild(record["guild_id"]) if record["guild_id"] != "global" else None
            server_name = guild.name if guild else f"Guild ID {record['guild_id']}"
            embed.add_field(
                name=f"{record['type'].capitalize()} in {server_name}",
                value=f"Moderator: **{record['moderator']}**\nReason: {record['reason']}",
                inline=False
            )
        embed_needed = True

    if embed_needed:
        await alert_channel.send(embed=embed)

@bot.tree.command(name="kick", description="Kick a member")
@app_commands.describe(user="User to kick")
async def kick(interaction: discord.Interaction, user: discord.User):
    if not has_role_permission(interaction, "kick"):
        return await styled_response(interaction, "❌ You do not have permission to use this command.", discord.Color.red())

    member = interaction.guild.get_member(user.id)
    if member:
        await member.kick()
        user_id_str = str(user.id)
        if user_id_str not in mod_history:
            mod_history[user_id_str] = []
        mod_history[user_id_str].append({
            "type": "kick",
            "guild_id": interaction.guild.id,
            "moderator": interaction.user.name,
            "reason": "N/A"
        })
        save_mod_history()
        await styled_response(interaction, f"👢 {member} has been kicked.")
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"👢 {interaction.user} kicked {member} in {interaction.guild.name}")
    else:
        await styled_response(interaction, "❌ User not found in this server.", discord.Color.red())

Here’s your updated code for the following commands:

/ban

/mute (text mute)

/voicemute

With these improvements:

✅ reason is now a required argument
🕒 time is added as an optional argument where it makes sense (mute, voicemute, ban)

⏳ (Note: This only collects the time; if you want auto-unmute/auto-unban after time, let me know and I’ll add that too.)

🔁 Updated Command Code:
python
Copy
Edit
@bot.tree.command(name="ban", description="Ban a member")
@app_commands.describe(member="Member to ban", reason="Reason for the ban", time="Optional duration (e.g., 10m, 1h, 1d)")
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str, time: str = None):
    if not has_role_permission(interaction, "ban"):
        return await styled_response(interaction, "❌ You do not have permission to use this command.", discord.Color.red())

    await member.ban(reason=reason)
    user_id_str = str(member.id)
    if user_id_str not in mod_history:
        mod_history[user_id_str] = []
    mod_history[user_id_str].append({
        "type": "ban",
        "guild_id": interaction.guild.id,
        "moderator": interaction.user.name,
        "reason": reason
    })
    save_mod_history()
    await styled_response(interaction, f"🔨 {member} has been banned. Reason: {reason}")
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(f"🔨 {interaction.user} banned {member} in {interaction.guild.name}. Reason: {reason}")

@bot.tree.command(name="mute", description="Mute a member in text channels")
@app_commands.describe(member="Member to mute", reason="Reason for the mute", time="Optional duration (e.g., 10m, 1h, 1d)")
async def mute(interaction: discord.Interaction, member: discord.Member, reason: str, time: str = None):
    if not has_role_permission(interaction, "mute"):
        return await styled_response(interaction, "❌ You do not have permission to use this command.", discord.Color.red())

    overwrite = discord.PermissionOverwrite(send_messages=False)
    for channel in interaction.guild.text_channels:
        await channel.set_permissions(member, overwrite=overwrite)
    await styled_response(interaction, f"🔇 {member} has been muted in text channels. Reason: {reason}")
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(f"🔇 {interaction.user} muted {member} in text channels on {interaction.guild.name}. Reason: {reason}")

@bot.tree.command(name="voicemute", description="Mute a member in voice channels")
@app_commands.describe(member="Member to voice mute", reason="Reason for the mute", time="Optional duration (e.g., 10m, 1h, 1d)")
async def voicemute(interaction: discord.Interaction, member: discord.Member, reason: str, time: str = None):
    if not has_role_permission(interaction, "voicemute"):
        return await styled_response(interaction, "❌ You do not have permission to use this command.", discord.Color.red())

    await member.edit(mute=True)
    await styled_response(interaction, f"🔇 {member} has been voice-muted. Reason: {reason}")
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(f"🔈 {interaction.user} voice-muted {member} in {interaction.guild.name}

@bot.tree.command(name="gban", description="Globally ban a user across servers")
@app_commands.describe(user="User to globally ban", reason="Reason for the global ban", time="Optional duration (e.g., 10m, 2h, 1d)")
async def gban(interaction: discord.Interaction, user: discord.User, reason: str, time: str = None):
    if not has_role_permission(interaction, "gban"):
        return await styled_response(interaction, "❌ You do not have permission to use this command.", discord.Color.red())
    user_id_str = str(user.id)
    if user_id_str not in mod_history:
        mod_history[user_id_str] = []
    mod_history[user_id_str].append({
        "type": "gban",
        "guild_id": "global",
        "moderator": interaction.user.name,
        "reason": reason
    })
    save_mod_history()
    await styled_response(interaction, f"🚫 {user} has been globally banned. Reason: {reason}")

@bot.tree.command(name="unban", description="Unban a user")
@app_commands.describe(user_id="ID of user to unban", reason="Reason for unbanning")
async def unban(interaction: discord.Interaction, user_id: str, reason: str):
    if not has_role_permission(interaction, "unban"):
        return await styled_response(interaction, "❌ You do not have permission to use this command.", discord.Color.red())
    user = await bot.fetch_user(int(user_id))
    await interaction.guild.unban(user, reason=reason)
    await styled_response(interaction, f"✅ Unbanned {user} for reason: {reason}")

@bot.tree.command(name="textmute", description="Mute a user in text channels")
@app_commands.describe(member="Member to mute", reason="Reason for mute", time="Optional duration (e.g., 10m, 1h, 1d)")
async def textmute(interaction: discord.Interaction, member: discord.Member, reason: str, time: str = None):
    if not has_role_permission(interaction, "mute"):
        return await styled_response(interaction, "❌ You do not have permission to use this command.", discord.Color.red())
    overwrite = discord.PermissionOverwrite(send_messages=False)
    for channel in interaction.guild.text_channels:
        await channel.set_permissions(member, overwrite=overwrite)
    await styled_response(interaction, f"🔇 {member} has been muted in text channels for reason: {reason}")

@bot.tree.command(name="untextmute", description="Unmute a user in text channels")
@app_commands.describe(member="Member to unmute", reason="Reason for unmuting")
async def untextmute(interaction: discord.Interaction, member: discord.Member, reason: str):
    if not has_role_permission(interaction, "mute"):
        return await styled_response(interaction, "❌ You do not have permission to use this command.", discord.Color.red())
    for channel in interaction.guild.text_channels:
        await channel.set_permissions(member, overwrite=None)
    await styled_response(interaction, f"🔊 {member} has been unmuted in text channels. Reason: {reason}")

@bot.tree.command(name="unvoicemute", description="Unmute a user in voice channels")
@app_commands.describe(member="Member to unmute", reason="Reason for unmuting")
async def unvoicemute(interaction: discord.Interaction, member: discord.Member, reason: str):
    if not has_role_permission(interaction, "voicemute"):
        return await styled_response(interaction, "❌ You do not have permission to use this command.", discord.Color.red())
    await member.edit(mute=False)
    await styled_response(interaction, f"🔊 {member} has been unmuted in voice channels. Reason: {reason}")

@bot.tree.command(name="warn", description="Warn a user")
@app_commands.describe(member="User to warn", reason="Reason for warning")
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str):
    if not has_role_permission(interaction, "warn"):
        return await styled_response(interaction, "❌ You do not have permission to use this command.", discord.Color.red())
    user_id_str = str(member.id)
    if user_id_str not in mod_history:
        mod_history[user_id_str] = []
    mod_history[user_id_str].append({
        "type": "warn",
        "guild_id": interaction.guild.id,
        "moderator": interaction.user.name,
        "reason": reason
    })
    save_mod_history()
    await styled_response(interaction, f"⚠️ {member} has been warned. Reason: {reason}")

@bot.tree.command(name="removewarn", description="Remove a warning from a user")
@app_commands.describe(member="User to remove warning from", reason="Reason for removing warning")
async def removewarn(interaction: discord.Interaction, member: discord.Member, reason: str):
    if not has_role_permission(interaction, "warn"):
        return await styled_response(interaction, "❌ You do not have permission to use this command.", discord.Color.red())
    user_id_str = str(member.id)
    if user_id_str in mod_history:
        mod_history[user_id_str] = [record for record in mod_history[user_id_str] if record["type"] != "warn"]
        save_mod_history()
        await styled_response(interaction, f"✅ Warning removed from {member}. Reason: {reason}")
    else:
        await styled_response(interaction, "⚠️ No warning history found for this user.", discord.Color.orange())

@app.route('/')
def index():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

threading.Thread(target=run_flask).start()

async def shutdown(sig):
    print(f"Received exit signal {sig.name}...")
    await bot.close()

def setup_shutdown_handler(loop):
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(shutdown(sig)))

setup_shutdown_handler(asyncio.get_event_loop())

bot.run(os.getenv("DISCORD_BOT_TOKEN"))
