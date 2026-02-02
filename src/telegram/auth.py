from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from loguru import logger

from src.telegram.client import save_session_string


async def interactive_auth(client: TelegramClient) -> bool:
    """
    Интерактивная авторизация при первом запуске.
    Запрашивает телефон и код через stdin.

    Returns:
        True если авторизация успешна, False если уже авторизован.
    """
    await client.connect()

    if await client.is_user_authorized():
        logger.info("Уже авторизован в Telegram")
        return False

    phone = input("Введи номер телефона (+7...): ").strip()
    await client.send_code_request(phone)

    code = input("Введи код из Telegram: ").strip()

    try:
        await client.sign_in(phone, code)
    except SessionPasswordNeededError:
        password = input("Введи 2FA пароль: ").strip()
        await client.sign_in(password=password)

    # Сохраняем сессию
    session_string = client.session.save()
    save_session_string(session_string)

    me = await client.get_me()
    logger.info(f"Авторизация успешна! Logged in as {me.first_name} (ID: {me.id})")

    return True
