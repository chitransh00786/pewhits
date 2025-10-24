import json
from Websocket.models import QueueSong
from typing import List, Optional

file_location = "json/requests.json"

def load_requests():
    """
    Load all requests from the JSON file. If the file does not exist, return an empty dictionary.
    """
    try:
        with open(file_location, "r") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}

def save_requests(requests):
    """
    Save the updated requests to the JSON file.
    """
    with open(file_location, "w") as file:
        json.dump(requests, file, indent=4)

def add_request(new_request):
    """
    Add a new request to the requests.json file.
    Before adding, ensure no request exists with the same spotifyID.
    """

    # Load the existing requests
    request_data = load_requests()

    # Determine the next ID
    new_id = len(request_data) + 1
    new_request["id"] = new_id  # Assign the new ID
    request_data[new_id] = new_request  # Add the request

    # Save the updated data
    save_requests(request_data)
    
async def remove_request_by_index(index, requester, moderator=False):
    """
    Remove a song request by its index from the JSON file, only if the requester username matches.

    Args:
        index (int): The index (ID) of the request to remove.
        requester (str): The username of the requester attempting to remove the song.

    Returns:
        str: A message indicating the result of the operation.
    """
    
    if index is None or not isinstance(index, int):
        return "error 801: Provide at least one valid index, song ID (Spotify or YouTube)."
    
    # Load the existing requests
    request_data = load_requests()

    # Check if the index exists in the data
    if str(index) not in request_data:
        return f"error 702: Request with index {index} does not exist."

    # Get the request details
    request = request_data[str(index)]

    if not moderator and request["requester"] != requester:
        return f"error 701: You are not authorized to remove this song request."

    # Remove the request
    del request_data[str(index)]

    # Reassign IDs to maintain order
    updated_data = {}
    for new_id, key in enumerate(request_data.keys(), start=1):
        updated_data[new_id] = request_data[key]
        updated_data[new_id]["id"] = new_id

    # Save the updated requests
    save_requests(updated_data)
    return f"Request with index {index} has been removed successfully."

def remove_request(spotify_id):
    """
    Remove a request by its spotifyID and re-index the remaining requests.
    """
    requests = load_requests()
    
    # Filter the requests, keeping only those without the specified spotifyID
    filtered_requests = {key: req for key, req in requests.items() if req.get("spotifyID") != spotify_id}
    
    # Rebuild the dictionary with sequential numeric keys
    reindexed_requests = {}
    for new_index, key in enumerate(sorted(filtered_requests.keys(), key=int), start=1):
        request = filtered_requests[key]
        request["id"] = new_index  # Update the "id" field
        reindexed_requests[str(new_index)] = request  # Assign a new numeric key
    
    save_requests(reindexed_requests)

def check_request_exists(spotify_id):
    """
    Check if a request with the specified spotifyID exists.
    """
    request_data = load_requests()
    for key, value in request_data.items():
        if value.get("spotifyID") == spotify_id:
            return True
    return False

def get_request() -> Optional[QueueSong]:
    request_data = load_requests()
    for key, value in request_data.items():
        if key == "1":
            return QueueSong(
                    id=int(value.get("id", key)),  # fallback to key if "id" not present
                    title=value.get("title", ""),
                    artist=value.get("artist", ""),
                    album=value.get("album", ""),
                    played=value.get("played", ""),
                    duration=int(value.get("duration", 0)),
                    albumart=value.get("albumart", ""),
                    YEAR=value.get("YEAR", ""),
                    spotifyID=value.get("spotifyID", ""),
                    requester=value.get("requester", ""),
                    apprequest=value.get("apprequest"),
                    radioname=value.get("radioname", ""),
                    radionameshort=value.get("radionameshort", ""),
                    external_url=value.get("external_url", "")
                )
    return None

def get_requests() -> Optional[List[QueueSong]]:
    """
    Retrieve the song requests in the queue.
    """
    
    raw_requests = load_requests()  # Assuming this loads a dictionary of song data
    queue_songs = []

    if raw_requests:
        for song_id, song in raw_requests.items():
            try:
                queue_song = QueueSong(
                    id=int(song.get("id", song_id)),  # fallback to key if "id" not present
                    title=song.get("title", ""),
                    artist=song.get("artist", ""),
                    album=song.get("album", ""),
                    played=song.get("played", ""),
                    duration=int(song.get("duration", 0)),
                    albumart=song.get("albumart", ""),
                    YEAR=song.get("YEAR", ""),
                    spotifyID=song.get("spotifyID", ""),
                    requester=song.get("requester", ""),
                    apprequest=song.get("apprequest"),
                    radioname=song.get("radioname", ""),
                    radionameshort=song.get("radionameshort", ""),
                    external_url=song.get("external_url", "")
                )
                queue_songs.append(queue_song)
            except Exception as e:
                print(f"⚠️ Failed to parse song in queue (ID: {song_id}): {e}")
        return queue_songs
    else:
        print("📭 No songs in the queue.")

    return None