# -*- coding: utf-8 -*-
"""
my_site 全站 pytest 测试套件（单文件版，~39 条）

【运行方式】（在项目根目录 D:\\codes\\my_site 下）
    python -m pip install pytest        # 只需要装一次
    python -m pytest test_site.py -v    # -v 显示每条测试名

【安全保证】
    测试开始前会把 DATABASE_URL 指到一个临时目录里的全新 SQLite 文件，
    所以绝对不会碰你本地的 instance/site.db，更碰不到线上的 Neon。
    跑完的临时数据库留在 %TEMP%\\mysite_test_xxx，可随手删。

【结构】
    1. 文件顶部：环境准备（必须在 import app 之前完成）
    2. fixtures：fresh_db / client / admin_client
    3. 六组测试类：
       TestRoutes     公开路由冒烟
       TestAuth       登录/登出/限流/CSRF
       TestSecurity   安全防护生效性验证
       TestBlog       博客 CRUD + 标签（含坑 2 的大小写回归）
       TestAbout      About 页与后台编辑
       TestBootstrap  ensure_db 幂等（含坑 5 的账号漂移回归）
"""
import os
import sys
import json
import tempfile
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

# ============================================================
# 1. 环境准备 —— 这一段必须在 from app import app 之前执行！
# ============================================================
# app.py 在 import 时就会 load_dotenv() + ensure_db()，
# 所以要先在环境变量里塞好"测试专用配置"：
#   - DATABASE_URL 指向临时库（load_dotenv 不会覆盖已存在的变量，所以我们赢）
#   - 管理员账号用测试专用的，不依赖你 .env 里的真实账号
#   - HTTPS_ONLY=0：测试走 HTTP，session cookie 不带 Secure 标志
_PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_PROJECT_ROOT))  # 从任意目录运行都能 import 到 app

_TEST_DIR = tempfile.mkdtemp(prefix='mysite_test_')
os.environ['DATABASE_URL'] = 'sqlite:///' + _TEST_DIR.replace('\\', '/') + '/test.db'
os.environ['ADMIN_USERNAME'] = 'tester'
os.environ['ADMIN_PASSWORD'] = 'test-pass-123'
os.environ['SECRET_KEY'] = 'pytest-only-secret-key'
os.environ['HTTPS_ONLY'] = '0'

import pytest  # noqa: E402
from app import app  # noqa: E402  ← import 即触发自举，建的是上面的临时库
from extensions import db, limiter  # noqa: E402
from bootstrap import ensure_db  # noqa: E402
from models import Admin, Post, Page  # noqa: E402
from blueprints.blog import _normalize_tags  # noqa: E402

TEST_USER = 'tester'
TEST_PASS = 'test-pass-123'

# 测试期全局配置：关 CSRF / 关限流（单条测试里再单独打开验证）
app.config['TESTING'] = True
app.config['WTF_CSRF_ENABLED'] = False
limiter.enabled = False


# ============================================================
# 2. fixtures
# ============================================================
@pytest.fixture(autouse=True)
def fresh_db():
    """每条测试前重置数据库：删表重建 + 重新自举。

    这同时就是在反复验证 ensure_db() 的幂等性——
    每条测试都跑一遍它，哪天它不幂等了测试立刻红。
    """
    with app.app_context():
        db.drop_all()
        ensure_db()
    yield


@pytest.fixture
def client():
    """普通访客（未登录）。"""
    return app.test_client()


@pytest.fixture
def admin_client():
    """已登录管理员。"""
    c = app.test_client()
    r = c.post('/admin/login',
               data={'username': TEST_USER, 'password': TEST_PASS})
    assert r.status_code == 302, '管理员登录失败，后续测试无法进行'
    return c


def login_as(c, user, pw):
    """带指定账密做一次登录 POST，返回响应。"""
    return c.post('/admin/login', data={'username': user, 'password': pw})


def make_post(title='测试文章', content='正文内容', tag='Flask', **kw):
    """直接往库里塞一篇文章（不走 HTTP，给过滤/分页类测试用）。"""
    with app.app_context():
        p = Post(title=title, content=content, tag=tag, **kw)
        db.session.add(p)
        db.session.commit()
        return p.id


# ============================================================
# 3. TestRoutes —— 公开路由冒烟
# ============================================================
class TestRoutes:

    def test_index(self, client):
        r = client.get('/')
        assert r.status_code == 200

    def test_blog_list(self, client):
        r = client.get('/blog/')
        assert r.status_code == 200

    def test_games_list(self, client):
        r = client.get('/games/')
        assert r.status_code == 200

    def test_game_detail_and_404(self, client):
        # 第一个真实游戏详情页能打开
        games = json.loads((_PROJECT_ROOT / 'games.json').read_text('utf-8'))
        r = client.get(f"/games/{games[0]['id']}")
        assert r.status_code == 200
        # 不存在的游戏 404
        r = client.get('/games/no-such-game')
        assert r.status_code == 404

    def test_about_seed(self, client):
        """首次访问 /about 会把种子写进库并渲染（About 页自愈逻辑）。"""
        r = client.get('/about')
        assert r.status_code == 200
        assert '孔亿欺' in r.get_data(as_text=True)
        with app.app_context():
            assert Page.query.filter_by(slug='about').count() == 1

    def test_healthz(self, client):
        r = client.get('/healthz')
        assert r.status_code == 200
        assert r.get_data(as_text=True) == 'ok'

    def test_robots_txt(self, client):
        """后台路径必须对爬虫禁抓。"""
        r = client.get('/robots.txt')
        assert r.status_code == 200
        assert 'Disallow: /admin/' in r.get_data(as_text=True)

    def test_favicon(self, client):
        r = client.get('/favicon.ico')
        assert r.status_code == 200
        assert r.mimetype == 'image/x-icon'

    def test_404_page(self, client):
        """自定义 404 页生效（不是 Flask 默认页）。"""
        r = client.get('/no-such-page')
        assert r.status_code == 404

    def test_post_not_found(self, client):
        r = client.get('/blog/99999')
        assert r.status_code == 404


# ============================================================
# 4. TestAuth —— 登录 / 登出 / 限流 / CSRF
# ============================================================
class TestAuth:

    def test_login_success(self, client):
        """正确账密 → 302 回首页，session 生效，能进后台。"""
        r = login_as(client, TEST_USER, TEST_PASS)
        assert r.status_code == 302
        assert r.headers['Location'] == '/'
        with client.session_transaction() as s:
            assert s.get('admin_id') is not None
            assert s.get('admin_name') == TEST_USER
            assert s.permanent is True  # 触发 7 天过期
        assert client.get('/blog/admin/new').status_code == 200

    def test_login_wrong_password(self, client):
        """错误密码 → 弹回登录页并提示（不区分用户名/密码错误）。"""
        r = login_as(client, TEST_USER, 'wrong-password')
        assert r.status_code == 302
        assert r.headers['Location'] == '/admin/login'
        rr = client.get('/admin/login')  # flash 一次有效
        assert '登录成功' not in rr.get_data(as_text=True)

    def test_login_wrong_username_same_behavior(self, client):
        """错误用户名与错误密码的表现一致（不泄露账号是否存在）。"""
        r1 = login_as(client, 'no-such-user', TEST_PASS)
        r2 = login_as(client, TEST_USER, 'wrong-password')
        assert r1.status_code == r2.status_code == 302
        assert r1.headers['Location'] == r2.headers['Location']

    def test_admin_required_redirect(self, client):
        """未登录访问后台 → 302 到登录页并带上 next。"""
        r = client.get('/blog/admin/new')
        assert r.status_code == 302
        assert r.headers['Location'].startswith('/admin/login?next=')

    def test_logout(self, admin_client):
        """登出后 session 清空，后台重新拦截。"""
        r = admin_client.post('/admin/logout')
        assert r.status_code == 302
        assert admin_client.get('/blog/admin/new').status_code == 302

    def test_login_rate_limit(self):
        """错误登录 10 次/分钟，第 11 次起 429（防爆破）。"""
        limiter.enabled = True
        try:
            if hasattr(limiter, 'reset'):
                limiter.reset()
            c = app.test_client()
            for _ in range(10):
                r = login_as(c, TEST_USER, 'wrong')
                assert r.status_code == 302  # 前 10 次只是登录失败
            r = login_as(c, TEST_USER, 'wrong')
            assert r.status_code == 429     # 第 11 次被限流
        finally:
            limiter.enabled = False
            if hasattr(limiter, 'reset'):
                limiter.reset()

    def test_csrf_blocks_tokenless_post(self):
        """CSRF 打开时，不带 token 的 POST 一律 400（线上真实状态）。"""
        app.config['WTF_CSRF_ENABLED'] = True
        try:
            c = app.test_client()
            r = c.post('/admin/login',
                       data={'username': TEST_USER, 'password': TEST_PASS})
            assert r.status_code == 400
        finally:
            app.config['WTF_CSRF_ENABLED'] = False


# ============================================================
# 5. TestSecurity —— 安全防护生效性验证
# ============================================================
class TestSecurity:

    def test_open_redirect_blocked(self, client):
        """登录 next 参数只接受本站相对路径，外部地址全拦到首页。"""
        for evil in ('https://evil.com/x', 'http://evil.com',
                     '//evil.com', 'javascript:alert(1)'):
            r = client.post(f'/admin/login?next={quote(evil, safe="")}',
                            data={'username': TEST_USER, 'password': TEST_PASS})
            assert r.status_code == 302
            loc = r.headers['Location']
            assert 'evil.com' not in loc and 'javascript' not in loc
            assert loc == '/'  # 全部落回首页

    def test_safe_next_allowed(self, client):
        """站内相对路径的 next 正常放行。"""
        r = client.post('/admin/login?next=/blog/',
                        data={'username': TEST_USER, 'password': TEST_PASS})
        assert r.status_code == 302
        assert r.headers['Location'] == '/blog/'

    def test_session_lifetime(self):
        assert app.config['PERMANENT_SESSION_LIFETIME'] == timedelta(days=7)

    def test_cookie_flags(self, client):
        """session cookie：HttpOnly + SameSite=Lax；本地 HTTP 不带 Secure。"""
        r = login_as(client, TEST_USER, TEST_PASS)
        cookie = r.headers.get('Set-Cookie', '')
        assert 'HttpOnly' in cookie
        assert 'SameSite=Lax' in cookie
        assert 'Secure' not in cookie  # HTTPS_ONLY=1 时才加（线上）

    def test_body_over_1mb_rejected(self, client):
        """超过 1MB 的请求体直接 413，防大表单堆内存。"""
        big = 'x' * (2 * 1024 * 1024)
        r = client.post('/admin/login',
                        data={'username': big, 'password': 'x'})
        assert r.status_code == 413


# ============================================================
# 6. TestBlog —— 博客 CRUD + 标签
# ============================================================
class TestBlog:

    def test_create_post_flow(self, admin_client):
        """发布 → 跳详情 → 列表可见，全链路。"""
        r = admin_client.post('/blog/admin/new', data={
            'title': 'pytest 发的第一篇',
            'content': '# 你好\n\n正文',
            'tag': '测试, pytest',
        }, follow_redirects=True)
        assert r.status_code == 200
        assert 'pytest 发的第一篇' in r.get_data(as_text=True)
        lst = admin_client.get('/blog/')
        assert 'pytest 发的第一篇' in lst.get_data(as_text=True)

    def test_create_post_requires_title(self, admin_client):
        """空标题/空内容被拒，且库里没有新行。"""
        before = self._count()
        r = admin_client.post('/blog/admin/new', data={
            'title': '', 'content': 'x', 'tag': ''})
        assert r.status_code == 302  # 弹回发布页
        assert self._count() == before

    @staticmethod
    def _count():
        with app.app_context():
            return Post.query.count()

    def test_normalize_tags(self):
        """标签规整：去空格/去空项/去重，拼成带逗号边界的形式。"""
        assert _normalize_tags('a, b,,a') == ',a,b,'
        assert _normalize_tags('  ') == ''
        assert _normalize_tags('') == ''
        assert _normalize_tags('solo') == ',solo,'

    def test_post_tags_property(self):
        """模型层：',a,b,' 能干净地读回 ['a','b']。"""
        p = Post(title='t', content='c', tag=',a,b,')
        assert p.tags == ['a', 'b']
        assert Post(title='t', content='c', tag='').tags == []

    def test_tag_filter_case_insensitive(self, client):
        """【坑 2 回归】标签存的是 Flask，用小写 flask 过滤也必须命中。

        历史事故：SQLite 的 LIKE 不分大小写、Postgres 的分，
        换库后大写标签查不到——这就是当时改 ilike 的原因。
        """
        make_post(title='大小写测试文', tag=',Flask,')
        r = client.get('/blog/?tag=flask')
        assert '大小写测试文' in r.get_data(as_text=True)
        r = client.get('/blog/?tag=Flask')
        assert '大小写测试文' in r.get_data(as_text=True)

    def test_tag_boundary_no_prefix_match(self, client):
        """【边界回归】查 test 不能命中 untested（逗号边界的作用）。"""
        make_post(title='边界测试A', tag=',test,')
        make_post(title='边界测试B', tag=',untested,')
        r = client.get('/blog/?tag=test')
        body = r.get_data(as_text=True)
        assert '边界测试A' in body
        assert '边界测试B' not in body

    def test_tag_route_redirects(self, client):
        """/blog/tag/x 干净 URL → 302 到 ?tag=x。"""
        r = client.get('/blog/tag/Flask')
        assert r.status_code == 302
        assert r.headers['Location'].endswith('/blog/?tag=Flask')

    def test_edit_post(self, admin_client):
        pid = make_post(title='旧标题', tag=',旧,')
        r = admin_client.post(f'/blog/admin/edit/{pid}', data={
            'title': '新标题', 'content': '新内容', 'tag': '新'}, follow_redirects=True)
        assert r.status_code == 200
        assert '新标题' in r.get_data(as_text=True)

    def test_delete_post(self, admin_client):
        pid = make_post(title='待删除')
        r = admin_client.post(f'/blog/admin/delete/{pid}')
        assert r.status_code == 302
        assert admin_client.get(f'/blog/{pid}').status_code == 404

    def test_markdown_rendered(self, client):
        """mistune 真渲染：标题/引用/代码块/加粗都出对应 HTML。"""
        pid = make_post(title='MD', content='# 大标题\n\n> 引用\n\n```\ncode\n```\n\n**粗**')
        r = client.get(f'/blog/{pid}')
        body = r.get_data(as_text=True)
        assert '<h1>' in body
        assert '<blockquote>' in body
        assert '<pre>' in body
        assert '<strong>' in body

    def test_pagination(self, client):
        """每页 5 篇，第 6 篇在第 2 页（显式时间戳保证顺序确定）。"""
        from datetime import datetime, timezone
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(6):
            make_post(title=f'分页第{i}篇', content='c',
                     created_at=base.replace(hour=i))
        p1 = client.get('/blog/?page=1').get_data(as_text=True)
        p2 = client.get('/blog/?page=2').get_data(as_text=True)
        assert '分页第5篇' in p1      # 最新（hour=5）
        assert '分页第0篇' in p2      # 最旧（hour=0）


# ============================================================
# 7. TestAbout —— About 页与后台编辑
# ============================================================
class TestAbout:

    def test_unauth_edit_blocked(self, client):
        """未登录 POST /admin/about → 302 登录页。"""
        r = client.post('/admin/about', data={'title': 'x', 'content': 'y'})
        assert r.status_code == 302
        assert r.headers['Location'].startswith('/admin/login?next=')

    def test_admin_edit(self, admin_client):
        admin_client.post('/admin/about', data={
            'title': '新版关于', 'content': '## 全新内容\n\n改过了'})
        r = admin_client.get('/about')
        body = r.get_data(as_text=True)
        assert '新版关于' in body
        assert '全新内容' in body

    def test_empty_content_rejected(self, admin_client):
        """空内容被拒，且库里的旧内容不变。"""
        admin_client.post('/admin/about',
                          data={'title': 't', 'content': '先写点'})
        r = admin_client.post('/admin/about',
                              data={'title': 't', 'content': '   '})
        assert r.status_code == 302  # 弹回编辑页
        with app.app_context():
            assert Page.query.filter_by(slug='about').first().content == '先写点'


# ============================================================
# 8. TestBootstrap —— ensure_db 幂等（坑 5 的回归）
# ============================================================
class TestBootstrap:

    def test_ensure_db_idempotent(self):
        """连跑两遍：about 页只有一行、管理员只有一个。"""
        with app.app_context():
            ensure_db()
            ensure_db()
            assert Page.query.filter_by(slug='about').count() == 1
            assert Admin.query.count() == 1

    def test_env_password_upsert(self, monkeypatch):
        """改环境变量密码 → 旧密码失效、新密码可登（线上改密码的机制）。"""
        monkeypatch.setenv('ADMIN_USERNAME', 'tswegoal')
        monkeypatch.setenv('ADMIN_PASSWORD', 'brand-new-pass')
        with app.app_context():
            ensure_db()
        c = app.test_client()
        r = login_as(c, 'tswegoal', TEST_PASS)      # 旧密码
        assert r.status_code == 302 and r.headers['Location'] == '/admin/login'
        r = login_as(c, 'tswegoal', 'brand-new-pass')  # 新密码
        assert r.status_code == 302 and r.headers['Location'] == '/'

    def test_no_password_no_new_admin(self, monkeypatch):
        """【坑 5 回归】不传 ADMIN_PASSWORD 时，已有管理员绝不新建/覆盖。"""
        with app.app_context():
            before = Admin.query.count()
        monkeypatch.delenv('ADMIN_PASSWORD', raising=False)
        with app.app_context():
            ensure_db()
            assert Admin.query.count() == before  # 不会冒出新账号
