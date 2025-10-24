import json, threading
from datetime import datetime, timedelta
from time import monotonic
from collections import defaultdict
from typing import Optional, Literal
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import uuid  # to generate unique connection IDs
from Websocket.client_manager import ClientManager
from Websocket.__init__ import PewHits, PewHitsServer
from Websocket.models import SessionMetadata
from Websocket.webAPI import WebAPI, ClientInfo
from dataclasses import dataclass, asdict

app = FastAPI()

# Allow cross-origin access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins (change this for security)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@dataclass
class BotDefinition:
    radio: PewHits
    
file_path = "json/auth_clients.json"

def load_clients_info(file_path: str):
    # Load authorized clients
    with open(file_path, "r") as file:
        return json.load(file)
    
def get_client_info_by_key(api_key: str) -> Optional[ClientInfo]:
    AUTHORIZED_CLIENTS = load_clients_info(file_path)
    
    for client in AUTHORIZED_CLIENTS.values():
        if client.get("client_auth_key") == api_key:
            return ClientInfo(
                client_id=client.get("client_id"),
                client_name=client.get("client_name"),
                api_key=api_key,
                is_DJ=client.get("is_DJ", False),
                client_description=client.get("client_description")
            )
    
    return None

def generate_connection_id():
    return str(uuid.uuid4())

def is_api_key_valid(api_key: str, client_info: ClientInfo) -> bool:
    if client_info.api_key == api_key:
        return True
    return False

rate_limiters = defaultdict(lambda: {"tokens": 10, "last_time": monotonic()})

RATE_LIMITS = {
    "/play": {"ip": (30, 60), "user": (20, 1200)},
    "/now-playing": (30, 120),  # 30 requests/2 minute
    "/next-coming": (30, 120),  # 30 requests/2 minute
    "/queue": (30, 120),  # 30 requests/2 minute
    "/remove": (30, 120),  # 30 requests/2 minute
    "/block": (30, 120),  # 30 requests/2 minute
    "/unblock": (30, 120),  # 30 requests/2 minute
    "/blocklist": (30, 120),
    "/skip": (1, 30),
    "/reloadall": (1, 30),
}

rate_limit_data = {
    "/play": {"ip": {}, "user": {}},
    "/now-playing": {},
    "/next-coming": {},
    "/queue": {},
    "/remove": {},
    "/block": {},
    "/unblock": {},
    "/blocklist": {},
    "/skip": {},
    "/reloadall": {},
}

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
    
async def send_rate_limited_response(websocket, endpoint, client_ip, username=None):
    if endpoint == "/play":
        # IP-based check
        allowed, retry_after = rate_limit(client_ip, endpoint)
        if not allowed:
            await websocket.send_json({
                "error": "Too many requests from your IP.",
                "code": 429,
                "retry_after": int(retry_after)
            })
            return True  # Blocked

        # Username-based check (if provided)
        if username:
            allowed, retry_after = is_rate_limited(endpoint, username, is_user=True)
            if allowed:  # Means it's rate-limited
                await websocket.send_json({
                    "error": "Requested too many songs within a short time, you can request again after a while.",
                    "code": 704,
                    "Retry-After": f"{int(retry_after)}"
                })
                return True
        return False

    # General endpoint check (non-/play)
    allowed, retry_after = rate_limit(client_ip, endpoint)
    if not allowed:
        await websocket.send_json({
            "error": "Too many requests",
            "retry_after": int(retry_after)
        })
        return True  # Blocked

    return False  # Allowed


# WebSocket Endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        # Initialize session metadata for the client connection
        connection_id = generate_connection_id()
        
        data = await websocket.receive_json()
        api_key = data.get("api_key")
        client_info = get_client_info_by_key(api_key)
        
        if not api_key or not is_api_key_valid(api_key, client_info) or not client_info:
            await websocket.send_json({"error": "Unauthorized: Invalid API key"})
            await websocket.close()
            return
        
        # Store connection in ClientManager
        ClientManager.add(api_key, websocket, client_info, connection_id)
        
        metadata = SessionMetadata(
            client_id=client_info.client_id,
            client_name=client_info.client_name,
            rate_limits={"global": (10, 1.0)},
            connection_id=connection_id
        )
        
        await PewHits.on_start(websocket, "notification", asdict(metadata))
        
        await PewHits.on_start_now_playing(websocket, "notification")  # Call the now_playing method
            
        while True:
            # Wait for client messages
            data_dict = await websocket.receive_json()
            action = data_dict.get("action")
            client_ip = websocket.client.host

            if action == "queue":
                response = await send_rate_limited_response(websocket, "/queue", client_ip)
                if response:
                    return response
                await PewHits.queue(websocket, data_dict, "response")  # Call the queue method
            elif action == "now":
                response = await send_rate_limited_response(websocket, "/now", client_ip)
                if response:
                    return response
                await PewHits.now_playing(websocket, data_dict, "response")  # Call the now_playing method
            elif action == "next":
                response = await send_rate_limited_response(websocket, "/next", client_ip)
                if response:
                    return response
                await PewHits.next_coming(websocket, data_dict, "response")
            elif action == "blocklist":
                response = await send_rate_limited_response(websocket, "/blocklist", client_ip)
                if response:
                    return response
                await PewHits.blocklist(websocket, data_dict, "response")
            elif action == "skip":
                response = await send_rate_limited_response(websocket, "/skip", client_ip)
                if response:
                    return response
                data_dict["DJ"] = client_info.is_DJ
                await PewHitsServer.skip_current_song(websocket, data_dict, "response")
            elif action == "unblock":
                response = await send_rate_limited_response(websocket, "/unblock", client_ip)
                if response:
                    return response
                data_dict["DJ"] = client_info.is_DJ
                await PewHitsServer.remove_blocked_song(websocket, data_dict, "response")
            elif action == "block":
                response = await send_rate_limited_response(websocket, "/block", client_ip)
                if response:
                    return response
                data_dict["DJ"] = client_info.is_DJ
                await PewHitsServer.block_current_song(websocket, data_dict, "response")
            elif action == "remove":
                response = await send_rate_limited_response(websocket, "/remove", client_ip)
                if response:
                    return response
                await PewHitsServer.remove_song(websocket, data_dict, "response")
            elif action == "play":
                response = await send_rate_limited_response(websocket, "/play", client_ip)
                if response:
                    return response
                await PewHitsServer.play_song(websocket, data_dict, "response")
            elif action == "reloadall":
                response = await send_rate_limited_response(websocket, "/reloadall", client_ip)
                if response:
                    return response
                await PewHitsServer.reloadall(websocket, data_dict, "response")
            elif action == "KeepAliveRequest":
                ClientManager.update_keepalive(api_key)
                await websocket.send_json({"action": "KeepAliveResponse", "type": "notification", "status": "ok"})

    except WebSocketDisconnect:
        print("Client disconnected cleanly.")
        ClientManager.remove(websocket)
    except Exception as e:
        print(f"Error during connection: {e}")
    finally:
        if not websocket.client_state.name == "DISCONNECTED":
            try:
                await websocket.close()
                ClientManager.remove(websocket)
            except RuntimeError as e:
                print(f"Error closing the connection: {e}")
                
@app.get("/next-coming")
async def next_coming(request: Request):
    return await WebAPI.next_coming(request)
    
@app.get("/now-playing")
async def now_playing(request: Request):
    return await WebAPI.now_playing(request)
    
@app.get("/queue")
async def get_queue(request: Request):
    return await WebAPI.get_queue(request)
    
@app.get("/blocklist")
async def get_blocklist(request: Request):
    return await WebAPI.blocklist(request)
    
@app.post("/skip")
async def skip_current_song(request: Request):
    return await WebAPI.skip_current_song(request)
    
@app.post("/unblock")
async def remove_blocked_song(request: Request):
    return await WebAPI.remove_blocked_song(request)
    
@app.post("/block")
async def block_current_song(request: Request):
    return await WebAPI.block_current_song(request)
    
@app.post("/remove")
async def remove_song(request: Request):
    return await WebAPI.remove_song(request)
    
@app.post("/play")
async def play_song(request: Request):
    return await WebAPI.play_song(request)

@app.post("/reloadall")
async def reloadall(request: Request):
    return await WebAPI.reloadall(request)

async def broadcast_now_playing(action: Literal["notification", "response"], song):
    print(f"📣 BROADCASTING NOW PLAYING SONG STARTS")
    clients = ClientManager.list_all()

    for api_key, client_data in clients.items():
        websocket = client_data["websocket"]
        try:
            if websocket.application_state.name == "CONNECTED":
                await websocket.send_json({
                    "action": "broadcast_now_playing",
                    "type": action,
                    "song": song.__dict__
                })
            else:
                print(f"⚠️ Client {client_data['client_name']} not connected.")
        except Exception as e:
            print(f"💔 Error sending to {api_key}: {e}")

async def start_ws_server_async():
    def start():
        uvicorn.run(app, host="0.0.0.0", port=9626)
        
    threading.Thread(target=start, daemon=True).start()
    
if __name__ == "__main__":
    uvicorn.run(app, host="localhost", port=8000)