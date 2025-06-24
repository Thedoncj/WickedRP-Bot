import os
import re
import asyncio
import threading
from flask import Flask
from discord.ext import commands
import discord
from discord import app_commands

# === INTENTS & BOT ===
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# === CONFIG ===
LOG_CHANNEL_ID = 1384882351678689431
WARN_CHANNEL_ID = 1384717083652264056

MODERATION_ROLES = {
    "Trial Moderator": ["kick", "mute"],
    "Moderator": ["kick", "mute"],
    "Head Moderator": ["kick", "mute"],
    "Trial Administrator": ["kick", "mute"],
    "Administrator": ["kick", "ban", "mute", "giverole"],
    "Head Administrator": ["kick", "ban", "gban", "mute", "giverole"],
    "Head Of Staff": ["all"],
    "Trial Manager": ["all"],
    "Management": ["all"],
    "Head of Management": ["all"],
    "Co Director": ["all"],
    "Director": ["all"]
}

PRIVILEGED_ROLES = ["Head Of Staff", "Trial Manager", "Management", "Head of Management", "Co Director", "Director"]
STREAMER_ROLE = "Streamer"
STREAMER_CHANNEL_ID = 1207227502003757077
ALLOWED_STREAMER_DOMAINS = ["twitch.tv", "youtube.com", "kick.com", "tiktok"]

# === UTILS ===
def has_permission(member: discord.Member, command_name: str):
    for role in member.roles:
        perms = MODERATION_ROLES.get(role.name)
        if perms:
            if perms == ["all"] or command_name in perms:
                return True
    return False

async def log_to_channel(bot, content):
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(content)

# === EVENTS ===
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    slurs = ["spick", "nigger", "retarded"]
    content = message.content.lower()
    if any(slur in content for slur in slurs):
        await message.delete()
        await log_to_channel(bot, f"🚫 Deleted slur message from {message.author} in #{message.channel}: `{message.content}`")
        try:
            await message.channel.send(f"🚫 {message.author.mention}, your message was removed for violating server rules.")
        except discord.Forbidden:
            pass
        try:
            await message.author.send("⚠️ You have been warned for using inappropriate language. Continued violations may lead to further actions.")
        except discord.Forbidden:
            pass
        return

    link_pattern = re.compile(r"https?://[^\s]+")
    links = link_pattern.findall(message.content)

    if links:
        has_privilege = any(role.name in PRIVILEGED_ROLES for role in message.author.roles)
        is_streamer = any(role.name == STREAMER_ROLE for role in message.author.roles)

        for link in links:
            if "discord.gg" in link or "discord.com/invite" in link:
                await message.delete()
                await message.channel.send(f"🚫 {message.author.mention}, Discord invites are not allowed.")
                await log_to_channel(bot, f"🚫 Deleted Discord invite from {message.author} in #{message.channel}: `{link}`")
                return

            if any(domain in link for domain in ["tenor.com", "giphy.com"]):
                continue

            if (
                message.channel.id == STREAMER_CHANNEL_ID and
                is_streamer and
                any(domain in link for domain in ALLOWED_STREAMER_DOMAINS)
            ):
                continue

            if not has_privilege:
                await message.delete()
                await message.channel.send(f"🚫 {message.author.mention}, you are not allowed to post this kind of link.")
                await log_to_channel(bot, f"🚫 Deleted unauthorized link from {message.author} in #{message.channel}: `{link}`")
                return

    await bot.process_commands(message)

# === MODERATION SLASH COMMANDS ===

def is_higher(member1: discord.Member, member2: discord.Member) -> bool:
    return member1.top_role > member2.top_role

async def fail(interaction, message: str):
    await interaction.followup.send(f"❌ {message}", ephemeral=True)

@bot.tree.command(name="kick", description="Kick a member")
@app_commands.describe(user="User to kick", reason="Reason for kicking")
async def kick(interaction: discord.Interaction, user: discord.Member, reason: str):
    await interaction.response.defer()
    if not has_permission(interaction.user, "kick"):
        return await interaction.followup.send("❌ You lack permission.", ephemeral=True)
    if not is_above(interaction.user, user):
        return await interaction.followup.send("❌ You must have a higher role than the target.", ephemeral=True)

    try:
        await user.kick(reason=reason)
        await interaction.followup.send(f"👢 {user.mention} was kicked. Reason: {reason}")
        await log_to_channel(bot, f"👢 {interaction.user} kicked {user} | Reason: {reason}")
    except Exception as e:
        await interaction.followup.send("❌ Kick failed.")
        await log_to_channel(bot, f"⚠️ Kick failed: {interaction.user} tried to kick {user} | {e}")

@bot.tree.command(name="ban", description="Ban a member")
@app_commands.describe(user="User to ban", reason="Reason for the ban")
async def ban(interaction: discord.Interaction, user: discord.User, reason: str):
    await interaction.response.defer()
    if not has_permission(interaction.user, "ban"):
        return await interaction.followup.send("❌ You lack permission.", ephemeral=True)

    member = interaction.guild.get_member(user.id)
    if member and not is_above(interaction.user, member):
        return await interaction.followup.send("❌ You must have a higher role than the target.", ephemeral=True)

    try:
        await interaction.guild.ban(user, reason=reason)
        await interaction.followup.send(f"🔨 {user.mention} was banned. Reason: {reason}")
        await log_to_channel(bot, f"🔨 {interaction.user} banned {user} | Reason: {reason}")
    except Exception as e:
        await interaction.followup.send("❌ Ban failed.")
        await log_to_channel(bot, f"⚠️ Ban failed: {interaction.user} tried to ban {user} | {e}")

@bot.tree.command(name="gban", description="Globally ban a user")
@app_commands.describe(user="User to globally ban", reason="Reason for global ban")
async def gban(interaction: discord.Interaction, user: discord.User, reason: str):
    await interaction.response.defer()
    if not has_permission(interaction.user, "gban"):
        return await interaction.followup.send("❌ You lack permission.", ephemeral=True)

    success_guilds = []
    fail_guilds = []

    for guild in bot.guilds:
        try:
            await guild.ban(user, reason=f"Global Ban: {reason}")
            success_guilds.append(guild.name)
        except:
            fail_guilds.append(guild.name)

    await interaction.followup.send(f"🌐 {user.mention} globally banned.\n✅ Success: {len(success_guilds)} | ❌ Failed: {len(fail_guilds)}")
    await log_to_channel(bot, f"🌐 {interaction.user} globally banned {user} | Reason: {reason}")

@bot.tree.command(name="warn", description="Warn a member")
@app_commands.describe(user="User to warn", reason="Reason for warning")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str):
    await interaction.response.defer()
    if not has_permission(interaction.user, "warn"):
        return await interaction.followup.send("❌ You lack permission.", ephemeral=True)
    if not is_above(interaction.user, user):
        return await interaction.followup.send("❌ You must have a higher role than the target.", ephemeral=True)

    await interaction.followup.send(f"⚠️ {user.mention} has been warned. Reason: {reason}")
    await log_to_channel(bot, f"⚠️ {interaction.user} warned {user} | Reason: {reason}")

@bot.tree.command(name="giverole", description="Give a role to a user")
@app_commands.describe(user="User to give role", role="Role to give", reason="Reason for giving role")
async def giverole(interaction: discord.Interaction, user: discord.Member, role: discord.Role, reason: str):
    await interaction.response.defer()
    if not has_permission(interaction.user, "giverole"):
        return await interaction.followup.send("❌ You lack permission.", ephemeral=True)
    if not is_above(interaction.user, user):
        return await interaction.followup.send("❌ You must have a higher role than the target.", ephemeral=True)

    try:
        await user.add_roles(role, reason=reason)
        await interaction.followup.send(f"✅ {role.name} given to {user.mention}.")
        await log_to_channel(bot, f"✅ {interaction.user} gave {role.name} to {user} | Reason: {reason}")
    except Exception as e:
        await interaction.followup.send("❌ Failed to assign role.")
        await log_to_channel(bot, f"⚠️ Failed to give {role.name} to {user} | {e}")

@bot.tree.command(name="takerole", description="Remove a role from a user")
@app_commands.describe(user="User to remove role from", role="Role to remove", reason="Reason")
async def takerole(interaction: discord.Interaction, user: discord.Member, role: discord.Role, reason: str):
    await interaction.response.defer()
    if not has_permission(interaction.user, "giverole"):
        return await interaction.followup.send("❌ You lack permission.", ephemeral=True)
    if not is_above(interaction.user, user):
        return await interaction.followup.send("❌ You must have a higher role than the target.", ephemeral=True)

    try:
        await user.remove_roles(role, reason=reason)
        await interaction.followup.send(f"🗑️ {role.name} removed from {user.mention}.")
        await log_to_channel(bot, f"🗑️ {interaction.user} removed {role.name} from {user} | Reason: {reason}")
    except Exception as e:
        await interaction.followup.send("❌ Failed to remove role.")
        await log_to_channel(bot, f"⚠️ Failed to remove {role.name} from {user} | {e}")

@bot.tree.command(name="textmute", description="Mute a user in text channels")
@app_commands.describe(user="User to mute", reason="Reason")
async def textmute(interaction: discord.Interaction, user: discord.Member, reason: str):
    await interaction.response.defer()
    if not has_permission(interaction.user, "mute"):
        return await interaction.followup.send("❌ You lack permission.", ephemeral=True)
    if not is_above(interaction.user, user):
        return await interaction.followup.send("❌ You must have a higher role than the target.", ephemeral=True)

    mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
    if not mute_role:
        return await interaction.followup.send("❌ 'Muted' role not found.", ephemeral=True)

    try:
        await user.add_roles(mute_role, reason=reason)
        await interaction.followup.send(f"🔇 {user.mention} was muted.")
        await log_to_channel(bot, f"🔇 {interaction.user} muted {user} | Reason: {reason}")
    except Exception as e:
        await interaction.followup.send("❌ Mute failed.")
        await log_to_channel(bot, f"⚠️ Failed to mute {user} | {e}")

@bot.tree.command(name="textunmute", description="Unmute a user in text channels")
@app_commands.describe(user="User to unmute", reason="Reason")
async def textunmute(interaction: discord.Interaction, user: discord.Member, reason: str):
    await interaction.response.defer()
    if not has_permission(interaction.user, "mute"):
        return await interaction.followup.send("❌ You lack permission.", ephemeral=True)
    if not is_above(interaction.user, user):
        return await interaction.followup.send("❌ You must have a higher role than the target.", ephemeral=True)

    mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
    if not mute_role:
        return await interaction.followup.send("❌ 'Muted' role not found.", ephemeral=True)

    try:
        await user.remove_roles(mute_role, reason=reason)
        await interaction.followup.send(f"🔊 {user.mention} was unmuted.")
        await log_to_channel(bot, f"🔊 {interaction.user} unmuted {user} | Reason: {reason}")
    except Exception as e:
        await interaction.followup.send("❌ Unmute failed.")
        await log_to_channel(bot, f"⚠️ Failed to unmute {user} | {e}")

# === KEEPALIVE ===
app = Flask(__name__)
@app.route('/')
def home():
    return "Bot is running!", 200
threading.Thread(target=lambda: app.run(host="0.0.0.0", port=8080)).start()

# === RUN ===
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
