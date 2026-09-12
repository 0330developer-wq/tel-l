from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from telethon import TelegramClient
from telethon.tl.functions.contacts import GetContactsRequest
import asyncio

app = FastAPI()

API_ID = 36672098
API_HASH = 'ac0e5f923698f6b5f2737043601d950f'

# Хранилище активных сессий в памяти бэкенда
sessions = {}

class PhoneReq(BaseModel):
    phone: str

class VerifyReq(BaseModel):
    phone: str
    code: str
    phone_code_hash: str

@app.post("/api/send-code")
async def send_code(data: PhoneReq):
    phone = data.phone.strip()
    
    # Создаем клиент и сохраняем его активным
    client = TelegramClient(
        f"session_{phone}", 
        API_ID, 
        API_HASH,
        device_model="PC 64bit",
        system_version="Windows 10",
        app_version="4.16.8"
    )
    
    await client.connect()
    
    try:
        sent_code = await client.send_code_request(phone)
        # Сохраняем подключенный клиент в глобальный словарь
        sessions[phone] = client
        return {"phone_code_hash": sent_code.phone_code_hash}
    except Exception as e:
        await client.disconnect()
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/verify-and-extract")
async def verify_and_extract(data: VerifyReq):
    phone = data.phone.strip()
    client = sessions.get(phone)
    
    if not client:
        raise HTTPException(status_code=400, detail="Сессия не найдена. Запросите код заново.")
        
    try:
        # Авторизуемся в ТОМ ЖЕ клиенте
        await client.sign_in(phone=phone, code=data.code, phone_code_hash=data.phone_code_hash)
        
        # Получаем контакты
        result = await client(GetContactsRequest(hash=0))
        contacts_data = [
            {
                "id": u.id,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "phone": u.phone,
                "username": u.username
            }
            for u.user in result.users
        ]
        
        # Завершаем сессию и чистим за собой
        await client.log_out()
        await client.disconnect()
        del sessions[phone]
        
        return {"status": "ok", "contacts": contacts_data}
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
