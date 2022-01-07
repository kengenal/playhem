import os
import sys
import uuid

import discord
import asyncio

import youtube_dl

from discord import Forbidden
from tinydb import TinyDB, where

from http.server import HTTPServer, BaseHTTPRequestHandler

servers_db = TinyDB("./server_settings.json")

bot = discord.Bot()
db = TinyDB("./queue.json")

youtube_dl.utils.bug_reports_message = lambda: ''

invite_url = "https://discord.com/api/oauth2/authorize?client_id={}" \
             "&scope=bot&permissions=156803300672&scope=bot%20applications.commands "

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
    'source_address': '0.0.0.0'  # bind to ipv4 since ipv6 addresses cause issues sometimes
}

ffmpeg_options = {
    'options': '-vn'
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

play_next_song = asyncio.Event()


class YoutubeStream(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        try:
            loop = loop or asyncio.get_event_loop()
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
            if 'entries' in data:
                data = data['entries'][0]
            filename = data['url'] if stream else ytdl.prepare_filename(data)
            return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)
        except discord.HTTPException:
            raise Exception("Something goes wrong!")


async def play_queue(ctx):
    while db.count(where("server") == ctx.guild.id) > 0:
        play_next_song.clear()
        song = db.get(where("server") == ctx.guild.id)
        if not song:
            ctx.respond("Nothing to play")
            break
        db.update({"is_playing": True}, where("id") == song["id"])
        try:
            server_settings = servers_db.get(where("id") == ctx.guild.id)
            player = await YoutubeStream.from_url(song["name"], loop=bot.loop, stream=True)
            image = [x for x in player.data["thumbnails"] if x['height'] == 188][0]["url"]
            embed = discord.Embed(title=player.title)
            embed.set_image(url=image)
            embed.set_author(name=song["author"])
            await ctx.respond(embed=embed)
            ctx.voice_client.play(player, after=lambda e: toggle_next(song["id"]))
            if server_settings:
                ctx.voice_client.source.volume = float(server_settings["volume"])
            else:
                ctx.voice_client.source.volume = 0.5
            await play_next_song.wait()
        except Exception as error:
            print(error)
            toggle_next(song["id"])


def toggle_next(song_id=None):
    if song_id is not None:
        db.remove(where("id") == song_id)
    bot.loop.call_soon_threadsafe(play_next_song.set)


@bot.slash_command()
async def play(ctx, name=None):
    """ play music from youtube you first you need connect to voice channel """
    if name is not None:
        db.insert({
            "id": str(uuid.uuid4()),
            "name": name,
            "author": str(ctx.author.name),
            "server": int(ctx.guild.id),
            "is_playing": False
        })
        await ctx.respond(embed=discord.Embed(title=f"{str(ctx.author.name)} add {str(name)} to playlist"))
    if not db.get((where("is_playing") == True) & (where("server") == ctx.guild.id)):
        if ctx.voice_client is None:
            if not ctx.author.voice:
                return await ctx.respond(embed=discord.Embed(title="You are not connected to a voice channel."))
            channel = ctx.author.voice.channel
            await channel.connect()
        async with ctx.typing():
            bot.loop.create_task(play_queue(ctx=ctx))


@bot.slash_command()
async def skip(ctx):
    """ Skip song """
    song = db.get((where("is_playing") == True) & (where("server") == ctx.guild.id))
    if not song:
        return await ctx.voice_client.disconnect()
    ctx.voice_client.pause()
    toggle_next(song["id"])


@bot.slash_command()
async def leave(ctx):
    """ stop playing music """
    song = db.get((where("is_playing") == True) & (where("server") == ctx.guild.id))
    db.update({"is_playing": False}, where("id") == song["id"])
    ctx.voice_client.stop()
    await ctx.voice_client.disconnect()
    return await ctx.respond(embed=discord.Embed(title="This is the end!"))


@bot.slash_command()
async def volume(ctx, volume: int = None):
    """ Change volume  0 - 10 """
    name = "Playhem"
    if ctx.voice_client is None:
        return await ctx.send(embed=discord.Embed(title=f":face_with_symbols_over_mouth: {name} is not connected"))
    if not volume:
        return await volume_display(ctx=ctx, volume=int(ctx.voice_client.source.volume * 10))
    if volume > 10:
        volume = 10
    ctx.voice_client.source.volume = float(volume / 10)
    servers_db.update({"volume": float(volume / 10)})
    return await volume_display(ctx=ctx, volume=volume)


async def volume_display(ctx, volume: int):
    display_volume = ":loud_sound:  | "
    for i in range(1, 11):
        if i <= int(volume):
            display_volume += ":metal:"
        else:
            display_volume += ":fist:"
    display_volume += ' |'

    embed = discord.Embed(
        title=display_volume,
        description=f"Volume {volume}/10"
    )
    return await ctx.send(embed=embed)


@bot.event
async def on_guild_join(guild):
    if not servers_db.get(where("id") == guild.id):
        servers_db.insert({
            "volume": 0.5,
            "id": int(guild.id)
        })
        await guid_builder(guild.id)


async def guid_builder(guid_id):
    try:
        update_guild_commands = {guid_id: []}
        for command in [
            cmd
            for cmd in bot.pending_application_commands
            if cmd.guild_ids is not None
        ]:
            as_dict = command.to_dict()
            for guild_id in command.guild_ids:
                to_update = update_guild_commands[guild_id]
                update_guild_commands[guild_id] = to_update + [as_dict]
            for guild_id, guild_data in update_guild_commands.items():
                try:
                    await bot.http.bulk_upsert_guild_commands(
                        bot.user.id, guild_id, update_guild_commands[guild_id]
                    )
                except Forbidden:
                    if not guild_data:
                        continue
                    print(f"Failed to add command to guild {guild_id}", file=sys.stderr)
                    raise
    except Forbidden:
        print(f"Failed to add command to guild {guid_id}", file=sys.stderr)
        raise


class RedirectWebHttpHandler(BaseHTTPRequestHandler):
    def _redirect(self):
        self.send_response(301)
        self.send_header("Location", invite_url.format(os.getenv("CLIENT_ID")))
        self.end_headers()

    def do_GET(self):
        self._redirect()

    def do_POST(self):
        self._redirect()

    def do_HEAD(self):
        self._redirect()


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "web":
        server = HTTPServer(("0.0.0.0", int(sys.argv[2])), RedirectWebHttpHandler)
        server.serve_forever()
        server.server_close()
    else:
        bot.run(os.getenv("TOKEN"))


if __name__ == '__main__':
    main()
