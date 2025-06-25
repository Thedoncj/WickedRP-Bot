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
    "Trial Moderator": ["kick", "textmute", "warn"],
    "Moderator": ["kick", "textmute", "warn"],
    "Head Moderator": ["kick", "textmute", "warn"],
    "Trial Administrator": ["kick", "textmute", "giverole", "takerole", "warn"],
    "Administrator": ["kick", "ban", "unban", "textmute", "giverole", "takerole", "warn"],
    "Head Administrator": ["kick", "ban", "unban", "textmute", "gban", "giverole", "takerole", "warn"],
    "Head Of Staff": ["all"],
    "Trial Manager": ["all"],
    "Management": ["all"],
    "Head Of Management": ["all"],
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

@bot.event
async def on_guild_role_update(before: discord.Role, after: discord.Role):
    warn_channel = bot.get_channel(WARN_CHANNEL_ID)
    if not warn_channel:
        return

    # Wait for audit log to update
    await asyncio.sleep(1)  # Wait 1 second to let audit logs catch up

    # Find the most recent audit log for this role
    entry = None
    async for log in before.guild.audit_logs(limit=5, action=discord.AuditLogAction.role_update):
        if log.target.id == before.id:
            entry = log
            break

    executor = entry.user if entry else None
    timestamp = entry.created_at if entry else discord.utils.utcnow()

    embed = discord.Embed(
        title="🔧 Role Updated",
        description=f"**Role:** {after.mention} (`{after.name}`)",
        color=discord.Color.orange(),
        timestamp=timestamp
    )

    if before.name != after.name:
        embed.add_field(name="Name Change", value=f"`{before.name}` → `{after.name}`", inline=False)
    if before.position != after.position:
        embed.add_field(name="Position Change", value=f"{before.position} → {after.position}", inline=False)
    if before.permissions != after.permissions:
        embed.add_field(name="Permissions Change", value="Permission set updated.", inline=False)

    if executor:
        embed.set_author(name=f"Changed by {executor} ({executor.id})", icon_url=executor.display_avatar.url)
    else:
        embed.set_author(name="Changed by Unknown")

    embed.set_footer(text=f"Role ID: {after.id}")
    await warn_channel.send(embed=embed)
    
# Check if invoker has permission and is above target
from main import has_permission, log_to_channel, bot

def can_act(invoker: discord.Member, target: discord.Member, command: str):
    return has_permission(invoker, command) and invoker.top_role > target.top_role

@bot.tree.command(name="kick", description="Kick a member")
@app_commands.describe(user="User to kick", reason="Reason for the kick")
async def kick(interaction: discord.Interaction, user: discord.Member, reason: str):
    await interaction.response.defer()
    if not can_act(interaction.user, user, "kick"):
        return await interaction.followup.send("❌ You lack permission or your role is not high enough.", ephemeral=True)
    try:
        await user.kick(reason=reason)
        await interaction.followup.send(f"👢 {user.mention} was kicked. Reason: {reason}")
        await log_to_channel(bot, f"👢 {interaction.user} kicked {user} | Reason: {reason}")
    except Exception as e:
        await interaction.followup.send("❌ Failed to kick user.", ephemeral=True)
        await log_to_channel(bot, f"❌ {interaction.user} failed to kick {user}: {e}")

@bot.tree.command(name="ban", description="Ban a member")
@app_commands.describe(user="User to ban", reason="Reason for the ban")
async def ban(interaction: discord.Interaction, user: discord.Member, reason: str):
    await interaction.response.defer()
    if not can_act(interaction.user, user, "ban"):
        return await interaction.followup.send("❌ You lack permission or your role is not high enough.", ephemeral=True)
    try:
        await user.ban(reason=reason)
        await interaction.followup.send(f"🔨 {user.mention} was banned. Reason: {reason}")
        await log_to_channel(bot, f"🔨 {interaction.user} banned {user} | Reason: {reason}")
    except Exception as e:
        await interaction.followup.send("❌ Failed to ban user.", ephemeral=True)
        await log_to_channel(bot, f"❌ {interaction.user} failed to ban {user}: {e}")

@bot.tree.command(name="gban", description="Globally ban a user from all servers")
@app_commands.describe(user="User to globally ban", reason="Reason for global ban")
async def gban(interaction: discord.Interaction, user: discord.User, reason: str):
    await interaction.response.defer()
    if not has_permission(interaction.user, "gban"):
        return await interaction.followup.send("❌ You lack permission.", ephemeral=True)
    failed = []
    for guild in bot.guilds:
        member = guild.get_member(user.id)
        if member:
            if not can_act(interaction.user, member, "gban"):
                failed.append(guild.name)
                continue
            try:
                await guild.ban(member, reason=f"Global Ban: {reason}")
            except:
                failed.append(guild.name)
    await interaction.followup.send(f"🌐 {user.mention} globally banned. Failed in: {', '.join(failed) if failed else 'None'}")
    await log_to_channel(bot, f"🌐 {interaction.user} globally banned {user} | Reason: {reason} | Failed in: {failed}")

@bot.tree.command(name="warn", description="Warn a member")
@app_commands.describe(user="User to warn", reason="Reason for warning")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str):
    await interaction.response.defer()
    if not can_act(interaction.user, user, "warn"):
        return await interaction.followup.send("❌ You lack permission or your role is not high enough.", ephemeral=True)
    await interaction.followup.send(f"⚠️ {user.mention} warned. Reason: {reason}")
    await log_to_channel(bot, f"⚠️ {interaction.user} warned {user} | Reason: {reason}")

@bot.tree.command(name="giverole", description="Give a role to a member")
@app_commands.describe(user="User to give role to", role="Role to assign", reason="Reason for giving role")
async def giverole(interaction: discord.Interaction, user: discord.Member, role: discord.Role, reason: str):
    await interaction.response.defer()
    if not can_act(interaction.user, user, "giverole"):
        return await interaction.followup.send("❌ You lack permission or your role is not high enough.", ephemeral=True)
    await user.add_roles(role, reason=reason)
    await interaction.followup.send(f"✅ Gave {role.name} to {user.mention}. Reason: {reason}")
    await log_to_channel(bot, f"✅ {interaction.user} gave {role.name} to {user} | Reason: {reason}")

@bot.tree.command(name="takerole", description="Remove a role from a member")
@app_commands.describe(user="User to remove role from", role="Role to remove", reason="Reason for removing role")
async def takerole(interaction: discord.Interaction, user: discord.Member, role: discord.Role, reason: str):
    await interaction.response.defer()
    if not can_act(interaction.user, user, "takerole"):
        return await interaction.followup.send("❌ You lack permission or your role is not high enough.", ephemeral=True)
    await user.remove_roles(role, reason=reason)
    await interaction.followup.send(f"🗑️ Removed {role.name} from {user.mention}. Reason: {reason}")
    await log_to_channel(bot, f"🗑️ {interaction.user} removed {role.name} from {user} | Reason: {reason}")

@bot.tree.command(name="textmute", description="Mute a user in text channels temporarily")
@app_commands.describe(user="User to mute", duration="Duration in minutes", reason="Reason for muting")
async def textmute(interaction: discord.Interaction, user: discord.Member, duration: int, reason: str):
    await interaction.response.defer()
    if not can_act(interaction.user, user, "textmute"):
        return await interaction.followup.send("❌ You lack permission or your role is not high enough.", ephemeral=True)
    mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
    if not mute_role:
        return await interaction.followup.send("❌ 'Muted' role not found.", ephemeral=True)
    await user.add_roles(mute_role, reason=reason)
    await interaction.followup.send(f"🔇 {user.mention} muted for {duration} minutes. Reason: {reason}")
    await log_to_channel(bot, f"🔇 {interaction.user} muted {user} for {duration} minutes | Reason: {reason}")

    await asyncio.sleep(duration * 60)
    await user.remove_roles(mute_role, reason="Mute duration expired")
    await log_to_channel(bot, f"🔊 {user.mention} was automatically unmuted after {duration} minutes.")

@bot.tree.command(name="textunmute", description="Unmute a user in text channels")
@app_commands.describe(user="User to unmute", reason="Reason for unmuting")
async def textunmute(interaction: discord.Interaction, user: discord.Member, reason: str):
    await interaction.response.defer()
    if not can_act(interaction.user, user, "textmute"):
        return await interaction.followup.send("❌ You lack permission or your role is not high enough.", ephemeral=True)
    mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
    if not mute_role:
        return await interaction.followup.send("❌ 'Muted' role not found.", ephemeral=True)
    await user.remove_roles(mute_role, reason=reason)
    await interaction.followup.send(f"🔊 {user.mention} was unmuted. Reason: {reason}")
    await log_to_channel(bot, f"🔊 {interaction.user} unmuted {user} | Reason: {reason}")

# === KEEPALIVE ===
app = Flask(__name__)
@app.route('/')
def home():
    return "Bot is running!", 200
threading.Thread(target=lambda: app.run(host="0.0.0.0", port=8080)).start()

# === RUN ===
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
