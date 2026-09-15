"""Flask 扩展集中初始化 + 跨蓝图共享的小工具

历史原因：早期很多模块 import admin_required，admin_required 又需要 session/url_for。
把拆装顺序最稳定的东西放这里。
"""
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from functools import wraps
from flask import session, redirect, url_for, request
from markupsafe import escape

db = SQLAlchemy()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)


def admin_required(f):
    """仅允许登录的管理员访问，否则重定向到 admin 登录页"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('admin_id'):
            return redirect(url_for('admin_login', next=request.path))
        return f(*args, **kwargs)
    return wrapper


# ===== Markdown 渲染（共享）=====
# mistune 是可选依赖：装了走真 Markdown，没装退化为纯文本段落。
try:
    import mistune
    _markdown = mistune.create_markdown()
except ImportError:
    _markdown = None


def render_markdown(text):
    """把 Markdown 文本渲染为 HTML 字符串。

    供 app.py 的 About 页 / blog.py 的文章过滤器共用，避免重复实例化 mistune。
    """
    if not text:
        return ''
    if _markdown is not None:
        return _markdown(text)
    # 退化：按空行分段，换行转 <br>
    paras = text.split('\n\n')
    return ''.join(
        '<p>%s</p>' % escape(p).replace('\n', '<br>')
        for p in paras if p.strip()
    )
