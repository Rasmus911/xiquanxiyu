from .audit import bp as audit_bp
from .auth import bp as auth_bp
from .business import bp as business_bp
from .catalog import bp as catalog_bp
from .checkout import bp as checkout_bp
from .employees import bp as employees_bp
from .inventory import bp as inventory_bp
from .members import bp as members_bp
from .mobile import bp as mobile_bp
from .reports import bp as reports_bp
from .settings import bp as settings_bp
from .terminals import bp as terminals_bp
from .visits import bp as visits_bp
from .wristbands import bp as wristbands_bp

BLUEPRINTS = [
    business_bp,
    auth_bp,
    terminals_bp,
    employees_bp,
    settings_bp,
    wristbands_bp,
    catalog_bp,
    visits_bp,
    checkout_bp,
    members_bp,
    mobile_bp,
    inventory_bp,
    reports_bp,
    audit_bp,
]
