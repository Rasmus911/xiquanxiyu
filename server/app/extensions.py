from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from flask_sqlalchemy.session import Session
from sqlalchemy import inspect


class PeriodSession(Session):
    def _get_impl(self, entity, primary_key_identity, db_load_fn, **kwargs):
        from .business_period import read_period_id
        from .models import PeriodMixin

        model = inspect(entity).class_
        if issubclass(model, PeriodMixin):
            # Force the scoped SELECT even when the identity is already cached.
            kwargs['populate_existing'] = True
        row = super()._get_impl(entity, primary_key_identity, db_load_fn, **kwargs)
        if row is not None and isinstance(row, PeriodMixin):
            period_id = read_period_id()
            if period_id is not None and row.period_id != period_id:
                return None
        return row


db = SQLAlchemy(session_options={'class_': PeriodSession})
migrate = Migrate()
jwt = JWTManager()
cors = CORS()
socketio = SocketIO()
