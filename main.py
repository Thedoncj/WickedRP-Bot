import discord  # type: ignore
from discord.ext import commands  # type: ignore
import asyncio
import re
import random
import os
import threading
from flask import Flask

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
    "Administrator": ["kick", "ban", "unban", "mute", "voicemute"],
    "Head Administrator": ["kick", "ban", "unban", "mute", "gban"],
    "Head Of Staff": ["all"],
    "Trial Manager": ["all"],
    "Management": ["all"],
    "Head of Management": ["all"],
    "Co Director": ["all"],
    "Director": ["all"],
}

PRIVILEGED_ROLES = [role for role, perms in MODERATION_ROLES.items() if perms == "all"]

def has_role_permission(ctx, command_name):
    for role in ctx.author.roles:
        for role_name, perms in MODERATION_ROLES.items():
            if role.name.lower() == role_name.lower():
                if perms == "all" or (perms and command_name in perms):
                    return True
    return False

SLURS = ["spick", "nigger", "retarded"]

STREAMER_ROLE = "Streamer"
STREAMER_CHANNEL_ID = 1207227502003757077
ALLOWED_STREAMER_DOMAINS = ["twitch.tv", "youtube.com", "kick.com", "tiktok"]

@bot.event
async def on_ready():
    print(f'Wicked RP Bot is online as {bot.user}!')

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Slur filter
    lower_content = message.content.lower()
    if any(slur in lower_content for slur in SLURS):
        await message.delete()
        warning_msg = f"🚫 {message.author.mention}, your message was removed for violating community rules."
        await message.channel.send(warning_msg)
        try:
            await message.author.send("⚠️ You have been warned for using prohibited language in the server.")
        except discord.Forbidden:
            pass
        log_channel_id = 123456789012345678  # Update to your actual log channel ID
        log_channel = bot.get_channel(log_channel_id)
        if log_channel:
            await log_channel.send(f"🛑 User {message.author} used a slur and was warned in {message.channel.mention}.\nMessage: `{message.content}`")
        return

    # Link filter
    link_pattern = re.compile(r"https?://[^\s]+")
    links = link_pattern.findall(message.content)
    if links:
        has_privilege = any(role.name in PRIVILEGED_ROLES for role in message.author.roles)
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
                await message.channel.send(f"🚫 {message.author.mention}, Discord invites are not allowed.")
                return
            if any(domain in link for domain in ["tenor.com", "giphy.com"]):
                continue
            if (message.channel.id == STREAMER_CHANNEL_ID and is_streamer and any(domain in link for domain in ALLOWED_STREAMER_DOMAINS)):
                continue
            if not has_privilege:
                await message.delete()
                await message.channel.send(f"🚫 {message.author.mention}, you are not allowed to post this kind of link.")
                return

    await bot.process_commands(message)

# === Commands (unchanged, kept as you wrote) ===
# ... [Your command code remains untouched and correct]

# === FLASK KEEP-ALIVE SERVER ===
app = Flask(__name__)

@app.route('/')
def index():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

threading.Thread(target=run_flask).start()

bot.run(os.getenv("DISCORD_BOT_TOKEN"))
