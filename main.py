import os
import re
import asyncio
import threading
from flask import Flask
from discord.ext import commands, tasks
import discord
from discord import app_commands
from datetime import datetime, timedelta
import aiosqlite
import random

# === INTENTS & BOT ===
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# === CONFIG ===
LOG_CHANNEL_ID = 1384882351678689431
WARN_CHANNEL_ID = 1384717083652264056
WHITELISTER_ROLE_ID = 1344882926965493823
WHITELISTED_ROLE_ID = 1127098119750951083

TICKET_CATEGORY_IDS = [
    1282992099876274187, 1163567127157035218, 1130779266880131223,
    1212553215606919188, 1212553308321874000, 1276565387579887616, 1394004814911766770, 1343968025388388392
]

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

PRIVILEGED_ROLES = ["Head Of Staff", "Trial Manager", "Management", "Head Of Management", "Co Director", "Director"]
STREAMER_ROLE = "Streamer"
STREAMER_CHANNEL_ID = 1207227502003757077
ALLOWED_STREAMER_DOMAINS = ["twitch.tv", "youtube.com", "kick.com", "tiktok"]

def has_permission(member: discord.Member, command: str) -> bool: 
    for role in member.roles:
        perms = MODERATION_ROLES.get(role.name)
        if perms and ("all" in perms or command in perms):
            return True
    return False

def can_act(invoker: discord.Member, target: discord.Member, command: str):
    return has_permission(invoker, command) and invoker.top_role > target.top_role

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

    if message.channel.category_id in TICKET_CATEGORY_IDS:
        await bot.process_commands(message)
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
  
# === DATABASE INITIALIZATION ===
async def initialize_database():
    async with aiosqlite.connect("database.db") as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS warns (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT, user_id TEXT,
            moderator_id TEXT, reason TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")

        await db.execute("""CREATE TABLE IF NOT EXISTS bans (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT, user_id TEXT,
            moderator_id TEXT, reason TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            unbanned BOOLEAN DEFAULT 0, unbanned_by TEXT, unban_reason TEXT, unban_timestamp DATETIME)""")

        await db.execute("""CREATE TABLE IF NOT EXISTS kicks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT, user_id TEXT,
            moderator_id TEXT, reason TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")

        await db.execute("""CREATE TABLE IF NOT EXISTS mutes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT, user_id TEXT,
            moderator_id TEXT, reason TEXT, duration INTEGER,
            start_time DATETIME DEFAULT CURRENT_TIMESTAMP, end_time DATETIME)""")

        await db.execute("""CREATE TABLE IF NOT EXISTS giveaways (
            id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT, message_id TEXT,
            prize TEXT, end_time DATETIME)""")

        await db.commit()

# === LOGGER WITH RATE LIMIT CATCH ===
async def log_to_channel(bot, content):
    try:
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(content)
    except discord.HTTPException as e:
        if e.status == 429:
            print("⚠️ Rate limit hit when logging to channel!")
        else:
            print(f"❌ Logging error: {e}")

# === BACKGROUND TASK FOR SCHEDULED UNMUTES ===
@tasks.loop(minutes=1)
async def check_mute_expirations():
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect("database.db") as db:
        async with db.execute("SELECT guild_id, user_id, end_time FROM mutes WHERE end_time <= ? AND end_time IS NOT NULL", (now,)) as cursor:
            async for guild_id, user_id, end_time in cursor:
                guild = bot.get_guild(int(guild_id))
                if guild:
                    member = guild.get_member(int(user_id))
                    if member:
                        mute_role = discord.utils.get(guild.roles, name="Muted")
                        if mute_role and mute_role in member.roles:
                            try:
                                await member.remove_roles(mute_role, reason="Scheduled unmute")
                                await log_to_channel(bot, f"🔊 {member.mention} was automatically unmuted.")
                            except Exception as e:
                                print(f"Error auto-unmuting {member}: {e}")
        await db.execute("DELETE FROM mutes WHERE end_time <= ? AND end_time IS NOT NULL", (now,))
        await db.commit()

# === BOT READY ===
@bot.event
async def on_ready():
    await initialize_database()
    await bot.tree.sync()
    check_mute_expirations.start()
    print(f"✅ Logged in as {bot.user}")

# === MESSAGE FILTERING (NO CHANGES NEEDED) ===
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    content = message.content.lower()
    if any(slur in content for slur in ["spick", "nigger", "retarded"]):
        await message.delete()
        await log_to_channel(bot, f"🚫 Slur message deleted from {message.author}: `{message.content}`")
        try:
            await message.channel.send(f"🚫 {message.author.mention}, message removed for breaking rules.")
            await message.author.send("⚠️ You were warned for using slurs.")
        except discord.Forbidden:
            pass
        return

    if message.channel.category_id in TICKET_CATEGORY_IDS:
        await bot.process_commands(message)
        return
    
    links = re.findall(r"https?://[^\s]+", message.content)
    if links:
        has_privilege = any(role.name in PRIVILEGED_ROLES for role in message.author.roles)
        is_streamer = any(role.name == STREAMER_ROLE for role in message.author.roles)

        for link in links:
            if "discord.gg" in link or "discord.com/invite" in link:
                await message.delete()
                await message.channel.send(f"🚫 {message.author.mention}, no Discord invites allowed.")
                await log_to_channel(bot, f"🚫 Discord invite deleted from {message.author}: `{link}`")
                return
            if any(domain in link for domain in ["tenor.com", "giphy.com"]):
                continue
            if message.channel.id == STREAMER_CHANNEL_ID and is_streamer and any(domain in link for domain in ALLOWED_STREAMER_DOMAINS):
                continue
            if not has_privilege:
                await message.delete()
                await message.channel.send(f"🚫 {message.author.mention}, you're not allowed to post links.")
                await log_to_channel(bot, f"🚫 Unauthorized link from {message.author}: `{link}`")
                return

    await bot.process_commands(message)

# === GIVEAWAY COMMAND ===
@bot.tree.command(name="giveaway", description="Start a giveaway")
@app_commands.describe(duration="Duration in minutes", prize="Prize name")
async def giveaway(interaction: discord.Interaction, duration: int, prize: str):
    await interaction.response.defer(thinking=True)
    try:
        embed = discord.Embed(title="🎉 Giveaway!", description=f"Prize: **{prize}**\nReact with 🎉 to enter!\nEnds in {duration} minutes.", color=discord.Color.gold())
        embed.set_footer(text="Giveaway started by " + str(interaction.user))
        msg = await interaction.channel.send(embed=embed)
        await msg.add_reaction("🎉")

        end_time = datetime.utcnow() + timedelta(minutes=duration)
        async with aiosqlite.connect("database.db") as db:
            await db.execute("INSERT INTO giveaways (channel_id, message_id, prize, end_time) VALUES (?, ?, ?, ?)",
                             (str(msg.channel.id), str(msg.id), prize, end_time.isoformat()))
            await db.commit()
        await interaction.followup.send("✅ Giveaway started!", ephemeral=True)

        await asyncio.sleep(duration * 60)
        new_msg = await interaction.channel.fetch_message(msg.id)
        users = await new_msg.reactions[0].users().flatten()
        users = [u for u in users if not u.bot]

        if not users:
            await interaction.channel.send("❌ No valid entries.")
            return

        winner = random.choice(users)
        await interaction.channel.send(f"🎉 Congrats {winner.mention}, you won **{prize}**!")

    except Exception as e:
        await interaction.followup.send("❌ Failed to start giveaway.", ephemeral=True)
        await log_to_channel(bot, f"❌ Giveaway error by {interaction.user}: {e}")

# === YOUR OTHER MODERATION COMMANDS HERE ===
@bot.tree.command(name="kick", description="Kick a member")
@app_commands.describe(user="User to kick", reason="Reason for the kick")
async def kick(interaction: discord.Interaction, user: discord.Member, reason: str):
    await interaction.response.defer(thinking=True)
    if not can_act(interaction.user, user, "kick"):
        return await interaction.followup.send("❌ You lack permission or your role is not high enough.", ephemeral=True)
    try:
        await user.kick(reason=reason)
        await interaction.followup.send(f"👢 {user.mention} was kicked. Reason: {reason}")
        await log_to_channel(bot, f"👢 {interaction.user} kicked {user} | Reason: {reason}")

        async with aiosqlite.connect("database.db") as db:
            await db.execute("INSERT INTO kicks (guild_id, user_id, moderator_id, reason) VALUES (?, ?, ?, ?)",
                             (str(interaction.guild.id), str(user.id), str(interaction.user.id), reason))
            await db.commit()
    except Exception as e:
        await interaction.followup.send("❌ Failed to kick user.", ephemeral=True)
        await log_to_channel(bot, f"❌ {interaction.user} failed to kick {user}: {e}")

@bot.tree.command(name="ban", description="Ban a user (even if they're not in the server)")
@app_commands.describe(user="User to ban", reason="Reason for the ban")
async def ban(interaction: discord.Interaction, user: discord.User, reason: str):
    await interaction.response.defer(thinking=True)
    # Permission check only applies if user is in guild
    member = interaction.guild.get_member(user.id)
    if member and not can_act(interaction.user, member, "ban"):
        return await interaction.followup.send("❌ You lack permission or your role is not high enough.", ephemeral=True)

    try:
        await interaction.guild.ban(user, reason=reason)
        await interaction.followup.send(f"🔨 {user.mention} was banned. Reason: {reason}")
        await log_to_channel(bot, f"🔨 {interaction.user} banned {user} | Reason: {reason}")

        async with aiosqlite.connect("database.db") as db:
            await db.execute("INSERT INTO bans (guild_id, user_id, moderator_id, reason, unbanned) VALUES (?, ?, ?, ?, 0)",
                             (str(interaction.guild.id), str(user.id), str(interaction.user.id), reason))
            await db.commit()
    except Exception as e:
        await interaction.followup.send("❌ Failed to ban user.", ephemeral=True)
        await log_to_channel(bot, f"❌ {interaction.user} failed to ban {user}: {e}")


@bot.tree.command(name="gban", description="Globally ban a user from all servers")
@app_commands.describe(user="User to globally ban", reason="Reason for global ban")
async def gban(interaction: discord.Interaction, user: discord.User, reason: str):
    await interaction.response.defer(thinking=True)
    if not has_permission(interaction.user, "gban"):
        return await interaction.followup.send("❌ You lack permission.", ephemeral=True)

    failed = []
    for guild in bot.guilds:
        member = guild.get_member(user.id)
        # Check role hierarchy if they're in the server
        if member and not can_act(interaction.user, member, "gban"):
            failed.append(guild.name)
            continue
        try:
            await guild.ban(user, reason=f"Global Ban: {reason}")
            async with aiosqlite.connect("database.db") as db:
                await db.execute("INSERT INTO bans (guild_id, user_id, moderator_id, reason, unbanned) VALUES (?, ?, ?, ?, 0)",
                                 (str(guild.id), str(user.id), str(interaction.user.id), f"Global Ban: {reason}"))
                await db.commit()
        except:
            failed.append(guild.name)

    await interaction.followup.send(f"🌐 {user.mention} globally banned. Failed in: {', '.join(failed) if failed else 'None'}")
    await log_to_channel(bot, f"🌐 {interaction.user} globally banned {user} | Reason: {reason} | Failed in: {failed}")

@bot.tree.command(name="warn", description="Warn a member")
@app_commands.describe(user="User to warn", reason="Reason for warning")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str):
    await interaction.response.defer(thinking=True)
    if not can_act(interaction.user, user, "warn"):
        return await interaction.followup.send("❌ You lack permission or your role is not high enough.", ephemeral=True)
    try:
        await interaction.followup.send(f"⚠️ {user.mention} warned. Reason: {reason}")
        await log_to_channel(bot, f"⚠️ {interaction.user} warned {user} | Reason: {reason}")

        async with aiosqlite.connect("database.db") as db:
            await db.execute("INSERT INTO warns (guild_id, user_id, moderator_id, reason) VALUES (?, ?, ?, ?)",
                             (str(interaction.guild.id), str(user.id), str(interaction.user.id), reason))
            await db.commit()
    except Exception as e:
        await interaction.followup.send("❌ Failed to warn user.", ephemeral=True)
        await log_to_channel(bot, f"❌ {interaction.user} failed to warn {user}: {e}")

@bot.tree.command(name="giverole", description="Give a role to a member")
@app_commands.describe(user="User to give role to", role="Role to assign", reason="Reason for giving role")
async def giverole(interaction: discord.Interaction, user: discord.Member, role: discord.Role, reason: str):
    await interaction.response.defer(thinking=True)
    if not can_act(interaction.user, user, "giverole"):
        return await interaction.followup.send("❌ You lack permission or your role is not high enough.", ephemeral=True)
    try:
        await user.add_roles(role, reason=reason)
        await interaction.followup.send(f"✅ Gave {role.name} to {user.mention}. Reason: {reason}")
        await log_to_channel(bot, f"✅ {interaction.user} gave {role.name} to {user} | Reason: {reason}")
    except Exception as e:
        await interaction.followup.send("❌ Failed to give role.", ephemeral=True)
        await log_to_channel(bot, f"❌ {interaction.user} failed to give {role.name} to {user}: {e}")

@bot.tree.command(name="takerole", description="Remove a role from a member")
@app_commands.describe(user="User to remove role from", role="Role to remove", reason="Reason for removing role")
async def takerole(interaction: discord.Interaction, user: discord.Member, role: discord.Role, reason: str):
    await interaction.response.defer(thinking=True)
    if not can_act(interaction.user, user, "takerole"):
        return await interaction.followup.send("❌ You lack permission or your role is not high enough.", ephemeral=True)
    try:
        await user.remove_roles(role, reason=reason)
        await interaction.followup.send(f"🗑️ Removed {role.name} from {user.mention}. Reason: {reason}")
        await log_to_channel(bot, f"🗑️ {interaction.user} removed {role.name} from {user} | Reason: {reason}")
    except Exception as e:
        await interaction.followup.send("❌ Failed to remove role.", ephemeral=True)
        await log_to_channel(bot, f"❌ {interaction.user} failed to remove {role.name} from {user}: {e}")

@bot.tree.command(name="textmute", description="Mute a user in text channels temporarily")
@app_commands.describe(user="User to mute", duration="Duration in minutes", reason="Reason for muting")
async def textmute(interaction: discord.Interaction, user: discord.Member, duration: int, reason: str):
    await interaction.response.defer(thinking=True)
    if not can_act(interaction.user, user, "textmute"):
        return await interaction.followup.send("❌ You lack permission or your role is not high enough.", ephemeral=True)
    mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
    if not mute_role:
        return await interaction.followup.send("❌ 'Muted' role not found.", ephemeral=True)
    try:
        await user.add_roles(mute_role, reason=reason)
        await interaction.followup.send(f"🔇 {user.mention} muted for {duration} minutes. Reason: {reason}")
        await log_to_channel(bot, f"🔇 {interaction.user} muted {user} for {duration} minutes | Reason: {reason}")

        now = datetime.utcnow()
        end_time = now + timedelta(minutes=duration)

        async with aiosqlite.connect("database.db") as db:
            await db.execute("""
                INSERT INTO mutes (guild_id, user_id, moderator_id, reason, duration, start_time, end_time) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (str(interaction.guild.id), str(user.id), str(interaction.user.id), reason, duration*60, now.isoformat(), end_time.isoformat()))
            await db.commit()

        await asyncio.sleep(duration * 60)
        # Before unmuting, check if user still has mute role
        if mute_role in user.roles:
            await user.remove_roles(mute_role, reason="Mute duration expired")
            await log_to_channel(bot, f"🔊 {user.mention} was automatically unmuted after {duration} minutes.")
    except Exception as e:
        await interaction.followup.send("❌ Failed to mute user.", ephemeral=True)
        await log_to_channel(bot, f"❌ {interaction.user} failed to mute {user}: {e}")
@bot.tree.command(name="textunmute", description="Unmute a user in text channels")
@app_commands.describe(user="User to unmute", reason="Reason for unmuting")
async def textunmute(interaction: discord.Interaction, user: discord.Member, reason: str):
    await interaction.response.defer(thinking=True)
    if not can_act(interaction.user, user, "textmute"):
        return await interaction.followup.send("❌ You lack permission or your role is not high enough.", ephemeral=True)
    mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
    if not mute_role:
        return await interaction.followup.send("❌ 'Muted' role not found.", ephemeral=True)
    try:
        await user.remove_roles(mute_role, reason=reason)
        await interaction.followup.send(f"🔊 {user.mention} has been unmuted. Reason: {reason}")
        await log_to_channel(bot, f"🔊 {interaction.user} unmuted {user} | Reason: {reason}")

        # Update mute DB to mark end_time as now
        now = datetime.utcnow()
        async with aiosqlite.connect("database.db") as db:
            await db.execute("""
                UPDATE mutes 
                SET end_time = ?, duration = 0 
                WHERE guild_id = ? AND user_id = ? AND end_time > ?
            """, (now.isoformat(), str(interaction.guild.id), str(user.id), now.isoformat()))
            await db.commit()

    except Exception as e:
        await interaction.followup.send("❌ Failed to unmute user.", ephemeral=True)
        await log_to_channel(bot, f"❌ {interaction.user} failed to unmute {user}: {e}")

@bot.tree.command(name="wl", description="Whitelist a member by giving them the Whitelisted role")
async def wl(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer(thinking=True)
    author = interaction.user
    if WHITELISTER_ROLE_ID not in [r.id for r in author.roles]:
        return await interaction.followup.send("❌ You do not have permission to whitelist users.", ephemeral=True)

    whitelisted_role = interaction.guild.get_role(WHITELISTED_ROLE_ID)
    if not whitelisted_role:
        return await interaction.followup.send("❌ Whitelisted role not found.", ephemeral=True)
    if whitelisted_role in user.roles:
        return await interaction.followup.send(f"ℹ️ {user.mention} is already whitelisted.", ephemeral=True)
    try:
        await user.add_roles(whitelisted_role, reason=f"Whitelisted by {author}")
        await interaction.followup.send(f"✅ {user.mention} has been whitelisted.")
        await log_to_channel(bot, f"✅ {author} whitelisted {user}")
    except Exception as e:
        await interaction.followup.send("❌ Failed to whitelist user.", ephemeral=True)
        await log_to_channel(bot, f"❌ {author} failed to whitelist {user}: {e}")

@bot.tree.command(name="modhistory", description="Show moderation history for a user")
@app_commands.describe(user="User to show history for")
async def modhistory(interaction: discord.Interaction, user: discord.User):
    await interaction.response.defer(thinking=True)
    guild_id = str(interaction.guild.id)

    try:
        async with aiosqlite.connect("database.db") as db:
            # Fetch warns
            warns = await db.execute_fetchall("SELECT moderator_id, reason, timestamp FROM warns WHERE guild_id = ? AND user_id = ?", (guild_id, str(user.id)))
            # Fetch bans
            bans = await db.execute_fetchall("SELECT moderator_id, reason, timestamp, unbanned FROM bans WHERE guild_id = ? AND user_id = ?", (guild_id, str(user.id)))
            # Fetch kicks
            kicks = await db.execute_fetchall("SELECT moderator_id, reason, timestamp FROM kicks WHERE guild_id = ? AND user_id = ?", (guild_id, str(user.id)))
            # Fetch mutes
            mutes = await db.execute_fetchall("SELECT moderator_id, reason, start_time, end_time FROM mutes WHERE guild_id = ? AND user_id = ?", (guild_id, str(user.id)))
        
        embed = discord.Embed(title=f"Mod History for {user}", color=discord.Color.blue())

        if warns:
            warn_lines = []
            for mod_id, reason, ts in warns:
                try:
                    mod = interaction.guild.get_member(int(mod_id))
                    mod_name = mod.display_name if mod else f"Mod ID: {mod_id}"
                except Exception:
                    mod_name = f"Invalid Mod ID: {mod_id}"
                warn_lines.append(f"⚠️ Warn by {mod_name} at {ts}: {reason}")
            embed.add_field(name="Warns", value="\n".join(warn_lines), inline=False)
        else:
            embed.add_field(name="Warns", value="None", inline=False)

        if bans:
            ban_lines = []
            for mod_id, reason, ts, unbanned in bans:
                try:
                    mod = interaction.guild.get_member(int(mod_id))
                    mod_name = mod.display_name if mod else f"Mod ID: {mod_id}"
                except Exception:
                    mod_name = f"Invalid Mod ID: {mod_id}"
                status = "Unbanned" if unbanned else "Banned"
                ban_lines.append(f"🔨 {status} by {mod_name} at {ts}: {reason}")
            embed.add_field(name="Bans", value="\n".join(ban_lines), inline=False)
        else:
            embed.add_field(name="Bans", value="None", inline=False)

        if kicks:
            kick_lines = []
            for mod_id, reason, ts in kicks:
                try:
                    mod = interaction.guild.get_member(int(mod_id))
                    mod_name = mod.display_name if mod else f"Mod ID: {mod_id}"
                except Exception:
                    mod_name = f"Invalid Mod ID: {mod_id}"
                kick_lines.append(f"👢 Kick by {mod_name} at {ts}: {reason}")
            embed.add_field(name="Kicks", value="\n".join(kick_lines), inline=False)
        else:
            embed.add_field(name="Kicks", value="None", inline=False)

        if mutes:
            mute_lines = []
            for mod_id, reason, start, end in mutes:
                try:
                    mod = interaction.guild.get_member(int(mod_id))
                    mod_name = mod.display_name if mod else f"Mod ID: {mod_id}"
                except Exception:
                    mod_name = f"Invalid Mod ID: {mod_id}"
                mute_lines.append(f"🔇 Mute by {mod_name} from {start} to {end}: {reason}")
            embed.add_field(name="Mutes", value="\n".join(mute_lines), inline=False)
        else:
            embed.add_field(name="Mutes", value="None", inline=False)

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"❌ Error fetching mod history: `{e}`")

@bot.tree.command(name="unban", description="Unban a user by their ID")
@app_commands.describe(user_id="User ID to unban", reason="Reason for unbanning")
async def unban(interaction: discord.Interaction, user_id: str, reason: str):
    await interaction.response.defer(thinking=True)

    if not has_permission(interaction.user, "unban"):
        return await interaction.followup.send("❌ You lack permission.", ephemeral=True)

    try:
        banned_users = [entry async for entry in interaction.guild.bans()]
        user = next((ban.user for ban in banned_users if str(ban.user.id) == user_id), None)

        if not user:
            return await interaction.followup.send("❌ User is not banned.", ephemeral=True)

        await interaction.guild.unban(user, reason=reason)
        await interaction.followup.send(f"✅ Unbanned user ID {user_id}. Reason: {reason}")
        await log_to_channel(bot, f"✅ {interaction.user} unbanned {user} | Reason: {reason}")

        now = datetime.utcnow()
        async with aiosqlite.connect("database.db") as db:
            await db.execute("""
                UPDATE bans
                SET unbanned = 1, unbanned_by = ?, unban_reason = ?, unban_timestamp = ?
                WHERE guild_id = ? AND user_id = ? AND unbanned = 0
            """, (str(interaction.user.id), reason, now.isoformat(), str(interaction.guild.id), user_id))
            await db.commit()

    except discord.NotFound:
        await interaction.followup.send("❌ User not found or already unbanned.", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("❌ I don't have permission to unban this user.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to unban user: {e}", ephemeral=True)
        await log_to_channel(bot, f"❌ {interaction.user} failed to unban user ID {user_id}: {e}")

# Your commands and setup go here...

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host="0.0.0.0", port=8080)

def keep_alive():
    t = threading.Thread(target=run)
    t.start()

# Start keep-alive and bot
keep_alive()
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
