import json, asyncio, os
from datetime import datetime
from typing import Optional
from Websocket.models import NowPlayingSong, NextComingSong

now_playing_file = "json/now_playing.json"
next_coming_file = "json/next_coming.json"
history_file = "json/history.json"
current_file = "json/currentFile.json"

# Function to load data from a JSON file
def load_json(file_location):
    try:
        if os.path.getsize(file_location) == 0:  # Check if file is empty
            return {}  # Return empty dict instead of crashing
        with open(file_location, "r") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}

# Function to save data to a JSON file
def save_json(file_location, data):
    with open(file_location, "w") as file:
        json.dump(data, file, indent=4)

# Function to move the data from next_coming.json to now_playing.json
async def move_to_now_playing():
    next_coming_data = load_json(next_coming_file)
    if next_coming_data:
        # Save the data to now_playing.json
        save_json(now_playing_file, next_coming_data)
        # Clear the next_coming.json data
        save_json(next_coming_file, {})
        
# Function to update position and remaining every second for the single item
async def update_position_and_remaining():
    data = load_json(now_playing_file)  # Load the data from the JSON file
    if data:  # Check if data is not empty
        item = data[0]  # Access the first item of the list (assuming there is one item)
        
        second = 0
        while second < item['durationsec'] - 1:
            
            item['position'] = second
            item['remaining'] = item['durationsec'] - second

            # Save the updated data to now_playing.json
            save_json(now_playing_file, data)

            await asyncio.sleep(1)  # Wait for 1 second before continuing
            second += 1  # Increment time
        

def save_to_next_coming(track_data, requester):
    # Handle case where a playlist item is passed instead of pure track
    if "track" in track_data:
        track_data = track_data["track"]

    data = [{
        "ID": track_data['id'],
        "title": track_data['name'],
        "artist": ", ".join(artist['name'] for artist in track_data['artists']),
        "album": track_data['album']['name'],
        "played": datetime.now().isoformat(),
        "albumart": track_data['album']['images'][0]['url'] if track_data['album']['images'] else None,
        "release_date": track_data['album']['release_date'],
        "spotifyID": track_data['id'],
        "requester": requester,
        "apprequest": None,
        "radioname": "Pew Hits",
        "radionameshort": "Pew",
        "durationsec": track_data['duration_ms'] // 1000,
        "position": 0,
        "remaining": track_data['duration_ms'] // 1000,
        "external_url": track_data['external_urls']['spotify']
    }]
    
    save_json(next_coming_file, data)

    
# Function to add now-playing data to history.json
async def add_to_history():
    now_playing_data = load_json(now_playing_file)
    history_data = load_json(history_file)

    if now_playing_data:
        # Assuming now_playing_data contains a list with a single song object
        song = now_playing_data[0]
        song_id = song["ID"]
        
        # Remove the song ID from history if it exists
        if song_id in history_data:
            del history_data[song_id]

        # Add song data to history under the song ID
        history_data[song_id] = {
            "title": song.get("title", ""),
            "artist": song.get("artist", ""),
            "album": song.get("album", ""),
            "played": song.get("played", ""),
            "durationsec": song.get("durationsec", 0),
            "albumart": song.get("albumart", ""),
            "release_date": song.get("release_date", ""),
            "spotifyID": song.get("spotifyID", ""),
            "external_url": song.get("external_url", "")
        }

        # Save updated history data
        save_json(history_file, history_data)
        
def get_now_playing_data() -> Optional[NowPlayingSong]:
    now_playing_dict = load_json(now_playing_file)

    if not now_playing_dict or not isinstance(now_playing_dict, list) or len(now_playing_dict) == 0:
        return None
    
    song = now_playing_dict[0]

    return NowPlayingSong(
        ID=song.get("ID"),
        title=song.get("title"),
        artist=song.get("artist"),
        album=song.get("album"),
        played=song.get("played"),
        albumart=song.get("albumart"),
        release_date=song.get("release_date"),
        spotifyID=song.get("spotifyID"),
        requester=song.get("requester"),
        apprequest=song.get("apprequest"),
        radioname=song.get("radioname"),
        radionameshort=song.get("radionameshort"),
        durationsec=song.get("durationsec"),
        position=song.get("position"),
        remaining=song.get("remaining"),
        external_url=song.get("external_url")
    )

def get_next_coming_data() -> Optional[NextComingSong]:
    next_coming_data = load_json(next_coming_file)
    if not next_coming_data or not isinstance(next_coming_data, list) or len(next_coming_data) == 0:
        return None
    
    song = next_coming_data[0]  # Assumes the first item is the next song
    return NextComingSong(
        ID=song.get("ID"),
        title=song.get("title"),
        artist=song.get("artist"),
        album=song.get("album"),
        played=song.get("played"),
        albumart=song.get("albumart"),
        release_date=song.get("release_date"),
        spotifyID=song.get("spotifyID"),
        requester=song.get("requester"),
        apprequest=song.get("apprequest"),
        radioname=song.get("radioname"),
        radionameshort=song.get("radionameshort"),
        durationsec=song.get("durationsec"),
        position=song.get("position"),
        remaining=song.get("remaining"),
        external_url=song.get("external_url")
    )

def next_coming_file_exists(spotifyID):
    next_coming_data = load_json(next_coming_file)
    if next_coming_data:
        for item in next_coming_data:
            if item['spotifyID'] == spotifyID:
                return True
    return False

def now_playing_file_exists(spotifyID):
    next_coming_data = load_json(now_playing_file)
    if next_coming_data:
        for item in next_coming_data:
            if item['spotifyID'] == spotifyID:
                return True
    return False

def track_already_played(song_data):
    # Load history from the JSON file
    history = load_json(history_file)
    
    # Get the Spotify ID safely
    spotify_id = song_data.get('spotifyID')  # Use .get() to avoid KeyError

    if not spotify_id:
        return False  # Assume song was not played if the key is missing

    if spotify_id in history:
        played_time = datetime.fromisoformat(history[spotify_id]['played'])
        if (datetime.now() - played_time).total_seconds() < 3 * 3600:  # 3 hours in seconds
            return True

    return False

def track_already_played_id(spotify_id):
    # Load history from the JSON file
    history = load_json(history_file)

    if not spotify_id:
        return False  # Assume song was not played if the key is missing

    if spotify_id in history:
        played_time = datetime.fromisoformat(history[spotify_id]['played'])
        if (datetime.now() - played_time).total_seconds() < 5 * 3600:  # 5 hours in seconds
            return True

    return False

        
def fetch_current_file():
    current_data = load_json(current_file)
    return current_data

def update_current_file(now: str, next: str):
    data = {
        "now_playing": now,
        "next_coming": next
    }
    save_json(current_file, data)
    
def reset_current_file():
    data = {
        "now_playing": "Audio/audio1.mp3",
        "next_coming": "Audio/audio2.mp3"
    }
    save_json(current_file, data)