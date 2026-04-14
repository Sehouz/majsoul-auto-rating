#!/usr/bin/env python3
"""
Utility functions for parsing Majsoul Protobuf messages

This module provides helper functions for parsing nested Wrapper messages
and game record data structures.
"""

from typing import Any, Dict, List, Optional, Type, Union
from google.protobuf.message import Message
from google.protobuf.json_format import MessageToDict

from .proto import liqi_pb2 as pb


def parse_wrapper(
    wrapper_bytes: bytes, message_type: Optional[Type[Message]] = None
) -> Message:
    """
    Parse a Wrapper message and extract its data

    Wrapper is used as a container for method calls and responses in Majsoul.
    This function decodes the Wrapper and either uses the provided message type
    or tries to infer it from the wrapper.name field.

    Args:
        wrapper_bytes: Serialized Wrapper message
        message_type: Expected message type (optional). If not provided,
                     will try to infer from wrapper.name

    Returns:
        Parsed protobuf message

    Raises:
        ValueError: If message type cannot be determined
        Exception: If parsing fails

    Example:
        >>> wrapper_data = b'...'
        >>> result = parse_wrapper(wrapper_data, pb.GameDetailRecords)
        >>> print(result.version)
    """
    # Parse the Wrapper container
    wrapper = pb.Wrapper()
    wrapper.ParseFromString(wrapper_bytes)

    # Determine the message type
    if message_type is None:
        # Try to infer from wrapper.name
        # Format: ".lq.Something" -> "Something"
        type_name = wrapper.name.split(".")[-1]
        message_type = getattr(pb, type_name, None)

        if message_type is None:
            raise ValueError(
                f"Unknown message type: {type_name} (from wrapper name: {wrapper.name})"
            )

    # Parse the contained data
    msg = message_type()
    msg.ParseFromString(wrapper.data)

    return msg


def to_dict(message: Message) -> Dict[str, Any]:
    """
    Convert protobuf message to dict, preserving field names

    Args:
        message: Any protobuf message

    Returns:
        Dictionary representation
    """
    return MessageToDict(
        message, preserving_proto_field_name=True, use_integers_for_enums=False
    )


def is_wrapper(data: bytes) -> bool:
    """
    检查 bytes 是否为 Wrapper 消息

    Args:
        data: bytes 数据

    Returns:
        True 如果是有效的 Wrapper
    """
    if not data or len(data) < 2:
        return False

    try:
        wrapper = pb.Wrapper()
        wrapper.ParseFromString(data)
        # Wrapper 的 name 字段通常以 .lq. 开头
        return bool(wrapper.name and wrapper.name.startswith((".lq.", "lq.")))
    except Exception:
        return False


def auto_parse_bytes(
    data: bytes, recursive: bool = True, include_defaults: bool = False
) -> Union[Message, Dict[str, Any], bytes]:
    """
    自动判断并解析 bytes，如果是 Wrapper 则解析内部数据，否则返回原始 bytes

    Args:
        data: 待解析的 bytes
        recursive: 是否递归解析内部的 bytes 字段

    Returns:
        如果是 Wrapper，返回 dict 包含 wrapper_name 和解析后的数据
        如果不是，返回原始 bytes
    """
    if not data:
        return data

    if not is_wrapper(data):
        return data

    try:
        wrapper = pb.Wrapper()
        wrapper.ParseFromString(data)

        # 根据 name 推断类型
        type_name = wrapper.name.split(".")[-1]
        msg_class = getattr(pb, type_name, None)

        if msg_class and wrapper.data:
            msg = msg_class()
            msg.ParseFromString(wrapper.data)

            if recursive:
                # 递归解析内部的 bytes 字段
                parsed_dict = auto_parse_message_fields(msg, include_defaults=include_defaults)
                return {
                    "_wrapper_name": wrapper.name,
                    "_wrapper_type": type_name,
                    **parsed_dict,
                }
            else:
                # 不递归，直接转 dict
                return {
                    "_wrapper_name": wrapper.name,
                    "_wrapper_type": type_name,
                    **to_dict(msg),
                }
        else:
            # Wrapper 但无法推断类型，返回 Wrapper 本身
            return {
                "_wrapper_name": wrapper.name,
                "_wrapper_data": wrapper.data.hex() if wrapper.data else None,
            }

    except Exception:
        return data


def auto_parse_message_fields(message: Message, *, include_defaults: bool = False) -> Dict[str, Any]:
    """
    递归转换 protobuf 为 dict，自动解析所有 bytes 字段

    如果 bytes 字段是 Wrapper，会自动解析为相应的 protobuf 对象，然后递归转换
    bytes 字段会被转换为包含 _wrapper_name 和解析后数据的 dict

    Args:
        message: protobuf 对象

    Returns:
        dict，所有 bytes 字段会自动尝试解析为 protobuf 对象

    Example:
        >>> record = await client.fetch_game_record(uuid)
        >>> parsed = auto_parse_message_fields(record)
        >>> print(json.dumps(parsed, indent=2))
    """
    result = {}
    present_fields = {field.name: (field, value) for field, value in message.ListFields()}

    for field in message.DESCRIPTOR.fields:
        field_name = field.name
        field_value = present_fields.get(field_name)
        if field_value is None:
            if not include_defaults:
                continue
            value = getattr(message, field_name)
        else:
            _, value = field_value

        if field.type == field.TYPE_BYTES:
            if field.label == field.LABEL_REPEATED:
                if not value and not include_defaults:
                    continue
                result[field_name] = [item.hex() if isinstance(item, bytes) else item for item in list(value)]
                continue
            # bytes 字段，尝试自动解析（递归）
            if not value and not include_defaults:
                continue
            parsed = auto_parse_bytes(value, recursive=True, include_defaults=include_defaults)
            if isinstance(parsed, dict):
                # 解析成功，已经是 dict 了
                result[field_name] = parsed
            elif isinstance(parsed, Message):
                # 解析成 protobuf 对象，递归转换
                result[field_name] = auto_parse_message_fields(parsed)
            elif isinstance(parsed, bytes):
                # 无法解析，保存为 hex
                result[field_name] = value.hex()
            else:
                result[field_name] = parsed

        elif field.type == field.TYPE_MESSAGE:
            if field.label == field.LABEL_REPEATED:
                # repeated message，递归处理每个元素
                if not value and not include_defaults:
                    continue
                result[field_name] = [
                    (
                        auto_parse_message_fields(item, include_defaults=include_defaults)
                        if isinstance(item, Message)
                        else item
                    )
                    for item in value
                ]
            else:
                # 单个 message，递归处理
                if field_value is None:
                    continue
                if isinstance(value, Message):
                    result[field_name] = auto_parse_message_fields(value, include_defaults=include_defaults)
                else:
                    result[field_name] = value

        elif field.label == field.LABEL_REPEATED:
            # repeated 基础类型
            if not value and not include_defaults:
                continue
            result[field_name] = list(value)

        else:
            # 基础类型（int, string, bool, float 等）
            result[field_name] = value

    return result


__all__ = [
    "parse_wrapper",
    "to_dict",
    "is_wrapper",
    "auto_parse_bytes",
    "auto_parse_message_fields",
]
