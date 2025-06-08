from flask import Blueprint, request, jsonify, current_app
from decimal import Decimal, InvalidOperation as InvalidDecimalOperation

from services import product_service
from utils.db_utils import get_db_session

battery_api_bp = Blueprint('battery_api_bp', __name__, url_prefix='/api/battery')

@battery_api_bp.route('/update-prices', methods=['POST'])
def update_battery_prices_api():
    auth_key = request.headers.get('X-Internal-API-Key')
    expected_key = current_app.config.get('INTERNAL_SERVICE_API_KEY')
    if not expected_key:
        current_app.logger.error("INTERNAL_SERVICE_API_KEY not configured.")
        return jsonify({"error": "Server configuration error"}), 500
    if not auth_key or auth_key != expected_key:
        current_app.logger.warning(f"Unauthorized price update attempt. Provided key: {auth_key}")
        return jsonify({"error": "Unauthorized access"}), 401

    json_data = request.json
    if not json_data or 'updates' not in json_data or not isinstance(json_data['updates'], list):
        current_app.logger.error(f"Invalid payload for price update: {json_data}")
        return jsonify({"error": "Invalid payload format. Expected a dictionary with an 'updates' list."}), 400

    update_items = json_data['updates']
    if not update_items:
        return jsonify({"status": "success", "message": "Received empty update list. No action taken."}), 200

    results = []
    all_ok = True

    with get_db_session() as session:
        if not session:
            current_app.logger.error("DB session not available for price update API.")
            return jsonify({"error": "Database connection error"}), 500

        for idx, item in enumerate(update_items, 1):
            identifier = None
            identifier_type = None

            if item.get('product_id'):
                identifier = item['product_id']
                identifier_type = 'product_id'
            elif item.get('model_code'):
                identifier = item['model_code']
                identifier_type = 'model_code'
            else:
                msg = "missing 'model_code' or 'product_id'"
                results.append({"item_index": idx, "identifier_value": "MISSING", "status": "error", "message": msg})
                current_app.logger.warning(f"Price update error: {msg} for item {item}")
                all_ok = False
                continue

            price_val = item.get('new_price')
            if price_val is None or str(price_val).strip() == "":
                msg = "missing 'new_price'"
                results.append({"item_index": idx, "identifier_value": identifier, "status": "error", "message": msg})
                current_app.logger.warning(f"Price update error: {msg} for {identifier_type} '{identifier}'")
                all_ok = False
                continue

            try:
                cleaned = ''.join(ch for ch in str(price_val).replace(',', '') if ch.isdigit() or ch == '.')
                price_decimal = Decimal(cleaned)
            except InvalidDecimalOperation:
                msg = f"invalid 'new_price' format ('{price_val}')"
                results.append({"item_index": idx, "identifier_value": identifier, "status": "error", "message": msg})
                current_app.logger.warning(f"Price update error: {msg}")
                all_ok = False
                continue

            updated = product_service.update_battery_price_or_stock(
                session=session,
                identifier_type=identifier_type,
                identifier_value=identifier,
                new_price=price_decimal,
                new_stock=None
            )

            if updated:
                results.append({"item_index": idx, "identifier_value": identifier, "status": "success", "message": "Price updated."})
            else:
                msg = f"Update failed for {identifier_type} '{identifier}'. Battery not found or no change needed."
                results.append({"item_index": idx, "identifier_value": identifier, "status": "error", "message": msg})
                current_app.logger.warning(msg)
                all_ok = False

        if all_ok and any(r['status'] == 'success' for r in results):
            try:
                session.commit()
                current_app.logger.info("Batch price update committed successfully.")
            except Exception as e:
                session.rollback()
                current_app.logger.error(f"Database commit failed: {e}", exc_info=True)
                for r in results:
                    if r['status'] == 'success':
                        r['status'] = 'error'
                        r['message'] = 'DB commit failed after individual success.'
                all_ok = False
                return jsonify({"error": "Database commit failed", "details": results}), 500
        elif not all_ok:
            session.rollback()
            current_app.logger.warning("Rolling back price update batch due to errors.")
        else:
            session.rollback()
            current_app.logger.info("No successful price updates in batch to commit.")

    status_code = 200 if all_ok else 207
    message = "All battery prices processed successfully." if all_ok else "Some battery prices could not be updated or were skipped."
    return jsonify({"status": "success" if all_ok else "partial_error", "message": message, "details": results}), status_code
