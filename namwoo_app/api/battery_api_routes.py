# namwoo_app/api/battery_api_routes.py (NamFulgor Version - Corrected Imports)
from flask import Blueprint, request, jsonify, current_app
from decimal import Decimal, InvalidOperation as InvalidDecimalOperation

# --- CORRECTED IMPORTS ---
# Assuming /usr/src/app/ is the effective root for these packages
from services import product_service # Assumes product_service.py is in namwoo_app/services/
from utils.db_utils import get_db_session # Assumes db_utils.py is in namwoo_app/utils/
# --------------------------

battery_api_bp = Blueprint('battery_api_bp', __name__, url_prefix='/api/battery')

@battery_api_bp.route('/update-prices', methods=['POST'])
def update_battery_prices_api():
    auth_key = request.headers.get('X-API-KEY')
    expected_key = current_app.config.get('INTERNAL_SERVICE_API_KEY')
    if not expected_key or not auth_key or auth_key != expected_key:
        current_app.logger.warning("Unauthorized price update attempt.")
        return jsonify({"error": "Unauthorized access"}), 401

    data = request.json
    if not isinstance(data, list): # Expecting a list of updates
        current_app.logger.error(f"Invalid payload for price update: Expected list, got {type(data)}")
        return jsonify({"error": "Invalid payload format. Expected a list."}), 400

    results = []
    all_successful = True
    with get_db_session() as session: # Uses corrected get_db_session import
        if not session:
            current_app.logger.error("DB session not available for price update API.")
            return jsonify({"error": "Database connection error"}), 500
        
        for item_num, item in enumerate(data, 1):
            battery_id = item.get('battery_id')
            new_price_reg_str = item.get('new_price_regular')
            new_price_fx_str = item.get('new_price_discount_fx')

            if not battery_id:
                msg = f"Item {item_num}: missing 'battery_id'."
                current_app.logger.warning(f"Price update error: {msg} Payload item: {item}")
                results.append({"item_index": item_num, "battery_id": "MISSING", "status": "error", "message": msg})
                all_successful = False
                continue
            
            price_reg, price_fx = None, None
            try:
                if new_price_reg_str is not None and str(new_price_reg_str).strip():
                    price_reg = Decimal(str(new_price_reg_str))
                if new_price_fx_str is not None and str(new_price_fx_str).strip():
                    price_fx = Decimal(str(new_price_fx_str))
            except InvalidDecimalOperation as e:
                msg = f"Invalid price format for battery_id '{battery_id}'. Reg: '{new_price_reg_str}', FX: '{new_price_fx_str}'. Error: {e}"
                current_app.logger.warning(f"Price update error: {msg}")
                results.append({"battery_id": battery_id, "status": "error", "message": msg})
                all_successful = False
                continue
            
            if price_reg is None and price_fx is None:
                results.append({"battery_id": battery_id, "status": "skipped", "message": "No new price values provided."})
                continue

            # Uses corrected product_service import
            updated_battery = product_service.update_battery_product_prices(
                session=session,
                battery_product_id=battery_id,
                new_price_regular=price_reg, # Already Decimal or None
                new_price_discount_fx=price_fx # Already Decimal or None
            )
            if updated_battery:
                results.append({"battery_id": battery_id, "status": "success", "message": "Prices updated."})
            else:
                # This could mean battery_id not found, or no actual price change occurred, or DB error
                # The service method should log specifics.
                msg = f"Update failed, battery_id '{battery_id}' not found, or no change applied."
                current_app.logger.warning(f"Price update issue: {msg}")
                results.append({"battery_id": battery_id, "status": "error", "message": msg})
                all_successful = False
    
    status_code = 200 if all_successful and results else (207 if results else 200) # 207 if there were items processed, some with errors
    if not results and not data: # Empty input list
        return jsonify({"status": "success", "message": "Received empty update list. No action taken."}), 200
        
    final_status_message = "All battery prices processed successfully." if all_successful else "Some battery prices could not be updated or were skipped."
    return jsonify({"status": "success" if all_successful else "partial_error", "message": final_status_message, "details": results}), status_code

# --- End of namwoo_app/api/battery_api_routes.py (NamFulgor Version - Corrected Imports) ---