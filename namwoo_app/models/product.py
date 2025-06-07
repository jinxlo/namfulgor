# namwoo_app/models/product.py
import logging
import re 
from sqlalchemy import (
    Column, String, Text, TIMESTAMP, func, Integer, NUMERIC,
    ForeignKey, Table
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
# from pgvector.sqlalchemy import Vector 
# from ..config import Config 

from . import Base 

logger = logging.getLogger(__name__)

# --- JUNCTION TABLE for Product (Battery) to Vehicle Fitment ---
# Name MUST match the table name in your schema.sql ('battery_vehicle_fitments')
battery_vehicle_fitments_junction_table = Table('battery_vehicle_fitments', Base.metadata, # <<< RENAMED VARIABLE & TABLE NAME
    Column('battery_product_id_fk', String(255), ForeignKey('batteries.id', ondelete='CASCADE'), primary_key=True), 
    Column('fitment_id_fk', Integer, ForeignKey('vehicle_battery_fitment.fitment_id', ondelete='CASCADE'), primary_key=True)
)

# --- TABLE for Vehicle Fitment Information ---
class VehicleBatteryFitment(Base): # This class defines a Vehicle Configuration
    __tablename__ = 'vehicle_battery_fitment' 

    fitment_id = Column(Integer, primary_key=True, autoincrement=True)
    vehicle_make = Column(String(100), nullable=False, index=True)
    vehicle_model = Column(String(100), nullable=False, index=True)
    year_start = Column(Integer, index=True)
    year_end = Column(Integer, index=True)
    engine_details = Column(Text, nullable=True) # Matched schema (nullable)
    notes = Column(Text, nullable=True)         # Matched schema (nullable)
    # created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False) # Add if in schema
    # updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False) # Add if in schema

    compatible_battery_products = relationship(
        "Product", 
        secondary=battery_vehicle_fitments_junction_table, # <<< Use corrected table name
        back_populates="fits_vehicles"
    )

    def __repr__(self):
        return (f"<VehicleBatteryFitment(fitment_id={self.fitment_id}, make='{self.vehicle_make}', "
                f"model='{self.vehicle_model}', years='{self.year_start}-{self.year_end}')>")

class Product(Base): 
    __tablename__ = 'batteries' 

    id = Column(String(255), primary_key=True, index=True, comment="Unique Battery ID, e.g., Fulgor_NS40-670")
    brand = Column(String(128), nullable=False, index=True, comment="Battery Brand (e.g., Fulgor, Optima)")
    model_code = Column(String(100), nullable=False, comment="Specific model code of the battery, e.g., NS40-670")
    item_name = Column(Text, nullable=True, comment="Full descriptive name, e.g., 'Fulgor PowerMax NS40-670 Heavy Duty'")
    description = Column(Text, nullable=True, comment="Additional details or features of the battery (plain text expected)")
    warranty_months = Column(Integer, nullable=True, comment="Warranty in months for the battery")
    price_regular = Column(NUMERIC(12, 2), nullable=False, comment="Regular retail price")
    battery_price_discount_fx = Column(NUMERIC(12, 2), nullable=True, comment="Special discounted price for FX payment") 
    stock = Column(Integer, default=0, nullable=False, comment="Overall stock for this battery model")
    additional_data = Column(JSONB, nullable=True, comment="Stores pre-formatted message templates or other battery-specific JSON data")
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    fits_vehicles = relationship(
        "VehicleBatteryFitment",
        secondary=battery_vehicle_fitments_junction_table, # <<< Use corrected table name
        back_populates="compatible_battery_products"
    )

    def __repr__(self):
        return (f"<Product(Battery)(id='{self.id}', brand='{self.brand}', model='{self.model_code}', "
                f"price_regular='{self.price_regular}')>")

    def to_dict(self):
        """Returns a dictionary representation of the battery product."""
        return {
            "id": self.id,
            "brand": self.brand,
            "model_code": self.model_code,
            "item_name": self.item_name,
            "description": self.description,
            "warranty_months": self.warranty_months,
            "price_regular": float(self.price_regular) if self.price_regular is not None else None,
            "battery_price_discount_fx": float(self.battery_price_discount_fx) if self.battery_price_discount_fx is not None else None,
            "stock": self.stock,
            "additional_data": self.additional_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def format_for_llm(self):
        """Formats battery information for presentation by an LLM."""
        # ... (your existing format_for_llm method - it looks fine) ...
        if self.additional_data and isinstance(self.additional_data, dict):
            template = self.additional_data.get("message_template")
            if template and isinstance(template, str):
                message = template
                message = message.replace("{BRAND}", self.brand or "N/A")
                message = message.replace("{MODEL_CODE}", self.model_code or "N/A")
                message = message.replace("{WARRANTY_MONTHS}", str(self.warranty_months or "N/A"))
                message = message.replace("{PRICE_REGULAR}", f"${float(self.price_regular):.2f}" if self.price_regular is not None else "N/A")
                message = message.replace("{PRICE_DISCOUNT_FX}", f"${float(self.battery_price_discount_fx):.2f}" if self.battery_price_discount_fx is not None else "N/A")
                message = message.replace("{STOCK}", str(self.stock if self.stock is not None else "N/A"))
                return message

        price_reg_str = f"Precio Regular: ${float(self.price_regular):.2f}" if self.price_regular is not None else "Precio Regular no disponible"
        price_fx_str = f"Descuento Pago en Divisas: ${float(self.battery_price_discount_fx):.2f}" if self.battery_price_discount_fx is not None else ""
        warranty_str = f"Garantía: {self.warranty_months} meses" if self.warranty_months is not None else "Garantía no especificada"
        stock_str = f"Stock: {self.stock}" if self.stock is not None else "Stock no disponible"
        name_str = self.item_name or f"{self.brand} {self.model_code}"

        return (f"Batería: {name_str}.\n"
                f"Marca: {self.brand}.\n"
                f"Modelo: {self.model_code}.\n"
                f"{warranty_str}.\n"
                f"{price_reg_str}.\n"
                f"{price_fx_str}.\n"
                f"{stock_str}.\n"
                f"Debe entregar la chatarra.\n" # This part is hardcoded from your example message
                f"⚠️ Para que su descuento sea válido, debe presentar este mensaje en la tienda.")

# --- End of product.py ---