import json
import logging
from typing import Dict, Set, List
from fastapi import WebSocket

logger = logging.getLogger("agrinex.ws")

class ConnectionManager:
    def __init__(self):
        # Map user_id -> set of active WebSockets
        self.active_connections: Dict[int, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        self.active_connections[user_id].add(websocket)
        logger.info(f"[WS] User {user_id} connected via WebSocket. Active sessions: {len(self.active_connections[user_id])}")

    def disconnect(self, websocket: WebSocket, user_id: int):
        if user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        logger.info(f"[WS] User {user_id} disconnected from WebSocket.")

    def is_online(self, user_id: int) -> bool:
        return user_id in self.active_connections and len(self.active_connections[user_id]) > 0

    async def send_json_to_user(self, user_id: int, data: dict):
        if user_id in self.active_connections:
            dead_sockets = set()
            for ws in list(self.active_connections[user_id]):
                try:
                    await ws.send_json(data)
                except Exception as e:
                    logger.warning(f"[WS] Error sending json to user {user_id}: {e}")
                    dead_sockets.add(ws)
            for ws in dead_sockets:
                self.disconnect(ws, user_id)

    async def broadcast_to_users(self, user_ids: List[int], data: dict):
        for uid in user_ids:
            await self.send_json_to_user(uid, data)

    async def broadcast_typing(self, conversation_id: int, sender_id: int, sender_name: str, is_typing: bool, recipient_ids: List[int]):
        payload = {
            "type": "typing",
            "conversation_id": conversation_id,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "is_typing": is_typing
        }
        await self.broadcast_to_users(recipient_ids, payload)

    async def broadcast_read_receipt(self, conversation_id: int, user_id: int, message_ids: List[int], recipient_ids: List[int]):
        payload = {
            "type": "read_receipt",
            "conversation_id": conversation_id,
            "user_id": user_id,
            "message_ids": message_ids,
            "status": "seen"
        }
        await self.broadcast_to_users(recipient_ids, payload)

    async def broadcast_message(self, message_data: dict, recipient_ids: List[int]):
        payload = {
            "type": "new_message",
            "message": message_data
        }
        await self.broadcast_to_users(recipient_ids, payload)

    async def broadcast_online_status(self, user_id: int, is_online: bool, last_seen: str, recipient_ids: List[int]):
        payload = {
            "type": "online_status",
            "user_id": user_id,
            "is_online": is_online,
            "last_seen": last_seen
        }
        await self.broadcast_to_users(recipient_ids, payload)

manager = ConnectionManager()
