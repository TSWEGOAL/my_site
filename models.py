from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db


class Admin(db.Model):
    """站点唯一管理员（个人博客不开放注册，管理员账号在 init_db.py 中创建）"""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    # 标签：逗号分隔的字符串，简单够用；
    # 不开 Many-to-many 是为了在没 admin 之前不引入 extra 表，避免复杂度
    tag = db.Column(db.String(200), default='', nullable=False)
    created_at = db.Column(db.DateTime,
                           default=lambda: datetime.now(timezone.utc))

    @property
    def tags(self):
        """返回 tag 的列表形式，空字符串返回 []"""
        if not self.tag:
            return []
        return [t.strip() for t in self.tag.split(',') if t.strip()]


class Page(db.Model):
    """站点静态/半静态页面（slug 路由 -> Markdown 内容）。

    现阶段只承载 about 一页；保留通用结构是为了以后能加
    比如 /privacy、/friends 等页面无需改 schema。
    """
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(80), unique=True, nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False, default='')
    content = db.Column(db.Text, nullable=False, default='')
    updated_at = db.Column(db.DateTime,
                           default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))
