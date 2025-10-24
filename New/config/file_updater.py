from mutagen.mp3 import MP3
from mutagen.mp3 import HeaderNotFoundError
import asyncio, requests
from config.BG_process_status import skip
import time
from config.config import config

class TaskGroup:
    def __init__(self):
        self._tasks = set()

    def create_task(self, coro):
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)  # Remove completed tasks
        return task
    
taskgroup = TaskGroup()

def manage_task(task_name: str, coro_func):
    task_list = list(taskgroup._tasks)

    # Cancel existing task if found
    for task in task_list:
        if task.get_name() == task_name:
            task.cancel()

    # Create a new task
    new_task = taskgroup.create_task(coro_func())
    new_task.set_name(task_name)
    
class nxt:
    next_up = ""

def update_icecast_metadata(song: str):
    host=f"http://{config.SERVER_HOST}:{config.SERVER_PORT}/"
    mount=config.MOUNT_POINT
    user=config.ADMIN
    password=config.ADMIN_PASSWORD

    url = f"{host}/admin/metadata"
    params = {
        "mount": mount,
        "mode": "updinfo",
        "song": song
    }

    try:
        response = requests.get(url, params=params, auth=(user, password))
        if not response.status_code == 200:
            print(f"⚠️ Failed! Status: {response.status_code}, Response: {response.text}")
    except Exception as e:
        print("🥺 Error updating metadata:", e)
        
async def safe_read_mp3(file_path, retries=5, delay=0.5):
    for attempt in range(retries):
        try:
            audio = MP3(file_path)
            return audio
        except HeaderNotFoundError as e:
            print(f"⚠️ MP3 read failed (attempt {attempt+1}): {e}")
            await asyncio.sleep(delay)
    raise HeaderNotFoundError(f"❌ Failed to read MP3 after {retries} attempts") 

async def looper_updater():
    from config.DJ import song_downloader
    from config.songHandler import update_current_file, get_now_playing_data, move_to_now_playing, add_to_history, update_position_and_remaining
    
    manage_task("update_position", update_position_and_remaining)
    
    audio_file1 = "Audio/audio1.mp3"
    audio_file2 = "Audio/audio2.mp3"
        
    now_playing = audio_file1
    next_song = audio_file2

    while True:
        try:
            from Websocket.websocket import broadcast_now_playing

            manage_task("song_downloader", song_downloader)

            # Load the audio file
            audio = await safe_read_mp3(now_playing)

            # Get the duration in seconds
            duration = audio.info.length

            print(f"Waiting for {duration} seconds to update the audio file...")
            
            """await asyncio.sleep(duration)"""
            start_time = time.perf_counter()  # High-resolution timer
            while (elapsed := time.perf_counter() - start_time) < duration:
                if skip.skip_status:
                    skip.skip_status = False
                    skip.stop_counter = True
                    break
                
                remaining_time = duration - elapsed
                sleep_time = min(0.1, remaining_time)  # Prevent oversleeping
                await asyncio.sleep(sleep_time)  # ✅ Non-blocking sleep
    
            # Swap `now_playing` and `next_song`
            now_playing, next_song = next_song, now_playing
            
            update_current_file(now_playing, next_song)
            
            await add_to_history()
            await move_to_now_playing()
            # Broadcast song change
            manage_task("update_position", update_position_and_remaining)

            print(f"Switching: Now playing -> {now_playing}, Next song -> {next_song}")
            np = get_now_playing_data()
            await broadcast_now_playing("notification", np)
            update_icecast_metadata(nxt.next_up)
            
        except HeaderNotFoundError:
            print("Error: 'audio.mp3' is not a valid MP3 file or is corrupted.")
            
        except Exception as e:
            print(f"Error in Looper: {e}")