"""
AI Decision Center Backend - Flask应用工厂
"""

import os
import warnings

# 抑制 multiprocessing resource_tracker 的警告（来自第三方库如 transformers）
warnings.filterwarnings("ignore", message=".*resource_tracker.*")

from flask import Flask, request
from flask_cors import CORS

from app.config import Config
from app.utils.logger import setup_logger, get_logger


def create_app(config_class=Config):
    """Flask应用工厂函数"""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Flask >= 2.3 使用 app.json.ensure_ascii
    if hasattr(app, 'json') and hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False

    Config.ensure_directories()

    logger = setup_logger('adc')

    # 确保 meta.db schema 就绪
    try:
        from app.ontology.registry import init_schema
        init_schema()
    except Exception as e:
        # 启动时不阻断；API 路由也会再 init
        pass

    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    debug_mode = app.config.get('DEBUG', False)
    should_log_startup = not debug_mode or is_reloader_process

    if should_log_startup:
        logger.info("=" * 50)
        logger.info("AI Decision Center Backend 启动中...")
        logger.info("=" * 50)

    CORS(app, resources={r"/api/*": {"origins": "*"}})

    from app.engine.simulation_runner import SimulationRunner
    SimulationRunner.register_cleanup()
    if should_log_startup:
        logger.info("已注册模拟进程清理函数")

    @app.before_request
    def log_request():
        req_logger = get_logger('adc.request')
        req_logger.debug(f"请求: {request.method} {request.path}")
        if request.content_type and 'json' in request.content_type:
            req_logger.debug(f"请求体: {request.get_json(silent=True)}")

    @app.after_request
    def log_response(response):
        req_logger = get_logger('adc.request')
        req_logger.debug(f"响应: {response.status_code}")
        return response

    from app.api import ontology_bp, decision_bp, run_bp, simulation_bp, report_bp
    app.register_blueprint(ontology_bp)
    app.register_blueprint(decision_bp)
    app.register_blueprint(run_bp)
    app.register_blueprint(simulation_bp)
    app.register_blueprint(report_bp)

    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'AI Decision Center Backend'}

    if should_log_startup:
        logger.info("AI Decision Center Backend 启动完成")

    return app
