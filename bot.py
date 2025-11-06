import discord
from discord.ext import commands
import asyncio
import yt_dlp
import os
from dotenv import load_dotenv
from collections import deque

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix='!', intents=intents)

YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
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

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

class MusicPlayer:
    def __init__(self):
        self.queue = deque()
        self.current = None
        self.voice_client = None
        self.volume = 0.5
        
    def add_to_queue(self, song):
        self.queue.append(song)
    
    def get_next(self):
        if self.queue:
            return self.queue.popleft()
        return None

music_players = {}

def get_player(guild_id):
    if guild_id not in music_players:
        music_players[guild_id] = MusicPlayer()
    return music_players[guild_id]

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.duration = data.get('duration')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if data and 'entries' in data:
            data = data['entries'][0]

        if not data:
            raise Exception("Could not extract video info")

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data)

async def play_next(ctx):
    player = get_player(ctx.guild.id)
    
    if player.voice_client and not player.voice_client.is_playing():
        next_song = player.get_next()
        if next_song:
            player.current = next_song
            try:
                async with ctx.typing():
                    audio_source = await YTDLSource.from_url(next_song['url'], loop=bot.loop, stream=True)
                    audio_source.volume = player.volume
                    
                    def after_playing(error):
                        if error:
                            print(f'Player error: {error}')
                            asyncio.run_coroutine_threadsafe(
                                ctx.send(f'An error occurred during playback: {str(error)}'),
                                bot.loop
                            )
                        asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)
                    
                    player.voice_client.play(audio_source, after=after_playing)
                    await ctx.send(f'Now playing: **{next_song["title"]}**')
            except Exception as e:
                await ctx.send(f'Failed to play **{next_song["title"]}**: {str(e)}')
                player.current = None
                await play_next(ctx)
        else:
            player.current = None
            await ctx.send('Queue is empty!')

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    print(f'Bot is ready to play music!')

@bot.command(name='join', help='Makes the bot join your voice channel')
async def join(ctx):
    if not ctx.message.author.voice:
        await ctx.send('You need to be in a voice channel to use this command!')
        return
    
    channel = ctx.message.author.voice.channel
    player = get_player(ctx.guild.id)
    
    if player.voice_client is None:
        player.voice_client = await channel.connect()
        await ctx.send(f'Joined {channel}')
    elif player.voice_client.channel != channel:
        await player.voice_client.move_to(channel)
        await ctx.send(f'Moved to {channel}')
    else:
        await ctx.send('Already in your voice channel!')

@bot.command(name='leave', help='Makes the bot leave the voice channel')
async def leave(ctx):
    player = get_player(ctx.guild.id)
    
    if player.voice_client:
        await player.voice_client.disconnect()
        player.voice_client = None
        player.queue.clear()
        player.current = None
        await ctx.send('Disconnected from voice channel!')
    else:
        await ctx.send('I am not in a voice channel!')

@bot.command(name='play', help='Plays a song from YouTube (URL or search query)')
async def play(ctx, *, url):
    if not ctx.message.author.voice:
        await ctx.send('You need to be in a voice channel to use this command!')
        return
    
    player = get_player(ctx.guild.id)
    channel = ctx.message.author.voice.channel
    
    if player.voice_client is None:
        try:
            player.voice_client = await channel.connect(timeout=60.0, reconnect=True)
        except Exception as e:
            await ctx.send(f'Failed to connect to voice channel: {str(e)}')
            return
    elif player.voice_client.channel != channel:
        await player.voice_client.move_to(channel)
    
    async with ctx.typing():
        try:
            data = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
            
            if data and 'entries' in data:
                data = data['entries'][0]
            
            if not data:
                await ctx.send('Could not find that song!')
                return
            
            song_info = {
                'url': url,
                'title': data.get('title'),
                'duration': data.get('duration')
            }
            
            if player.voice_client.is_playing() or player.current:
                player.add_to_queue(song_info)
                await ctx.send(f'Added to queue: **{song_info["title"]}**')
            else:
                player.current = song_info
                audio_source = await YTDLSource.from_url(url, loop=bot.loop, stream=True)
                audio_source.volume = player.volume
                
                def after_playing(error):
                    if error:
                        print(f'Player error: {error}')
                        asyncio.run_coroutine_threadsafe(
                            ctx.send(f'An error occurred during playback: {str(error)}'),
                            bot.loop
                        )
                    asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)
                
                player.voice_client.play(audio_source, after=after_playing)
                await ctx.send(f'Now playing: **{song_info["title"]}**')
        except Exception as e:
            print(f'Play command error: {e}')
            await ctx.send(f'An error occurred: {str(e)}')
            player.current = None
            await play_next(ctx)

@bot.command(name='pause', help='Pauses the currently playing song')
async def pause(ctx):
    player = get_player(ctx.guild.id)
    
    if player.voice_client and player.voice_client.is_playing():
        player.voice_client.pause()
        await ctx.send('Music paused!')
    else:
        await ctx.send('Nothing is playing right now!')

@bot.command(name='resume', help='Resumes the paused song')
async def resume(ctx):
    player = get_player(ctx.guild.id)
    
    if player.voice_client and player.voice_client.is_paused():
        player.voice_client.resume()
        await ctx.send('Music resumed!')
    else:
        await ctx.send('Music is not paused!')

@bot.command(name='stop', help='Stops playing and clears the queue')
async def stop(ctx):
    player = get_player(ctx.guild.id)
    
    if player.voice_client:
        player.queue.clear()
        player.current = None
        player.voice_client.stop()
        await ctx.send('Stopped playing and cleared the queue!')
    else:
        await ctx.send('I am not in a voice channel!')

@bot.command(name='skip', help='Skips the current song')
async def skip(ctx):
    player = get_player(ctx.guild.id)
    
    if player.voice_client and player.voice_client.is_playing():
        player.voice_client.stop()
        await ctx.send('Skipped the current song!')
    else:
        await ctx.send('Nothing is playing right now!')

@bot.command(name='queue', help='Shows the current queue')
async def queue_command(ctx):
    player = get_player(ctx.guild.id)
    
    if player.current:
        message = f'**Now Playing:** {player.current["title"]}\n\n'
    else:
        message = '**Nothing is currently playing**\n\n'
    
    if player.queue:
        message += '**Queue:**\n'
        for i, song in enumerate(player.queue, 1):
            message += f'{i}. {song["title"]}\n'
    else:
        message += 'Queue is empty!'
    
    await ctx.send(message)

@bot.command(name='volume', help='Changes the volume (0-100)')
async def volume(ctx, volume: int):
    player = get_player(ctx.guild.id)
    
    if not 0 <= volume <= 100:
        await ctx.send('Volume must be between 0 and 100!')
        return
    
    player.volume = volume / 100
    
    if player.voice_client and player.voice_client.source:
        player.voice_client.source.volume = player.volume
    
    await ctx.send(f'Volume set to {volume}%')

@bot.command(name='nowplaying', help='Shows information about the current song')
async def nowplaying(ctx):
    player = get_player(ctx.guild.id)
    
    if player.current:
        duration = player.current.get('duration')
        duration_str = f"{duration // 60}:{duration % 60:02d}" if duration else "Unknown"
        await ctx.send(f'**Now Playing:** {player.current["title"]}\n**Duration:** {duration_str}')
    else:
        await ctx.send('Nothing is playing right now!')

@bot.command(name='help_music', help='Shows all music commands')
async def help_music(ctx):
    help_text = """
**Music Bot Commands:**
`!join` - Join your voice channel
`!leave` - Leave the voice channel
`!play <URL or search>` - Play a song from YouTube
`!pause` - Pause the current song
`!resume` - Resume the paused song
`!stop` - Stop playing and clear queue
`!skip` - Skip the current song
`!queue` - Show the current queue
`!volume <0-100>` - Set the volume
`!nowplaying` - Show current song info
`!help_music` - Show this message
    """
    await ctx.send(help_text)

if __name__ == '__main__':
    TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    if not TOKEN:
        print('ERROR: DISCORD_BOT_TOKEN not found in environment variables!')
        print('Please add your Discord bot token to the Secrets.')
        exit(1)
    
    bot.run(TOKEN)
