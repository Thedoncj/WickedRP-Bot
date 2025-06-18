import os
import re
import random
import asyncio
import threading
import aiohttp
from flask import Flask
from discord.ext import commands
import discord
from discord import app_commands
import signal

# === CONFIGURATION ===
ALERT_CHANNEL_ID = 1384717083652264056  # This is where detailed alerts will be sent
STREAMER_CHANNEL_ID = 1207227502003757077
LOG_CHANNEL_ID = 1384882351678689431
STREAMER_ROLE = "Streamer"

# === DISCORD BOT SETUP ===
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# === PERMISSIONS AND ROLES ===
MODERATION_ROLES = {
    "Trial Moderator": ["kick", "mute", "voicemute"],
    "Moderator": ["kick", "mute", "voicemute"],
    "Head Moderator": ["kick", "mute", "voicemute"],
    "Trial Administrator": ["kick", "mute", "voicemute", "giverole"],
    "Administrator": ["kick", "ban", "unban", "mute", "voicemute", "giverole"],
    "Head Administrator": ["kick", "ban", "unban", "mute", "gban", "voicemute", "giverole"],
    "Head Of Staff": ["kick", "ban", "unban", "mute", "gban", "voicemute", "giverole", "all"],
    "Trial Manager": ["all"],
    "Management": ["all"],
    "Head Of Management": ["all"],
    "Co Director": ["all"],
    "Director": ["all"],
}
LINK_PRIVILEGED_ROLES = list(MODERATION_ROLES.keys())

# === GLOBAL BAN LIST ===
global_ban_list = set()
known_bad_users = set()

# --- Helper functions ---

async def send_alert_to_channel(message):
    """Send detailed alerts directly to the designated Discord channel."""
    channel = bot.get_channel(ALERT_CHANNEL_ID)
    if channel:
        embed = discord.Embed(title="Alert Notification", description=message, color=discord.Color.orange())
        await channel.send(embed=embed)

async def notify_status(status):
    message = "🟢 Bot is now ONLINE" if status == "up" else "🔴 Bot is now OFFLINE or restarting"
    # Here, instead of webhook, we send directly to alert channel
    await send_alert_to_channel(message)

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

    # Send startup message to the alert channel
    await send_alert_to_channel("🟢 **Bot has started and is online!**")

# Handle shutdown to notify offline
def handle_shutdown():
    # Schedule the shutdown alert
    asyncio.get_event_loop().create_task(send_alert_to_channel("🔴 **Bot is shutting down.**"))
    # Also send the webhook message here if needed
    asyncio.get_event_loop().stop()

# Register signal handlers for graceful shutdown
import signal
signal.signal(signal.SIGINT, lambda s, f: handle_shutdown())
signal.signal(signal.SIGTERM, lambda s, f: handle_shutdown())

@bot.event
async def on_member_join(member):
    account_age = (discord.utils.utcnow() - member.created_at).days
    is_flagged = member.id in known_bad_users or account_age < 7
    reason = []
    if member.id in known_bad_users:
        reason.append(":firecracker: Matched known banned user")
    if account_age < 7:
        reason.append(f":date: Account is only {account_age} days old")
    if is_flagged:
        await send_alert_to_channel(
            f":warning: **Suspicious User Joined:** {member}\nID: {member.id}\nReason(s): {' | '.join(reason)}"
        )

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Slur and inappropriate language detection
    content_lower = message.content.lower()
    if any(slur in content_lower for slur in ["spick", "nigger", "retarded"]):
        await message.delete()
        log_msg = f"🚫 Message from {message.author} deleted for slur usage in #{message.channel}: {message.content}"
        await send_alert_to_channel(log_msg)
        await log_to_channel(log_msg)
        try:
            await message.channel.send(f"🚫 {message.author.mention}, your message was removed.")
            await message.author.send("⚠️ You have been warned for inappropriate language.")
        except:
            pass
        return

    # Spam detection
    if len(message.content) > 400 or message.content.count("\n") > 5:
        await send_alert_to_channel(f":anger_right: **Possible Spam** from {message.author} in #{message.channel}: {message.content[:400]}")

   # Track user link timestamps
user_link_log = defaultdict(list)

link_pattern = re.compile(r"https?://[^\s]+")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    links = link_pattern.findall(message.content)
    if links:
        has_privilege = any(role.name in LINK_PRIVILEGED_ROLES for role in message.author.roles)
        is_streamer = any(role.name == STREAMER_ROLE for role in message.author.roles)

        # Record each link with a timestamp
        now = datetime.utcnow()
        user_id = message.author.id
        user_link_log[user_id] = [ts for ts in user_link_log[user_id] if now - ts < timedelta(minutes=3)]
        user_link_log[user_id].extend([now] * len(links))

        if len(user_link_log[user_id]) > 3:
            alert_channel = bot.get_channel(ALERT_CHANNEL_ID)
            if alert_channel:
                await alert_channel.send(f"🚨 {message.author.mention} has sent more than 3 links within 3 minutes.")

        for link in links:
            if "discord.gg" in link or "discord.com/invite" in link:
                invite_code = link.split("/invite/")[-1] if "/invite/" in link else link.split("discord.gg/")[-1]
                try:
                    invite = await bot.fetch_invite(invite_code)
                    if invite.guild and invite.guild.id in [g.id for g in bot.guilds]:
                        continue
                except:
                    pass
                await message.delete()
                log_msg = f"🚫 Invite link deleted from {message.author} in #{message.channel}: {message.content}"
                await send_alert_to_channel(log_msg)
                await log_to_channel(log_msg)
                await message.channel.send(f"🚫 {message.author.mention}, Discord invites are not allowed.")
                return

            if any(domain in link for domain in ["tenor.com", "giphy.com"]):
                continue

            if (
                message.channel.id == STREAMER_CHANNEL_ID and
                is_streamer and
                any(domain in link for domain in ["twitch.tv", "youtube.com", "kick.com", "tiktok"])
            ):
                continue

            if not has_privilege:
                await message.delete()
                log_msg = f"🚫 Unauthorized link from {message.author} in #{message.channel}: {message.content}"
                await send_alert_to_channel(log_msg)
                await log_to_channel(log_msg)
                await message.channel.send(f"🚫 {message.author.mention}, you are not allowed to post this link.")
                return

    # Racial slur filter
    slurs = ["spick", "nigger", "retarded"]
    content_lower = message.content.lower()
    if any(slur in content_lower for slur in slurs):
        await message.delete()
        log_msg = f"🚫 Message from {message.author} deleted for slur usage in #{message.channel}: {message.content}"
        await send_alert_to_channel(log_msg)
        await log_to_channel(log_msg)
        try:
            await message.channel.send(f"🚫 {message.author.mention}, your message was removed for violating server rules.")
            await message.author.send("⚠️ You have been warned for using inappropriate language.")
        except:
            pass
        return

    await bot.process_commands(message)

# Helper function to log messages to log channel
async def log_to_channel(content):
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel:
        await channel.send(content)

# Command: kick
@bot.command()
async def kick(ctx, user: discord.User):
    if not has_role_permission(ctx, "kick"):
        return await styled_reply(ctx, "❌ You do not have permission to use this command.", discord.Color.red())

    member = ctx.guild.get_member(user.id)
    if member:
        await member.kick()
        log_msg = f"{ctx.author} kicked {member}"
        await log_to_channel(log_msg)
        await send_alert_to_channel(f"👢 {log_msg}")
        await styled_reply(ctx, f"👢 {member} has been kicked.")
    else:
        await styled_reply(ctx, "❌ User not found in this server.", discord.Color.red())

# Command: ban
@bot.command()
async def ban(ctx, member: discord.Member, *, reason=None):
    if not has_role_permission(ctx, "ban"):
        return await styled_reply(ctx, "❌ You do not have permission to use this command.", discord.Color.red())

    await member.ban(reason=reason)
    log_msg = f"{ctx.author} banned {member} for reason: {reason}"
    await log_to_channel(log_msg)
    await send_alert_to_channel(f"🔨 {log_msg}")
    await styled_reply(ctx, f'🔨 {member} has been banned.')

# Command: unban
@bot.command()
async def unban(ctx, *, user):
    banned_users = [entry async for entry in ctx.guild.bans()]
    if user.isdigit():
        user_id = int(user)
        for ban_entry in banned_users:
            if ban_entry.user.id == user_id:
                await ctx.guild.unban(ban_entry.user)
                log_msg = f"{ctx.author} unbanned {ban_entry.user}"
                await log_to_channel(log_msg)
                await send_alert_to_channel(f"♻️ {log_msg}")
                await styled_reply(ctx, f"✅ Unbanned {ban_entry.user}")
                return
        await styled_reply(ctx, "❌ User ID not found in ban list.", discord.Color.red())
    elif '#' in user:
        try:
            name, discriminator = user.split('#')
        except:
            await styled_reply(ctx, "❌ Invalid format. Use Username#1234 or user ID.", discord.Color.red())
            return
        for ban_entry in banned_users:
            if ban_entry.user.name == name and ban_entry.user.discriminator == discriminator:
                await ctx.guild.unban(ban_entry.user)
                log_msg = f"{ctx.author} unbanned {ban_entry.user}"
                await log_to_channel(log_msg)
                await send_alert_to_channel(f"♻️ {log_msg}")
                await styled_reply(ctx, f"✅ Unbanned {ban_entry.user}")
                return
        await styled_reply(ctx, "❌ User not found in ban list.", discord.Color.red())
    else:
        await styled_reply(ctx, "❌ Invalid format. Use Username#1234 or user ID.", discord.Color.red())

# Command: mute
@bot.command()
async def mute(ctx, member: discord.Member):
    if not has_role_permission(ctx, "mute"):
        return await styled_reply(ctx, "❌ You do not have permission to use this command.", discord.Color.red())
    overwrite = discord.PermissionOverwrite(send_messages=False)
    for channel in ctx.guild.text_channels:
        await channel.set_permissions(member, overwrite=overwrite)
    log_msg = f"{ctx.author} muted {member} in text channels."
    await log_to_channel(log_msg)
    await send_alert_to_channel(log_msg)
    await styled_reply(ctx, f'🔇 {member} has been muted in text channels.')

# Command: voicemute
@bot.command()
async def voicemute(ctx, member: discord.Member):
    if not has_role_permission(ctx, "voicemute"):
        return await styled_reply(ctx, "❌ You do not have permission to use this command.", discord.Color.red())
    await member.edit(mute=True)
    log_msg = f"{ctx.author} voice-muted {member}"
    await log_to_channel(log_msg)
    await send_alert_to_channel(log_msg)
    await styled_reply(ctx, f'🔇 {member} has been voice-muted.')

# Command: gban (global ban)
@bot.command()
async def gban(ctx, user: discord.User, *, reason=None):
    if not has_role_permission(ctx, "ban"):
        return await styled_reply(ctx, "❌ You do not have permission to use this command.", discord.Color.red())
    global global_ban_list
    if user.id in global_ban_list:
        return await styled_reply(ctx, f"⚠️ {user} is already globally banned.")
    global_ban_list.add(user.id)
    for guild in bot.guilds:
        member = guild.get_member(user.id)
        if member:
            try:
                await guild.ban(member, reason=f"Global Ban: {reason}")
            except:
                pass
    await styled_reply(ctx, f'🌐 {user} has been globally banned from all servers.')
    await log_to_channel(f"🌐 {ctx.author} globally banned {user}. Reason: {reason}")
    await send_alert_to_channel(f"🌐 {user} was globally banned. Reason: {reason}")

# Command: ungban (remove global ban)
@bot.command()
async def ungban(ctx, user: discord.User):
    if not has_role_permission(ctx, "ban"):
        return await styled_reply(ctx, "❌ You do not have permission to use this command.", discord.Color.red())
    global global_ban_list
    if user.id not in global_ban_list:
        return await styled_reply(ctx, f"❌ {user} is not in the global ban list.")
    global_ban_list.remove(user.id)
    await styled_reply(ctx, f'✅ {user} has been removed from the global ban list.')
    await log_to_channel(f"🌍 {ctx.author} removed {user} from global ban list")
    await send_alert_to_channel(f"{user} has been unglobally banned.")

# Command: giverole
@bot.command()
async def giverole(ctx, member: discord.Member, role_id: int):
    if not has_role_permission(ctx, "giverole"):
        return await styled_reply(ctx, "❌ You do not have permission to use this command.", discord.Color.red())

    role = ctx.guild.get_role(role_id)
    if not role:
        return await styled_reply(ctx, "❌ Invalid role ID provided.", discord.Color.red())

    try:
        await member.add_roles(role, reason=f"Given by {ctx.author}")
        log_msg = f"{ctx.author} gave role {role.name} to {member}"
        await log_to_channel(log_msg)
        await send_alert_to_channel(f"🎖️ {log_msg}")
        await styled_reply(ctx, f'🎖️ Gave {role.name} to {member.mention}')
    except:
        await styled_reply(ctx, "❌ I do not have permission to give that role.", discord.Color.red())

# Command: takerole
@bot.command()
async def takerole(ctx, member: discord.Member, role_id: int):
    if not has_role_permission(ctx, "giverole"):
        return await styled_reply(ctx, "❌ You do not have permission to use this command.", discord.Color.red())

    role = ctx.guild.get_role(role_id)
    if not role:
        return await styled_reply(ctx, "❌ Invalid role ID provided.", discord.Color.red())

    try:
        await member.remove_roles(role, reason=f"Removed by {ctx.author}")
        log_msg = f"{ctx.author} removed role {role.name} from {member}"
        await log_to_channel(log_msg)
        await send_alert_to_channel(f"🧼 {log_msg}")
        await styled_reply(ctx, f'🧼 Removed {role.name} from {member.mention}')
    except:
        await styled_reply(ctx, "❌ I do not have permission to remove that role.", discord.Color.red())

# Command: giveaway
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
        await send_alert_to_channel(f"🎁 Giveaway winner: {winner}. Prize: {prize}")
    else:
        await styled_reply(ctx, "No one entered the giveaway. 😢")
        await log_to_channel(f"🎁 {ctx.author} hosted a giveaway but no entries were received. Prize: {prize}")
        await send_alert_to_channel(f"Giveaway ended with no entries. Prize: {prize}")

# Utility function to check roles permissions
def has_role_permission(ctx, command_name):
    for role in ctx.author.roles:
        perms = MODERATION_ROLES.get(role.name)
        if perms and ("all" in perms or command_name in perms):
            return True
    return False

# Helper for styled reply
async def styled_reply(ctx, message: str, color=discord.Color.blurple()):
    embed = discord.Embed(description=message, color=color)
    await ctx.send(embed=embed)
    try:
        await ctx.message.delete()
    except:
        pass

# --- Run the bot ---
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
