# bot.py

import discord
import os
from discord.ext import commands

# Get your bot token securely from Render environment variable
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

# Create the bot instance
intents = discord.Intents.default()
intents.message_content = True  # Needed to read messages

bot = commands.Bot(command_prefix='!', intents=intents)

# Simple ready event
@bot.event
async def on_ready():
    print(f'✅ Bot is ready. Logged in as {bot.user.name}')

# Example command
@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")

# Run the bot
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ DISCORD_BOT_TOKEN is not set!")
