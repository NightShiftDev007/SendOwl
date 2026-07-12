"""
LLM客户端封装
统一使用OpenAI格式调用；含 429/限流指数退避
"""

import json
import re
import time
from typing import Optional, Dict, Any, List, Callable, TypeVar

from openai import OpenAI

from app.config import Config

T = TypeVar("T")


def is_rate_limit_error(exc: BaseException) -> bool:
    """判断是否为限流/429 类错误。"""
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status == 429:
        return True
    body = getattr(exc, "body", None)
    text = f"{exc} {body or ''}".lower()
    markers = ("429", "rate limit", "rate_limit", "too many requests", "限流", "quota")
    return any(m in text for m in markers)


def with_rate_limit_retry(
    fn: Callable[[], T],
    max_retries: Optional[int] = None,
    base_delay: float = 1.5,
) -> T:
    """
    对可调用对象执行限流退避重试。
    仅对 429/限流错误退避；其它异常直接抛出（由调用方决定是否再重试）。
    """
    retries = max_retries if max_retries is not None else Config.LLM_RATE_LIMIT_RETRIES
    last_exc: Optional[BaseException] = None
    for attempt in range(max(1, retries)):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if not is_rate_limit_error(e) or attempt >= retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            time.sleep(delay)
    raise last_exc  # type: ignore[misc]


class LLMClient:
    """LLM客户端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model = model or Config.LLM_MODEL_NAME

        if not self.api_key:
            raise ValueError("LLM_API_KEY 未配置")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None
    ) -> str:
        """
        发送聊天请求（含限流退避）

        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大token数
            response_format: 响应格式（如JSON模式）

        Returns:
            模型响应文本
        """
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format:
            kwargs["response_format"] = response_format

        def _do():
            response = self.client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content or ""
            # 部分模型（如MiniMax M2.5）会在content中包含<think>思考内容，需要移除
            return re.sub(r'<think>[\s\S]*?</think>', '', content).strip()

        return with_rate_limit_retry(_do)

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096
    ) -> Dict[str, Any]:
        """
        发送聊天请求并返回JSON

        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大token数

        Returns:
            解析后的JSON对象
        """
        response = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"}
        )
        # 清理markdown代码块标记
        cleaned_response = response.strip()
        cleaned_response = re.sub(r'^```(?:json)?\s*\n?', '', cleaned_response, flags=re.IGNORECASE)
        cleaned_response = re.sub(r'\n?```\s*$', '', cleaned_response)
        cleaned_response = cleaned_response.strip()

        try:
            return json.loads(cleaned_response)
        except json.JSONDecodeError:
            raise ValueError(f"LLM返回的JSON格式无效: {cleaned_response}")
