"""初始化数据库（命令行入口）。

真正的逻辑在 bootstrap.ensure_db()，这里只负责把它们拿到 app context 里跑。

    python init_db.py

幂等：表已存在不动、about 页已存在不动。
传了 ADMIN_PASSWORD 环境变量则强制 upsert 管理员密码，否则首次随机创建。
"""
from app import app
from bootstrap import ensure_db

with app.app_context():
    ensure_db(verbose=True)
    print('数据库初始化完成')
