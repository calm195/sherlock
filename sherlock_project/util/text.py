"""字符串模板替换与终端文本处理。"""


def interpolate_string(input_object, username):
    """递归替换字符串、字典值和列表中的 {}，保留其他类型和原始输入。"""
    if isinstance(input_object, str):
        return input_object.replace("{}", username)
    elif isinstance(input_object, dict):
        return {k: interpolate_string(v, username) for k, v in input_object.items()}
    elif isinstance(input_object, list):
        return [interpolate_string(i, username) for i in input_object]
    return input_object


def has_control_characters(text: str) -> bool:
    """检查 ASCII 控制字符（U+0000–U+001F 和 U+007F）。"""
    return any(ord(char) < 32 or ord(char) == 127 for char in text)


def escape_terminal_text(text: str) -> str:
    """转义不可打印字符，避免网页昵称或用户输入改变终端显示。"""
    return "".join(char if char.isprintable() else repr(char)[1:-1] for char in text)
