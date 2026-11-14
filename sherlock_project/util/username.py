"""用户名占位符检查与展开。"""

checksymbols = ["_", "-", "."]


def check_for_parameter(username):
    """检查用户名是否包含 {?} 占位符，以判断是否需要生成多个用户名。"""
    return "{?}" in username


def multiple_usernames(username):
    """用不同符号替换占位符，并返回生成的用户名列表。"""
    allUsernames = []
    for i in checksymbols:
        allUsernames.append(username.replace("{?}", i))
    return allUsernames
