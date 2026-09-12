import re
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
    FloodWaitError
)

app = FastAPI()

# Разрешаем CORS-запросы
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_ID = 36672098
API_HASH = 'ac0e5f923698f6b5f2737043601d950f'

# Хранилище сессий в оперативной памяти (без создания мусорных .session файлов на диске)
sessions = {}

def clean_phone(phone: str) -> str:
    """Очищает номер от пробелов, скобок и дефисов, оставляя только + и цифры"""
    cleaned = re.sub(r'[^\d+]', '', phone.strip())
    if not cleaned.startswith('+'):
        cleaned = '+' + cleaned
    return cleaned


class PhoneReq(BaseModel):
    phone: str


class VerifyReq(BaseModel):
    phone: str
    code: str
    phone_code_hash: str
    password: str = None  # На случай двухфакторной аутентификации (2FA)


@app.post("/api/send-code")
async def send_code(data: PhoneReq):
    phone = clean_phone(data.phone)
    
    if len(phone) < 7:
        raise HTTPException(status_code=400, detail="Некорректный номер телефона")

    # Если для этого номера уже был открыт старый клиент, отключаем его
    if phone in sessions:
        try:
            await sessions[phone].disconnect()
        except Exception:
            pass

    # Создаем клиент в оперативной памяти (MemorySession)
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
        # Авторизация по коду
        try:
            await client.sign_in(phone=phone, code=data.code.strip(), phone_code_hash=data.phone_code_hash)
        except SessionPasswordNeededError:
            if not data.password:
                return {"status": "need_2fa", "detail": "Требуется пароль двухфакторной аутентификации"}
            await client.sign_in(password=data.password)

        # Выгрузка контактов
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

        # Завершаем сессию и выходим
        await client.log_out()
        await client.disconnect()
        del sessions[phone]

        return {
            "status": "ok",
            "contacts_count": len(contacts_data),
            "contacts": contacts_data
        }

    except (PhoneCodeInvalidError, PhoneCodeExpiredError):
        raise HTTPException(status_code=400, detail="Введен неверный или устаревший код.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
