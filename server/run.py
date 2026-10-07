import os
import sys

from app import create_app
from app.extensions import socketio

app = create_app()

if "--smoke-test" in sys.argv:
    with app.test_client() as client:
        response = client.get("/api/health")
        print(response.get_json())
        raise SystemExit(0 if response.status_code == 200 else 1)


if __name__ == "__main__":
    if app.config.get('RESET_WORKER_ENABLED'):
        with app.app_context():
            from app.reset_service import recover_reset_tasks
            from app.security_spool import import_spool_events
            recover_reset_tasks()
            import_spool_events()
    socketio.run(
        app,
        host=os.getenv("XIQUAN_HOST", "0.0.0.0"),
        port=int(os.getenv("XIQUAN_PORT", "5000")),
        debug=app.config["DEBUG"],
    )
