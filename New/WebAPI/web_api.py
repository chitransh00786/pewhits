import json, threading, asyncio, random, string
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import ngrok, os, time
from flask_cors import CORS
from config.config import Authorization
from config.requestHandler import remove_request_by_index, get_requests
from config.songHandler import get_now_playing_data, get_next_coming_data
from config.request_adder import request_maker, get_app_id
from config.DJ import create_silent_audio
from config.blocker import add_song, remove_song_by_index, list_blocked_songs
from config.BG_process_status import songDownloader

app = Flask(__name__)

CORS(app)

AUTHORIZED_KEYS_FILE = 'json/authorized_keys.json'

RATE_LIMITS = {
    "/play": {"ip": (30, 60), "user": (20, 1200)},
    "/now-playing": (30, 120),  # 30 requests/2 minute
    "/next-coming": (30, 120),  # 30 requests/2 minute
    "/queue": (30, 120),  # 30 requests/2 minute
    "/remove": (30, 120),  # 30 requests/2 minute
    "/block": (30, 120),  # 30 requests/2 minute
    "/unblock": (30, 120),  # 30 requests/2 minute
    "blocklist": (30, 120),
    "/skip": (1, 30),
}

rate_limit_data = {
    "/play": {"ip": {}, "user": {}},
    "/now-playing": {},
    "/next-coming": {},
    "/queue": {},
    "/remove": {},
    "/block": {},
    "/unblock": {},
    "blocklist": {},
    "/skip": {},
}

def load_json_data(file_location):
    """Load authorized keys from the JSON file."""
    try:
        with open(file_location, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_json(file_location, data):
    with open(file_location, "w") as file:
        json.dump(data, file, indent=4)
        
# Function to check the API key and bot platform
def check_api_key(request):
    # Get API key and bot platform from headers
    api_key = request.headers.get("x-api-key")
    
    api_keys = load_json_data(AUTHORIZED_KEYS_FILE)
    if api_key not in api_keys:
        return False

    return True

def is_rate_limited(endpoint, identifier, is_user=False):
    limits = RATE_LIMITS.get(endpoint)
    if not limits:
        return False, 0

    limit_type = "user" if is_user else "ip"
    rate_limit = limits.get(limit_type)
    if not rate_limit:
        return False, 0

    max_requests, time_window = rate_limit
    now = datetime.now()  # Use datetime consistently

    # Get or initialize rate limit data
    endpoint_data = rate_limit_data[endpoint][limit_type]
    if identifier not in endpoint_data:
        endpoint_data[identifier] = []

    # Filter timestamps outside the window
    request_times = [
        t for t in endpoint_data[identifier]
        if t > now - timedelta(seconds=time_window)
    ]
    endpoint_data[identifier] = request_times

    # Check limit
    if len(request_times) >= max_requests:
        retry_after = (request_times[0] + timedelta(seconds=time_window) - now).total_seconds()
        return True, retry_after

    # Add current request
    endpoint_data[identifier].append(now)
    return False, 0

def rate_limit(ip_address, endpoint, username=None):
    now = datetime.now()

    if endpoint in rate_limit_data:
        if endpoint != "/play":
            max_requests, window = RATE_LIMITS[endpoint]
            if ip_address not in rate_limit_data[endpoint]:
                rate_limit_data[endpoint][ip_address] = []
            rate_limit_data[endpoint][ip_address] = [
                ts for ts in rate_limit_data[endpoint][ip_address]
                if ts > now - timedelta(seconds=window)
            ]
            if len(rate_limit_data[endpoint][ip_address]) >= max_requests:
                retry_after = (
                    rate_limit_data[endpoint][ip_address][0]
                    + timedelta(seconds=window)
                    - now
                ).total_seconds()
                return False, retry_after
            rate_limit_data[endpoint][ip_address].append(now)
        else:
            ip_max, ip_window = RATE_LIMITS["/play"]["ip"]
            user_max, user_window = RATE_LIMITS["/play"]["user"]

            if ip_address not in rate_limit_data["/play"]["ip"]:
                rate_limit_data["/play"]["ip"][ip_address] = []
            rate_limit_data["/play"]["ip"][ip_address] = [
                ts for ts in rate_limit_data["/play"]["ip"][ip_address]
                if ts > now - timedelta(seconds=ip_window)
            ]
            if len(rate_limit_data["/play"]["ip"][ip_address]) >= ip_max:
                retry_after = (
                    rate_limit_data["/play"]["ip"][ip_address][0]
                    + timedelta(seconds=ip_window)
                    - now
                ).total_seconds()
                return False, retry_after

            if username:
                if username not in rate_limit_data["/play"]["user"]:
                    rate_limit_data["/play"]["user"][username] = []
                rate_limit_data["/play"]["user"][username] = [
                    ts for ts in rate_limit_data["/play"]["user"][username]
                    if ts > now - timedelta(seconds=user_window)
                ]
                if len(rate_limit_data["/play"]["user"][username]) >= user_max:
                    retry_after = (
                        rate_limit_data["/play"]["user"][username][0]
                        + timedelta(seconds=user_window)
                        - now
                    ).total_seconds()
                    return False, retry_after

            rate_limit_data["/play"]["ip"][ip_address].append(now)
            if username:
                rate_limit_data["/play"]["user"][username].append(now)

    return True, None

def run_async_task(duration):
    """Runs the async function in a separate thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(create_silent_audio(duration))
    loop.close()

@app.route('/play', methods=['POST'])
def play_song():
    """Play a song."""
    client_ip = request.remote_addr
    
    data = request.get_json(silent=True)  # Ensure JSON is parsed safely

    if not data:
        return jsonify({"error": "Invalid or missing JSON data"}), 400
    
    song_id = data.get("song_id")  # Changed to song_id for consistency
    requester = data.get("requester")
    app_name = data.get("app")
    
    if not check_api_key(request):
        return jsonify({"error": "Unauthorized access, invalid API key"}), 403

    # Check IP-based rate limit first
    allowed, retry_after = rate_limit(client_ip, "/play")
    if not allowed:
        return jsonify({"error": "Too many requests"}), 429, {"Retry-After": f"{int(retry_after)}"}
    
    # Check username-based rate limit
    exceeded, retry_after = is_rate_limited("/play", requester, is_user=True)
    if exceeded:
        return (
            jsonify({"error": "Requested too many songs within a short time, you can request again after a while."}),
            704,
            {"Retry-After": f"{int(retry_after)}"}
        )

    try:
        # Run the async request_maker function
        song_data = asyncio.run(request_maker(song_id, requester, app_name))

        # Map specific errors from `request_maker` to status codes
        if isinstance(song_data, str):  # Errors from request_maker are returned as strings
            if "Unknown app" in song_data:
                return jsonify({"error": song_data}), 608
            elif "error 609" in song_data:
                return jsonify({"error": "Track recently played."}), 609
            elif "error 709" in song_data:
                return jsonify({"error": "Requested song is blocked."}), 709
            elif "error 708" in song_data:
                return jsonify({"error": "You have already requested this song, and it is waiting in the queue."}), 708
            elif "error 707" in song_data:
                return jsonify({"error": "This song is already in the queue."}), 707
            elif "error 706" in song_data:
                return jsonify({"error": "This song is currently playing."}), 706
            elif "error 500" in song_data:
                return jsonify({"error": "Internal server error. Please try again later."}), 500
            else:
                return jsonify({"error": song_data}), 400
            
        # Check username-based rate limit
        user_allowed, user_retry_after = rate_limit(client_ip, "/play", username=requester)
        if not user_allowed:
            return (
                jsonify({"error": "Requested too many songs within a short time, you can request again after a while."}),
                704,
                {"Retry-After": f"{int(user_retry_after)}"}
            )

        # Successful request
        return jsonify({"success": True, "data": song_data}), 200

    except Exception as e:
        return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500
    
@app.route('/remove', methods=['POST'])
def remove_song():
    """Remove a song from the queue."""
    client_ip = request.remote_addr
    data = request.get_json(silent=True)  # Ensure JSON is parsed safely

    if not data:
        return jsonify({"error": "Invalid or missing JSON data"}), 400
    
    song_index = data.get("index")
    requester = data.get("requester")
    moderator = str(data.get("moderator")).lower() == "true"  # Convert to proper boolean
    app_name = data.get("app")
    
    # Map app name to app ID
    app_id = get_app_id(app_name) if app_name else None

    # Determine apprequest value
    if app_name and app_id is None:
        return jsonify({"error": f"Unknown app: {app_name}"}), 608
    
    if not check_api_key(request):
        return jsonify({"error": "Unauthorized access, invalid API key"}), 403

    # Check IP-based rate limit first
    allowed, retry_after = rate_limit(client_ip, "/remove")
    if not allowed:
        return jsonify({"error": "Too many requests"}), 429, {"Retry-After": f"{int(retry_after)}"}

    try:
        song_data = asyncio.run(remove_request_by_index(song_index, requester, moderator))

        # Map specific errors from `request_maker` to status codes
        if isinstance(song_data, str):  # Errors from request_maker are returned as strings
            if "error 701" in song_data:
                return jsonify({"error": "You are not authorized to remove this song request."}), 701
            elif "error 702" in song_data:
                return jsonify({"error": "Request with index provided does not exist."}), 702
            elif "error 801" in song_data:
                return jsonify({"error": "Provide at least one valid song ID (Spotify or YouTube)."}), 801

        # Successful request
        return jsonify({"success": True, "data": song_data}), 200

    except Exception as e:
        return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500
    
@app.route('/block', methods=['POST'])
def block_current_song():
    client_ip = request.remote_addr
    data = request.get_json(silent=True)  # Ensure JSON is parsed safely

    if not data:
        return jsonify({"error": "Invalid or missing JSON data"}), 400
    
    blocker = data.get("blocker")
    moderator = str(data.get("moderator")).lower() == "true"  # Convert to proper boolean
    app_name = data.get("app")
    
    # Map app name to app ID
    app_id = get_app_id(app_name) if app_name else None

    # Determine apprequest value
    if app_name and app_id is None:
        return jsonify({"error": f"Unknown app: {app_name}"}), 608
    
    allowed, retry_after = rate_limit(client_ip, "/block")
    if not allowed:
        return jsonify({"error": "Too many requests"}), 429, {"Retry-After": f"{int(retry_after)}"}
    
    if not check_api_key(request):
        return jsonify({"error": "Unauthorized access, invalid API key"}), 403
    
    if not moderator:
        return jsonify({"error": "You are not authorized to remove this blocked song."}), 703

    if songDownloader.song_downloader:
        return jsonify({"error": "Cannot block songs when next song is being downloaded."}), 805

    now_playing = get_now_playing_data()
    
    if not now_playing:
        return jsonify({"error": "No song is currently playing"}), 404

    ID = now_playing.ID
    title = now_playing.title
    artist = now_playing.artist
    album = now_playing.album
    
    try:
        song_resp = add_song(ID, None, title, artist, album, blocker)  # Call normally

        if isinstance(song_resp, str):  # Errors from request_maker are returned as strings
            if "error 802" in song_resp:
                return jsonify({"error": "This song is already blocked."}), 802
            elif "error 801" in song_resp:
                return jsonify({"error": "Provide at least one valid song ID (Spotify or YouTube)."}), 801

        duration = (now_playing.position or 0)
        # Run create_silent_audio in a separate thread to avoid blocking Flask
        threading.Thread(target=run_async_task, args=(duration,), daemon=True).start()
        
        return jsonify({"success": True, "data": song_resp}), 200  # ✅ Success Response
    except Exception as e:
        return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500
    
@app.route('/unblock', methods=['POST'])
def remove_blocked_song():
    client_ip = request.remote_addr
    data = request.get_json(silent=True)  # Ensure JSON is parsed safely

    if not data:
        return jsonify({"error": "Invalid or missing JSON data"}), 400
    
    index = data.get("index")
    moderator = str(data.get("moderator")).lower() == "true"  # Convert to proper boolean
    app_name = data.get("app")
    
    # Map app name to app ID
    app_id = get_app_id(app_name) if app_name else None

    # Determine apprequest value
    if app_name and app_id is None:
        return jsonify({"error": f"Unknown app: {app_name}"}), 608
    
    allowed, retry_after = rate_limit(client_ip, "/unblock")
    if not allowed:
        return jsonify({"error": "Too many requests"}), 429, {"Retry-After": f"{int(retry_after)}"}
    
    if not check_api_key(request):
        return jsonify({"error": "Unauthorized access, invalid API key"}), 403
    
    if not moderator:
        return jsonify({"error": "You are not authorized to remove this blocked song."}), 703
    
    try:
        song_resp = remove_song_by_index(index)
        
        if isinstance(song_resp, str):  # Errors from request_maker are returned as strings
            if "error 801" in song_resp:
                return jsonify({"error": "Provide at least one valid song ID (Spotify or YouTube)."}), 801
            elif "error 804" in song_resp:
                return jsonify({"error": "Blocked song with index provided does not exist."}), 804
            
        # Successful request
        return jsonify({"success": True, "data": song_resp}), 200
    
    except Exception as e:
        return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500
    
@app.route('/blocklist', methods=['GET'])
def blocklist():
    """Retrieve the blocklist songs data."""
    client_ip = request.remote_addr
    allowed, retry_after = rate_limit(client_ip, "/blocklist")
    if not allowed:
        return jsonify({"error": "Too many requests"}), 429, {"Retry-After": f"{int(retry_after)}"}
    
    if not check_api_key(request):
        return jsonify({"error": "Unauthorized access, invalid API key"}), 403
    
    blocked_songs = list_blocked_songs()
    
    return jsonify({"success": True, "blocklist": blocked_songs}), 200

@app.route('/skip', methods=['POST'])
def skip_current_song():
    client_ip = request.remote_addr
    allowed, retry_after = rate_limit(client_ip, "/skip")
    if not allowed:
        return jsonify({"error": "Too many requests"}), 429, {"Retry-After": f"{int(retry_after)}"}
    
    if not check_api_key(request):
        return jsonify({"error": "Unauthorized access, invalid API key"}), 403
    
    if songDownloader.song_downloader:
        return jsonify({"error": "Cannot skip songs when next song is being download is in processing."}), 805
    
    now_playing_data = get_now_playing_data()

    if not now_playing_data:
        return jsonify({"error": "No song is currently playing"}), 404

    duration = (now_playing_data.position or 0)

    # Run create_silent_audio in a separate thread to avoid blocking Flask
    threading.Thread(target=run_async_task, args=(duration,), daemon=True).start()

    return jsonify({"success": True, "message": f"Skipping current song"}), 200
        
@app.route('/queue', methods=['GET'])
def get_queue():
    """Retrieve the current song queue."""
    client_ip = request.remote_addr
    allowed, retry_after = rate_limit(client_ip, "/queue")
    if not allowed:
        return jsonify({"error": "Too many requests"}), 429, {"Retry-After": f"{int(retry_after)}"}
    
    if not check_api_key(request):
        return jsonify({"error": "Unauthorized access, invalid API key"}), 403
    
    requests = get_requests()  # Assumes `get_requests()` retrieves the queue data
    return jsonify({"success": True, "queue": requests}), 200

@app.route('/now-playing', methods=['GET'])
def now_playing():
    """Retrieve the currently playing song."""
    client_ip = request.remote_addr
    allowed, retry_after = rate_limit(client_ip, "/now-playing")
    if not allowed:
        return jsonify({"error": "Too many requests"}), 429, {"Retry-After": f"{int(retry_after)}"}
    
    if not check_api_key(request):
        return jsonify({"error": "Unauthorized access, invalid API key"}), 403
    
    now_playing = get_now_playing_data()  # Assumes this retrieves the current song data
    return jsonify({"success": True, "now_playing": now_playing}), 200

@app.route('/next-coming', methods=['GET'])
def next_coming():
    """Retrieve the next upcoming song."""
    client_ip = request.remote_addr
    allowed, retry_after = rate_limit(client_ip, "/next-coming")
    if not allowed:
        return jsonify({"error": "Too many requests"}), 429, {"Retry-After": f"{int(retry_after)}"}
    
    if not check_api_key(request):
        return jsonify({"error": "Unauthorized access, invalid API key"}), 403
    
    next_coming = get_next_coming_data()  # Assumes this retrieves the next song data
    return jsonify({"success": True, "next_coming": next_coming}), 200
    
# Encapsulated function to start the server
def start_server():
    ngrok.set_auth_token(Authorization.ngrok_auth_token)
    public_url = ngrok.forward("localhost:5000", authtoken_from_env=True, domain=Authorization.ngrok_domain)
    print(f"Ngrok URL: {public_url}")
    app.run(port=5000)  # This blocks, so we need to run it in a thread.

# Function to run Flask server in a separate thread
async def start_server_async():
    threading.Thread(target=start_server, daemon=True).start()  # Run Flask in a thread