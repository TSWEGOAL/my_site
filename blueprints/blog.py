from flask import (Blueprint, render_template, abort, redirect, url_for,
                   request, flash)
from markupsafe import Markup
from sqlalchemy import or_

from extensions import db, admin_required, render_markdown
from models import Post

blog_bp = Blueprint('blog', __name__, url_prefix='/blog')


# mistune 是否装上由 extensions._markdown 决定；这里只复用渲染函数。
@blog_bp.app_template_filter('markdown')
def markdown_filter(text):
    """模板过滤器：把文章内容渲染成 HTML。"""
    return Markup(render_markdown(text))


# ---------- 公开页面 ----------

@blog_bp.route('/')
def list_posts():
    """博客列表，支持 ?tag=xxx 过滤。

    不开独立 ?query=&category= 等参数，MVP 阶段 tag 已经够用。
    """
    page = request.args.get('page', 1, type=int)
    active_tag = request.args.get('tag', '').strip()

    query = Post.query.order_by(Post.created_at.desc())
    if active_tag:
        # 简单 LIKE 匹配：tag 存为 "tag1, tag2" 字符串，LIKE '%tag%' 会撞前缀的
        # 比如查 "test" 也会命中 "untested"。所以先匹配 ",tag," 边界。
        # 这里用 INSTR 模拟边界匹配：',' || tag || ',' LIKE '%,tag,%'
        query = query.filter(
            Post.tag.like(f'%,{active_tag},%')
            | Post.tag.like(f'{active_tag},%')
            | Post.tag.like(f'%,{active_tag}')
            | (Post.tag == active_tag)
        )

    pagination = query.paginate(page=page, per_page=5, error_out=False)

    # 标签云：从所有文章里聚合一遍
    all_tags = {}
    for p in Post.query.all():
        for t in p.tags:
            all_tags[t] = all_tags.get(t, 0) + 1

    return render_template(
        'blog/list.html',
        posts=pagination.items,
        pagination=pagination,
        active_tag=active_tag,
        tags=all_tags,
    )


@blog_bp.route('/tag/<tag>')
def tag_filter(tag):
    """标签过滤页（与列表页等价但 URL 更干净）"""
    return redirect(url_for('blog.list_posts', tag=tag))


@blog_bp.route('/<int:post_id>')
def post_detail(post_id):
    post = Post.query.get_or_404(post_id)
    return render_template('blog/detail.html', post=post)


# ---------- 后台：发布 ----------

@blog_bp.route('/admin/new', methods=['GET', 'POST'])
@admin_required
def new_post():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        tag = _normalize_tags(request.form.get('tag', ''))

        if not title or not content:
            flash('标题和内容都不能为空', 'error')
            return redirect(url_for('blog.new_post'))

        post = Post(title=title, content=content, tag=tag)
        db.session.add(post)
        db.session.commit()

        flash('文章发布成功', 'success')
        return redirect(url_for('blog.post_detail', post_id=post.id))

    return render_template('blog/admin.html')


# ---------- 后台：编辑 ----------

@blog_bp.route('/admin/edit/<int:post_id>', methods=['GET', 'POST'])
@admin_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        tag = _normalize_tags(request.form.get('tag', ''))

        if not title or not content:
            flash('标题和内容都不能为空', 'error')
            return redirect(url_for('blog.edit_post', post_id=post.id))

        post.title = title
        post.content = content
        post.tag = tag
        db.session.commit()

        flash('文章已更新', 'success')
        return redirect(url_for('blog.post_detail', post_id=post.id))

    return render_template('blog/admin.html', post=post)


# ---------- 后台：删除 ----------

@blog_bp.route('/admin/delete/<int:post_id>', methods=['POST'])
@admin_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    db.session.delete(post)
    db.session.commit()

    flash('文章已删除', 'success')
    return redirect(url_for('blog.list_posts'))


# ---------- helpers ----------

def _normalize_tags(raw):
    """把用户输入的 tag 字符串规整成 ",tag1,tag2," 这种边界形式。

    - 去前后空格
    - 按逗号切
    - 去空 / 去重
    - 重新拼成 ",tag1,tag2,"（便于 LIKE 边界匹配）

    存储形态在 list_posts 的查询里假设这种带逗号边界的格式。
    """
    if not raw:
        return ''
    parts = [t.strip() for t in raw.split(',') if t.strip()]
    seen = []
    for p in parts:
        if p not in seen:
            seen.append(p)
    return ',' + ','.join(seen) + ',' if seen else ''
