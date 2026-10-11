# -*- coding: utf-8 -*-
"""在 python -I（隔离模式，不加载用户 site-packages）下找回 pip 装的包。

隔离模式的好处是 CWD 和脚本目录不会自动进 sys.path，
所以这样跑读数据的脚本不会被目录里埋的 json.py 之类劫持；
代价是用户级 site-packages 也不加载，这里手工补上。
"""
import os
import site
import sys


def add_user_site():
    try:
        paths = [site.getusersitepackages()]
    except Exception:  # noqa: BLE001
        paths = []
    for p in paths:
        if p and os.path.isdir(p) and p not in sys.path:
            sys.path.append(p)
