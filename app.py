import os
import secrets
from datetime import timedelta
from urllib.parse import urlparse
from collections import Counter

from flask import (Flask, render_template, redirect, url_for, request,
                   session, flash, abort, send_from_directory)
from dotenv import load_dotenv
from markupsafe import Markup

from extensions import (db, csrf, limiter, admin_required,
                       render_markdown)
from blueprints.games import games_bp
from blueprints.blog import blog_bp
from models import Admin, Post, Page
from bootstrap import ensure_db, ABOUT_SEED_MD

# 加载 .env（开发环境用；部署到云端时改用平台的环境变量面板）
load_dotenv()

app = Flask(__name__)

# instance/ 放 SQLite 文件；托管平台首次启动时这个目录可能还不存在
os.makedirs(app.instance_path, exist_ok=True)

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY',
                                          'dev-secret-only-for-local')

# 数据库：默认 SQLite（落到 instance/site.db）
# 线上若配了 DATABASE_URL（Render Postgres / Neon / Supabase 均可）则用它
_db_url = os.environ.get('DATABASE_URL', 'sqlite:///site.db')
if _db_url.startswith('postgres://'):  # Render/Heroku 旧式前缀，SQLAlchemy 不认
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# 云数据库会掐空闲连接，pre_ping 让 SQLAlchemy 取连接前先探活
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}

# === 安全 & 资源限制 ===
# admin session 过期时间（仅在 session.permanent = True 时生效）
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
# POST body 上限（避免被大表单 / 文件堆爆内存）
app.config['MAX_CONTENT_LENGTH'] = 1 * 1024 * 1024  # 1MB
# 生产环境由环境变量 HTTPS_ONLY=True 开启
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('HTTPS_ONLY', '0') == '1'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# 初始化扩展
db.init_app(app)
csrf.init_app(app)
limiter.init_app(app)


# 模板里也能直接判断是否管理员
@app.context_processor
def inject_admin_state():
    return {'is_admin': bool(session.get('admin_id'))}


# ---------- 注册蓝图 ----------
app.register_blueprint(games_bp)
app.register_blueprint(blog_bp)


@app.route('/')
def index():
    # 最近 3 篇文章 + 标签聚合（首页展示用）
    recent = Post.query.order_by(Post.created_at.desc()).limit(3).all()
    tag_counter = Counter()
    for p in Post.query.all():
        for t in p.tags:
            tag_counter[t] += 1
    return render_template('index.html',
                           recent_posts=recent,
                           tags=tag_counter)


@app.route('/about')
def about():
    """关于我页面：内容从 Page 表读，管理员可在 /blog/admin/about 编辑。

    如果数据库还没这一行（首次运行 / 未初始化），退化到硬编码种子内容，
    保证页面不 500 —— 同时把种子回写到数据库，下次就是正常路径。
    """
    page = Page.query.filter_by(slug='about').first()
    if page is None:
        page = Page(slug='about', title='关于我', content=ABOUT_SEED_MD)
        db.session.add(page)
        db.session.commit()
    return render_template('about.html',
                           content=Markup(render_markdown(page.content)),
                           page=page,
                           is_admin_view=bool(session.get('admin_id')))


# ---------- 管理员：编辑 About ----------
@app.route('/admin/about', methods=['GET', 'POST'])
@admin_required
def admin_edit_about():
    """编辑 /about 的 Markdown 源。无 id 直接走 slug 查唯一一行。"""
    page = Page.query.filter_by(slug='about').first()
    if page is None:
        page = Page(slug='about', title='关于我', content=ABOUT_SEED_MD)
        db.session.add(page)
        db.session.commit()

    if request.method == 'POST':
        title = request.form.get('title', '').strip() or '关于我'
        content = request.form.get('content', '').strip()
        if not content:
            flash('内容不能为空', 'error')
            return redirect(url_for('admin_edit_about'))
        page.title = title
        page.content = content
        db.session.commit()
        flash('关于页已更新', 'success')
        return redirect(url_for('about'))

    return render_template('admin_about.html', page=page)


# About 页种子统一放在 bootstrap.py（ABOUT_SEED_MD），init_db 与运行时共用一份


# ---------- 管理员登录/登出 ----------
@app.route('/admin/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def admin_login():
    if session.get('admin_id'):
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        admin = Admin.query.filter_by(username=username).first()
        if admin is None or not admin.check_password(password):
            flash('用户名或密码错误', 'error')
            return redirect(url_for('admin_login'))

        session['admin_id'] = admin.id
        session['admin_name'] = admin.username
        session.permanent = True  # 触发 PERMANENT_SESSION_LIFETIME 7 天过期
        flash('登录成功', 'success')
        next_url = request.args.get('next') or url_for('index')
        # 防开放重定向：只接受相对路径（无 scheme 或 scheme 在 http/https 内）且 netloc 同站
        parsed = urlparse(next_url)
        if (parsed.scheme and parsed.scheme not in ('http', 'https')) \
                or (parsed.netloc and parsed.netloc != request.host):
            next_url = url_for('index')
        return redirect(next_url)

    return render_template('admin/login.html')


@app.route('/admin/logout', methods=['POST'])
def admin_logout():
    session.pop('admin_id', None)
    session.pop('admin_name', None)
    flash('已登出', 'success')
    return redirect(url_for('index'))


# ---------- 站点元文件（搜索引擎协议 / 浏览器图标）----------
@app.route('/robots.txt')
def robots_txt():
    """robots.txt 协议要求放在域名根路径，文件本体在 static/ 下。"""
    return send_from_directory(app.static_folder, 'robots.txt',
                               mimetype='text/plain')


@app.route('/favicon.ico')
def favicon():
    """兜底路由：部分爬虫和旧浏览器会直接请求 /favicon.ico。"""
    return send_from_directory(app.static_folder, 'favicon.ico',
                               mimetype='image/x-icon')


@app.route('/healthz')
def healthz():
    """健康检查端点（Render 面板的 Health Check Path 填 /healthz）。

    刻意不查数据库：Neon 免费档会休眠，查库可能因冷启动超时，
    被 Render 误判为不健康而反复重启服务。
    这里只证明「Web 进程活着、能响应请求」。
    """
    return 'ok', 200, {'Content-Type': 'text/plain; charset=utf-8'}


@app.errorhandler(404)
def not_found(e):
    return render_template('errors/404.html'), 404


@app.errorhandler(403)
def forbidden(e):
    return render_template('errors/403.html'), 403


@app.errorhandler(500)
def server_error(e):
    return render_template('errors/500.html'), 500


# ---------- 启动自举 ----------
# 关键：托管平台（Render 免费实例等）的文件系统是临时的，
# 每次重启 / 重新部署 / 从休眠唤醒都会把 instance/site.db 清掉。
# 所以进程一启动就确保表和管理员账号在位，任何启动方式（gunicorn / python app.py）都自愈。
with app.app_context():
    ensure_db()


if __name__ == '__main__':
    # 本地开发用；线上由 gunicorn 接管（见 Procfile）
    app.run(debug=True, host='127.0.0.1', port=int(os.environ.get('PORT', 5000)))
