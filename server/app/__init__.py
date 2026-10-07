import logging
import re
import uuid
from pathlib import Path

from flask import Flask, g, request
from sqlalchemy import literal, select
from werkzeug.middleware.proxy_fix import ProxyFix

from .api import BLUEPRINTS
from .api.errors import register_error_handlers
from .config import Config
from .extensions import cors, db, jwt, migrate, socketio


def create_app(config_object=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object or Config)
    if any(app.config.get(key, 1) != 1 for key in ('API_WORKERS', 'WEB_CONCURRENCY', 'API_REPLICAS')):
        raise RuntimeError('Access-policy sockets require a single API worker and a single replica')
    if app.config.get("PRODUCTION"):
        for key in ("SECRET_KEY", "JWT_SECRET_KEY"):
            value = str(app.config.get(key, ""))
            if len(value) < 32 or value.startswith("dev-only-"):
                raise RuntimeError(f"Production requires a strong {key} of at least 32 characters")
        if app.config.get("AUDIT_HMAC_KEY") and len(app.config["AUDIT_HMAC_KEY"]) < 32:
            raise RuntimeError("Production AUDIT_HMAC_KEY must contain at least 32 characters")
    if app.config.get("TRUST_PROXY_HEADERS"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    app.config["CORS_ORIGINS"] = list(dict.fromkeys([*app.config["CORS_ORIGINS"], "https://localhost"]))
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    from .business_period import register_period_hooks

    register_period_hooks(app)
    from .access_policy import register_access_policy

    register_access_policy(app)
    from .operations_upgrade import register_operations_cli

    register_operations_cli(app)
    from .operations_backup import register_operations_backup_cli

    register_operations_backup_cli(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    cors.init_app(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}},
                  expose_headers=['X-Request-ID', 'X-Business-Period', 'X-Access-Policy-Version'])
    socketio.init_app(
        app,
        cors_allowed_origins=app.config["CORS_ORIGINS"],
        async_mode=app.config.get("SOCKETIO_ASYNC_MODE"),
    )
    from .access_policy import register_policy_sockets

    if not app.config.get('MAINTENANCE_PROCESS'):
        register_policy_sockets(app)

    for blueprint in ([] if app.config.get('MAINTENANCE_PROCESS') else BLUEPRINTS):
        app.register_blueprint(blueprint, url_prefix=f"/api{blueprint.url_prefix or ''}")

    @app.before_request
    def attach_request_context():
        supplied = request.headers.get("X-Request-ID", "")
        g.request_id = supplied if re.fullmatch(r"[A-Za-z0-9._:-]{1,80}", supplied) else str(uuid.uuid4())
        if request.path.startswith("/api/") and request.is_json:
            body = request.get_json(silent=True)
            if body is not None and not isinstance(body, dict):
                from .api.errors import ApiError

                raise ApiError("请求内容必须是 JSON 对象", 400, "INVALID_BODY")

    from .business_barrier import register_barrier
    register_barrier(app)
    from .audit_service import record_rejected_request

    app.after_request(record_rejected_request)

    @app.after_request
    def append_request_id(response):
        response.headers["X-Request-ID"] = getattr(g, "request_id", "")
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/api/health")
    def health():
        db.session.execute(select(literal(1)))
        return {
            "success": True,
            "message": "服务正常",
            "data": {"api": "ok", "database": "ok"},
            "request_id": g.request_id,
        }

    register_error_handlers(app)
    # Flask runs after_request hooks in reverse registration order. Validate the
    # materialized read before audit/error headers run, so cutover failures retain
    # the normal response envelope, audit handling, and CORS headers.
    from .business_period import validate_read_response
    app.after_request(validate_read_response)

    logging.basicConfig(
        level=logging.DEBUG if app.config.get("DEBUG") else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    with app.app_context():
        if app.config.get("AUTO_CREATE_DB"):
            db.create_all()
            from .schema_maintenance import ensure_runtime_schema
            from .seed import seed_defaults

            ensure_runtime_schema()
            seed_defaults()

    return app
