import logging
from sqlalchemy import (
    Column, Integer, String, Text, Numeric, BigInteger, Index, TIMESTAMP, func,
    Boolean # Import Boolean type
)
# Import Union for Python 3.9 type hinting compatibility
from typing import List, Dict, Optional, Union
from pgvector.sqlalchemy import Vector # Import Vector type from pgvector library
from . import Base # Import Base from the models package's __init__.py
# Corrected Import: Use relative import for Config
from ..config import Config # Import Config to get embedding dimension

logger = logging.getLogger(__name__)

class Product(Base):
    """
    SQLAlchemy ORM model representing the 'products' table.
    Maps Python objects to rows in the products table.
    """
    __tablename__ = 'products'

    # --- Column Definitions ---
    id = Column(Integer, primary_key=True) # Local DB auto-incrementing key
    wc_product_id = Column(BigInteger, unique=True, nullable=False, index=True) # WooCommerce ID
    sku = Column(String(255), unique=True, index=True) # SKU, indexed for lookups
    name = Column(String(512), nullable=False) # Product Name
    description = Column(Text) # Full Description
    short_description = Column(Text) # Short Description
    searchable_text = Column(Text) # Combined text for embedding / search index
    price = Column(Numeric(12, 2)) # Price (adjust precision/scale if needed)
    stock_status = Column(String(50), index=True) # Stock status ('instock', 'outofstock', etc.)
    stock_quantity = Column(Integer) # Actual quantity (can be null)
    manage_stock = Column(Boolean) # Is stock managed?
    permalink = Column(String(1024)) # Product URL
    categories = Column(Text) # Comma-separated string of category names
    tags = Column(Text) # Comma-separated string of tag names
    embedding = Column(Vector(Config.EMBEDDING_DIMENSION)) # Ensure dimension matches config/schema
    last_synced_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(), # Set default to current time on insert
        onupdate=func.now() # Update timestamp automatically on record update
    )

    # --- Optional: Define Indexes in Model (Alternative to schema.sql) ---
    # Use __table_args__ for multi-column indexes or specific index types
    # __table_args__ = (
    #     Index('idx_products_embedding_hnsw', embedding, postgresql_using='hnsw', postgresql_with={'m': 16, 'ef_construction': 64}, postgresql_ops={'embedding': 'vector_cosine_ops'}),
    #     # Add other indexes if needed here
    # )

    def __repr__(self):
        """Provides a developer-friendly representation of the Product object."""
        return f"<Product(id={self.id}, wc_product_id={self.wc_product_id}, sku='{self.sku}', name='{self.name[:30]}...')>"

    def to_search_result_dict(self):
        """
        Returns a dictionary representation suitable for basic info display
        in search results (e.g., to show the user).
        """
        price_str = f"${self.price:.2f}" if self.price is not None else "N/A"
        return {
            "wc_product_id": self.wc_product_id,
            "sku": self.sku or "N/A",
            "name": self.name,
            "price": price_str,
            "stock_status": self.stock_status or "Unknown",
            "permalink": self.permalink
        }

    def format_for_llm_search_result(self):
        """
        Formats the product information concisely for the LLM to use when
        summarizing search results found via the `search_local_products` function.
        Focuses on information present in the local cache.
        """
        price_str = f"${self.price:.2f}" if self.price is not None else "Price not available"
        status_str = f"Status: {self.stock_status}" if self.stock_status else "Status unknown"
        sku_str = f" (SKU: {self.sku})" if self.sku else ""
        return f"Name: {self.name}{sku_str}, Price: {price_str}, {status_str}"

    @staticmethod
    def prepare_searchable_text(product_data: dict) -> str:
        """
        Helper method to consistently generate the combined text field
        used for generating embeddings, based on raw product data from WC API.
        """
        parts = []
        if name := product_data.get('name'):
            parts.append(f"Name: {name}")
        if sku := product_data.get('sku'):
             parts.append(f"SKU: {sku}")
        # Prioritize short description if available
        if short_desc := product_data.get('short_description'):
            # Strip HTML tags simply (more robust parsing might be needed)
            clean_short_desc = Product._simple_strip_html(short_desc)
            parts.append(f"Info: {clean_short_desc}")
        elif desc := product_data.get('description'):
            # Use beginning of long description if short is missing
            clean_desc = Product._simple_strip_html(desc)
            parts.append(f"Info: {clean_desc[:500]}") # Limit length

        # Add categories and tags for more context
        if categories := product_data.get('categories'):
            cat_names = [cat.get('name') for cat in categories if cat.get('name')]
            if cat_names:
                 parts.append(f"Categories: {', '.join(cat_names)}")
        if tags := product_data.get('tags'):
             tag_names = [tag.get('name') for tag in tags if tag.get('name')]
             if tag_names:
                  parts.append(f"Tags: {', '.join(tag_names)}")

        return "\n".join(parts).strip()

    @staticmethod
    def _simple_strip_html(html_string: str) -> str:
        """Very basic HTML tag stripping. For more complex HTML, use a library like BeautifulSoup."""
        if not html_string:
            return ""
        import re
        # Remove HTML tags
        clean_text = re.sub(r'<[^>]+>', '', html_string)
        # Replace common HTML entities and normalize whitespace
        # Corrected replacement for non-breaking space
        clean_text = clean_text.replace('\xa0', ' ').replace(' ', ' ').replace('&', '&').replace('<', '<').replace('>', '>')
        clean_text = ' '.join(clean_text.split()) # Remove extra whitespace
        return clean_text

    @staticmethod
    # Corrected Type Hint for Python 3.9
    def format_categories_tags(data_list: Union[List[Dict], None]) -> str:
        """Formats lists of category/tag dicts from WC API into a comma-separated string."""
        if not data_list:
            return ""
        return ', '.join(item.get('name', '') for item in data_list if item.get('name'))