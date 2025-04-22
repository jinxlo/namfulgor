from flask import Blueprint

# Create a Blueprint instance for API endpoints
# The url_prefix will prepend '/api' to all routes defined in this blueprint
api_bp = Blueprint(
    'api',
    __name__,
    url_prefix='/api'
)

# Import the routes module associated with this blueprint.
# This import should be *after* the Blueprint object is created
# to avoid circular dependencies.
from . import routes # noqa: F401 E402

# You could also import specific things if needed, but importing
# the routes module itself is usually sufficient as it registers
# the routes onto the api_bp instance upon import.