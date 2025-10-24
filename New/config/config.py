class Authorization:
    ngrok_auth_token = "2ryTNIRJt7EfI8YH911S9pw3SGN_2bXVyi1ZdVMHAWgF6vJ6d"
    ngrok_domain = "stirring-thoroughly-kid.ngrok-free.app"
    SPOTIPY_CLIENT_ID = '61f786cf566f4e2489c4f0507a3e059e'
    SPOTIPY_CLIENT_SECRET = '02786c3a37cf4e6f8fe56f5d5a73aae3'
    
class DJ:
    playlists = [
        "https://open.spotify.com/playlist/5cSazwVC79ajs382BdSZC0?si=Oai7IHDMS8u7MDzVTyo-wg",
        "https://open.spotify.com/playlist/1BfpZk1ImUkjksKM0wUa4U?si=J_N-YfhHRE2nZ8tmv_nBLg"
    ]
    
class config:
    # --- CONFIGURATION ---
    SERVER_HOST = "80.225.211.98"       # your Icecast server IP or domain
    SERVER_PORT = 8261                  # Icecast port (usually 8000)
    ADMIN = "1LoVVe"                    # Icecast Admin username
    ADMIN_PASSWORD = "Study@hard819DJ"  # Icecast Admin password
    MOUNT_POINT = "/tester"             # mount point (e.g., /radio.mp3)
    STREAM_PASSWORD = "tester00786"     # Icecast source password
    BITRATE = "320k"                    # bitrate for ffmpeg output
    AUDIO_FILE = "Nothing.mp3"          # path to silent audio file
    RECONNECT_DELAY = 5                 # seconds between reconnection attempts