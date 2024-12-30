import json
import os
from typing import List, Optional
import asyncio
from asyncgpt import OpenAIChatBot
import aiofiles

history_path = "db"

if not os.path.exists(history_path):
    os.makedirs(history_path)

max_history_len = 1024

default_settings = "Используй форматирование только MarkdownV2.\n"


def history_len(history: list[dict]) -> int:
    def estimate_tokens(text: str) -> int:
        return len(text) // 4 if text else 0

    total_tokens = 0
    for message in history:
        text_tokens = estimate_tokens(message.get("text", ""))
        total_tokens += text_tokens
        if message.get("image_url", False): total_tokens += 85
    return total_tokens


class Message:
    def __init__(self, role: str, text: Optional[str] = None, image_url: Optional[str] = None):
        self.role = role
        self.text = text
        self.image_url = image_url

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "text": self.text,
            "image_url": self.image_url,
        }

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            role=data.get("role"),
            text=data.get("text"),
            image_url=data.get("image_url")
        )


def get_path(user_id: int) -> str:
    return os.path.join(history_path, f"{user_id}.json")


async def add_to_history(user_id: int, role: str, text: Optional[str] = None, image_url: Optional[str] = None):
    file_path = get_path(user_id)

    if os.path.exists(file_path):
        async with aiofiles.open(file_path, mode='r', encoding='utf-8') as f:
            history = json.loads(await f.read())
    else:
        history = {
            "settings": None,
            "messages": []
        }

    history["messages"].append(Message(role, text, image_url).to_dict())

    while history_len(history["messages"]) > max_history_len and len(history) > 3:
        history.pop(0)

    async with aiofiles.open(file_path, mode='w', encoding='utf-8') as f:
        await f.write(json.dumps(history, ensure_ascii=False, indent=4))


async def get_settings(user_id: int) -> str:
    file_path = get_path(user_id)

    if not os.path.exists(file_path):
        return None

    async with aiofiles.open(file_path, mode='r', encoding='utf-8') as f:
        history_data = json.loads(await f.read())

    return history_data["settings"]


async def get_history(user_id: int) -> List[Message]:
    file_path = get_path(user_id)

    if not os.path.exists(file_path):
        return []

    async with aiofiles.open(file_path, mode='r', encoding='utf-8') as f:
        history_data = json.loads(await f.read())

    return [Message.from_dict(item) for item in history_data["messages"]]


async def get_full_context(user_id: int) -> List[dict]:
    settings_str = await get_settings(user_id)
    history = await get_history(user_id)
    context = []
    if settings_str:
        context.append(OpenAIChatBot.pack_message(default_settings + settings_str, role="system"))
    else:
        context.append(OpenAIChatBot.pack_message(default_settings, role="system"))
    for message in history:
        context.append(OpenAIChatBot.pack_message(message.text, [message.image_url], message.role))
    print(f"Got {history_len([msg.to_dict() for msg in history])} tokens from history")
    return context


async def set_settings(user_id: int, settings: str):
    file_path = get_path(user_id)
    if os.path.exists(file_path):
        async with aiofiles.open(file_path, mode='r', encoding='utf-8') as f:
            history_data = json.loads(await f.read())
        history_data["settings"] = settings
        async with aiofiles.open(file_path, mode='w', encoding='utf-8') as f:
            await f.write(json.dumps(history_data, ensure_ascii=False, indent=4))


async def drop_settings(user_id: int):
    file_path = get_path(user_id)
    if os.path.exists(file_path):
        async with aiofiles.open(file_path, mode='r', encoding='utf-8') as f:
            history_data = json.loads(await f.read())
        history_data["settings"] = None
        async with aiofiles.open(file_path, mode='w', encoding='utf-8') as f:
            await f.write(json.dumps(history_data, ensure_ascii=False, indent=4))


async def drop_history(user_id: int):
    file_path = get_path(user_id)
    if os.path.exists(file_path):
        async with aiofiles.open(file_path, mode='r', encoding='utf-8') as f:
            history_data = json.loads(await f.read())
        history_data["messages"] = []
        async with aiofiles.open(file_path, mode='w', encoding='utf-8') as f:
            await f.write(json.dumps(history_data, ensure_ascii=False, indent=4))
