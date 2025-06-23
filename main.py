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

@bot.event
async def on_ready():
    await bot.wait_until_ready()
    await bot.tree.sync()
    print(f"Logged in as {bot.user} and synced commands.")

@bot.event
async def on_ready():
    await bot.change_presence(status=discord.Status.online)
    print(f"Logged in as {bot.user}")

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

    try:
        await member.ban(reason=f"{reason} - banned by {interaction.user}")
        mod_history.setdefault(str(member.id), []).append({
            "type": "ban",
            "guild_id": interaction.guild.id,
            "moderator": interaction.user.name,
            "reason": reason
        })
        save_mod_history()
        await interaction.followup.send(f"🔨 {member} has been banned. Reason: {reason}")
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"🔨 {interaction.user} banned {member} in {interaction.guild.name}. Reason: {reason}")

        if time:
            seconds = parse_time(time)
            unban_time = datetime.utcnow() + timedelta(seconds=seconds)
            asyncio.create_task(schedule_unban(interaction.guild, member.id, unban_time))
            await interaction.followup.send(f"⏲️ {member} will be unbanned in {time}.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to ban: {e}", ephemeral=True)

@bot.tree.command(name="gban", description="Globally ban a user across servers")
@app_commands.describe(user="User to globally ban", reason="Reason for the global ban", time="Optional duration (e.g., 10m, 2h, 1d)")
async def gban(interaction: discord.Interaction, user: discord.User, reason: str, time: str = None):
    await interaction.response.defer()
    if not has_role_permission(interaction, "gban"):
        return await interaction.followup.send("❌ You do not have permission to use this command.", ephemeral=True)

    mod_history.setdefault(str(user.id), []).append({
        "type": "gban",
        "guild_id": "global",
        "moderator": interaction.user.name,
        "reason": reason
    })
    save_mod_history()
    await interaction.followup.send(f"🚫 {user} has been globally banned. Reason: {reason}")

    if time:
        await interaction.followup.send(f"⏲️ {user} will be un-gbanned in {time} if supported.", ephemeral=True)

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

    mod_history.setdefault(str(member.id), []).append({
        "type": "warn",
        "guild_id": interaction.guild.id,
        "moderator": interaction.user.name,
        "reason": reason
    })
    save_mod_history()

    await interaction.followup.send(f"⚠️ {member} has been warned. Reason: {reason}")
    log_channel = bot.get_channel(1372296224803258480)
    if log_channel:
        await log_channel.send(f"⚠️ {interaction.user} warned {member} in {interaction.guild.name}. Reason: {reason}")
def format_case(entry):
    return f"• {entry['type'].upper()} by {entry['moderator']}: {entry['reason']}"

async def send_case_list(interaction, user_id: str, case_type: str):
    cases = mod_history.get(user_id, [])
    filtered = [case for case in cases if case["type"] == case_type]
    if not filtered:
        await interaction.followup.send(f"📂 No {case_type} records found.", ephemeral=True)
    else:
        formatted = "\n".join(format_case(entry) for entry in filtered)
        await interaction.followup.send(f"📂 {case_type.upper()} Records:\n{formatted}", ephemeral=True)

@bot.tree.command(name="warnlist", description="View all warnings for a user")
@app_commands.describe(user="User to check")
async def warnlist(interaction: discord.Interaction, user: discord.User):
    await interaction.response.defer(ephemeral=True)
    await send_case_list(interaction, str(user.id), "warn")

@bot.tree.command(name="kicklist", description="View all kicks for a user")
@app_commands.describe(user="User to check")
async def kicklist(interaction: discord.Interaction, user: discord.User):
    await interaction.response.defer(ephemeral=True)
    await send_case_list(interaction, str(user.id), "kick")

@bot.tree.command(name="banlist", description="View all bans for a user")
@app_commands.describe(user="User to check")
async def banlist(interaction: discord.Interaction, user: discord.User):
    await interaction.response.defer(ephemeral=True)
    await send_case_list(interaction, str(user.id), "ban")

@bot.tree.command(name="gbanlist", description="View all global bans for a user")
@app_commands.describe(user="User to check")
async def gbanlist(interaction: discord.Interaction, user: discord.User):
    await interaction.response.defer(ephemeral=True)
    await send_case_list(interaction, str(user.id), "gban")

@bot.tree.command(name="giverole", description="Give a role to a user")
@app_commands.describe(member="Member to give role to", role="Role to give", reason="Reason for giving the role")
async def giverole(interaction: discord.Interaction, member: discord.Member, role: discord.Role, reason: str):
    await interaction.response.defer()
    if not has_role_permission(interaction, "giverole"):
        return await interaction.followup.send("❌ You do not have permission to use this command.", ephemeral=True)

    try:
        await member.add_roles(role, reason=f"{reason} - given by {interaction.user}")
        await interaction.followup.send(f"✅ Role **{role.name}** has been given to {member}. Reason: {reason}")
        log_channel = bot.get_channel(1372296224803258480)
        if log_channel:
            await log_channel.send(f"✅ {interaction.user} gave role **{role.name}** to {member}. Reason: {reason}")
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to give role: {e}", ephemeral=True)

@bot.tree.command(name="takerole", description="Remove a role from a user")
@app_commands.describe(member="Member to remove role from", role="Role to remove", reason="Reason for removing the role")
async def takerole(interaction: discord.Interaction, member: discord.Member, role: discord.Role, reason: str):
    await interaction.response.defer()
    if not has_role_permission(interaction, "takerole"):
        return await interaction.followup.send("❌ You do not have permission to use this command.", ephemeral=True)

    try:
        await member.remove_roles(role, reason=f"{reason} - removed by {interaction.user}")
        await interaction.followup.send(f"❎ Role **{role.name}** has been removed from {member}. Reason: {reason}")
        log_channel = bot.get_channel(1372296224803258480)
        if log_channel:
            await log_channel.send(f"❎ {interaction.user} removed role **{role.name}** from {member}. Reason: {reason}")
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to remove role: {e}", ephemeral=True)

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

@app.route("/")
def home():
    return "Bot is running!", 200

def run():
    app.run(host="0.0.0.0", port=10000)

def keep_alive():
    t = Thread(target=run)
    t.start()

# Start the keep-alive server
keep_alive()

# Start the Discord bot
import os
bot.run(os.getenv("TOKEN"))
