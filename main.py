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

async def schedule_unvoicemute(guild: discord.Guild, member_id: int, unvoicemute_time: datetime):
    await discord.utils.sleep_until(unvoicemute_time)
    member = guild.get_member(member_id)
    if member and member.voice and member.voice.mute:
        try:
            await member.edit(mute=False, reason="Temporary voice mute expired")
        except Exception:
            pass

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

# -------- MODERATION COMMANDS --------

@bot.tree.command(name="kick", description="Kick a member")
@app_commands.describe(user="User to kick", reason="Reason for kicking")
async def kick(interaction: discord.Interaction, user: discord.User, reason: str):
    if not has_role_permission(interaction, "kick"):
        return await styled_response(interaction, "❌ You do not have permission to use this command.", discord.Color.red())

    member = interaction.guild.get_member(user.id)
    if member:
        try:
            await member.kick(reason=f"{reason} - kicked by {interaction.user}")
            user_id_str = str(user.id)
            if user_id_str not in mod_history:
                mod_history[user_id_str] = []
            mod_history[user_id_str].append({
                "type": "kick",
                "guild_id": interaction.guild.id,
                "moderator": interaction.user.name,
                "reason": reason
            })
            save_mod_history()
            await styled_response(interaction, f"👢 {member} has been kicked. Reason: {reason}")
            log_channel = bot.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                await log_channel.send(f"👢 {interaction.user} kicked {member} in {interaction.guild.name}. Reason: {reason}")
        except Exception as e:
            await styled_response(interaction, f"❌ Failed to kick: {e}", discord.Color.red())
    else:
        await styled_response(interaction, "❌ User not found in this server.", discord.Color.red())

@bot.tree.command(name="ban", description="Ban a member")
@app_commands.describe(member="Member to ban", reason="Reason for the ban", time="Optional duration (e.g., 10m, 1h, 1d)")
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str, time: str = None):
    if not has_role_permission(interaction, "ban"):
        return await styled_response(interaction, "❌ You do not have permission to use this command.", discord.Color.red())

    try:
        await member.ban(reason=f"{reason} - banned by {interaction.user}")
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

        if time:
            seconds = parse_time(time)
            unban_time = datetime.utcnow() + timedelta(seconds=seconds)
            asyncio.create_task(schedule_unban(interaction.guild, member.id, unban_time))
            await interaction.followup.send(f"⏲️ {member} will be unbanned in {time}.", ephemeral=True)
    except Exception as e:
        await styled_response(interaction, f"❌ Failed to ban: {e}", discord.Color.red())

@bot.tree.command(name="mute", description="Mute a member in text channels")
@app_commands.describe(member="Member to mute", reason="Reason for the mute", time="Optional duration (e.g., 10m, 1h, 1d)")
async def mute(interaction: discord.Interaction, member: discord.Member, reason: str, time: str = None):
    if not has_role_permission(interaction, "mute"):
        return await styled_response(interaction, "❌ You do not have permission to use this command.", discord.Color.red())

    mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
    if not mute_role:
        return await styled_response(interaction, "❌ 'Muted' role does not exist. Please create it first.", discord.Color.red())

    try:
        await member.add_roles(mute_role, reason=f"{reason} - muted by {interaction.user}")
        await styled_response(interaction, f"🔇 {member} has been muted in text channels. Reason: {reason}")
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"🔇 {interaction.user} muted {member} in {interaction.guild.name}. Reason: {reason}")

        if time:
            seconds = parse_time(time)
            unmute_time = datetime.utcnow() + timedelta(seconds=seconds)
            asyncio.create_task(schedule_unmute(interaction.guild, member.id, unmute_time))
            await interaction.followup.send(f"⏲️ {member} will be unmuted in {time}.", ephemeral=True)
    except Exception as e:
        await styled_response(interaction, f"❌ Failed to mute: {e}", discord.Color.red())

@bot.tree.command(name="unmute", description="Unmute a user in text channels")
@app_commands.describe(member="Member to unmute", reason="Reason for unmuting")
async def unmute(interaction: discord.Interaction, member: discord.Member, reason: str):
    if not has_role_permission(interaction, "mute"):
        return await styled_response(interaction, "❌ You do not have permission to use this command.", discord.Color.red())

    mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
    if not mute_role:
        return await styled_response(interaction, "❌ 'Muted' role does not exist.", discord.Color.red())

    try:
        await member.remove_roles(mute_role, reason=f"{reason} - unmuted by {interaction.user}")
        await styled_response(interaction, f"🔊 {member} has been unmuted in text channels. Reason: {reason}")
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"🔊 {interaction.user} unmuted {member} in {interaction.guild.name}. Reason: {reason}")
    except Exception as e:
        await styled_response(interaction, f"❌ Failed to unmute: {e}", discord.Color.red())

@bot.tree.command(name="textmute", description="Mute a user in text channels")
@app_commands.describe(member="Member to mute", reason="Reason for mute", time="Optional duration (e.g., 10m, 1h, 1d)")
async def textmute(interaction: discord.Interaction, member: discord.Member, reason: str, time: str = None):
    await mute(interaction, member, reason, time)

@bot.tree.command(name="untextmute", description="Unmute a user in text channels")
@app_commands.describe(member="Member to unmute", reason="Reason for unmuting")
async def untextmute(interaction: discord.Interaction, member: discord.Member, reason: str):
    await unmute(interaction, member, reason)

@bot.tree.command(name="voicemute", description="Mute a member in voice channels")
@app_commands.describe(member="Member to voice mute", reason="Reason for the mute", time="Optional duration (e.g., 10m, 1h, 1d)")
async def voicemute(interaction: discord.Interaction, member: discord.Member, reason: str, time: str = None):
    if not has_role_permission(interaction, "voicemute"):
        return await styled_response(interaction, "❌ You do not have permission to use this command.", discord.Color.red())

    if not member.voice or not member.voice.channel:
        return await styled_response(interaction, f"❌ {member} is not connected to a voice channel.", discord.Color.red())

    try:
        await member.edit(mute=True, reason=f"{reason} - voice muted by {interaction.user}")
        await styled_response(interaction, f"🔇 {member} has been voice-muted. Reason: {reason}")
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"🔈 {interaction.user} voice-muted {member} in {interaction.guild.name}. Reason: {reason}")

        if time:
            seconds = parse_time(time)
            unvoicemute_time = datetime.utcnow() + timedelta(seconds=seconds)
            asyncio.create_task(schedule_unvoicemute(interaction.guild, member.id, unvoicemute_time))
            await interaction.followup.send(f"⏲️ {member} will be unvoicemuted in {time}.", ephemeral=True)
    except Exception as e:
        await styled_response(interaction, f"❌ Failed to voice mute: {e}", discord.Color.red())

@bot.tree.command(name="unvoicemute", description="Unmute a user in voice channels")
@app_commands.describe(member="Member to unmute", reason="Reason for unmuting")
async def unvoicemute(interaction: discord.Interaction, member: discord.Member, reason: str):
    if not has_role_permission(interaction, "voicemute"):
        return await styled_response(interaction, "❌ You do not have permission to use this command.", discord.Color.red())

    try:
        await member.edit(mute=False, reason=f"{reason} - voice unmuted by {interaction.user}")
        await styled_response(interaction, f"🔊 {member} has been unmuted in voice channels. Reason: {reason}")
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"🔊 {interaction.user} unvoicemuted {member} in {interaction.guild.name}. Reason: {reason}")
    except Exception as e:
        await styled_response(interaction, f"❌ Failed to unvoice mute: {e}", discord.Color.red())

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

    if time:
        # Global unban scheduling would depend on your system specifics
        await interaction.followup.send(f"⏲️ {user} will be un-gbanned in {time} if supported.", ephemeral=True)

@bot.tree.command(name="banlist", description="Show all banned users in this server")
async def banlist(interaction: discord.Interaction):
    if not has_role_permission(interaction, "ban"):
        return await styled_response(interaction, "❌ You do not have permission to use this command.", discord.Color.red())

    banned_users = []
    for user_id, records in mod_history.items():
        for record in records:
            if record["type"] == "ban" and record["guild_id"] == interaction.guild.id:
                banned_users.append((user_id, record))

    if not banned_users:
        return await styled_response(interaction, "✅ No bans recorded in this server.")

    embed = discord.Embed(title="🔨 Ban List", color=discord.Color.red())
    for user_id, record in banned_users[:25]:  # Discord embeds max out at 25 fields
        embed.add_field(
            name=f"User ID: {user_id}",
            value=f"Moderator: {record['moderator']}\nReason: {record['reason']}",
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="kicklist", description="Show all kicked users")
async def kicklist(interaction: discord.Interaction):
    if not has_role_permission(interaction, "kick"):
        return await styled_response(interaction, "❌ You do not have permission to use this command.", discord.Color.red())

    kicked_users = []
    for user_id, records in mod_history.items():
        for record in records:
            if record["type"] == "kick" and record["guild_id"] == interaction.guild.id:
                kicked_users.append((user_id, record))

    if not kicked_users:
        return await styled_response(interaction, "✅ No kicks recorded in this server.")

    embed = discord.Embed(title="👢 Kick List", color=discord.Color.orange())
    for user_id, record in kicked_users[:25]:
        embed.add_field(
            name=f"User ID: {user_id}",
            value=f"Moderator: {record['moderator']}\nReason: {record['reason']}",
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)
@bot.tree.command(name="warnlist", description="Show all warned users")
async def warnlist(interaction: discord.Interaction):
    if not has_role_permission(interaction, "warn"):
        return await styled_response(interaction, "❌ You do not have permission to use this command.", discord.Color.red())

    warned_users = []
    for user_id, records in mod_history.items():
        for record in records:
            if record["type"] == "warn" and record["guild_id"] == interaction.guild.id:
                warned_users.append((user_id, record))

    if not warned_users:
        return await styled_response(interaction, "✅ No warnings recorded in this server.")

    embed = discord.Embed(title="⚠️ Warn List", color=discord.Color.gold())
    for user_id, record in warned_users[:25]:
        embed.add_field(
            name=f"User ID: {user_id}",
            value=f"Moderator: {record['moderator']}\nReason: {record['reason']}",
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)
@bot.tree.command(name="gbanlist", description="Show all globally banned users")
async def gbanlist(interaction: discord.Interaction):
    if not has_role_permission(interaction, "gban"):
        return await styled_response(interaction, "❌ You do not have permission to use this command.", discord.Color.red())

    globally_banned_users = []
    for user_id, records in mod_history.items():
        for record in records:
            if record["type"] == "gban":
                globally_banned_users.append((user_id, record))

    if not globally_banned_users:
        return await styled_response(interaction, "✅ No global bans recorded.")

    embed = discord.Embed(title="🚫 Global Ban List", color=discord.Color.dark_red())
    for user_id, record in globally_banned_users[:25]:
        embed.add_field(
            name=f"User ID: {user_id}",
            value=f"Moderator: {record['moderator']}\nReason: {record['reason']}",
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)

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

# ====== DISCORD BOT TOKEN ======

if __name__ == "__main__":
bot.run(os.getenv("DISCORD_BOT_TOKEN"))  # ← ERROR: not indented!
