import os
import json
import random
import time
from typing import List, Dict
from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials
from config.config import DJ, Authorization


class SpotifyPlaylistFetcher:
    def __init__(self, json_file="json/playlists.json"):
        """SpotifyPlaylistFetcher object create hote hi Spotify se sab tracks fetch karke queue bana lega"""
        self.playlists = DJ.playlists
        self.json_file = json_file
        self.data = {
            "tracks": {},   # yaha sab playlists ke tracks save honge
            "queue": [],    # shuffled queue
            "history": []   # played songs ka history
        }

        # Spotify client setup
        auth_manager = SpotifyClientCredentials(client_id=Authorization.SPOTIPY_CLIENT_ID, client_secret=Authorization.SPOTIPY_CLIENT_SECRET)
        self.sp = Spotify(auth_manager=auth_manager)

        # Load or create queue JSON
        if not os.path.exists(self.json_file):
            self.data = {"tracks": {}, "queue": [], "history": []}
            self._save()
        else:
            with open(self.json_file, "r", encoding="utf-8") as f:
                self.data = json.load(f)

        # agar purana JSON hai aur usme keys missing hain to add karo
        if "tracks" not in self.data:
            self.data["tracks"] = {}
        if "queue" not in self.data:
            self.data["queue"] = []
        if "history" not in self.data:
            self.data["history"] = []

        # Fetch tracks from playlists & build queue if empty
        self._build_tracks()
        if not self.data["queue"]:
            self._build_queue()
            
    def _build_tracks(self):
        """Fetch all playlist tracks and build 'tracks' directory"""
        for playlist_url in self.playlists:
            playlist_id = playlist_url.split("/")[-1].split("?")[0]

            if playlist_id not in self.data["tracks"]:
                self.data["tracks"][playlist_id] = {}

            # Paginate all tracks
            limit = 100
            offset = 0

            while True:
                results = self.sp.playlist_tracks(
                    playlist_id,
                    limit=limit,
                    offset=offset
                )

                for item in results["items"]:
                    track = item["track"]
                    if track:  # only if track exists
                        track_id = track["id"]
                        metadata = {
                            "title": track["name"],
                            "artists": ", ".join(artist['name'] for artist in track["artists"] if artist.get("name")),
                            "album": track["album"]["name"],
                            "duration_sec": track["duration_ms"] // 1000,
                            "release_date": track["album"]["release_date"],
                            "albumart": track["album"]["images"][0]["url"] if track["album"]["images"] else None,
                            "external_url": track["external_urls"]["spotify"],
                            "track_id": track_id,
                            "playlist_id": playlist_id
                        }
                        self.data["tracks"][playlist_id][track_id] = metadata

                # check if we reached the end
                if results["next"]:
                    offset += limit
                else:
                    break

        self._save()

    def _build_queue(self):
        """Build a shuffled queue from all tracks"""
        all_tracks = []
        for playlist_id, tracks in self.data["tracks"].items():
            for tid, metadata in tracks.items():
                all_tracks.append(tid)

        random.shuffle(all_tracks)
        self.data["queue"] = all_tracks
        self._save()

    def _save(self):
        """Save current queue and history into JSON"""
        with open(self.json_file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=4, ensure_ascii=False)

    def next_song(self) -> Dict:
        """Play next song: remove from queue, add to history, return metadata"""
        if not self.data["queue"]:
            # queue khali ho gayi -> reshuffle
            self._build_queue()

        if not self.data["queue"]:
            return {"message": "No tracks available!"}

        track_id = self.data["queue"].pop(0)
        self.data["history"].append(track_id)

        # metadata find karna (track_id kis playlist me hai)
        metadata = None
        for pid, tracks in self.data["tracks"].items():
            if track_id in tracks:
                metadata = tracks[track_id]
                break

        self._save()
        return metadata if metadata else {"track_id": track_id, "message": "Metadata not found"}

    def current_queue(self) -> List[Dict]:
        """Return the current queue with metadata"""
        queue_meta = []
        for tid in self.data["queue"]:
            for pid, tracks in self.data["tracks"].items():
                if tid in tracks:
                    queue_meta.append(tracks[tid])
        return queue_meta

    def history(self) -> List[Dict]:
        """Return history with metadata"""
        history_meta = []
        for tid in self.data["history"]:
            for pid, tracks in self.data["tracks"].items():
                if tid in tracks:
                    history_meta.append(tracks[tid])
        return history_meta


""" # ---------------- Usage Example ----------------
if __name__ == "__main__":

    dj = SpotifyPlaylistFetcher()

    print("Current Queue:", dj.current_queue()[:3])  # first 3 songs preview
    print("Next Song:", dj.next_song())
    print(f"\n\n")
    
    time.sleep(5)
    
    print("Next Song:", dj.next_song())
    print(f"\n\n")
    
    time.sleep(5)
    
    print("Next Song:", dj.next_song())
    print(f"\n\n") """
