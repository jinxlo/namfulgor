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
        return jsonify({"error": "Error de configuración del servidor"}), 500
    if not auth_key or auth_key != expected_key:
        current_app.logger.warning(f"Unauthorized price update attempt. Provided key: {auth_key}")
        return jsonify({"error": "Acceso no autorizado"}), 401

    json_data = request.json
    if not json_data or 'updates' not in json_data or not isinstance(json_data['updates'], list):
        current_app.logger.error(f"Invalid payload for price update: {json_data}")
        return jsonify({"error": "Formato de payload inválido. Se esperaba un diccionario con una lista de 'updates'."}), 400

    update_items = json_data['updates']
    if not update_items:
        return jsonify({"status": "success", "message": "Se recibió una lista de actualizaciones vacía. No se realizó ninguna acción."}), 200

    results = []
    success_count = 0
    skipped_count = 0
    failure_count = 0

    for idx, item in enumerate(update_items, 1):
        model_code = item.get('model_code')
        brand = item.get('brand')
        if not model_code or not brand:
            message = "Falta identificador de 'marca' o 'modelo'"
            results.append({
                "item_index": idx,
                "model_code": model_code or "FALTANTE",
                "brand": brand or "FALTANTE",
                "status": "error",
                "message": message,
                "changes": {}
            })
            failure_count += 1
            continue

        fields_to_update = {k: v for k, v in item.items() if k not in ['brand', 'model_code']}
        
        validated_update_data = {}
        if 'price_regular' in fields_to_update and str(fields_to_update['price_regular']).strip():
            try:
                cleaned = ''.join(ch for ch in str(fields_to_update['price_regular']).replace(',', '') if ch.isdigit() or ch == '.')
                validated_update_data['price_regular'] = Decimal(cleaned)
            except InvalidDecimalOperation:
                current_app.logger.warning(f"Precio regular inválido para '{brand} {model_code}'")
        if 'price_discount_fx' in fields_to_update and str(fields_to_update['price_discount_fx']).strip():
            try:
                cleaned_fx = ''.join(ch for ch in str(fields_to_update['price_discount_fx']).replace(',', '') if ch.isdigit() or ch == '.')
                validated_update_data['price_discount_fx'] = Decimal(cleaned_fx)
            except InvalidDecimalOperation:
                current_app.logger.warning(f"Precio en divisas inválido para '{brand} {model_code}'")
        if 'warranty_months' in fields_to_update and str(fields_to_update['warranty_months']).strip():
            try:
                validated_update_data['warranty_months'] = int(float(str(fields_to_update['warranty_months']).strip()))
            except (ValueError, TypeError):
                current_app.logger.warning(f"Meses de garantía inválidos para '{brand} {model_code}'")

        if not validated_update_data:
            message = "Sin campos válidos para actualizar"
            results.append({"item_index": idx, "model_code": model_code, "brand": brand, "status": "skipped", "message": message, "changes": {}})
            skipped_count += 1
            continue

        try:
            updated, changes = product_service.update_battery_fields_by_brand_and_model(
                session=db.session,
                brand=brand,
                model_code=model_code,
                fields_to_update=validated_update_data,
                return_changes=True
            )
            
            if updated:
                db.session.commit()
                results.append({"item_index": idx, "model_code": model_code, "brand": brand, "status": "success", "message": "Actualizado.", "changes": changes})
                success_count += 1
            else:
                db.session.rollback()
                message = "Sin cambios detectados o producto no encontrado."
                results.append({"item_index": idx, "model_code": model_code, "brand": brand, "status": "skipped", "message": message, "changes": {}})
                skipped_count += 1
        
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error procesando la actualización para '{brand} {model_code}': {e}", exc_info=True)
            message = "Excepción durante la actualización de la base de datos."
            results.append({"item_index": idx, "model_code": model_code, "brand": brand, "status": "error", "message": message, "changes": {}})
            failure_count += 1

    overall_status = "success" if failure_count == 0 else "partial_error"
    status_code = 200 if failure_count == 0 else 207
    message = "Todos los artículos fueron procesados exitosamente." if failure_count == 0 else "Algunos artículos no pudieron ser procesados."
    
    return jsonify({
        "status": overall_status,
        "message": message,
        "summary": {
            "success_count": success_count,
            "skipped_count": skipped_count,
            "error_count": failure_count,
            "total_items": len(update_items)
        },
        "details": results,
    }), status_code


# --- NEW ENDPOINT FOR UPDATING FINANCING RULES ---
@battery_api_bp.route('/update-financing-rules', methods=['POST'])
def update_financing_rules_api():
    """
    API endpoint to update financing rules (e.g., Cashea) from a structured payload.
    This is called by the email processor.
    """
    auth_key = request.headers.get('X-Internal-API-Key')
    expected_key = current_app.config.get('INTERNAL_SERVICE_API_KEY')
    if not expected_key or not auth_key or auth_key != expected_key:
        return jsonify({"error": "Acceso no autorizado"}), 401

    json_data = request.json
    if not json_data or 'rules' not in json_data or not isinstance(json_data['rules'], list):
        return jsonify({"error": "Formato de payload inválido. Se esperaba una lista de 'rules'."}), 400

    rules = json_data['rules']
    provider = json_data.get('provider', 'Cashea') # Default to Cashea

    try:
        success, details = product_service.update_financing_rules(
            session=db.session,
            provider_name=provider,
            new_rules=rules
        )
        if success:
            db.session.commit()
            return jsonify({
                "status": "success",
                "message": f"Reglas de financiamiento para '{provider}' actualizadas exitosamente.",
                "details": details
            }), 200
        else:
            db.session.rollback()
            # This 'else' case might not be hit if the service always returns True on success,
            # but it's good practice for error handling.
            return jsonify({
                "status": "error",
                "message": "La actualización de las reglas de financiamiento falló.",
                "details": details
            }), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Excepción al actualizar reglas de financiamiento: {e}", exc_info=True)
        return jsonify({"error": f"Error interno del servidor: {e}"}), 500