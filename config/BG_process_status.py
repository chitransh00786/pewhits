class skip:
    skip_status = False
    stop_counter = False
    skip_st = False
    
class songDownloader:
    song_downloader = False
    
class playlist_manager:
    playlist_manager = None
    
from config.PlaylistHandler import SpotifyPlaylistFetcher

class Objects:
    pl: SpotifyPlaylistFetcher