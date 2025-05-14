# === IMPORTS ===
import os
import re
import random
import asyncio
import threading
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
    "Administrator": ["kick", "ban", "unban", "mute", "voicemute"],
    "Head Administrator": ["kick", "ban", "unban", "mute", "gban"],
    "Head Of Staff": ["all"],
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
ALLOWED_STREAMER_DOMAINS = ["twitch.tv", "youtube.com", "kick.com", "tiktok"]

def has_role_permission(ctx, command_name):
    for role in ctx.author.roles:
        for role_name, perms in MODERATION_ROLES.items():
            if role.name.lower() == role_name.lower():
                if perms == "all" or (perms and command_name in perms):
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
    slurs = ["spick", "nigger", "retarded"]  # Add more if needed
    content = message.content.lower()
    if any(slur in content for slur in slurs):
        await message.delete()
        try:
            await message.channel.send(f"🚫 {message.author.mention}, your message was removed for violating server rules.")
        except discord.Forbidden:
            pass
        try:
            await message.author.send("⚠️ You have been warned for using inappropriate language. Continued violations may lead to further actions.")
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
                await message.channel.send(f"🚫 {message.author.mention}, Discord invites are not allowed.")
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
                return

    await bot.process_commands(message)

# === MODERATION COMMANDS ===

@bot.command()
async def kick(ctx, user: discord.User):
    if not has_role_permission(ctx, "kick"):
        await ctx.send("❌ You do not have permission to use this command.")
        return
    member = ctx.guild.get_member(user.id)
    if member:
        await member.kick()
        await ctx.send(f"Kicked {member}")
    else:
        await ctx.send("User not found in this server.")

@bot.command()
async def ban(ctx, member: discord.Member, *, reason=None):
    if not has_role_permission(ctx, "ban"):
        await ctx.send("❌ You do not have permission to use this command.")
        return
    await member.ban(reason=reason)
    await ctx.send(f'🔨 {member} has been banned.')

@bot.command()
async def unban(ctx, *, user):
    banned_users = [entry async for entry in ctx.guild.bans()]

    if user.isdigit():
        user_id = int(user)
        for ban_entry in banned_users:
            if ban_entry.user.id == user_id:
                await ctx.guild.unban(ban_entry.user)
                await ctx.send(f"✅ Unbanned {ban_entry.user}")
                return
        await ctx.send("❌ User ID not found in ban list.")
        return

    if '#' in user:
        try:
            name, discriminator = user.split('#')
        except ValueError:
            await ctx.send("❌ Invalid format. Use Username#1234 or user ID.")
            return

        for ban_entry in banned_users:
            if ban_entry.user.name == name and ban_entry.user.discriminator == discriminator:
                await ctx.guild.unban(ban_entry.user)
                await ctx.send(f"✅ Unbanned {ban_entry.user}")
                return

        await ctx.send("❌ User not found in ban list.")
    else:
        await ctx.send("❌ Invalid format. Use Username#1234 or user ID.")

@bot.command()
async def mute(ctx, member: discord.Member):
    if not has_role_permission(ctx, "mute"):
        await ctx.send("❌ You do not have permission to use this command.")
        return
    overwrite = discord.PermissionOverwrite()
    overwrite.send_messages = False
    for channel in ctx.guild.text_channels:
        await channel.set_permissions(member, overwrite=overwrite)
    await ctx.send(f'✉️ {member} has been text-muted.')

@bot.command()
async def voicemute(ctx, member: discord.Member):
    if not has_role_permission(ctx, "voicemute"):
        await ctx.send("❌ You do not have permission to use this command.")
        return
    await member.edit(mute=True)
    await ctx.send(f'🔇 {member} has been voice-muted.')

@bot.command()
async def gban(ctx, user: discord.User, *, reason=None):
    if not has_role_permission(ctx, "ban"):
        await ctx.send("❌ You do not have permission to use this command.")
        return

    global global_ban_list
    if user.id in global_ban_list:
        await ctx.send(f"⚠️ {user} is already globally banned.")
        return

    global_ban_list.add(user.id)
    for guild in bot.guilds:
        member = guild.get_member(user.id)
        if member:
            try:
                await guild.ban(member, reason=f"Global Ban: {reason}")
            except discord.Forbidden:
                await ctx.send(f"❌ Failed to ban {user} in {guild.name} due to permissions.")
    await ctx.send(f'🌐 {user} has been globally banned from all servers.')

@bot.command()
async def ungban(ctx, user: discord.User):
    if not has_role_permission(ctx, "ban"):
        await ctx.send("❌ You do not have permission to use this command.")
        return
    global global_ban_list
    if user.id not in global_ban_list:
        await ctx.send(f"❌ {user} is not in the global ban list.")
        return
    global_ban_list.remove(user.id)
    await ctx.send(f'✅ {user} has been removed from the global ban list.')

@bot.command()
async def giverole(ctx, member: discord.Member, role: discord.Role):
    await member.add_roles(role)
    await ctx.send(f'🎖️ {member.mention} was given the role {role.name}')

@bot.command()
async def takerole(ctx, member: discord.Member, role: discord.Role):
    await member.remove_roles(role)
    await ctx.send(f'🧼 {role.name} was removed from {member.mention}')

@bot.command()
async def giveaway(ctx, duration: int, *, prize: str):
    await ctx.send(f'🎉 **GIVEAWAY** 🎉\nPrize: **{prize}**\nReact with 🎉 to enter!\nTime: {duration} seconds')
    message = await ctx.send("React below 👇")
    await message.add_reaction("🎉")
    await asyncio.sleep(duration)
    message = await ctx.channel.fetch_message(message.id)
    users = await message.reactions[0].users().flatten()
    users = [u for u in users if not u.bot]
    if users:
        winner = random.choice(users)
        await ctx.send(f'🎊 Congrats {winner.mention}, you won **{prize}**!')
    else:
        await ctx.send("No one entered the giveaway. 😢")

# === FLASK KEEP-ALIVE SERVER ===
app = Flask(__name__)

@app.route('/')
def index():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

# Start Flask server in a background thread
threading.Thread(target=run_flask).start()

# === RUN THE BOT ===
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
