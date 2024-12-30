import os
import aiogram
from aiogram.exceptions import TelegramBadRequest
from aiogram import Bot, Dispatcher
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup,
    InlineKeyboardButton, Message, ErrorEvent, Poll, PhotoSize)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.fsm.storage.memory import MemoryStorage
import logger
import sys
import json
import asyncgpt
import db

# region Utils


def escape_characters(text: str, characters: str):
    for char in characters:
        text = text.replace(char, f"\\{char}")
    return text


def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


# region Initialization


with open(resource_path("creds.json"), "r") as f:
    creds = json.load(f)

logger = logger.Logger()

print("Setting bot token")
dp = Dispatcher(storage=MemoryStorage())
bot: Bot = Bot(creds["telegram_token"])
print("Bot connected")

print("Setting OpenAI token")
gpt = asyncgpt.OpenAIChatBot(
    creds["openai_token"],
    temperature=0.4,
    model="gpt-4o-mini",
)
print("OpenAI connected")


# endregion


# region Handlers


@dp.error()
async def error_handler(event: ErrorEvent):
    logger.err(event.exception)
    if hasattr(event, "message"):
        await event.message.answer("Произошла неизвестная ошибка, попробуйте еще раз позже.")
    # await bot.send_message(event, "Произошла неизвестная ошибка, попробуйте еще раз позже.")


@dp.startup()
async def on_startup(dispatcher: Dispatcher):
    print(f"Bot \'{(await bot.get_me()).username}\' started")


@dp.shutdown()
async def on_shutdown(*args, **kwargs):
    print(f"Bot \'{(await bot.get_me()).username}\' stopped")


class LogCommandsMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Message, data: dict):
        print(f"Message from {event.from_user.username} ({event.from_user.id}): {event.text}")
        return await handler(event, data)


dp.message.middleware.register(LogCommandsMiddleware())


# endregion


# region Commands


@dp.message(Command("start"))
async def start(message: Message):
    resp = await gpt.gen_answer(
        "Привет"
    )
    await message.answer(resp)
    await db.add_to_history(message.from_user.id, "user", text="Привет")
    await db.add_to_history(message.from_user.id, "assistant", text=resp)


@dp.message(Command("drop_history"))
async def history(message: Message):
    await db.drop_history(message.from_user.id)
    await message.answer("История очищена")


class SettingsState(StatesGroup):
    waiting_for_settings = State()


@dp.message(Command("set_settings"))
async def set_settings(message: Message, state: FSMContext):
    await message.answer("Напишите новые настройки (пример: Отвечай только на английском)")
    await state.set_state(SettingsState.waiting_for_settings)


@dp.message(Command("settings"))
async def get_settings(message: Message):
    s = await db.get_settings(message.from_user.id)
    await message.answer(f"Текущие настройки:\n```text\n{s}\n```", parse_mode="MarkdownV2")


@dp.message(SettingsState.waiting_for_settings)
async def set_settings(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Напишите новые настройки (пример: Отвечай только на английском)")
        return
    await db.set_settings(message.from_user.id, message.text)
    await message.answer("Настройки сохранены")
    await state.clear()


@dp.message(Command("drop_settings"))
async def drop_settings(message: Message):
    await db.drop_settings(message.from_user.id)
    await message.answer("Настройки очищены")

# endregion


@dp.message()
async def handle_message(message: Message):
    user_id = message.from_user.id

    if not message.text and not message.photo or message.from_user.id == bot.id:
        return

    await bot.send_chat_action(chat_id=user_id, action="typing")

    file_url = None
    user_text = message.text
    if message.photo:
        photo_id = message.photo[-1].file_id
        file_info = await bot.get_file(photo_id)
        file_url = f'https://api.telegram.org/file/bot{creds["telegram_token"]}/{file_info.file_path}'
        if message.caption:
            user_text = message.caption

    context = await db.get_full_context(user_id)
    print("Text: ", user_text, "File: ", file_url)
    context += [gpt.pack_message(user_text, [file_url], "user")]

    try:
        response = await gpt.gen_answer(context)
    except Exception as e:
        logger.err(e)
        response = "Произошла неизвестная ошибка, попробуйте еще раз позже."

    try:
        await message.answer(escape_characters(response, "!.-"), parse_mode="MarkdownV2")
    except TelegramBadRequest as e:
        logger.log(f"Error while sending message to Telegram: {e.message}")
        await message.answer(response)

    await db.add_to_history(user_id, "user", text=user_text, image_url=file_url)
    await db.add_to_history(user_id, "assistant", text=response)


async def main():
    await dp.start_polling(bot)
