# websocket_server.py 
import asyncio 
import websockets 
import json 
import os 
from datetime import datetime 

class VerificationWebSocket: 
    """Real-time verification status updates""" 
    
    def __init__(self, host="localhost", port=8765): 
        self.host = host 
        self.port = port 
        self.clients = set() 
    
    async def handler(self, websocket): 
        self.clients.add(websocket) 
        try: 
            async for message in websocket: 
                await self.broadcast(message) 
        finally: 
            self.clients.remove(websocket) 
    
    async def broadcast(self, message): 
        if self.clients: 
            await asyncio.gather(*[ 
                client.send(message) for client in self.clients 
            ]) 
    
    async def start(self): 
        async with websockets.serve(self.handler, self.host, self.port): 
            await asyncio.Future() 
    
    def send_update(self, data): 
        asyncio.run(self.broadcast(json.dumps(data))) 
