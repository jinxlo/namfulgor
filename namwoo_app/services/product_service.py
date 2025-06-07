# NAMWOO/services/product_service.py (NamFulgor - Battery Version - Corrected Imports)
import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation as InvalidDecimalOperation
# from datetime import datetime # Not currently used

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_

# --- CORRECTED IMPORTS ---
# Product model (representing a Battery) and VehicleBatteryFitment are in /usr/src/app/models/product.py
from models.product import Product, VehicleBatteryFitment
# db_utils is in /usr/src/app/utils/db_utils.py
from utils import db_utils
# Config class is in /usr/src/app/config/config.py (if you need it here)
# from config.config import Config # Uncomment if Config specific settings are needed directly in this service
# embedding_utils was removed, so its import is definitely gone.

logger = logging.getLogger(__name__)


# --- Search Batteries by Vehicle Fitment ---
def find_batteries_for_vehicle(
    db_session: Session,
    vehicle_make: str,
    vehicle_model: str,
    vehicle_year: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Finds battery products (represented by the Product model) that fit a given vehicle.
    This is the primary search method for the LLM tool.
    """
    if not vehicle_make or not vehicle_model:
        logger.warning("find_batteries_for_vehicle: vehicle_make and vehicle_model are required.")
        return []

    logger.info(
        "Battery fitment search initiated for: Make='%s', Model='%s', Year='%s'",
        vehicle_make, vehicle_model, vehicle_year or "Any"
    )

    try:
        fitment_query = db_session.query(VehicleBatteryFitment).filter(
            VehicleBatteryFitment.vehicle_make.ilike(f'%{vehicle_make}%'),
            VehicleBatteryFitment.vehicle_model.ilike(f'%{vehicle_model}%')
        )
        if vehicle_year is not None:
            fitment_query = fitment_query.filter(
                and_(
                    VehicleBatteryFitment.year_start <= vehicle_year,
                    VehicleBatteryFitment.year_end >= vehicle_year
                )
            )
        
        vehicle_fitments_with_batteries = fitment_query.options(
            joinedload(VehicleBatteryFitment.compatible_battery_products) # Relationship name
        ).all()

        battery_results: List[Dict[str, Any]] = []
        seen_product_ids = set()

        for fitment in vehicle_fitments_with_batteries:
            for battery_product_entry in fitment.compatible_battery_products: # Product instances
                if battery_product_entry.id not in seen_product_ids:
                    item_dict = battery_product_entry.to_dict()
                    item_dict['fitted_vehicle_description'] = (
                        f"{fitment.vehicle_make} {fitment.vehicle_model} "
                        f"({fitment.year_start or ''}-{fitment.year_end or ''})"
                    ).strip()
                    item_dict['llm_formatted_message'] = battery_product_entry.format_for_llm()
                    battery_results.append(item_dict)
                    seen_product_ids.add(battery_product_entry.id)
            
        logger.info("Battery fitment search returned %d unique battery products.", len(battery_results))
        return battery_results
    except SQLAlchemyError as db_exc:
        logger.exception("Database error during battery fitment search: %s", db_exc)
        return []
    except Exception as exc:
        logger.exception("Unexpected error during battery fitment search: %s", exc)
        return []

# --- Add/Update Battery Product ---
def add_or_update_battery_product(
    session: Session,
    battery_id: str,
    battery_data: Dict[str, Any]
) -> Tuple[bool, str]:
    """
    Adds a new battery product or updates an existing one.
    The Product model is now used exclusively for batteries.
    """
    if not battery_id:
        return False, "Missing battery_id."
    if not battery_data or not isinstance(battery_data, dict):
        return False, "Missing or invalid battery_data."

    log_prefix = f"BatteryProduct DB Upsert (ID='{battery_id}'):"

    try:
        entry = session.query(Product).filter(Product.id == battery_id).first()
        action_taken = ""
        updated_fields_details = [] # For more detailed logging

        if entry: # Update existing battery
            logger.info(f"{log_prefix} Found existing battery. Checking for updates.")
            action_taken = "updated"
            changed = False
            for key, new_value in battery_data.items():
                if hasattr(entry, key):
                    current_value = getattr(entry, key)
                    # Handle price conversion to Decimal for comparison and setting
                    if key in ["price_regular", "battery_price_discount_fx"] and new_value is not None:
                        try:
                            new_decimal_value = Decimal(str(new_value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                            if current_value != new_decimal_value:
                                setattr(entry, key, new_decimal_value)
                                changed = True
                                updated_fields_details.append(f"{key}: {current_value} -> {new_decimal_value}")
                        except InvalidDecimalOperation:
                            logger.warning(f"{log_prefix} Invalid decimal value for {key}: {new_value}")
                    elif current_value != new_value:
                        setattr(entry, key, new_value)
                        changed = True
                        updated_fields_details.append(f"{key}: {current_value} -> {new_value}")
            
            if not changed:
                action_taken = "skipped_no_change"
                logger.info(f"{log_prefix} No changes detected. Skipping DB write.")
                return True, action_taken
            else:
                logger.info(f"{log_prefix} Changes detected: {'; '.join(updated_fields_details)}")


        else: # Add new battery
            logger.info(f"{log_prefix} New battery. Adding to DB.")
            action_taken = "added_new"
            # Ensure 'id' is part of battery_data or add it explicitly
            init_data = battery_data.copy() # Work with a copy
            init_data['id'] = battery_id
            
            # Convert prices to Decimal before creating new object
            if "price_regular" in init_data and init_data["price_regular"] is not None:
                init_data["price_regular"] = Decimal(str(init_data["price_regular"])).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if "battery_price_discount_fx" in init_data and init_data["battery_price_discount_fx"] is not None:
                init_data["battery_price_discount_fx"] = Decimal(str(init_data["battery_price_discount_fx"])).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            entry = Product(**init_data)
            session.add(entry)
        
        session.commit() # Commit is handled by get_db_session usually, but explicit here if session is passed directly
        logger.info(f"{log_prefix} Battery successfully {action_taken}.")
        return True, action_taken

    except SQLAlchemyError as db_exc:
        session.rollback()
        logger.error(f"{log_prefix} DB error during add/update: {db_exc}", exc_info=True)
        return False, f"db_sqlalchemy_error: {str(db_exc)}"
    except Exception as exc:
        session.rollback()
        logger.exception(f"{log_prefix} Unexpected error processing: {exc}")
        return False, f"db_unexpected_error: {str(exc)}"

# --- Update Battery Prices ---
def update_battery_product_prices(
    session: Session,
    battery_product_id: str,
    new_price_regular: Optional[Decimal] = None, # Expect Decimal
    new_price_discount_fx: Optional[Decimal] = None # Expect Decimal
) -> Optional[Product]:
    if not battery_product_id:
        logger.warning("update_battery_product_prices: battery_product_id is required.")
        return None

    battery_product = session.query(Product).filter(Product.id == battery_product_id).first()

    if not battery_product:
        logger.warning(f"update_battery_product_prices: Battery Product with ID '{battery_product_id}' not found.")
        return None

    updated = False
    if new_price_regular is not None:
        # Ensure it's Decimal, quantize if necessary (though ideally already Decimal)
        if not isinstance(new_price_regular, Decimal): new_price_regular = Decimal(str(new_price_regular))
        price_reg_quantized = new_price_regular.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if battery_product.price_regular != price_reg_quantized:
            battery_product.price_regular = price_reg_quantized
            updated = True
            logger.info(f"Price regular for {battery_product_id} set to {price_reg_quantized}")


    if new_price_discount_fx is not None:
        if not isinstance(new_price_discount_fx, Decimal): new_price_discount_fx = Decimal(str(new_price_discount_fx))
        price_fx_quantized = new_price_discount_fx.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if battery_product.battery_price_discount_fx != price_fx_quantized:
            battery_product.battery_price_discount_fx = price_fx_quantized
            updated = True
            logger.info(f"Price discount fx for {battery_product_id} set to {price_fx_quantized}")
            
    if updated:
        try:
            session.commit() # Commit is handled by get_db_session usually
            session.refresh(battery_product)
            logger.info(f"Prices successfully updated for Battery Product ID '{battery_product_id}'.")
            return battery_product
        except SQLAlchemyError as e:
            session.rollback()
            logger.exception(f"DB Error committing price updates for Battery Product ID '{battery_product_id}': {e}")
            return None
    else:
        logger.info(f"No price changes to apply for Battery Product ID '{battery_product_id}'.")
        return battery_product


# --- Manage Vehicle Fitments ---
def add_vehicle_fitment_with_links(
    session: Session,
    fitment_data: Dict[str, Any],
    compatible_battery_ids: List[str]
) -> Optional[VehicleBatteryFitment]:
    if not fitment_data or not fitment_data.get("vehicle_make") or not fitment_data.get("vehicle_model"):
        logger.error("add_vehicle_fitment_with_links: Missing required fitment_data (make, model).")
        return None
    
    try:
        new_fitment = VehicleBatteryFitment(**fitment_data)
        
        if compatible_battery_ids:
            battery_products_to_link = session.query(Product).filter(Product.id.in_(compatible_battery_ids)).all()
            
            if len(battery_products_to_link) != len(set(compatible_battery_ids)):
                found_ids = {bp.id for bp in battery_products_to_link}
                missing_ids = set(compatible_battery_ids) - found_ids
                logger.warning(f"Could not find all battery IDs for linking. Missing: {missing_ids}")

            new_fitment.compatible_battery_products = battery_products_to_link
        
        session.add(new_fitment)
        session.commit() # Commit is handled by get_db_session usually
        session.refresh(new_fitment)
        logger.info(f"Added vehicle fitment ID {new_fitment.fitment_id} for {new_fitment.vehicle_make} {new_fitment.vehicle_model}")
        return new_fitment
    except SQLAlchemyError as db_exc:
        session.rollback()
        logger.exception(f"DB Error adding vehicle fitment: {db_exc}")
        return None
    except Exception as exc:
        session.rollback()
        logger.exception(f"Unexpected error adding vehicle fitment: {exc}")
        return None

def get_battery_product_by_id(session: Session, battery_product_id: str) -> Optional[Dict[str, Any]]:
    if not battery_product_id:
        return None
    battery = session.query(Product).filter(Product.id == battery_product_id).first()
    if battery:
        result = battery.to_dict()
        result['llm_formatted_message'] = battery.format_for_llm()
        return result
    return None

# --- End of NAMWOO/services/product_service.py (NamFulgor - Battery Version - Corrected Imports) ---