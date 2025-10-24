from pathlib import Path
import random
from datetime import datetime, timedelta
from spotdl import Spotdl
from spotdl.types.song import Song
from spotipy import Spotify
from spotipy.exceptions import SpotifyException
from requests.exceptions import ReadTimeout
from spotipy.oauth2 import SpotifyClientCredentials
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2
import re, time, asyncio, datetime, subprocess, os
from requests.exceptions import ReadTimeout
from config.requestHandler import *
from config.songHandler import *
from config.BG_process_status import *
from config.blocker import *
from config.config import *
from config.smartCrossfader import crossfader
import aiofiles
import os, gc, requests

class TaskGroup:
    def __init__(self):
        self._tasks = set()

    def create_task(self, coro):
        task = asyncio.create_task(coro)  # Create the task from the coroutine
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)  # Remove completed tasks
        return task

taskgroup = TaskGroup()

# This function cancels an existing task (if found) and creates a new one
def manage_task(task_name: str, coro_func):
    task_list = list(taskgroup._tasks)

    # Cancel any existing task with the same name
    for task in task_list:
        if task.get_name() == task_name:
            task.cancel()

    # Create a new task and pass the coroutine (as a callable)
    new_task = taskgroup.create_task(coro_func)  # Pass the coroutine function itself
    new_task.set_name(task_name)

    return new_task  # Return the task for awaiting later


async def async_copy_file(src_path, dest_path, title=None):
    """Asynchronously apply fade-in/out using FFmpeg and save the result."""
    print("🎶 Copying the song...")

    try:
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",  # overwrite output
            "-i", src_path,
            "-c:a", "libmp3lame",
            "-b:a", "192k",
            dest_path
        ]

        proc = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )

        stdout, stderr = await proc.communicate()
        
        """await crossfader()"""

        if proc.returncode != 0:
            print(f"💥 FFmpeg failed with code {proc.returncode}")
            print(stderr.decode())
        else:
            print(f"✅ Song copied to: {dest_path}")
            if title:
                await update_mp3_metadata(dest_path, title)

    except Exception as e:
        print(f"💥 Error in async_copy_file_with_fade: {e}")
    
async def update_mp3_metadata(mp3_path, title):
    audio = MP3(mp3_path, ID3=ID3)

    try:
        audio.add_tags()
    except Exception:
        pass  # Ignore if tags already exist

    audio.tags.add(TIT2(encoding=3, text=title))
    audio.save()
    print(f"🎧 Metadata updated to: {title} for {mp3_path}")
    from config.file_updater import nxt
    nxt.next_up = title
    
def get_track_details_by_id(track_id: str):
    """Fetch full track details by track ID for direct use in save_to_next_coming."""
    try:
        track_data = sp.track(track_id)  # Spotify client call
    except Exception as e:
        print(f"⚠️ Error fetching track {track_id}: {e}")
        return None

    if not track_data or "id" not in track_data:
        print(f"⚠️ No valid data returned for track ID: {track_id}")
        return None

    track_name = track_data["name"]
    track_artist = ", ".join(artist["name"] for artist in track_data["artists"])

    return {
        "track": track_data,  # Raw object for save_to_next_coming
        "id": track_data["id"],
        "name": track_name,
        "artist": track_artist,
        "album": track_data["album"]["name"],
        "query": f"{track_name} {track_artist}",
        "duration": track_data["duration_ms"] // 1000,
        "url": track_data["external_urls"]["spotify"],
    }


def create_spotify_client(retries=3, delay=5):
    for attempt in range(retries):
        try:
            return Spotify(auth_manager=SpotifyClientCredentials(
                client_id=Authorization.SPOTIPY_CLIENT_ID,
                client_secret=Authorization.SPOTIPY_CLIENT_SECRET,
                requests_timeout=30
            ))
        except Exception as e:
            print(f"🚨 Spotify Auth Error (attempt {attempt+1}/{retries}): {e}")
            time.sleep(delay * (attempt + 1))  # exponential backoff
    raise Exception("❌ Failed to authenticate with Spotify after multiple attempts.")

# Authenticate with Spotify
sp = create_spotify_client()

def check_song_duration(search_query: str, expected_duration: int | None = None) -> str | None:
    import yt_dlp, difflib

    search_url = f"ytsearch15:{search_query}"  # Search more results
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'extract_flat': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_url, download=False)

            best_score = -1
            best_entry_url = None
            best_entry_name = None

            for entry in info.get("entries", []):
                title = entry.get("title", "").lower()
                duration = entry.get("duration") or 0
                url = entry.get("url")

                # Normalize URL
                url = url if url.startswith("http") else f"https://www.youtube.com/watch?v={url}"

                # --- Step 1: Duration scoring ---
                duration_score = 0
                if expected_duration:
                    # Penalize difference from expected duration
                    diff = abs(duration - expected_duration)
                    duration_score = max(0, 100 - diff)  # closer = higher score
                else:
                    # Default "reasonable song length"
                    if 90 <= duration <= 480:
                        duration_score = 50

                # --- Step 2: Title similarity scoring ---
                title_score = difflib.SequenceMatcher(None, search_query.lower(), title).ratio() * 100

                # --- Step 3: Channel/keyword penalty ---
                penalty = 0
                for bad in ["cover", "remix", "live", "karaoke"]:
                    if bad in title:
                        penalty -= 30

                # --- Step 4: Combine score ---
                score = duration_score + title_score + penalty

                print(f"🔍 {title} ({duration}s) -> Score {score:.1f}")

                if score > best_score:
                    best_score = score
                    best_entry_url = url
                    best_entry_name = title

            if best_entry_url:
                print(f"✅ Selected: {best_entry_name} ({best_entry_url}) (Score {best_score:.1f})")
                return best_entry_url

    except Exception as e:
        print(f"⚠️ Error: {e}")

    return None

async def download_song(video_url: str, track_id: str) -> str | None:
    import yt_dlp, os, asyncio, gc

    COOKIES_FILE = 'cookies.txt'
    BACKUP_COOKIES = 'backup_cookies.txt'

    base_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{track_id}.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'noplaylist': True,
        'quiet': True,
        'cachedir': False,
        'socket_timeout': 60,
        'retries': 3,
        'geo_bypass': True,
        'cookiefile': COOKIES_FILE,
        'noprogress': True,
    }

    mp3_file = f"{track_id}.mp3"
    loop = asyncio.get_running_loop()

    def _download(video_url, opts):
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([video_url])

    for attempt in range(3):
        try:
            print(f"⬇️ Downloading '{track_id}' (Attempt {attempt+1})...")

            opts = dict(base_opts)
            if attempt > 0 and os.path.exists(BACKUP_COOKIES):
                print("🔄 Switching to backup cookies...")
                opts['cookiefile'] = BACKUP_COOKIES

            await loop.run_in_executor(None, _download, video_url, opts)

            if os.path.exists(mp3_file):
                print(f"✅ Successfully downloaded: {mp3_file}")
                gc.collect()  # free RAM
                return mp3_file
            else:
                print(f"⚠️ Download finished but MP3 not found: {mp3_file}")
        except Exception as e:
            print(f"⚠️ Attempt {attempt+1} failed: {e}")

    print(f"❌ Failed to download '{track_id}' after 3 attempts")
    gc.collect()
    return None

async def song_downloader():
    songDownloader.song_downloader = True
    await asyncio.sleep(5) # Wait for 5 seconds to start the current song timer
    request = get_request()
    if request:
        spotify_id = request.spotifyID
        requester = request.requester
        duration = request.duration // 1000  # convert to seconds
        if spotify_id:
            asyncio.create_task(download_song_from_id(spotify_id, requester, duration))
            remove_request(spotify_id)
    else:
        asyncio.create_task(download_song_from_playlist())

async def download_song_from_id(track_id, requester, length):
    """
    Downloads a song using its Spotify track ID.
    
    Args:
        track_id (str): Spotify track ID.
    
    Returns:
        tuple: Filename of the downloaded song and time spent (in seconds).
    """
    
    try:
        # Get track details using Spotify API
        for attempt in range(3):
            try:
                track = sp.track(track_id)
            except ReadTimeout as e:
                print(f"Attempt {attempt+1}: Spotify timeout or error - {e}")
        track_name = track['name']
        artist_name = ", ".join(artist['name'] for artist in track['artists'])
        album_name = track['album']['name']
        save_to_next_coming(track, requester)
        print(f"Found track: {track_name} by {artist_name}")
        
        # Sanitize track name for filename (removes any special characters)
        track_name_sanitized = re.sub(r'[\\/*?:"<>|]', "", track_name)
        
        video_url = check_song_duration(f"{track_name_sanitized} {artist_name} {album_name}", length)

        source_file = await download_song(video_url, track_id)
        
        if not source_file or not os.path.exists(source_file):
            print(f"⚠️ Skipping overwriting — download failed for {track_id}")
            return

        current_file = fetch_current_file()
        target_file = current_file.get("next_coming")
        
        # Copy file asynchronously
        await async_copy_file(source_file, target_file, f"{track_name} - {artist_name}")
                
        if os.path.exists(source_file):
            os.remove(source_file)
            
        # Load the audio file
        audio = MP3(target_file)

        # Get the duration in seconds
        duration = audio.info.length
            
        next_coming_data = load_json(next_coming_file)
        
        if next_coming_data:
            next_coming_data[0]["duration"] = int(duration * 1000)
            next_coming_data[0]["durationsec"] = int(duration)
            next_coming_data[0]["remaining"] = int(duration)
            
        save_json(next_coming_file, next_coming_data)
        songDownloader.song_downloader = False
            
    except SpotifyException as e:
        print(f"Spotify API error: {e}")
    except Exception as e:
        print(f"Error downloading the song: {e}")


def get_next_song_from_playlist():
    """Get a random song from a random playlist."""
    while True:
        track = Objects.pl.next_song()

        track_name = track['title']
        track_artist = track['artists']
        track_album = track['album']
        track_id = track['track_id']
        track_duration_sec = track['duration_sec']
        
        if is_song_blocked(track_id):
            print(f"Track {track_name} by {track_artist} was already blocked. Trying another track...")
            continue

        # Check if the track was played recently
        if track_already_played_id(track_id):
            print(f"Track {track_name} by {track_artist} was played recently. Trying another track...")
            continue  # Pick another track
        
        track_data = get_track_details_by_id(track_id)

        save_to_next_coming(track_data, "PewDJ")
        return track_name, track_artist, track_id, f"{track_name} {track_artist} {track_album}", track_duration_sec

async def download_song_from_playlist():
    
    # Keep selecting a song until we find one that hasn't been played
        
    track_name, track_artist, track_id, search_query, track_duration_sec = get_next_song_from_playlist()

    print(f"⬇️ Downloading: {track_name} by {track_artist} (Track ID: {track_id})")

    video_url = check_song_duration(search_query, track_duration_sec)

    source_file = await download_song(video_url, track_id)
    
    if not source_file or not os.path.exists(source_file):
        print(f"⚠️ Skipping overwriting — download failed for {track_id}")
        return

    current_file = fetch_current_file()
    target_file = current_file.get("next_coming")
        
        
    # Copy file asynchronously
    await async_copy_file(source_file, target_file, f"{track_name} - {track_artist}")
            
    if os.path.exists(source_file):
        os.remove(source_file)
        
    # Load the audio file
    audio = MP3(target_file)

    # Get the duration in seconds
    duration = audio.info.length
        
    next_coming_data = load_json(next_coming_file)
    
    if next_coming_data:
        next_coming_data[0]["duration"] = int(duration * 1000)
        next_coming_data[0]["durationsec"] = int(duration)
        next_coming_data[0]["remaining"] = int(duration)
        
    save_json(next_coming_file, next_coming_data)
    songDownloader.song_downloader = False
    
async def create_silent_audio(duration):
    """
    Creates a silent audio file of the given duration (in seconds) using FFmpeg.

    Args:
        output_file (str): The name of the output audio file (e.g., "silence.mp3").
        duration (int): The duration of the silent audio in seconds.
    """
    
    output_file = "silent_audio.mp3"
    command = [
        "ffmpeg",
        "-f", "lavfi",
        "-t", str(duration),
        "-i", "anullsrc",
        "-q:a", "9",
        "-acodec", "libmp3lame",
        output_file
    ]
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    current_file = fetch_current_file()
    source_file = output_file
    target_file = current_file.get("now_playing")

    # Copy file asynchronously
    await async_copy_file(source_file, target_file)
    print(f"Skipping by updating {target_file} with {source_file}")
            
    if os.path.exists(source_file):
        os.remove(source_file)
        
    skip.skip_status = True