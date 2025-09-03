import discord
from discord.ext import commands
import asyncio
import yt_dlp
import os
from collections import deque
import urllib.parse
import re

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix='.', intents=intents, help_command=None)

# Custom emojis (using Unicode alternatives)
EMOJIS = {
    'play': '▶️',
    'pause': '⏸️',
    'stop': '⏹️',
    'skip': '⏭️',
    'previous': '⏮️',
    'shuffle': '🔀',
    'repeat': '🔁',
    'volume_up': '🔊',
    'volume_down': '🔉',
    'volume_mute': '🔇',
    'queue': '📋',
    'music': '🎵',
    'headphones': '🎧',
    'speaker': '🔊',
    'microphone': '🎤',
    'cd': '💿',
    'radio': '📻',
    'musical_note': '🎶',
    'success': '✅',
    'error': '❌',
    'warning': '⚠️',
    'info': 'ℹ️',
    'loading': '⏳'
}

# YouTube-DL options
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.duration = data.get('duration')
        self.thumbnail = data.get('thumbnail')
        self.uploader = data.get('uploader')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        
        if 'entries' in data:
            data = data['entries'][0]
        
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

class MusicPlayer:
    def __init__(self, bot):
        self.bot = bot
        self.queue = deque()
        self.history = deque(maxlen=10)
        self.current = None
        self.voice_client = None
        self.volume = 0.5
        self.loop = False
        self.shuffle = False
        self.paused = False
        
    def is_playing(self):
        return self.voice_client and self.voice_client.is_playing()
    
    def is_paused(self):
        return self.voice_client and self.voice_client.is_paused()
    
    async def add_to_queue(self, song):
        self.queue.append(song)
    
    async def play_next(self, ctx):
        if self.loop and self.current:
            source = await YTDLSource.from_url(self.current.url, loop=self.bot.loop, stream=True)
            self.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self.play_next(ctx), self.bot.loop))
            return
            
        if not self.queue:
            return
            
        if self.shuffle:
            import random
            song = random.choice(self.queue)
            self.queue.remove(song)
        else:
            song = self.queue.popleft()
            
        if self.current:
            self.history.append(self.current)
            
        try:
            source = await YTDLSource.from_url(song['url'], loop=self.bot.loop, stream=True)
            source.volume = self.volume
            self.current = source
            self.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self.play_next(ctx), self.bot.loop))
            
            embed = discord.Embed(
                title=f"{EMOJIS['music']} Now Playing",
                description=f"**{source.title}**",
                color=0x00ff00
            )
            if source.thumbnail:
                embed.set_thumbnail(url=source.thumbnail)
            if source.uploader:
                embed.add_field(name=f"{EMOJIS['microphone']} Uploader", value=source.uploader, inline=True)
            if source.duration:
                mins, secs = divmod(source.duration, 60)
                embed.add_field(name=f"{EMOJIS['info']} Duration", value=f"{int(mins):02d}:{int(secs):02d}", inline=True)
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            embed = discord.Embed(
                title=f"{EMOJIS['error']} Error",
                description=f"Could not play the song: {str(e)}",
                color=0xff0000
            )
            await ctx.send(embed=embed)
            await self.play_next(ctx)

# Global music players for each guild
music_players = {}

def get_player(guild_id):
    if guild_id not in music_players:
        music_players[guild_id] = MusicPlayer(bot)
    return music_players[guild_id]

@bot.event
async def on_ready():
    print(f'{EMOJIS["success"]} {bot.user} is now online!')
    print(f'{EMOJIS["info"]} Loaded in {len(bot.guilds)} servers')
    
    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        print(f'{EMOJIS["success"]} Synced {len(synced)} slash commands')
    except Exception as e:
        print(f'{EMOJIS["error"]} Failed to sync commands: {e}')

# MUSIC COMMANDS

@bot.command(name='play', aliases=['p'])
async def play(ctx, *, query):
    """Play a song or add to queue"""
    if not ctx.author.voice:
        embed = discord.Embed(
            title=f"{EMOJIS['error']} Error",
            description="You need to be in a voice channel!",
            color=0xff0000
        )
        await ctx.send(embed=embed)
        return
        
    player = get_player(ctx.guild.id)
    
    if not player.voice_client:
        player.voice_client = await ctx.author.voice.channel.connect()
    
    embed = discord.Embed(
        title=f"{EMOJIS['loading']} Searching...",
        description=f"Looking for: **{query}**",
        color=0xffff00
    )
    message = await ctx.send(embed=embed)
    
    try:
        # Search for the song
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(f"ytsearch:{query}", download=False))
        
        if 'entries' in data and data['entries']:
            song_data = data['entries'][0]
            song_info = {
                'url': song_data['url'],
                'title': song_data['title'],
                'duration': song_data.get('duration'),
                'thumbnail': song_data.get('thumbnail'),
                'uploader': song_data.get('uploader'),
                'requester': ctx.author
            }
            
            if player.is_playing() or player.queue:
                await player.add_to_queue(song_info)
                
                embed = discord.Embed(
                    title=f"{EMOJIS['success']} Added to Queue",
                    description=f"**{song_info['title']}**",
                    color=0x00ff00
                )
                embed.add_field(name=f"{EMOJIS['queue']} Position", value=len(player.queue), inline=True)
                if song_info['thumbnail']:
                    embed.set_thumbnail(url=song_info['thumbnail'])
                embed.set_footer(text=f"Requested by {ctx.author.display_name}")
                
                await message.edit(embed=embed)
            else:
                await player.add_to_queue(song_info)
                await player.play_next(ctx)
                await message.delete()
        else:
            embed = discord.Embed(
                title=f"{EMOJIS['error']} Error",
                description="No songs found with that query!",
                color=0xff0000
            )
            await message.edit(embed=embed)
            
    except Exception as e:
        embed = discord.Embed(
            title=f"{EMOJIS['error']} Error",
            description=f"An error occurred: {str(e)}",
            color=0xff0000
        )
        await message.edit(embed=embed)

@bot.command(name='pause')
async def pause(ctx):
    """Pause the current song"""
    player = get_player(ctx.guild.id)
    
    if player.is_playing():
        player.voice_client.pause()
        player.paused = True
        embed = discord.Embed(
            title=f"{EMOJIS['pause']} Paused",
            description="Music has been paused",
            color=0xffff00
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title=f"{EMOJIS['error']} Error",
            description="Nothing is currently playing!",
            color=0xff0000
        )
        await ctx.send(embed=embed)

@bot.command(name='resume')
async def resume(ctx):
    """Resume the current song"""
    player = get_player(ctx.guild.id)
    
    if player.is_paused():
        player.voice_client.resume()
        player.paused = False
        embed = discord.Embed(
            title=f"{EMOJIS['play']} Resumed",
            description="Music has been resumed",
            color=0x00ff00
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title=f"{EMOJIS['error']} Error",
            description="Music is not paused!",
            color=0xff0000
        )
        await ctx.send(embed=embed)

@bot.command(name='stop')
async def stop(ctx):
    """Stop the music and clear queue"""
    player = get_player(ctx.guild.id)
    
    if player.voice_client:
        player.voice_client.stop()
        player.queue.clear()
        player.current = None
        embed = discord.Embed(
            title=f"{EMOJIS['stop']} Stopped",
            description="Music stopped and queue cleared",
            color=0xff0000
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title=f"{EMOJIS['error']} Error",
            description="Nothing is currently playing!",
            color=0xff0000
        )
        await ctx.send(embed=embed)

@bot.command(name='skip', aliases=['s'])
async def skip(ctx):
    """Skip the current song"""
    player = get_player(ctx.guild.id)
    
    if player.voice_client and player.voice_client.is_playing():
        player.voice_client.stop()
        embed = discord.Embed(
            title=f"{EMOJIS['skip']} Skipped",
            description="Skipped to next song",
            color=0x00ff00
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title=f"{EMOJIS['error']} Error",
            description="Nothing is currently playing!",
            color=0xff0000
        )
        await ctx.send(embed=embed)

@bot.command(name='queue', aliases=['q'])
async def queue(ctx):
    """Show the current queue"""
    player = get_player(ctx.guild.id)
    
    if not player.queue and not player.current:
        embed = discord.Embed(
            title=f"{EMOJIS['queue']} Queue",
            description="The queue is empty!",
            color=0xff0000
        )
        await ctx.send(embed=embed)
        return
    
    embed = discord.Embed(
        title=f"{EMOJIS['queue']} Music Queue",
        color=0x3498db
    )
    
    if player.current:
        embed.add_field(
            name=f"{EMOJIS['music']} Now Playing",
            value=f"**{player.current.title}**",
            inline=False
        )
    
    if player.queue:
        queue_text = ""
        for i, song in enumerate(list(player.queue)[:10], 1):
            queue_text += f"`{i}.` **{song['title']}**\n"
        
        embed.add_field(
            name=f"{EMOJIS['musical_note']} Up Next",
            value=queue_text,
            inline=False
        )
        
        if len(player.queue) > 10:
            embed.set_footer(text=f"And {len(player.queue) - 10} more songs...")
    
    await ctx.send(embed=embed)

@bot.command(name='volume', aliases=['vol'])
async def volume(ctx, volume: int = None):
    """Change or show volume (0-100)"""
    player = get_player(ctx.guild.id)
    
    if volume is None:
        embed = discord.Embed(
            title=f"{EMOJIS['speaker']} Volume",
            description=f"Current volume: **{int(player.volume * 100)}%**",
            color=0x3498db
        )
        await ctx.send(embed=embed)
        return
    
    if volume < 0 or volume > 100:
        embed = discord.Embed(
            title=f"{EMOJIS['error']} Error",
            description="Volume must be between 0 and 100!",
            color=0xff0000
        )
        await ctx.send(embed=embed)
        return
    
    player.volume = volume / 100
    if player.voice_client and player.voice_client.source:
        player.voice_client.source.volume = player.volume
    
    if volume == 0:
        emoji = EMOJIS['volume_mute']
    elif volume < 50:
        emoji = EMOJIS['volume_down']
    else:
        emoji = EMOJIS['volume_up']
    
    embed = discord.Embed(
        title=f"{emoji} Volume Changed",
        description=f"Volume set to **{volume}%**",
        color=0x00ff00
    )
    await ctx.send(embed=embed)

@bot.command(name='loop')
async def loop(ctx):
    """Toggle loop mode"""
    player = get_player(ctx.guild.id)
    player.loop = not player.loop
    
    embed = discord.Embed(
        title=f"{EMOJIS['repeat']} Loop {'Enabled' if player.loop else 'Disabled'}",
        description=f"Loop mode is now {'ON' if player.loop else 'OFF'}",
        color=0x00ff00 if player.loop else 0xff0000
    )
    await ctx.send(embed=embed)

@bot.command(name='shuffle')
async def shuffle(ctx):
    """Toggle shuffle mode"""
    player = get_player(ctx.guild.id)
    player.shuffle = not player.shuffle
    
    embed = discord.Embed(
        title=f"{EMOJIS['shuffle']} Shuffle {'Enabled' if player.shuffle else 'Disabled'}",
        description=f"Shuffle mode is now {'ON' if player.shuffle else 'OFF'}",
        color=0x00ff00 if player.shuffle else 0xff0000
    )
    await ctx.send(embed=embed)

@bot.command(name='disconnect', aliases=['dc', 'leave'])
async def disconnect(ctx):
    """Disconnect from voice channel"""
    player = get_player(ctx.guild.id)
    
    if player.voice_client:
        await player.voice_client.disconnect()
        player.voice_client = None
        player.queue.clear()
        player.current = None
        
        embed = discord.Embed(
            title=f"{EMOJIS['success']} Disconnected",
            description="Successfully disconnected from voice channel",
            color=0x00ff00
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title=f"{EMOJIS['error']} Error",
            description="Not connected to a voice channel!",
            color=0xff0000
        )
        await ctx.send(embed=embed)

@bot.command(name='nowplaying', aliases=['np'])
async def nowplaying(ctx):
    """Show current song info"""
    player = get_player(ctx.guild.id)
    
    if not player.current:
        embed = discord.Embed(
            title=f"{EMOJIS['error']} Error",
            description="Nothing is currently playing!",
            color=0xff0000
        )
        await ctx.send(embed=embed)
        return
    
    embed = discord.Embed(
        title=f"{EMOJIS['headphones']} Now Playing",
        description=f"**{player.current.title}**",
        color=0x3498db
    )
    
    if player.current.thumbnail:
        embed.set_thumbnail(url=player.current.thumbnail)
    
    if player.current.uploader:
        embed.add_field(name=f"{EMOJIS['microphone']} Uploader", value=player.current.uploader, inline=True)
    
    if player.current.duration:
        mins, secs = divmod(player.current.duration, 60)
        embed.add_field(name=f"{EMOJIS['info']} Duration", value=f"{int(mins):02d}:{int(secs):02d}", inline=True)
    
    embed.add_field(name=f"{EMOJIS['speaker']} Volume", value=f"{int(player.volume * 100)}%", inline=True)
    embed.add_field(name=f"{EMOJIS['repeat']} Loop", value="ON" if player.loop else "OFF", inline=True)
    embed.add_field(name=f"{EMOJIS['shuffle']} Shuffle", value="ON" if player.shuffle else "OFF", inline=True)
    embed.add_field(name=f"{EMOJIS['queue']} Queue", value=f"{len(player.queue)} songs", inline=True)
    
    await ctx.send(embed=embed)

# SLASH COMMANDS

@bot.tree.command(name="play", description="Play a song or add to queue")
async def slash_play(interaction: discord.Interaction, query: str):
    """Slash command version of play"""
    ctx = await bot.get_context(interaction)
    await play(ctx, query=query)

@bot.tree.command(name="pause", description="Pause the current song")
async def slash_pause(interaction: discord.Interaction):
    """Slash command version of pause"""
    ctx = await bot.get_context(interaction)
    await pause(ctx)

@bot.tree.command(name="resume", description="Resume the current song")
async def slash_resume(interaction: discord.Interaction):
    """Slash command version of resume"""
    ctx = await bot.get_context(interaction)
    await resume(ctx)

@bot.tree.command(name="skip", description="Skip the current song")
async def slash_skip(interaction: discord.Interaction):
    """Slash command version of skip"""
    ctx = await bot.get_context(interaction)
    await skip(ctx)

@bot.tree.command(name="stop", description="Stop music and clear queue")
async def slash_stop(interaction: discord.Interaction):
    """Slash command version of stop"""
    ctx = await bot.get_context(interaction)
    await stop(ctx)

@bot.tree.command(name="queue", description="Show the current queue")
async def slash_queue(interaction: discord.Interaction):
    """Slash command version of queue"""
    ctx = await bot.get_context(interaction)
    await queue(ctx)

@bot.tree.command(name="volume", description="Change volume (0-100)")
async def slash_volume(interaction: discord.Interaction, volume: int):
    """Slash command version of volume"""
    ctx = await bot.get_context(interaction)
    await volume(ctx, volume=volume)

@bot.tree.command(name="nowplaying", description="Show current song info")
async def slash_nowplaying(interaction: discord.Interaction):
    """Slash command version of nowplaying"""
    ctx = await bot.get_context(interaction)
    await nowplaying(ctx)

# HELP COMMAND

@bot.command(name='help')
async def music_help(ctx):
    """Show help for music commands"""
    embed = discord.Embed(
        title=f"{EMOJIS['cd']} Music Bot Commands",
        description="Use `.command` or `/command` for slash commands",
        color=0x3498db
    )
    
    playback_cmds = f"""
    `play <song/url/playlist>` - Play song, URL, or playlist
    `pause` - Pause current song
    `resume` - Resume paused song
    `stop` - Stop music and clear queue
    `skip` - Skip to next song
    `disconnect` - Leave voice channel
    """
    
    queue_cmds = f"""
    `queue` - Show current queue
    `nowplaying` - Show current song info
    `loop` - Toggle loop mode
    `shuffle` - Toggle shuffle mode
    `volume <0-100>` - Change volume
    """
    
    embed.add_field(name=f"{EMOJIS['play']} Playback", value=playback_cmds, inline=False)
    embed.add_field(name=f"{EMOJIS['queue']} Queue & Info", value=queue_cmds, inline=False)
    
    embed.set_footer(text="Bot made with ❤️")
    await ctx.send(embed=embed)

# Error handling
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(
            title=f"{EMOJIS['error']} Missing Argument",
            description=f"Please provide: **{error.param.name}**",
            color=0xff0000
        )
        await ctx.send(embed=embed)
    elif isinstance(error, commands.CommandNotFound):
        pass  # Ignore unknown commands
    else:
        embed = discord.Embed(
            title=f"{EMOJIS['error']} Error",
            description=f"An error occurred: {str(error)}",
            color=0xff0000
        )
        await ctx.send(embed=embed)
        print(f"Error: {error}")

# Run the bot
bot.run(os.getenv('DISCORD_TOKEN'))
