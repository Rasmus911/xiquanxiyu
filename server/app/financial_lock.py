"""One transaction lock for money/stock writes; row locks follow it."""
from functools import wraps

from sqlalchemy import text

from .extensions import db

FINANCIAL_LOCK_KEY = 713829418


def lock_financial_writes(session):
    if session.get_bind().dialect.name == 'postgresql':
        session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': FINANCIAL_LOCK_KEY})


def serialized_financial_write(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        serialize_financial_session(db.session)
        return function(*args, **kwargs)
    return wrapped


def serialize_financial_session(session):
    """Same barrier -> money -> rows order for HTTP and direct services."""
    from .business_barrier import shared_barrier
    shared_barrier(session.connection())
    lock_financial_writes(session)
