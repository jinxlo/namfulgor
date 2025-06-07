# namwoo_app/api/__init__.py
from flask import Blueprint

# This blueprint instance will be imported by routes.py and battery_api_routes.py
# (or rather, routes.py will import this as 'api_bp' and battery_api_routes.py
# will create its own 'battery_api_bp').
# The main app registration in the root __init__.py will handle the url_prefix.
api_bp = Blueprint(
    'api',
    __name__
    # url_prefix='/api' # This is not strictly necessary here, as the registration in app factory handles it.
)

# Import route modules that use THIS specific 'api_bp' blueprint.
# 'battery_api_routes.py' creates and uses its own blueprint ('battery_bp'),
# so it's not imported here directly to be part of 'api_bp'.
# It's registered separately in the app factory.
from . import routes # This line imports routes.py, which uses 'api_bp'

# REMOVED: from . import receiver_routes # This file does not exist

# Note: Your main app factory (namwoo_app/__init__.py) correctly imports and registers
# 'routes.bp' (which is this 'api_bp') and 'battery_api_routes.battery_bp' separately.
# This structure is fine.