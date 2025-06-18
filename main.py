import discord  # type: ignore
from discord.ext import commands  # type: ignore
import asyncio
import re
import random
import os
import threading
from flask import Flask
import aiohttp

# === DISCORD BOT SETUP ===
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# === WEB SERVER TO KEEP BOT ALIVE ===
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = threading.Thread(target=run)
    t.start()

keep_alive()

WEBHOOK_URL = "https://discord.com/api/webhooks/1384721071705428060/GkThFDUdsrhz7TTl2Ge-hOqF_tRvVO0HN1z4DVAmIwfOd69bl6qkSm0H1MCaLwb9qkV_"

# === On Member Join: Run Checks and Alert ===

@bot.event
async def on_member_join(member: discord.Member):
    account_age = (discord.utils.utcnow() - member.created_at).days

    is_flagged = member.id in known_bad_users or account_age < 7
    reason = []

    if member.id in known_bad_users:
        reason.append("🧨 Matched known banned user")
    if account_age < 7:
        reason.append(f"📅 Account is only {account_age} days old")

    if is_flagged:
        await send_webhook_alert(
            f"⚠️ **Suspicious User Joined:** `{member}`\n" +
            f"ID: `{member.id}`\n" +
            f"Reason(s): {' | '.join(reason)}"
        )

# === On Message: Track Spam & Links ===
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Detect spammy behavior (basic)
    if len(message.content) > 400 or message.content.count("\n") > 5:
        await send_webhook_alert(
            f"🗯️ **Possible Spam Detected**\nUser: `{message.author}`\nChannel: {message.channel.mention}\nContent: {message.content[:400]}"
        )

    # Detect invite links
    if "discord.gg/" in message.content or "discord.com/invite" in message.content:
        await send_webhook_alert(
            f"🔗 **Invite Link Detected**\nUser: `{message.author}`\nChannel: {message.channel.mention}\nContent: {message.content}"
        )

    await bot.process_commands(message)

# === Send Alerts to Staff via Webhook ===
async def send_webhook_alert(content):
    async with aiohttp.ClientSession() as session:
        webhook = discord.Webhook.from_url(WEBHOOK_URL, session=session)
        await webhook.send(content, username="WickedRP Bot")

# === COMMANDS ===
@bot.command()
async def kick(ctx, member: discord.Member, *, reason=None):
    await member.kick(reason=reason)
    await ctx.send(f'{member} has been kicked.')

@bot.command()
async def ban(ctx, member: discord.Member, *, reason=None):
    await member.ban(reason=reason)
    await ctx.send(f'{member} has been banned.')

@bot.command()
async def unban(ctx, *, member):
    banned_users = await ctx.guild.bans()
    member_name, member_discriminator = member.split('#')

    for ban_entry in banned_users:
        user = ban_entry.user

        if (user.name, user.discriminator) == (member_name, member_discriminator):
            await ctx.guild.unban(user)
            await ctx.send(f'Unbanned {user.mention}')
            return

@bot.command()
async def clear(ctx, amount=5):
    await ctx.channel.purge(limit=amount)
    await ctx.send(f"Cleared {amount} messages", delete_after=3)

@bot.command()
async def ping(ctx):
    await ctx.send(f'Pong! {round(bot.latency * 1000)}ms')

# === RUN THE BOT ===
bot.run(os.getenv("DISCORD_BOT_TOKEN"))


