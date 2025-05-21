import logging
from sqlalchemy import (
    Column, String, Text, TIMESTAMP, func, UniqueConstraint, Integer, NUMERIC
)
# Corrected imports for PostgreSQL specific types and pgvector
from sqlalchemy.dialects.postgresql import JSONB # JSONB is correctly part of sqlalchemy.dialects.postgresql
from pgvector.sqlalchemy import Vector          # VECTOR type comes from the pgvector library

from typing import Dict # List might not be needed here if only Dict is used by to_dict
from . import Base # Assuming Base is your SQLAlchemy declarative_base() from models/__init__.py
from ..config import Config # Assuming Config is your app's central config object

logger = logging.getLogger(__name__)

class Product(Base):
    __tablename__ = 'products'

    # Composite Primary Key from schema.sql
    id = Column(String(512), primary_key=True, comment="Composite ID: item_code + sanitized warehouse_name")

    # Core product details - lengths aligned with schema.sql
    item_code = Column(String(64), nullable=False, index=True, comment="Original item code from Damasco (e.g., D0007277)")
    item_name = Column(Text, nullable=False, comment="Product's full name or title")

    # Descriptive attributes - lengths aligned with schema.sql
    category = Column(String(128), index=True)
    sub_category = Column(String(128), index=True)
    brand = Column(String(128), index=True)
    line = Column(String(128), comment="Product line, if available")
    item_group_name = Column(String(128), index=True, comment="Broader group name like 'LÍNEA MARRÓN'")

    # Location-specific attributes - lengths aligned with schema.sql
    warehouse_name = Column(String(255), nullable=False, index=True, comment="Warehouse name from Damasco's 'whsName'")
    branch_name = Column(String(255), index=True, comment="Branch name from Damasco's 'branchName'")
    
    # Financial and stock - types aligned with schema.sql
    price = Column(NUMERIC(12, 2))
    stock = Column(Integer, default=0)
    
    # Embedding related fields
    searchable_text_content = Column(Text, comment="The actual text string used to generate the embedding")
    # Ensure Config.EMBEDDING_DIMENSION is defined and typically 1536 for text-embedding-3-small
    embedding = Column(Vector(Config.EMBEDDING_DIMENSION), comment="pgvector embedding for semantic search") 
    
    # Auditing and additional data - THIS COLUMN NAME MATCHES schema.sql
    source_data_json = Column(JSONB, default={}, comment="Original JSON data for this specific product-warehouse entry from Damasco")
    
    # Timestamps - aligned with schema.sql
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), comment="Creation timestamp with timezone")
    # The onupdate=func.now() is an ORM-level default for updates if the DB doesn't handle it.
    # Your DB trigger `set_products_timestamp` for `updated_at` is the primary mechanism.
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), comment="Last update timestamp with timezone")

    # Database constraint from schema.sql
    __table_args__ = (
        UniqueConstraint('item_code', 'warehouse_name', name='uq_item_code_per_warehouse'),
    )

    def __repr__(self):
        return (f"<Product(id='{self.id}', item_name='{self.item_name[:30]}...', "
                f"warehouse='{self.warehouse_name}', stock={self.stock})>")

    def to_dict(self) -> Dict:
        """Returns a dictionary representation of the product-location entry."""
        return {
            "id": self.id,
            "item_code": self.item_code,
            "item_name": self.item_name,
            "category": self.category,
            "sub_category": self.sub_category,
            "brand": self.brand,
            "line": self.line,
            "item_group_name": self.item_group_name,
            "warehouse_name": self.warehouse_name,
            "branch_name": self.branch_name,
            "price": float(self.price) if self.price is not None else None,
            "stock": self.stock,
            "searchable_text_content": self.searchable_text_content,
            "source_data_json": self.source_data_json,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None # Changed from last_synced_at
        }

    def format_for_llm(self, include_stock_location: bool = True) -> str:
        """Formats product information for presentation by an LLM."""
        price_str = f"${float(self.price):.2f}" if self.price is not None else "Price not available"
        
        base_info = f"{self.item_name} (Brand: {self.brand if self.brand else 'N/A'}, Category: {self.category if self.category else 'N/A'}) - {price_str}."
        
        if include_stock_location:
            stock_str = f"Stock: {self.stock}" if self.stock is not None else "Stock level unknown"
            location_str = f"Available at {self.warehouse_name}"
            if self.branch_name and self.branch_name != self.warehouse_name:
                location_str += f" (Branch: {self.branch_name})"
            return f"{base_info} {location_str}. {stock_str}."
        return base_info

    @staticmethod
    def prepare_text_for_embedding(damasco_product_data: dict) -> str:
        """
        Constructs and cleans the text string from product data specifically for generating semantic embeddings.
        """
        parts = [
            damasco_product_data.get("brand", ""),
            damasco_product_data.get("itemName", ""),
            damasco_product_data.get("category", ""),
            damasco_product_data.get("subCategory", ""),
            damasco_product_data.get("itemGroupName", ""),
            damasco_product_data.get("line", "")
        ]
        processed_parts = []
        for part in parts:
            if part and isinstance(part, str):
                cleaned_part = part.lower().strip()
                if cleaned_part:
                    processed_parts.append(cleaned_part)
            elif part:
                cleaned_part = str(part).lower().strip()
                if cleaned_part:
                    processed_parts.append(cleaned_part)
        final_text = " ".join(processed_parts)
        final_text = " ".join(final_text.split())
        return final_text.strip()

# --- End of NAMWOO/models/product.py ---