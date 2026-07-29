from __future__ import annotations

import json


def format_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def status_event(step: str, message: str) -> str:
    return format_sse("status", {"step": step, "message": message})


def result_event(data: dict) -> str:
    return format_sse("result", data)


def error_event(code: str, message: str) -> str:
    return format_sse("error", {"error": {"code": code, "message": message}})
