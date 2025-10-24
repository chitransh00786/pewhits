import asyncio
from config.songHandler import reset_current_file
from config.BG_process_status import Objects
from WebAPI.web_api import start_server_async
from Websocket.websocket import start_ws_server_async
from config.PlaylistHandler import SpotifyPlaylistFetcher




# ---------------------------------------------------------------------



import socket
import base64
import subprocess
import time
import os
import requests
from collections import deque
from config.config import config
from config.state import next_coming, now_playing


def connect_to_icecast():
    """Establishes connection and authenticates with Icecast server."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        sock.settimeout(10)
        sock.connect((config.SERVER_HOST, config.SERVER_PORT))

        auth = f"source:{config.STREAM_PASSWORD}"
        headers = (
            f"PUT {config.MOUNT_POINT} HTTP/1.0\r\n"
            f"Authorization: Basic {base64.b64encode(auth.encode()).decode()}\r\n"
            f"Content-Type: audio/mpeg\r\n"
            f"ice-name: Pew Hits\r\n"
            f"ice-description: The best tunes, 24/7 live!\r\n"
            f"ice-genre: Ambient\r\n"
            f"ice-url: http://{config.SERVER_HOST}:{config.SERVER_PORT}{config.MOUNT_POINT}\r\n"
            f"ice-public: 1\r\n"
            f"ice-audio-info: bitrate={config.BITRATE.replace('k','')}\r\n"
            f"\r\n"
        )

        sock.sendall(headers.encode("utf-8"))
        response = sock.recv(1024).decode("utf-8", errors="ignore")

        print(f"[CONNECT] Server response: {response.strip()}")

        if "200 OK" in response:
            print("[CONNECT] Connected and authenticated successfully.")
            return sock
        else:
            print("[CONNECT] Authentication failed or bad response.")
            sock.close()
            return None
    except Exception as e:
        print(f"[CONNECT] Error connecting to Icecast: {e}")
        return None

def stream_audio(sock, audio_file):
    try:
        if not os.path.exists(audio_file):
            raise FileNotFoundError(f"{audio_file} not found!")

        command = [
            "ffmpeg",
            "-re",                      # real-time mode
            "-i", audio_file,           # input file
            "-c:a", "libmp3lame",       # encode to mp3
            "-ar", "44100",             # sample rate
            "-b:a", config.BITRATE,     # bitrate
            "-f", "mp3",                # output format
            "-content_type", "audio/mpeg",
            "-"                         # output to stdout
        ]

        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        

        print(f"[STREAM] Streaming {audio_file}...")
        while True:
            data = process.stdout.read(4096)
            if not data:
                print("[STREAM] Finished streaming (file ended). Restarting loop...")
                break
            try:
                sock.sendall(data)
            except (BrokenPipeError, ConnectionResetError):
                print("[STREAM] Connection lost during stream.")
                process.terminate()
                return False
        process.terminate()
        return True

    except Exception as e:
        print(f"[STREAM] Error while streaming: {e}")
        return False
        

async def stream_audio(sock):
    """
    Streams URLs from next_coming deque to Icecast.
    Updates now_playing deque with current URL.
    Streams fallback file if next_coming is empty.
    """
    from config.DJ import song_downloader
    while True:
        
        await song_downloader()
        
        # --- Get next URL ---
        if next_coming:
            url = next_coming.popleft()
            now_playing.clear()
            now_playing.append(url)
            print(f"[STREAM] Now playing: {url}")
            source_type = "youtube" if url.startswith("http") else "file"
        else:
            url = config.AUDIO_FILE
            source_type = "file"
            now_playing.clear()
            now_playing.append(url)
            print(f"[STREAM] No next song, streaming fallback: {url}")

        try:
            if source_type == "youtube":
                # YouTube streaming
                yt_process = subprocess.Popen(
                    ["/home/container/.local/bin/yt-dlp", "-o", "-", "-f", "bestaudio", url],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                ffmpeg_process = subprocess.Popen(
                    ["ffmpeg", "-re", "-i", "pipe:0",
                     "-c:a", "libmp3lame", "-b:a", config.BITRATE,
                     "-ar", "44100", "-f", "mp3",
                     "-content_type", "audio/mpeg", "-"],
                    stdin=yt_process.stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                yt_process.stdout.close()

                # Streaming loop
                while True:
                    chunk = ffmpeg_process.stdout.read(4096)
                    if not chunk:
                        print("[STREAM] Finished YouTube URL, moving to next...")
                        break
                    try:
                        sock.sendall(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        print("[STREAM] Connection lost!")
                        yt_process.kill()
                        ffmpeg_process.kill()
                        return
                    time.sleep(0.01)

                ffmpeg_process.terminate()
                yt_process.terminate()

            else:
                # Local file streaming
                if not os.path.exists(url):
                    print(f"[STREAM] File not found: {url}, skipping...")
                    continue

                ffmpeg_process = subprocess.Popen(
                    ["ffmpeg", "-re", "-i", url,
                     "-c:a", "libmp3lame", "-b:a", config.BITRATE,
                     "-ar", "44100", "-f", "mp3",
                     "-content_type", "audio/mpeg", "-"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )

                while True:
                    chunk = ffmpeg_process.stdout.read(4096)
                    if not chunk:
                        print("[STREAM] Finished local file, moving to next...")
                        break
                    try:
                        sock.sendall(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        print("[STREAM] Connection lost!")
                        ffmpeg_process.terminate()
                        return
                    time.sleep(0.01)

                ffmpeg_process.terminate()

        except Exception as e:
            print(f"[STREAM] Error streaming {url}: {e}")
            time.sleep(1)
            continue
        
async def stream_manager():
    while True:
        sock = connect_to_icecast()
        if not sock:
            print(f"[MAIN] Retry connecting in {config.RECONNECT_DELAY}s...")
            await asyncio.sleep(config.RECONNECT_DELAY)
            continue

        try:
            success = await stream_audio(sock)
            if not success:
                print("[MAIN] Stream failed, closing socket and reconnecting...")
                sock.close()
                break
        except Exception as e:
            print(f"[MAIN] Error during streaming: {e}")
            sock.close()

        print(f"[MAIN] Reconnecting in {config.RECONNECT_DELAY}s...")
        await asyncio.sleep(config.RECONNECT_DELAY)

async def main():
    print("🚀 Launching all systems!\n")
    reset_current_file()
    Objects.pl = SpotifyPlaylistFetcher()

    await asyncio.create_task(stream_manager())

if __name__ == "__main__":
    # Run the main async function
    asyncio.run(main())