import os
import re
import random
import asyncio
import threading
import requests
import signal
from datetime import datetime, timedelta, timezone
from flask import Flask
from discord.ext import commands
import discord

# === DISCORD BOT SETUP ===
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# === GLOBAL BAN LIST ===
global_ban_list = set()

# === PERMISSIONS AND ROLES ===
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
LINK_PRIVILEGED_ROLES = list(MODERATION_ROLES.keys())

# === CONFIGURATION ===
ALERT_CHANNEL_ID = 1384717083652264056  # Replace with your alert channel ID
STREAMER_CHANNEL_ID = 1207227502003757077
LOG_CHANNEL_ID = 1384882351678689431     # Replace with your log channel ID
STREAMER_ROLE = "Streamer"

# Example: Prior moderation history
mod_history = {
    123456789012345678: [  # User ID
        {"type": "ban", "guild_id": 111111111111111111, "moderator": "Alice", "reason": "Spamming"},
        {"type": "warn", "guild_id": 222222222222222222, "moderator": "Bob", "reason": "Toxic behavior"},
    ]
}

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

    # 🚩 No profile picture
    if member.avatar is None:
        embed.add_field(name="⚠️ No Profile Picture", value="This user has the default avatar.", inline=False)
        embed_needed = True

    # 🕒 Account age check
    account_age = datetime.now(timezone.utc) - member.created_at
    if account_age < timedelta(days=7):
        embed.add_field(name="⚠️ New Account", value=f"Account is only `{account_age.days}` days old.", inline=False)
        embed_needed = True

    # 🧾 Prior mod actions
    if user_id in mod_history:
        embed.title = "🚨 Member with Prior Moderation History Joined"
        embed.color = discord.Color.red()
        for record in mod_history[user_id]:
            guild = bot.get_guild(record["guild_id"])
            server_name = guild.name if guild else f"Guild ID {record['guild_id']}"
            embed.add_field(
                name=f"{record['type'].capitalize()} in {server_name}",
                value=f"Moderator: **{record['moderator']}**\nReason: {record['reason']}",
                inline=False
            )
        embed_needed = True

    # Only send if something triggered
    if embed_needed:
        await alert_channel.send(embed=embed)

# === Link pattern regex (for detecting URLs) ===
link_pattern = re.compile(r"https?://[^\s]+")

# === Data structures for link monitoring ===
user_link_log = {}  # {user_id: [timestamps]}

# --- Event handlers ---

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        await notify_status("up")
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Sync error: {e}")

    # Send startup alert
    await send_startup_alert()

# === Helper functions ===

async def notify_status(status):
    # Placeholder for status notification if needed
    pass

async def log_to_channel(message: str):
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(message)

def has_role_permission(ctx, command_name):
    for role in ctx.author.roles:
        perms = MODERATION_ROLES.get(role.name)
        if perms:
            if "all" in perms or command_name in perms:
                return True
    return False

# --- Startup and Shutdown alerts ---

async def send_startup_alert():
    alert_channel = bot.get_channel(ALERT_CHANNEL_ID)
    if alert_channel:
        embed = discord.Embed(
            title="✅ Alert Notification",
            description="🟢 **Bot is now ONLINE**",
            color=discord.Color.green()
        )
        embed.set_footer(text="Wicked RP Bot • Status Monitor")
        embed.timestamp = discord.utils.utcnow()

        await alert_channel.send(embed=embed)
    print(f"{bot.user.name} is online.")

async def send_shutdown_message():
    alert_channel = bot.get_channel(ALERT_CHANNEL_ID)
    if alert_channel:
        embed = discord.Embed(
            title="❌ Alert Notification",
            description="🔴 **Bot is going OFFLINE**",
            color=discord.Color.red()
        )
        embed.set_footer(text="Wicked RP Bot • Status Monitor")
        embed.timestamp = discord.utils.utcnow()

        await alert_channel.send(embed=embed)

def setup_shutdown_handler(loop):
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig,
            lambda: asyncio.ensure_future(shutdown(sig))
        )

async def shutdown(sig):
    print(f"Received exit signal {sig.name}...")
    await send_shutdown_message()
    await bot.close()

# Helper for styled reply
async def styled_reply(ctx, message: str, color=discord.Color.blurple()):
    embed = discord.Embed(description=message, color=color)
    sent_message = await ctx.send(embed=embed)
    # Delete the bot's reply after 2 minutes
    await asyncio.sleep(120)
    try:
        await sent_message.delete()
    except:
        pass

# === Event handler for message content ===
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # === Racial slur filter ===
    slurs = ["spick", "nigger", "retarded"]
    content = message.content.lower()
    if any(slur in content for slur in slurs):
        await message.delete()
        await log_to_channel(f"🚫 Message from {message.author} deleted for slur usage in #{message.channel}: {message.content}")
        try:
            await message.channel.send(f"🚫 {message.author.mention}, your message was removed for violating server rules.")
            await message.author.send("⚠️ You have been warned for using inappropriate language.")
        except discord.Forbidden:
            pass
        return

    # --- Link moderation ---
    links = link_pattern.findall(message.content)
    if links:
        # Check for privilege roles
        has_privilege = any(role.name in LINK_PRIVILEGED_ROLES for role in message.author.roles)
        is_streamer = any(role.name == STREAMER_ROLE for role in message.author.roles)

        # Track recent link timestamps
        now = datetime.utcnow()
        uid = message.author.id
        user_link_log.setdefault(uid, [])
        # Remove timestamps older than 3 minutes
        user_link_log[uid] = [ts for ts in user_link_log[uid] if now - ts < timedelta(minutes=3)]
        # Add current timestamps
        user_link_log[uid].extend([now] * len(links))

        # Alert if user sent more than 3 links in 3 minutes
        if len(user_link_log[uid]) > 3:
            alert_channel = bot.get_channel(ALERT_CHANNEL_ID)
            if alert_channel:
                await alert_channel.send(f"🚨 {message.author.mention} has sent more than 3 links in 3 minutes.")

        for link in links:
            # Check for invite links
            if "discord.gg" in link or "discord.com/invite" in link:
                invite_code = None
                if "discord.gg" in link:
                    invite_code = link.split("discord.gg/")[-1]
                elif "discord.com/invite" in link:
                    invite_code = link.split("/invite/")[-1]
                if invite_code:
                    try:
                        invite = await bot.fetch_invite(invite_code)
                        # If invite is valid and guild is in server list, skip deletion
                        if invite.guild and invite.guild.id in [g.id for g in bot.guilds]:
                            continue
                    except:
                        pass
                # Delete invite links
                await message.delete()
                log_msg = f"🚫 Invite link deleted from {message.author} in #{message.channel}: {message.content}"
                await log_to_channel(log_msg)
                await message.channel.send(f"🚫 {message.author.mention}, Discord invites are not allowed.")
                return

            # Allow specific domains
            if any(domain in link for domain in ["tenor.com", "giphy.com"]):
                continue

            # Allow stream links in stream channel
            if (
                message.channel.id == STREAMER_CHANNEL_ID and
                is_streamer and
                any(domain in link for domain in ["twitch.tv", "youtube.com", "kick.com", "tiktok"])
            ):
                continue

            # Delete unauthorized links
            if not has_privilege:
                await message.delete()
                log_msg = f"🚫 Unauthorized link from {message.author} in #{message.channel}: {message.content}"
                await log_to_channel(log_msg)
                await message.channel.send(f"🚫 {message.author.mention}, you are not allowed to post this link.")
                return

    await bot.process_commands(message)

# Command to log command usage
@bot.event
async def on_command(ctx):
    await log_to_channel(f"📌 Command used: `{ctx.command}` by {ctx.author} in #{ctx.channel}")

# === STARTUP AND SHUTDOWN ALERTS ===

# Run the Flask app for keep-alive
app = Flask(__name__)

@app.route('/')
def index():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

# Run Flask in separate thread
threading.Thread(target=run_flask).start()

# --- Signal handling for graceful shutdown ---
def start_signal_handlers():
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig,
            lambda s=sig: asyncio.ensure_future(shutdown(s))
        )

async def shutdown(sig):
    print(f"Received exit signal {sig.name}...")
    await send_shutdown_message()
    await bot.close()

# Load moderation history from file or initialize empty
MOD_HISTORY_FILE = "mod_history.json"
if os.path.exists(MOD_HISTORY_FILE):
    with open(MOD_HISTORY_FILE, 'r') as f:
        mod_history = json.load(f)
else:
    mod_history = {}

def save_mod_history():
    with open(MOD_HISTORY_FILE, 'w') as f:
        json.dump(mod_history, f, indent=4)

# Your existing kick command
@bot.command()
async def kick(ctx, user: discord.User):
    if not has_role_permission(ctx, "kick"):
        return await styled_reply(ctx, "❌ You do not have permission to use this command.", discord.Color.red())
    member = ctx.guild.get_member(user.id)
    if member:
        await member.kick()
        # Add to kick list
        kick_list.add(user.id)
        # Log to history
        user_id_str = str(user.id)
        if user_id_str not in mod_history:
            mod_history[user_id_str] = []
        mod_history[user_id_str].append({
            "type": "kick",
            "guild_id": ctx.guild.id,
            "moderator": ctx.author.name,
            "reason": "N/A"  # You can extend this to accept reason if needed
        })
        save_mod_history()
        await styled_reply(ctx, f"👢 {member} has been kicked.")
        await log_to_channel(f"👢 {ctx.author} kicked {member} in {ctx.guild.name}")
    else:
        await styled_reply(ctx, "❌ User not found in this server.", discord.Color.red())

@bot.command()
async def warn(ctx, user: discord.User, *, reason=None):
    # Your warning logic...
    warn_list.add(user.id)
    # Log to history
    user_id_str = str(user.id)
    if user_id_str not in mod_history:
        mod_history[user_id_str] = []
    mod_history[user_id_str].append({
        "type": "warn",
        "guild_id": ctx.guild.id,
        "moderator": ctx.author.name,
        "reason": reason or "No reason provided"
    })
    save_mod_history()
    await styled_reply(ctx, f"⚠️ {user} has been warned.")
    await log_to_channel(f"⚠️ {ctx.author} warned {user}. Reason: {reason}")

@bot.command()
async def ban(ctx, member: discord.Member, *, reason=None):
    await member.ban(reason=reason)
    # Add to ban list
    ban_list.add(member.id)
    # Log to history
    user_id_str = str(member.id)
    if user_id_str not in mod_history:
        mod_history[user_id_str] = []
    mod_history[user_id_str].append({
        "type": "ban",
        "guild_id": ctx.guild.id,
        "moderator": ctx.author.name,
        "reason": reason or "No reason provided"
    })
    save_mod_history()
    await styled_reply(ctx, f'🔨 {member} has been banned.')
    await log_to_channel(f"🔨 {ctx.author} banned {member} in {ctx.guild.name}. Reason: {reason}")

@bot.command()
async def unban(ctx, *, user):
    banned_users = [entry async for entry in ctx.guild.bans()]
    if user.isdigit():
        user_id = int(user)
        for ban_entry in banned_users:
            if ban_entry.user.id == user_id:
                await ctx.guild.unban(ban_entry.user)
                await styled_reply(ctx, f"✅ Unbanned {ban_entry.user}")
                await log_to_channel(f"♻️ {ctx.author} unbanned {ban_entry.user} in {ctx.guild.name}")
                return
        return await styled_reply(ctx, "❌ User ID not found in ban list.", discord.Color.red())
    if '#' in user:
        try:
            name, discriminator = user.split('#')
        except ValueError:
            return await styled_reply(ctx, "❌ Invalid format. Use Username#1234 or user ID.", discord.Color.red())
        for ban_entry in banned_users:
            if ban_entry.user.name == name and ban_entry.user.discriminator == discriminator:
                await ctx.guild.unban(ban_entry.user)
                await styled_reply(ctx, f"✅ Unbanned {ban_entry.user}")
                await log_to_channel(f"♻️ {ctx.author} unbanned {ban_entry.user} in {ctx.guild.name}")
                return
        return await styled_reply(ctx, "❌ User not found in ban list.", discord.Color.red())
    return await styled_reply(ctx, "❌ Invalid format. Use Username#1234 or user ID.", discord.Color.red())

@bot.command()
async def mute(ctx, member: discord.Member):
    if not has_role_permission(ctx, "mute"):
        return await styled_reply(ctx, "❌ You do not have permission to use this command.", discord.Color.red())
    overwrite = discord.PermissionOverwrite(send_messages=False)
    for channel in ctx.guild.text_channels:
        await channel.set_permissions(member, overwrite=overwrite)
    await styled_reply(ctx, f'🔇 {member} has been muted in text channels.')
    await log_to_channel(f"🔇 {ctx.author} muted {member} in text channels on {ctx.guild.name}")

@bot.command()
async def voicemute(ctx, member: discord.Member):
    if not has_role_permission(ctx, "voicemute"):
        return await styled_reply(ctx, "❌ You do not have permission to use this command.", discord.Color.red())
    await member.edit(mute=True)
    await styled_reply(ctx, f'🔇 {member} has been voice-muted.')
    await log_to_channel(f"🔈 {ctx.author} voice-muted {member} in {ctx.guild.name}")

@bot.command()
async def gban(ctx, user: discord.User, *, reason=None):
    if not has_role_permission(ctx, "ban"):
        return await styled_reply(ctx, "❌ You do not have permission to use this command.", discord.Color.red())
    global gban_list
    if user.id in gban_list:
        return await styled_reply(ctx, f"⚠️ {user} is already globally banned.")
    gban_list.add(user.id)
    for guild in bot.guilds:
        member = guild.get_member(user.id)
        if member:
            try:
                await guild.ban(member, reason=f"Global Ban: {reason}")
            except discord.Forbidden:
                await styled_reply(ctx, f"❌ Failed to ban {user} in {guild.name} due to permissions.")
    await styled_reply(ctx, f'🌐 {user} has been globally banned from all servers.')
    await log_to_channel(f"🌐 {ctx.author} globally banned {user}. Reason: {reason}")

@bot.command()
async def gban(ctx, user: discord.User, *, reason=None):
    # your existing gban code...
    global gban_list
    if user.id in gban_list:
        return await styled_reply(ctx, f"⚠️ {user} is already globally banned.")
    gban_list.add(user.id)
    # Log to history
    user_id_str = str(user.id)
    if user_id_str not in mod_history:
        mod_history[user_id_str] = []
    mod_history[user_id_str].append({
        "type": "gban",
        "guild_id": "global",
        "moderator": ctx.author.name,
        "reason": reason or "No reason provided"
    })
    save_mod_history()
    # Continue with your existing gban logic...
    for guild in bot.guilds:
        member = guild.get_member(user.id)
        if member:
            try:
                await guild.ban(member, reason=f"Global Ban: {reason}")
            except discord.Forbidden:
                await styled_reply(ctx, f"❌ Failed to ban {user} in {guild.name} due to permissions.")
    await styled_reply(ctx, f'🌐 {user} has been globally banned from all servers.')
    await log_to_channel(f"🌐 {ctx.author} globally banned {user}. Reason: {reason}")

@bot.command()
async def giverole(ctx, member: discord.Member, role_id: int):
    if not has_role_permission(ctx, "giverole"):
        return await styled_reply(ctx, "❌ You do not have permission to use this command.", discord.Color.red())

    role = ctx.guild.get_role(role_id)
    if not role:
        return await styled_reply(ctx, "❌ Invalid role ID provided.", discord.Color.red())

    try:
        await member.add_roles(role, reason=f"Given by {ctx.author}")
        await styled_reply(ctx, f'🎖️ Gave `{role.name}` to {member.mention}')
        await log_to_channel(f"🎖️ {ctx.author} gave role `{role.name}` (ID: {role.id}) to {member.mention} in {ctx.guild.name}")
    except discord.Forbidden:
        await styled_reply(ctx, "❌ I do not have permission to give that role.", discord.Color.red())
    except Exception as e:
        await styled_reply(ctx, f"⚠️ Error: {str(e)}", discord.Color.red())

@bot.command()
async def takerole(ctx, member: discord.Member, role_id: int):
    if not has_role_permission(ctx, "giverole"):
        return await styled_reply(ctx, "❌ You do not have permission to use this command.", discord.Color.red())

    role = ctx.guild.get_role(role_id)
    if not role:
        return await styled_reply(ctx, "❌ Invalid role ID provided.", discord.Color.red())

    try:
        await member.remove_roles(role, reason=f"Removed by {ctx.author}")
        await styled_reply(ctx, f'🧼 Removed `{role.name}` from {member.mention}')
        await log_to_channel(f"🧼 {ctx.author} removed role `{role.name}` (ID: {role.id}) from {member.mention} in {ctx.guild.name}")
    except discord.Forbidden:
        await styled_reply(ctx, "❌ I do not have permission to remove that role.", discord.Color.red())
    except Exception as e:
        await styled_reply(ctx, f"⚠️ Error: {str(e)}", discord.Color.red())

@bot.command()
async def giveaway(ctx, duration: int, *, prize: str):
    await styled_reply(ctx, f'🎉 **GIVEAWAY** 🎉\nPrize: **{prize}**\nReact with 🎉 to enter!\nTime: {duration} seconds')
    message = await ctx.send("React below 👇")
    await message.add_reaction("🎉")
    await asyncio.sleep(duration)
    message = await ctx.channel.fetch_message(message.id)
    users = await message.reactions[0].users().flatten()
    users = [u for u in users if not u.bot]
    if users:
        winner = random.choice(users)
        await styled_reply(ctx, f'🎊 Congrats {winner.mention}, you won **{prize}**!')
        await log_to_channel(f"🎁 {ctx.author} hosted a giveaway. Winner: {winner}. Prize: {prize}")
    else:
        await styled_reply(ctx, "No one entered the giveaway. 😢")
        await log_to_channel(f"🎁 {ctx.author} hosted a giveaway but no entries were received. Prize: {prize}")
@bot.command()
async def banlist(ctx):
    user_id_str = str(ctx.author.id)
    if user_id_str not in mod_history:
        return await styled_reply(ctx, "You have no moderation history.", discord.Color.orange())

    # Filter ban actions performed by the user
    user_bans = [
        entry for entry in mod_history.get(user_id_str, [])
        if entry['type'] == 'ban'
    ]

    if not user_bans:
        return await styled_reply(ctx, "You have no ban actions in your history.", discord.Color.orange())

    # Build the message
    message_lines = []
    for entry in user_bans:
        guild_name = "Unknown Guild"
        guild = bot.get_guild(entry['guild_id'])
        if guild:
            guild_name = guild.name
        message_lines.append(
            f"Guild: {guild_name} | Moderator: {entry['moderator']} | Reason: {entry['reason']}"
        )

    message = "\n".join(message_lines)
    # Send as DM to the user
    try:
        await ctx.author.send(f"Your ban history:\n{message}")
        await styled_reply(ctx, "Sent your ban history via DM.", discord.Color.green())
    except:
        # fallback if DM fails
        await styled_reply(ctx, "Could not send DM. Here's your ban history:\n" + message, discord.Color.green())

# Similarly for kicklist
@bot.command()
async def kicklist(ctx):
    user_id_str = str(ctx.author.id)
    if user_id_str not in mod_history:
        return await styled_reply(ctx, "You have no moderation history.", discord.Color.orange())

    user_kicks = [
        entry for entry in mod_history.get(user_id_str, [])
        if entry['type'] == 'kick'
    ]

    if not user_kicks:
        return await styled_reply(ctx, "You have no kick actions in your history.", discord.Color.orange())

    message_lines = []
    for entry in user_kicks:
        guild_name = "Unknown Guild"
        guild = bot.get_guild(entry['guild_id'])
        if guild:
            guild_name = guild.name
        message_lines.append(
            f"Guild: {guild_name} | Moderator: {entry['moderator']} | Reason: {entry['reason']}"
        )

    message = "\n".join(message_lines)
    try:
        await ctx.author.send(f"Your kick history:\n{message}")
        await styled_reply(ctx, "Sent your kick history via DM.", discord.Color.green())
    except:
        await styled_reply(ctx, "Could not send DM. Here's your kick history:\n" + message, discord.Color.green())

# Similarly for warnlist
@bot.command()
async def warnlist(ctx):
    user_id_str = str(ctx.author.id)
    if user_id_str not in mod_history:
        return await styled_reply(ctx, "You have no moderation history.", discord.Color.orange())

    user_warns = [
        entry for entry in mod_history.get(user_id_str, [])
        if entry['type'] == 'warn'
    ]

    if not user_warns:
        return await styled_reply(ctx, "You have no warnings in your history.", discord.Color.orange())

    message_lines = []
    for entry in user_warns:
        guild_name = "Unknown Guild"
        guild = bot.get_guild(entry['guild_id'])
        if guild:
            guild_name = guild.name
        message_lines.append(
            f"Guild: {guild_name} | Moderator: {entry['moderator']} | Reason: {entry['reason']}"
        )

    message = "\n".join(message_lines)
    try:
        await ctx.author.send(f"Your warning history:\n{message}")
        await styled_reply(ctx, "Sent your warning history via DM.", discord.Color.green())
    except:
        await styled_reply(ctx, "Could not send DM. Here's your warning history:\n" + message, discord.Color.green())

# And for gbanlist
@bot.command()
async def gbanlist(ctx):
    user_id_str = str(ctx.author.id)
    if user_id_str not in mod_history:
        return await styled_reply(ctx, "You have no moderation history.", discord.Color.orange())

    user_gbans = [
        entry for entry in mod_history.get(user_id_str, [])
        if entry['type'] == 'gban'
    ]

    if not user_gbans:
        return await styled_reply(ctx, "You have no global bans in your history.", discord.Color.orange())

    message_lines = []
    for entry in user_gbans:
        guild_name = entry['guild_id']
        if guild_name == "global":
            guild_name = "Global"
        else:
            guild = bot.get_guild(entry['guild_id'])
            if guild:
                guild_name = guild.name
        message_lines.append(
            f"Guild: {guild_name} | Moderator: {entry['moderator']} | Reason: {entry['reason']}"
        )

    message = "\n".join(message_lines)
    try:
        await ctx.author.send(f"Your global ban history:\n{message}")
        await styled_reply(ctx, "Sent your global ban history via DM.", discord.Color.green())
    except:
        await styled_reply(ctx, "Could not send DM. Here's your global ban history:\n" + message, discord.Color.green())

# --- Run the bot ---

bot.run(os.getenv("DISCORD_BOT_TOKEN"))
