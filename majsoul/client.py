#!/usr/bin/env python3
"""
Majsoul WebSocket Client

A simple client for communicating with Majsoul servers using WebSocket and Protobuf.
"""

import asyncio
import logging
import struct
import time
import uuid
from typing import Any, Optional, Dict, Callable
from enum import IntEnum

import aiohttp
import websockets

from .proto import liqi_pb2 as pb
from .exceptions import (
    ConnectionError as MajsoulConnectionError,
    AuthenticationError,
    TimeoutError as MajsoulTimeoutError,
    MessageError,
)


# Server configurations
SERVERS = {
    "cn": {
        "name": "China",
        "base_url": "https://game.maj-soul.com/1/",
    },
    "jp": {
        "name": "Japan",
        "base_url": "https://game.mahjongsoul.com/",
    },
    "en": {
        "name": "International",
        "base_url": "https://mahjongsoul.game.yo-star.com/",
    },
}

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
logger = logging.getLogger(__name__)


def _build_response_class_map() -> Dict[str, Any]:
    """Build a method -> response message map from protobuf service descriptors."""
    response_map: Dict[str, Any] = {}
    for service_name, service_desc in pb.DESCRIPTOR.services_by_name.items():
        for method_name, method_desc in service_desc.methods_by_name.items():
            response_class = getattr(pb, method_desc.output_type.name, None)
            if response_class is None:
                continue
            response_map[f".lq.{service_name}.{method_name}"] = response_class
    return response_map


PROTO_RESPONSE_CLASS_MAP = _build_response_class_map()


class MsgType(IntEnum):
    """Majsoul message types"""
    NOTIFY = 1
    REQUEST = 2
    RESPONSE = 3


class MajsoulClient:
    """
    Majsoul WebSocket Client
    
    A simple client for communicating with Majsoul game servers.
    
    Usage:
        client = MajsoulClient(server="cn")
        await client.connect()
        await client.login(access_token)
        
        # Make API calls
        request = pb.ReqGameRecordList()
        request.start = 0
        request.count = 10
        response = await client.call(".lq.Lobby.fetchGameRecordList", request)
        
        await client.close()
    """
    
    def __init__(self, server: str = "cn", request_timeout: float = 30.0):
        """
        Initialize Majsoul client
        
        Args:
            server: Server region ("cn", "jp", or "en")
            request_timeout: Default timeout for requests in seconds
        """
        if server not in SERVERS:
            raise ValueError(f"Invalid server: {server}. Must be one of {list(SERVERS.keys())}")
        
        self.server = server
        self.server_config = SERVERS[server]
        self.base_url = self.server_config["base_url"]
        self.request_timeout = request_timeout
        
        # Connection state
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.version: Optional[str] = None
        self.client_version_string: Optional[str] = None
        self.account_id: Optional[int] = None
        
        # Message handling
        self.msg_id = 0
        self.pending_requests: Dict[int, tuple] = {}  # msg_id -> (future, response_class)
        self._receiver_task: Optional[asyncio.Task] = None
        self._notify_callbacks = []
        
    async def _fetch_json(self, url: str, bust_cache: bool = False) -> dict:
        """Fetch JSON from URL"""
        if bust_cache:
            url += ("&" if "?" in url else "?") + f"randv={int(time.time() * 1000)}"
        
        headers = {"User-Agent": USER_AGENT}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                return await resp.json()
    
    async def _get_server_list(self) -> list:
        """Get available WebSocket servers"""
        # Get version info
        version_info = await self._fetch_json(f"{self.base_url}version.json", bust_cache=True)
        self.version = version_info["version"]
        self.client_version_string = "web-" + self.version.replace(".w", "")
        
        # Get resource version info
        res_info = await self._fetch_json(f"{self.base_url}resversion{self.version}.json")
        
        # Get config with server list
        config_prefix = res_info["res"]["config.json"]["prefix"]
        config = await self._fetch_json(f"{self.base_url}{config_prefix}/config.json")
        
        # Extract server list
        ip_def = next((x for x in config.get("ip", []) if x.get("name") == "player"), None)
        if not ip_def:
            ip_def = config.get("ip", [{}])[0]
        
        servers = []
        
        # Try gateways first
        if ip_def.get("gateways"):
            for gw in ip_def["gateways"]:
                url = gw.get("url", "")
                if url:
                    # Remove http(s):// prefix
                    url = url.replace("https://", "").replace("http://", "")
                    servers.append(url)
        
        # Try region_urls
        if not servers and ip_def.get("region_urls"):
            region_urls = ip_def["region_urls"]
            if isinstance(region_urls, dict):
                region_urls = list(region_urls.values())
            for region in region_urls:
                url = region.get("url", region) if isinstance(region, dict) else region
                if url:
                    servers.append(url)
        
        return servers
    
    async def connect(self):
        """Connect to Majsoul server"""
        if self.ws is not None:
            raise MajsoulConnectionError("Already connected")
        
        servers = await self._get_server_list()
        if not servers:
            raise MajsoulConnectionError("No servers available")
        
        # Try each server
        last_error = None
        for server in servers:
            try:
                # Get route info
                route_url = f"https://{server}/api/clientgate/routes?platform=Web&version={self.version}"
                try:
                    route_info = await self._fetch_json(route_url, bust_cache=True)
                    if route_info.get("data", {}).get("maintenance"):
                        logger.info("Server %s is under maintenance", server)
                        continue
                except Exception:
                    pass
                
                ws_url = f"wss://{server}/gateway"
                logger.debug("Connecting to %s", ws_url)
                
                self.ws = await websockets.connect(
                    ws_url,
                    additional_headers={"User-Agent": USER_AGENT},
                )
                logger.info("Connected to %s", server)
                
                # Start message receiver
                self._receiver_task = asyncio.create_task(self._message_receiver())
                return
                
            except Exception as e:
                last_error = e
                logger.warning("Failed to connect to %s: %s", server, e)
                continue
        
        raise MajsoulConnectionError(f"Failed to connect to any server: {last_error}")
    
    async def close(self):
        """Close connection"""
        if self._receiver_task:
            self._receiver_task.cancel()
            try:
                await self._receiver_task
            except asyncio.CancelledError:
                pass
        
        if self.ws:
            await self.ws.close()
            self.ws = None
        
        # Clear pending requests
        for msg_id, (future, _) in self.pending_requests.items():
            if not future.done():
                future.set_exception(MajsoulConnectionError("Connection closed"))
        self.pending_requests.clear()
    
    def _encode_request(self, msg_id: int, method: str, request_pb: Any) -> bytes:
        """
        Encode a request message
        
        Args:
            msg_id: Message ID
            method: Method name (e.g., ".lq.Lobby.fetchGameRecord")
            request_pb: Protobuf request object
            
        Returns:
            Encoded message bytes
        """
        try:
            # Create wrapper
            wrapper = pb.Wrapper()
            wrapper.name = method
            wrapper.data = request_pb.SerializeToString()
            
            # Pack into Majsoul message format:
            # [type:1byte][msg_id:2bytes][wrapper_data]
            message = (
                bytes([MsgType.REQUEST]) +
                struct.pack("<H", msg_id) +
                wrapper.SerializeToString()
            )
            
            return message
        except Exception as e:
            raise MessageError(f"Failed to encode request: {e}")
    
    def _decode_response(self, data: bytes) -> Optional[Any]:
        """
        Decode a response message
        
        Args:
            data: Raw message bytes
            
        Returns:
            Decoded response or None if not a valid response
        """
        if len(data) < 3:
            return None
        
        msg_type = data[0]
        
        if msg_type == MsgType.RESPONSE:
            msg_id = struct.unpack("<H", data[1:3])[0]
            
            if msg_id not in self.pending_requests:
                return None
            
            future, response_class = self.pending_requests.pop(msg_id)
            
            try:
                # Parse wrapper
                wrapper = pb.Wrapper()
                wrapper.ParseFromString(data[3:])
                
                # Parse response
                response = response_class()
                response.ParseFromString(wrapper.data)
                
                # Set future result
                if not future.done():
                    future.set_result(response)
                
            except Exception as e:
                if not future.done():
                    future.set_exception(MessageError(f"Failed to decode response: {e}"))
        
        elif msg_type == MsgType.NOTIFY:
            # Handle notify messages
            try:
                wrapper = pb.Wrapper()
                wrapper.ParseFromString(data[3:])
                
                # Call registered callbacks
                for callback in self._notify_callbacks:
                    try:
                        asyncio.create_task(callback(wrapper.name, wrapper.data))
                    except Exception as e:
                        logger.exception("Error in notify callback")
            except Exception as e:
                logger.warning("Failed to decode notify: %s", e)
        
        return None
    
    async def _message_receiver(self):
        """Background task: continuously receive and process messages"""
        try:
            while True:
                data = await self.ws.recv()
                self._decode_response(data)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("Message receiver error: %s", e)
            # Notify all pending requests of the error
            for msg_id, (future, _) in list(self.pending_requests.items()):
                if not future.done():
                    future.set_exception(MajsoulConnectionError(f"Receiver error: {e}"))
            self.pending_requests.clear()
    
    def _get_response_class(self, method: str, request_pb: Any) -> Any:
        """
        Resolve response class from protobuf descriptors first, then fall back
        to name-based inference for compatibility.
        
        Args:
            method: Method name
            request_pb: Request protobuf object
            
        Returns:
            Response protobuf class
        """
        response_class = PROTO_RESPONSE_CLASS_MAP.get(method)
        if response_class:
            return response_class

        # Fallback 1: Infer from request class name (Req -> Res)
        req_name = request_pb.__class__.__name__
        if req_name.startswith("Req"):
            res_name = "Res" + req_name[3:]
            res_class = getattr(pb, res_name, None)
            if res_class:
                return res_class

        # Fallback 2: Try to infer from method name
        method_simple = method.split(".")[-1]
        res_name = "Res" + method_simple[0].upper() + method_simple[1:]
        res_class = getattr(pb, res_name, None)
        if res_class:
            return res_class
        
        raise MessageError(f"Cannot infer response class for method: {method}")
    
    async def call(self, method: str, request_pb: Any, timeout: Optional[float] = None) -> Any:
        """
        Call a Majsoul API method
        
        Args:
            method: Method name (e.g., ".lq.Lobby.fetchGameRecord")
            request_pb: Protobuf request object (already filled with data)
            timeout: Request timeout in seconds (default: use client's timeout)
            
        Returns:
            Protobuf response object
            
        Raises:
            MajsoulConnectionError: If not connected
            MajsoulTimeoutError: If request times out
            MessageError: If encoding/decoding fails
        """
        if self.ws is None:
            raise MajsoulConnectionError("Not connected. Call connect() first.")
        
        self.msg_id += 1
        msg_id = self.msg_id
        
        # Get response class
        response_class = self._get_response_class(method, request_pb)
        
        # Create future for response
        future = asyncio.Future()
        self.pending_requests[msg_id] = (future, response_class)
        
        # Encode and send
        message = self._encode_request(msg_id, method, request_pb)
        await self.ws.send(message)
        
        # Wait for response
        if timeout is None:
            timeout = self.request_timeout
        
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            # Clean up pending request
            if msg_id in self.pending_requests:
                del self.pending_requests[msg_id]
            raise MajsoulTimeoutError(f"Request timeout after {timeout}s: {method}")
    
    async def login(self, access_token: str) -> dict:
        """
        Login with access token
        
        Args:
            access_token: OAuth2 access token
            
        Returns:
            Login response data
            
        Raises:
            AuthenticationError: If login fails
        """
        # Send heartbeat first
        heatbeat_req = pb.ReqHeatBeat()
        heatbeat_req.no_operation_counter = 0
        await self.call(".lq.Lobby.heatbeat", heatbeat_req)
        await asyncio.sleep(0.1)
        
        # Check token
        check_req = pb.ReqOauth2Check()
        check_req.type = 0
        check_req.access_token = access_token
        
        check_result = await self.call(".lq.Lobby.oauth2Check", check_req)
        
        if not check_result.has_account:
            await asyncio.sleep(2)
            check_result = await self.call(".lq.Lobby.oauth2Check", check_req)
        
        if not check_result.has_account:
            raise AuthenticationError("Token invalid or no account associated")
        
        # Login
        login_req = pb.ReqOauth2Login()
        login_req.type = 0
        login_req.access_token = access_token
        login_req.reconnect = False
        login_req.device.platform = "pc"
        login_req.device.hardware = "pc"
        login_req.device.os = "windows"
        login_req.device.os_version = "win10"
        login_req.device.is_browser = True
        login_req.device.software = "Chrome"
        login_req.device.sale_platform = "web"
        login_req.random_key = str(uuid.uuid4())
        login_req.client_version.resource = self.version
        login_req.client_version_string = self.client_version_string
        
        result = await self.call(".lq.Lobby.oauth2Login", login_req)
        
        if not result.account_id:
            raise AuthenticationError(f"Login failed: {result}")
        
        self.account_id = result.account_id
        logger.info("Logged in as account: %s", result.account_id)
        
        return result
    
    def on_notify(self, callback: Callable[[str, bytes], Any]):
        """
        Register a callback for NOTIFY messages
        
        Args:
            callback: Async function that takes (method_name, data_bytes)
        """
        self._notify_callbacks.append(callback)
    
    # Convenience methods for common operations
    
    async def fetch_game_record(self, game_uuid: str) -> pb.ResGameRecord:
        """
        Fetch a specific game record
        
        Args:
            game_uuid: Game UUID
            
        Returns:
            ResGameRecord
        """
        req = pb.ReqGameRecord()
        req.game_uuid = game_uuid
        req.client_version_string = self.client_version_string
        return await self.call(".lq.Lobby.fetchGameRecord", req)
    
    async def fetch_game_record_list(self, start: int = 0, count: int = 10) -> pb.ResGameRecordList:
        """
        Fetch list of game records
        
        Args:
            start: Start index
            count: Number of records to fetch
            
        Returns:
            ResGameRecordList
        """
        req = pb.ReqGameRecordList()
        req.start = start
        req.count = count
        req.type = 0
        return await self.call(".lq.Lobby.fetchGameRecordList", req)
