from dataclasses import dataclass

from flask import g, jsonify
from sqlalchemy.exc import IntegrityError


@dataclass
class ApiError(Exception):
    message: str
    status: int = 400
    code: str = "BAD_REQUEST"
    details: dict | None = None


def success(data=None, message="操作成功", status=200):
    return (
        jsonify(
            {
                "success": True,
                "message": message,
                "data": data,
                "request_id": getattr(g, "request_id", None),
            }
        ),
        status,
    )


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def handle_api_error(error):
        from ..extensions import db

        db.session.rollback()
        return (
            jsonify(
                {
                    "success": False,
                    "message": error.message,
                    "error": {"code": error.code, "details": error.details},
                    "request_id": getattr(g, "request_id", None),
                }
            ),
            error.status,
        )

    @app.errorhandler(IntegrityError)
    def handle_integrity_error(error):
        from ..extensions import db

        db.session.rollback()
        app.logger.warning("database integrity error: %s", error)
        return (
            jsonify(
                {
                    "success": False,
                    "message": "数据冲突，请刷新后重试",
                    "error": {"code": "DATA_CONFLICT", "details": None},
                    "request_id": getattr(g, "request_id", None),
                }
            ),
            409,
        )

    @app.errorhandler(404)
    def handle_not_found(_error):
        return (
            jsonify(
                {
                    "success": False,
                    "message": "接口不存在",
                    "error": {"code": "NOT_FOUND", "details": None},
                    "request_id": getattr(g, "request_id", None),
                }
            ),
            404,
        )

    from werkzeug.exceptions import HTTPException

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        return jsonify(
            {
                "success": False,
                "message": "请求不符合接口要求",
                "error": {"code": f"HTTP_{error.code}", "details": None},
                "request_id": getattr(g, "request_id", None),
            }
        ), error.code

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        from ..extensions import db

        db.session.rollback()
        app.logger.exception("unhandled exception: %s", error)
        return (
            jsonify(
                {
                    "success": False,
                    "message": "服务器内部错误",
                    "error": {"code": "INTERNAL_ERROR", "details": None},
                    "request_id": getattr(g, "request_id", None),
                }
            ),
            500,
        )
