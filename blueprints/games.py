from flask import Blueprint, render_template, abort, send_from_directory
import json
import os

games_bp = Blueprint('games', __name__, url_prefix='/games')

# 项目根目录（blueprints 的上一级）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAMES_DIR = os.path.join(BASE_DIR, 'games')


def load_games():
    path = os.path.join(BASE_DIR, 'games.json')
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


@games_bp.route('/')
def list_games():
    return render_template('games/list.html', games=load_games())


@games_bp.route('/<game_id>')
def play_game(game_id):
    games = load_games()
    game = next((g for g in games if g['id'] == game_id), None)
    if game is None:
        abort(404)
    return render_template('games/detail.html', game=game)


@games_bp.route('/<game_id>/assets/<path:filename>')
def game_assets(game_id, filename):
    """静态游戏资源（index.html、JS、CSS、图片等）"""
    return send_from_directory(os.path.join(GAMES_DIR, game_id), filename)
