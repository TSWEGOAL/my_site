"""数据库自举：建表 + 灌种子 + 摆平管理员账号。

本地和线上共用这一个入口：

  - 本地：   python init_db.py
  - Render： app.py 导入时自动调用（免费实例的文件系统是临时的，
             每次重启 / 重新部署 / 从休眠唤醒都会清空，必须能自愈）

幂等：表已存在不动、about 页已存在不动、管理员按环境变量决定 upsert 还是跳过。
"""
import os
import secrets

from sqlalchemy import inspect

from extensions import db
from models import Admin, Page

# About 页缺省 Markdown；第一次跑就把这个写进数据库，
# 之后管理员在 /admin/about 后台改的就是数据库里的版本。
ABOUT_SEED_MD = """\
## 关于我

我是 **孔亿欺**，主攻数据分析 / 研究方向的学生。

平时喜欢折腾后端、脚本和有趣的小项目。这个博客是我自己写的——
**Flask + SQLite + 原生 HTML/CSS/JS**，部署在 Render 上。

### 方向

- 数据分析 / 研究
- 后端 / Web 开发
- 游戏模拟器（CS 比赛回合）
- 学习 Linux、嵌入式

### 这个站点

- **博客**：记点学习笔记和踩坑心得
- **小游戏**：6 个 HTML5 写的休闲游戏，最高分存在浏览器 localStorage
- **源码**：见本站底部 GitHub 链接（待补）

### 联系

- 评论和留言功能目前未开放，欢迎发邮件
- Email：见页脚（或后续补充）
"""


def ensure_db(verbose=False):
    """幂等自举。必须在 Flask app context 内调用。

    verbose=True 时打印每一步（本地跑 init_db.py / 看 Render 日志用）。
    """
    log = print if verbose else (lambda *a, **k: None)

    db.create_all()
    log('数据库中的表：', inspect(db.engine).get_table_names())

    # ===== 站点页面种子 =====
    if not Page.query.filter_by(slug='about').first():
        db.session.add(Page(slug='about', title='关于我', content=ABOUT_SEED_MD))
        db.session.commit()
        log('已写入 about 页种子')
    else:
        log('about 页已存在，跳过种子')

    # ===== 管理员账户 =====
    env_user = os.environ.get('ADMIN_USERNAME')
    env_pass = os.environ.get('ADMIN_PASSWORD')

    # 模式 1: 显式传了 ADMIN_PASSWORD → 强制 upsert
    #   - USERNAME 已存在 : 覆盖密码（方便线上改密码：改环境变量再重启）
    #   - USERNAME 不存在 : 用 USERNAME + PASSWORD 创建（USERNAME 缺省 'admin'）
    if env_pass:
        username = env_user or 'admin'
        existing = Admin.query.filter_by(username=username).first()
        if existing:
            existing.set_password(env_pass)
            log(f'已按环境变量重置管理员 {username} 的密码')
        else:
            admin = Admin(username=username)
            admin.set_password(env_pass)
            db.session.add(admin)
            log(f'已创建管理员 {username}（来自 ADMIN_USERNAME / ADMIN_PASSWORD）')
        db.session.commit()

    # 模式 2: 没传 ADMIN_PASSWORD → 首次随机创建，已存在跳过
    else:
        username = env_user or 'admin'
        if not Admin.query.filter_by(username=username).first():
            password = secrets.token_urlsafe(12)
            admin = Admin(username=username)
            admin.set_password(password)
            db.session.add(admin)
            db.session.commit()
            log(f'已创建管理员账号：{username}')
            log(f'随机初始密码：{password}')
            log('（请妥善保存，或通过 ADMIN_USERNAME / ADMIN_PASSWORD 环境变量指定）')
        else:
            log(f'管理员 {username} 已存在，未传 ADMIN_PASSWORD，跳过创建')
