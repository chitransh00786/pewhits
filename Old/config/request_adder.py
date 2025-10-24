import json
from datetime import datetime
import spotipy, time
from spotipy.oauth2 import SpotifyClientCredentials
from spotipy.exceptions import SpotifyException
from requests.exceptions import ReadTimeout
from flask import Flask, request, jsonify
from .config import *
from .songHandler import *
from .blocker import *
from .config import *


sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=Authorization.SPOTIPY_CLIENT_ID, 
    client_secret=Authorization.SPOTIPY_CLIENT_SECRET,
    requests_timeout=30  # Increase timeout to 30 seconds
))

APPS_FILE = "json/apps.json"

def load_josn_data(file_location):
    """Load authorized keys from the JSON file."""
    try:
        with open(file_location, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

# Function to save data to a JSON file
def save_json(file_location, data):
    with open(file_location, "w") as file:
        json.dump(data, file, indent=4)
 

def get_app_id(app_name):
    """
    Map app name to app ID using the apps dictionary.
    If the app name is not found, return None.
    """
    apps = load_josn_data(APPS_FILE)
    
    for app_id, name in apps.items():
        if name.lower() == app_name.lower():
            return app_id
    return None

def get_song_data(song_name: str, requester: str, id: str) -> dict:
    max_retries = 3
    delay = 2  # seconds

    for attempt in range(max_retries):
        try:
            results = sp.search(q=song_name, limit=1, type='track')

            if not results['tracks']['items']:
                return {"error": "Track not found"}

            track = results['tracks']['items'][0]

            data = {
                "title": track['name'],
                "artist": ', '.join(artist['name'] for artist in track['artists']),
                "album": track['album']['name'],
                "played": datetime.now().isoformat(),
                "duration": track['duration_ms'],
                "albumart": track['album']['images'][0]['url'] if track['album']['images'] else None,
                "YEAR": track['album']['release_date'][:4],
                "spotifyID": track['id'],
                "requester": requester,
                "apprequest": id,
                "radioname": "Pew Hits",
                "radionameshort": "Pew",
                "external_url": track['external_urls']['spotify']
            }

            return data

        except (ReadTimeout, SpotifyException) as e:
            print(f"Attempt {attempt+1} failed with error: {e}")
            if attempt < max_retries - 1:
                time.sleep(delay * (attempt + 1))  # backoff delay
            else:
                return {"error": f"Spotify API error after {max_retries} attempts: {e}"}
        except Exception as e:
            return {"error": f"Unexpected error: {e}"}
        
def get_song_data_by_id(track_id: str, requester: str, id: str) -> dict:
    max_retries = 3
    delay = 2  # seconds

    for attempt in range(max_retries):
        try:
            track = sp.track(track_id)

            if not track:
                return {"error": "Track not found"}

            data = {
                "title": track['name'],
                "artist": ', '.join(artist['name'] for artist in track['artists']),
                "album": track['album']['name'],
                "played": datetime.now().isoformat(),
                "duration": track['duration_ms'],
                "albumart": track['album']['images'][0]['url'] if track['album']['images'] else None,
                "YEAR": track['album']['release_date'][:4],
                "spotifyID": track['id'],
                "requester": requester,
                "apprequest": id,
                "radioname": "Pew Hits",
                "radionameshort": "Pew",
                "external_url": track['external_urls']['spotify'],
                "popularity": track.get('popularity', 0),
                "preview_url": track.get('preview_url')
            }

            return data

        except (ReadTimeout, SpotifyException) as e:
            print(f"Attempt {attempt+1} failed with error: {e}")
            if attempt < max_retries - 1:
                time.sleep(delay * (attempt + 1))  # exponential backoff
            else:
                return {"error": f"Spotify API error after {max_retries} attempts: {e}"}

        except Exception as e:
            return {"error": f"Unexpected error: {e}"}

async def request_maker(song_id: str, requester: str, app: str):
    """
    Add a song request to the queue.

    :param song_id: ID of the song to search for
    :param requester: The name or ID of the person requesting the song
    :param app: The application requesting the song
    :return: A message indicating the success or failure of the request
    """
    from config.requestHandler import check_request_exists, add_request
    try:
        # Map app name to app ID
        app_id = get_app_id(app) if app else None

        # Determine apprequest value
        if app and app_id is None:
            return f"Unknown app: {app}"
        
        # Get song data from Spotify
        song_data = get_song_data_by_id(song_id, requester, str(app_id))
        
        if "error" in song_data:
            return song_data["error"]
        
        if track_already_played(song_data):
            return "error 609: Song recently played."
        
        if is_song_blocked(song_data['spotifyID']):
            return "error 709: Requested song is blocked."
        
        if check_request_exists(song_data['spotifyID']):
            return "error 708: You have already requested this song, and it is waiting in the request queue to be played."
        
        if next_coming_file_exists(song_data['spotifyID']):
            return "error 707: This song is already in the queue to be played."
        
        if now_playing_file_exists(song_data['spotifyID']):
            return "error 706: This song is currently playing."
        
        # Add the request to the queue
        add_request(song_data)
        return song_data
    except Exception as e:
        print(f"An error occurred: {e}")