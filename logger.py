import requests
import traceback
import os
import sys
import json
import re

loaded = False


def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def slice_text(text: str, length: int = 1990) -> list[str]:
    if not text:
        return [""]

    if len(text) <= length:
        return [text]

    # Разбиваем текст на блоки Markdown и на обычный текст
    blocks = re.split(r'(```.*?```)', text, flags=re.DOTALL)

    result = []
    for block in blocks:
        if block.startswith("```") and block.endswith("```"):  # Это Markdown блок
            content = block[3:-3]  # Убираем ```

            # Разбиваем содержимое Markdown блока на части
            slices = [f"```python\n{content[i:i + length]}```" for i in range(0, len(content), length)]
            result.extend(slices)
        else:
            # Разбиваем обычный текст на части
            result.extend([block[i:i + length] for i in range(0, len(block), length)])

    return result


def singleton(cls):
    instances = {}

    def getinstance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return getinstance


@singleton
class Logger:
    def __init__(self, creds_path="creds.json"):

        with open(resource_path(creds_path), "r") as f:
            creds = json.load(f)

        print("Setting telegram logger token")
        self.telegram_apikey = creds.get("logger_token", None)
        if self.telegram_apikey is None:
            raise ValueError("WARNING: Telegram API key is not set, logs will not be sent to Telegram.")
        self.logs_user_id = creds.get("logger_chat_id", None)
        if self.logs_user_id is None:
            raise ValueError("WARNING: User ID is not set, logs will not be sent to Telegram.")
        self.name = creds.get("logger_name", None)
        if self.name is None:
            print("WARNING: Project name is not set in the logger.json file, using default name 'Test Logger'")
            self.name = "Test Logger"

    @staticmethod
    def escape_markdown(text):
        escape_chars = ['_', '*', '[', ']', '(', ')', '~', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in escape_chars:
            text = text.replace(char, f'\\{char}')
        return text

    def log(self, text, markdown: bool = True) -> None:
        url = f"https://api.telegram.org/bot{self.telegram_apikey}/sendMessage"
        text = f"From {self.name}:\n\n" + str(text)
        text = self.escape_markdown(text)
        if self.logs_user_id is None:
            print("WARNING: This message was not sent to Telegram because the ID_LOGS is not set in the .env file")
            return

        for text_part in slice_text(text):
            params = {
                "chat_id": self.logs_user_id,
                "text": text_part,
            }
            if markdown: params["parse_mode"] = "MarkdownV2"
            print(text_part)
            resp = requests.post(url, params=params)

            if resp.status_code != 200:
                with open("log.txt", "a") as f:
                    f.write(f"{resp.status_code}: {resp.text}\n\n{text_part}\n\n")

                params = {
                    "chat_id": self.logs_user_id,
                    "text": f"Error sending message to Telegram:\n{resp.status_code} {resp.text}\nLog saved to log.txt",
                }
                requests.post(url, params=params)

    def err(self, error: Exception, additional_text: str = ""):
        traceback_str = ''.join(traceback.format_exception(
            type(error),
            error,
            error.__traceback__)
        )
        text = f"""{additional_text}\n```python\n{traceback_str}```"""
        self.log(text)
