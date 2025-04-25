# This file makes the 'models' directory a Python package and defines the Base for ORM classes.

# Define the SQLAlchemy Base here to be imported by models
from sqlalchemy.orm import declarative_base

Base = declarative_base()

# Import your models here AFTER defining Base, so they register with its metadata.
# This is important for tools like Alembic or create_all to find the tables.
from .product import Product             # Assuming product.py contains the Product model
from .conversation_pause import ConversationPause # Import the new model

# You can add other models here if you create more later.
# e.g., from .user import User