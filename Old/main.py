import asyncio
from config.file_updater import looper_updater
from config.songHandler import *
from WebAPI.web_api import start_server_async
from Websocket.websocket import start_ws_server_async
from config.PlaylistHandler import SpotifyPlaylistFetcher

# Paths to your MP3 files
audio_files = ["Audio/audio1.mp3", "Audio/audio2.mp3"]

stream_url = "icecast://source:Study@hard819@80.225.211.98:8261/pewhits"

async def stream_audio():
    command = [
        "ffmpeg",
        "-re",                # Read input in real-time
        "-stream_loop", "-1", # Loop the playlist infinitely
        "-i", "concat:Audio/audio1.mp3|Audio/audio2.mp3",  # Use the 'concat:' protocol for looping
        "-vn",                # Disable video streams
        "-c:a", "libmp3lame", # Use MP3 encoder
        "-b:a", "128k",       # Set bitrate to 128 kbps
        "-f", "mp3",          # Output format
        stream_url            # Icecast stream URL
    ]
            
    print(f"Starting seamless stream to {stream_url}")

    # Run the subprocess in an asynchronous way
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE  # Capture stderr silently
    )
        
        
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        print("❌ FFmpeg error:")
        print(stderr.decode())
            
async def stream_with_looper():
    while True:
        try:
            print("🔁 Starting looper + stream")
            looper_task = asyncio.create_task(looper_updater())
            await stream_audio()  # will block until FFmpeg dies
        except Exception as e:
            print(f"💥 Stream crashed: {e}")
        finally:
            print("🧹 Cleaning up looper...")
            looper_task.cancel()
            await asyncio.sleep(5)

async def main():
    print("🚀 Launching all systems!\n")
    reset_current_file()
    
    Objects.pl = SpotifyPlaylistFetcher()

    await asyncio.gather(
        start_server_async(),
        start_ws_server_async(),
        stream_with_looper()
    )

if __name__ == "__main__":
    # Run the main async function
    asyncio.run(main())