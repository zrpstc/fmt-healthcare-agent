"""Normalize native and Qwen text tool calls at the model boundary."""
from __future__ import annotations

import json
import re
import uuid
from typing import Any


class ModelProtocolError(ValueError):
    pass


def visible_text(text: str) -> str:
    # Some SGLang templates omit the opening think tag in message.content.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    if re.search(r"</think>", text, re.I):
        text = re.split(r"</think>", text, flags=re.I)[-1]
    text = re.sub(r"<think>.*$", "", text, flags=re.S | re.I)
    text = re.sub(r"<tool_call>.*?</tool_call>", "", text, flags=re.S)
    return text.strip()


def _validate(value: Any, schema: dict, path: str) -> None:
    kind = schema.get("type")
    valid = {"object": isinstance(value, dict), "array": isinstance(value, list),
             "string": isinstance(value, str), "integer": type(value) is int,
             "number": type(value) in (int, float), "boolean": type(value) is bool}
    if kind in valid and not valid[kind]:
        raise ModelProtocolError(f"工具参数 {path} 必须是 {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ModelProtocolError(f"工具参数 {path} 不在允许值中")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        if set(schema.get("required", [])) - value.keys():
            raise ModelProtocolError(f"工具参数 {path} 缺少必填字段")
        if schema.get("additionalProperties") is False and value.keys() - properties.keys():
            raise ModelProtocolError(f"工具参数 {path} 含未定义字段")
        for key, item in value.items():
            if key in properties:
                _validate(item, properties[key], f"{path}.{key}")
    if isinstance(value, list):
        if len(value) > schema.get("maxItems", float("inf")):
            raise ModelProtocolError(f"工具参数 {path} 项数超过上限")
        for item in value:
            _validate(item, schema.get("items", {}), path + "[]")
    if type(value) in (int, float):
        if value < schema.get("minimum", -float("inf")) or value > schema.get("maximum", float("inf")):
            raise ModelProtocolError(f"工具参数 {path} 超出范围")


def decode_message(message: Any, tools: list[dict]) -> tuple[str, list[dict]]:
    schemas = {tool["function"]["name"]: tool["function"]["parameters"] for tool in tools}
    raw = message.content or ""
    # Remove only reasoning before attempting to recover a tool request.
    body = re.sub(r"<think>.*?</think>", "", raw, flags=re.S | re.I)
    if re.search(r"</think>", body, re.I):
        body = re.split(r"</think>", body, flags=re.I)[-1]
    if re.search(r"<think>", body, re.I):
        raise ModelProtocolError("模型只返回了未结束的思考内容")
    calls = []
    if message.tool_calls:
        for call in message.tool_calls:
            calls.append({"id": call.id or f"call_{uuid.uuid4().hex}", "type": "function",
                          "function": {"name": call.function.name, "arguments": call.function.arguments or "{}"}})
    elif "<tool_call>" in body:
        blocks = re.findall(r"<tool_call>\s*(.*?)\s*</tool_call>", body, flags=re.S)
        if not blocks or body.count("<tool_call>") != len(blocks):
            raise ModelProtocolError("模型工具调用未完整结束")
        for block in blocks:
            if block.startswith("{"):
                try:
                    payload = json.loads(block)
                    name, params = payload["name"], payload.get("arguments", {})
                    if isinstance(params, str):
                        params = json.loads(params)
                except (ValueError, KeyError, TypeError) as exc:
                    raise ModelProtocolError("工具调用 JSON 无效") from exc
            else:
                match = re.fullmatch(r"<function=([A-Za-z_][A-Za-z0-9_]*)>\s*(.*?)\s*</function>", block, re.S)
                if not match:
                    raise ModelProtocolError("无法识别模型工具调用格式")
                name, parameter_text = match.groups()
                properties = schemas.get(name, {}).get("properties", {})
                params = {}
                pattern = r"<parameter=([A-Za-z_][A-Za-z0-9_]*)>\s*(.*?)\s*</parameter>"
                if re.sub(pattern, "", parameter_text, flags=re.S).strip():
                    raise ModelProtocolError("工具参数标签不完整")
                for key, value in re.findall(pattern, parameter_text, re.S):
                    if key in params:
                        raise ModelProtocolError("工具参数重复")
                    if properties.get(key, {}).get("type") != "string":
                        try:
                            value = json.loads(value)
                        except ValueError as exc:
                            raise ModelProtocolError(f"工具参数 {key} 格式错误") from exc
                    params[key] = value
            calls.append({"id": f"call_{uuid.uuid4().hex}", "type": "function",
                          "function": {"name": name, "arguments": json.dumps(params, ensure_ascii=False)}})
    for call in calls:
        name = call["function"]["name"]
        if name not in schemas:
            raise ModelProtocolError(f"模型调用了本轮未开放的工具：{name}")
        try:
            params = json.loads(call["function"]["arguments"])
        except (TypeError, ValueError) as exc:
            raise ModelProtocolError("工具参数不是有效 JSON") from exc
        _validate(params, schemas[name], name)
    text = visible_text(raw)
    if not calls and ("<function=" in text or "<parameter=" in text or "<tool_call" in text):
        raise ModelProtocolError("模型返回了未解析的工具调用")
    return text, calls
