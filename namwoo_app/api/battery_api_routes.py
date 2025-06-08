from flask import Blueprint, request, jsonify, current_app
from decimal import Decimal, InvalidOperation as InvalidDecimalOperation

from services import product_service
from __init__ import db

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
    success_count = 0
    failure_count = 0

    for idx, item in enumerate(update_items, 1):
        model_code = item.get('model_code')
        if not model_code:
            msg = "missing 'model_code'"
            results.append({"item_index": idx, "identifier_value": "MISSING", "status": "error", "message": msg})
            current_app.logger.warning(f"Battery update error: {msg} for item {item}")
            failure_count += 1
            continue

        update_data = {}

        if 'brand' in item and str(item['brand']).strip() != '':
            update_data['brand'] = str(item['brand']).strip()

        if 'price_regular' in item and str(item['price_regular']).strip() != '':
            try:
                cleaned = ''.join(ch for ch in str(item['price_regular']).replace(',', '') if ch.isdigit() or ch == '.')
                update_data['price_regular'] = Decimal(cleaned)
            except InvalidDecimalOperation:
                current_app.logger.warning(
                    f"Invalid price_regular for model_code '{model_code}': {item['price_regular']}"
                )

        if 'price_discount_fx' in item and str(item['price_discount_fx']).strip() != '':
            try:
                cleaned_fx = ''.join(ch for ch in str(item['price_discount_fx']).replace(',', '') if ch.isdigit() or ch == '.')
                update_data['price_discount_fx'] = Decimal(cleaned_fx)
            except InvalidDecimalOperation:
                current_app.logger.warning(
                    f"Invalid price_discount_fx for model_code '{model_code}': {item['price_discount_fx']}"
                )

        if 'warranty_months' in item and str(item['warranty_months']).strip() != '':
            try:
                update_data['warranty_months'] = int(float(str(item['warranty_months']).strip()))
            except (ValueError, TypeError):
                current_app.logger.warning(
                    f"Invalid warranty_months for model_code '{model_code}': {item['warranty_months']}"
                )

        if not update_data:
            msg = "no updatable fields present"
            results.append({"item_index": idx, "identifier_value": model_code, "status": "error", "message": msg})
            current_app.logger.warning(f"Battery update error: {msg} for model_code '{model_code}'")
            failure_count += 1
            continue

        try:
            updated = product_service.update_battery_fields_by_model_code(
                session=db.session,
                model_code=model_code,
                fields_to_update=update_data,
            )
            if updated:
                db.session.commit()
                results.append({"item_index": idx, "identifier_value": model_code, "status": "success", "message": "Updated."})
                success_count += 1
            else:
                db.session.rollback()
                msg = f"Update failed or no change for model_code '{model_code}'."
                results.append({"item_index": idx, "identifier_value": model_code, "status": "error", "message": msg})
                current_app.logger.warning(msg)
                failure_count += 1
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error processing update for model_code '{model_code}': {e}", exc_info=True
            )
            results.append({"item_index": idx, "identifier_value": model_code, "status": "error", "message": "Exception during update"})
            failure_count += 1

    overall_success = failure_count == 0
    status_code = 200 if overall_success else 207
    message = (
        "All battery prices processed successfully." if overall_success
        else "Some battery prices could not be updated or were skipped."
    )
    return jsonify({
        "status": "success" if overall_success else "partial_error",
        "message": message,
        "details": results,
    }), status_code
