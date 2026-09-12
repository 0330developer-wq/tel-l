import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from telethon import TelegramClient
from telethon.tl.functions.contacts import GetContactsRequest
from telethon.sessions import StringSession

API_ID = 36672098
API_HASH = 'ac0e5f923698f6b5f2737043601d950f'

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SendCodeRequest(BaseModel):
    phone: str

class VerifyRequest(BaseModel):
    phone: str
    code: str
    phone_code_hash: str

@app.post("/api/send-code")
async def send_code(data: SendCodeRequest):
    client = TelegramClient(StringSession(""), API_ID, API_HASH)
    await client.connect()
    try:
        res = await client.send_code_request(data.phone)
        return {"status": "ok", "phone_code_hash": res.phone_code_hash}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        await client.disconnect()

@app.post("/api/verify-and-extract")
async def verify(data: VerifyRequest):
    client = TelegramClient(StringSession(""), API_ID, API_HASH)
    await client.connect()
    try:
        await client.sign_in(phone=data.phone, code=data.code, phone_code_hash=data.phone_code_hash)
        
        # Исправленный запрос контактов для Telethon
        result = await client(GetContactsRequest(hash=0))
        contacts = [
            {
                "id": u.id,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "phone": u.phone,
                "username": u.username
            }
            for u in result.users
        ]

        # Полный выход (сессия уничтожается)
        await client.log_out()
        return {"status": "success", "contacts": contacts}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        await client.disconnect()
