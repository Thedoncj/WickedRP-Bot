import os
import re
import random
import asyncio
import threading
import requests
from flask import Flask
from discord.ext import commands
import discord

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
    "Head of Management": ["all"],
    "Co Director": ["all"],
    "Director": ["all"],
}

LINK_PRIVILEGED_ROLES = [
    "Head Of Staff", "Trial Manager", "Management", "Head of Management", "Co Director", "Director"
]
STREAMER_ROLE = "Streamer"
STREAMER_CHANNEL_ID = 1207227502003757077
LOG_CHANNEL_ID = 1372296224803258480

# === Logging to a Discord channel instead of a webhook ===
async def log_to_channel(content):
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel:
        await channel.send(content)

def has_role_permission(ctx, command_name):
    for role in ctx.author.roles:
        perms = MODERATION_ROLES.get(role.name)
        if perms:
            if "all" in perms or command_name in perms:
                return True
    return False

@bot.event
async def on_ready():
    print(f'Wicked RP Bot is online as {bot.user}!')

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

    # === Link moderation ===
    link_pattern = re.compile(r"https?://[^\s]+")
    links = link_pattern.findall(message.content)

    if links:
        has_privilege = any(role.name in LINK_PRIVILEGED_ROLES for role in message.author.roles)
        is_streamer = any(role.name == STREAMER_ROLE for role in message.author.roles)

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
                await log_to_channel(f"🚫 Invite link deleted from {message.author} in #{message.channel}: {message.content}")
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
                await log_to_channel(f"🚫 Link deleted from {message.author} in #{message.channel}: {message.content}")
                await message.channel.send(f"🚫 {message.author.mention}, you are not allowed to post this kind of link.")
                return

    await bot.process_commands(message)

@bot.listen("on_command")
async def log_command(ctx):
    await log_to_channel(f"📌 Command used: `{ctx.command}` by {ctx.author} in #{ctx.channel}")

# === Command Wrapper to delete original command and send styled embeds ===
async def styled_reply(ctx, message: str, color=discord.Color.blurple()):
    embed = discord.Embed(description=message, color=color)
    await ctx.send(embed=embed)
    try:
        await ctx.message.delete()
    except discord.NotFound:
        pass

# === MODERATION COMMANDS ===

@bot.command()
async def kick(ctx, user: discord.User):
    if not has_role_permission(ctx, "kick"):
        return await styled_reply(ctx, "❌ You do not have permission to use this command.", discord.Color.red())

    member = ctx.guild.get_member(user.id)
    if member:
        await member.kick()
        await styled_reply(ctx, f"👢 {member} has been kicked.")
        await log_to_channel(f"👢 {ctx.author} kicked {member} in {ctx.guild.name}")
    else:
        await styled_reply(ctx, "❌ User not found in this server.", discord.Color.red())

@bot.command()
async def ban(ctx, member: discord.Member, *, reason=None):
    if not has_role_permission(ctx, "ban"):
        return await styled_reply(ctx, "❌ You do not have permission to use this command.", discord.Color.red())

    await member.ban(reason=reason)
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
    global global_ban_list
    if user.id in global_ban_list:
        return await styled_reply(ctx, f"⚠️ {user} is already globally banned.")
    global_ban_list.add(user.id)
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
async def ungban(ctx, user: discord.User):
    if not has_role_permission(ctx, "ban"):
        return await styled_reply(ctx, "❌ You do not have permission to use this command.", discord.Color.red())
    global global_ban_list
    if user.id not in global_ban_list:
        return await styled_reply(ctx, f"❌ {user} is not in the global ban list.")
    global_ban_list.remove(user.id)
    await styled_reply(ctx, f'✅ {user} has been removed from the global ban list.')
    await log_to_channel(f"🌍 {ctx.author} removed {user} from global ban list")

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

# === FLASK KEEP-ALIVE SERVER ===
app = Flask(__name__)

@app.route('/')
def index():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

threading.Thread(target=run_flask).start()

bot.run(os.getenv("DISCORD_BOT_TOKEN"))
