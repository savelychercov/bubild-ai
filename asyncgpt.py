import openai
import asyncio
from typing import Dict, Optional, Callable, Any
import json

function_pool = {}
regex_for_names = '^[a-zA-Z0-9_-]{1,64}$'


def register_function(
        description: str = None,
        param_descriptions: Dict[str, str] = None,
        followup: bool = False
):
    def decorator(func: Callable):
        annotations = func.__annotations__  # noqa

        param_info = {}
        for param_name, param_type in annotations.items():
            if param_name == 'return':
                continue
            param_info[param_name] = {
                "type": param_type.__name__ if hasattr(param_type, "__name__") else str(param_type),
                "description": param_descriptions.get(param_name, "Нет описания") if param_descriptions else "Нет описания"
            }
            if param_type.__name__ == "list":
                param_info[param_name]["type"] = "array"
                param_info[param_name]["items"] = {
                    "type": param_type.__args__[0].__name__ if hasattr(param_type.__args__[0], "__name__") else str(param_type.__args__[0])
                }
                if param_type.__args__[0].__name__ == "str":
                    param_info[param_name]["items"]["type"] = "string"
            if param_type.__name__ == "str":
                param_info[param_name]["type"] = "string"

        function_pool[func.__name__] = {
            "description": description or "Нет описания",
            "parameters": {
                "type": "object",
                "properties": {
                    param: (
                        {
                            "type": info["type"],
                            "description": info["description"]
                        }
                        if info["type"] != "array" else
                        {
                            "type": "array",
                            "description": info["description"],
                            "items": {
                                "type": info["items"]["type"],
                            }
                        }
                    )
                    for param, info in param_info.items()
                },
                "required": list(param_info.keys())
            },
            "followup": followup,
            "function": func
        }
        print(function_pool[func.__name__])
        return func

    return decorator


async def call_function_by_name(function_name: str, arguments: dict) -> Any:
    if function_name in function_pool:
        func = function_pool[function_name]["function"]
        followup = function_pool[function_name]["followup"]
        return followup, await func(**arguments)
    else:
        return {"error": "Function not found"}


class OpenAIChatBot:
    def __init__(self, api_key: str, model: str = "gpt-4o-mini", temperature: float = 0.4):
        self.client = openai.OpenAI(api_key=api_key)
        self.model = model
        self.temperature = temperature

    async def gen_answer(self, full_context: list[Dict] | str) -> tuple:
        if isinstance(full_context, str):
            full_context = [{"role": "user", "content": full_context}]

        # print("full_context:\n", json.dumps(full_context, ensure_ascii=False, indent=4))

        functions = [{
            "name": func_name,
            "description": func_data["description"],
            "parameters": func_data["parameters"]
        } for func_name, func_data in function_pool.items()]

        completion = await asyncio.to_thread(
            self.client.chat.completions.create,
            model=self.model,
            messages=full_context,
            functions=functions if functions else openai.NOT_GIVEN,
            function_call="auto" if functions else openai.NOT_GIVEN
        )

        print(f"Completion created: {completion.usage.prompt_tokens}t input, {completion.usage.completion_tokens}t output, {completion.usage.total_tokens}t sum")

        function_call = self.get_function_call(completion)
        if function_call:
            arguments = self.get_args_from_response(completion)
            needs_followup, function_result = await call_function_by_name(function_call, arguments)

            if not needs_followup: return function_result

            follow_up: openai.ChatCompletion = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=self.model,
                messages=full_context + [
                    {"role": "assistant", "content": None, "function_call": completion.function_call},
                    {"role": "function", "name": function_call, "content": json.dumps(function_result)}
                ]
            )
            return follow_up.choices[0].message.content

        # Если функция не вызвана, возвращаем обычный ответ
        return completion.choices[0].message.content

    r'''@staticmethod
    def refine_name(name: str) -> str:
        if not re.match(regex_for_names, name):
            transliterated_name = transliterate.translit(name, "ru", reversed=True)
            name = re.sub(r'[^a-zA-Z0-9_\-]', "", transliterated_name)
        name = name[:60] if len(name) > 60 else name
        return name or "NoName"'''

    @staticmethod
    def pack_message(text: str, image_urls: Optional[list[str]] = None, role: str = "user") -> Dict:
        message = {"role": role, "content": []}
        if text:
            message["content"].append({"type": "text", "text": text})
        if image_urls:
            for url in image_urls:
                if url is None or url == "": continue
                message["content"].append({"type": "image_url", "image_url": {"url": url, "detail": "low"}})
        return message

    @staticmethod
    def get_args_from_response(resp: openai.ChatCompletion) -> Optional[dict]:
        return eval(resp.choices[0].message.function_call.arguments) if resp.choices[0].message.function_call.arguments else None

    @staticmethod
    def get_function_call(resp: openai.ChatCompletion) -> Optional[str]:
        return resp.choices[0].message.function_call.name if resp.choices[0].message.function_call else None


class ClarifyQuestion:
    def __init__(self, question: str, options: list[str]):
        self.question = question
        self.options = options


@register_function(
    description="Задать уточняющий вопрос",
    param_descriptions={
        "question": "Вопрос",
        "options": "Варианты ответов"
    },
    followup=False
)
async def clarify(question: str, options: list[str]) -> str:
    return ClarifyQuestion(question, options)


class Memory:
    def __init__(self, memory: str):
        self.memory = memory


@register_function(
    description="Задать информацию о пользователе (память)",
    param_descriptions={
        "memory": "Информация о пользователе"
    },
    followup=False
)
async def set_memory(memory: str) -> str:
    return Memory(memory)


@register_function(
    description="Очистить информацию о пользователе",
    followup=False
)
async def clear_memory() -> str:
    return Memory(None)
