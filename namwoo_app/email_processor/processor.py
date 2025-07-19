import csv
import io
import os
import sys
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import List, Dict, Any, Optional

import logging
import requests
from dotenv import load_dotenv
from imap_tools import MailBox, AND, MailMessageFlags

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --- Environment variables (loaded in main()) ---
IMAP_SERVER, EMAIL_USER_IMAP, EMAIL_PASS_IMAP = None, None, None
API_PRICE_URL, API_RULES_URL, API_KEY = None, None, None
POLL_INTERVAL = None
PRICE_EMAIL_SUBJECT, RULES_EMAIL_SUBJECT, AUTHORIZED_EMAIL_SENDER = None, None, None
SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASS, CONFIRMATION_RECIPIENT = None, None, None, None, None

# --- CSV Header Constants ---
CSV_BRAND, CSV_MODEL_CODE, CSV_PRECIO_BOLIVARES, CSV_PRECIO_DOLARES, CSV_WARRANTY_MONTHS = 'brand', 'model_code', 'Precio Bolivares', 'Precio Dolares', 'warranty_months'
CASHEA_CSV_LEVEL, CASHEA_CSV_INITIAL_PCT, CASHEA_CSV_INSTALLMENTS, CASHEA_CSV_DISCOUNT_PCT = 'Nivel cashea', 'Porcentaje inicial normal', 'Cuotas normales', 'porcentaje de descuento'

# --- API Payload Keys (Internal names) ---
API_BRAND, API_MODEL_CODE_KEY, API_PRICE_REGULAR, API_PRICE_DISCOUNT_FX, API_WARRANTY_MONTHS = 'brand', 'model_code', 'price_regular', 'price_discount_fx', 'warranty_months'
API_RULE_LEVEL, API_RULE_INITIAL_PCT, API_RULE_INSTALLMENTS, API_RULE_DISCOUNT_PCT = 'level_name', 'initial_payment_percentage', 'installments', 'provider_discount_percentage'


def parse_price_csv_payload(payload: bytes) -> List[Dict[str, Any]]:
    logger.info("Parsing Battery Price CSV attachment payload...")
    # Use 'utf-8-sig' to handle potential BOM from Excel, with a fallback
    try:
        text = payload.decode('utf-8-sig')
    except UnicodeDecodeError:
        logger.warning("Price CSV: Failed to decode with 'utf-8-sig', falling back to 'latin-1'.")
        text = payload.decode('latin-1', errors='ignore')

    reader = csv.DictReader(io.StringIO(text))
    
    actual_headers = [h.strip() for h in reader.fieldnames] if reader.fieldnames else []
    required_headers = [CSV_BRAND, CSV_MODEL_CODE, CSV_PRECIO_BOLIVARES, CSV_PRECIO_DOLARES, CSV_WARRANTY_MONTHS]

    if not all(h in actual_headers for h in required_headers):
        logger.error("Price CSV missing required headers. Expected: %s, Found: %s", required_headers, actual_headers)
        return []

    updates = []
    for row in reader:
        stripped_row = {k.strip(): v for k, v in row.items() if k}
        model_code_val = stripped_row.get(CSV_MODEL_CODE)
        if not model_code_val or not str(model_code_val).strip(): continue

        update_item = {API_MODEL_CODE_KEY: model_code_val.strip()}
        if brand_val := stripped_row.get(CSV_BRAND):
            if str(brand_val).strip(): update_item[API_BRAND] = str(brand_val).strip()
        if price_bs_str := stripped_row.get(CSV_PRECIO_BOLIVARES):
            if str(price_bs_str).strip():
                cleaned = ''.join(ch for ch in str(price_bs_str).replace(',', '.') if ch.isdigit() or ch == '.')
                try: update_item[API_PRICE_REGULAR] = float(cleaned)
                except ValueError: logger.warning("Invalid '%s' for model %s", CSV_PRECIO_BOLIVARES, model_code_val)
        if price_usd_str := stripped_row.get(CSV_PRECIO_DOLARES):
            if str(price_usd_str).strip():
                cleaned_fx = ''.join(ch for ch in str(price_usd_str).replace(',', '.') if ch.isdigit() or ch == '.')
                try: update_item[API_PRICE_DISCOUNT_FX] = float(cleaned_fx)
                except ValueError: logger.warning("Invalid '%s' for model %s", CSV_PRECIO_DOLARES, model_code_val)
        if warranty_str := stripped_row.get(CSV_WARRANTY_MONTHS):
            if str(warranty_str).strip():
                try: update_item[API_WARRANTY_MONTHS] = int(float(str(warranty_str).strip()))
                except ValueError: logger.warning("Invalid warranty_months for model %s", warranty_str, model_code_val)
        if len(update_item) > 1: updates.append(update_item)

    logger.info("Parsed %d price update items from CSV", len(updates))
    return updates

# --- THIS IS THE CORRECTED FUNCTION ---
def parse_cashea_csv_payload(payload: bytes) -> List[Dict[str, Any]]:
    logger.info("Parsing Cashea Rules CSV attachment payload...")
    
    # FIX 1: Use 'utf-8-sig' to automatically handle the invisible BOM character from Excel.
    try:
        text = payload.decode('utf-8-sig')
    except UnicodeDecodeError:
        logger.warning("Cashea CSV: Failed to decode with 'utf-8-sig', falling back to 'latin-1'.")
        text = payload.decode('latin-1', errors='ignore')

    reader = csv.DictReader(io.StringIO(text))
    
    # FIX 2: Make header checking more robust by trimming whitespace from what's read in the file.
    actual_headers = [h.strip() for h in reader.fieldnames] if reader.fieldnames else []

    required_headers = [CASHEA_CSV_LEVEL, CASHEA_CSV_INITIAL_PCT, CASHEA_CSV_INSTALLMENTS, CASHEA_CSV_DISCOUNT_PCT]
    
    if not all(h in actual_headers for h in required_headers):
        logger.error("Cashea Rules CSV missing required headers. Expected: %s, Found: %s", required_headers, actual_headers)
        return []

    rules = []
    # FIX 3: Also strip whitespace from keys when looking up row data for maximum safety.
    for row in reader:
        stripped_row = {k.strip(): v for k, v in row.items() if k}
        try:
            level_name = stripped_row[CASHEA_CSV_LEVEL].strip()
            initial_pct = float(stripped_row[CASHEA_CSV_INITIAL_PCT].replace('%', '').strip()) / 100
            installments = int(stripped_row[CASHEA_CSV_INSTALLMENTS].strip())
            discount_pct = float(stripped_row[CASHEA_CSV_DISCOUNT_PCT].replace('%', '').strip()) / 100
            rules.append({
                API_RULE_LEVEL: level_name, API_RULE_INITIAL_PCT: initial_pct,
                API_RULE_INSTALLMENTS: installments, API_RULE_DISCOUNT_PCT: discount_pct
            })
        except (ValueError, KeyError) as e:
            logger.warning(f"Skipping invalid row in Cashea CSV: {row}. Error: {e}")
            continue
            
    logger.info("Parsed %d financing rules from CSV", len(rules))
    return rules

def send_price_updates(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    logger.info(f"Sending {len(rows)} price updates to API...")
    if not API_PRICE_URL or not API_KEY: return None
    try:
        resp = requests.post(
            API_PRICE_URL, json={"updates": rows}, headers={"X-Internal-API-Key": API_KEY}, timeout=30)
        logger.info(f"API response - Status: {resp.status_code}.")
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.error(f"Error during price update API call: {e}", exc_info=True)
        return None

def send_financing_rules_update(rules: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Send financing rules update to API. Handles empty response bodies gracefully.
    """
    logger.info(f"Sending {len(rules)} financing rules to API...")
    if not API_RULES_URL or not API_KEY: 
        return None
    
    try:
        resp = requests.post(
            API_RULES_URL, 
            json={"provider": "Cashea", "rules": rules}, 
            headers={"X-Internal-API-Key": API_KEY}, 
            timeout=15
        )
        logger.info(f"API response - Status: {resp.status_code}")
        
        # Check for successful status code
        if resp.status_code == 200:
            # Check if response body is empty
            content_length = resp.headers.get('content-length', '0')
            if content_length == '0' or not resp.content:
                logger.warning("API returned 200 with empty response body. Creating synthetic success response.")
                return {
                    "status": "success",
                    "message": "Reglas de financiamiento para 'Cashea' actualizadas exitosamente.",
                    "details": {
                        "deleted": "unknown",  # We don't know the actual count
                        "inserted": len(rules)
                    }
                }
            
            # Try to parse JSON if content exists
            try:
                return resp.json()
            except ValueError as json_err:
                logger.error(f"Failed to parse JSON response: {json_err}")
                logger.error(f"Response content: {resp.text[:500]}")
                # Still return success since we got 200 status
                return {
                    "status": "success",
                    "message": "Reglas actualizadas (respuesta no-JSON del servidor)",
                    "details": {
                        "deleted": "unknown",
                        "inserted": len(rules)
                    }
                }
        else:
            # Non-200 status code
            resp.raise_for_status()
            return None
            
    except requests.RequestException as e:
        logger.error(f"Error during financing rules update API call: {e}", exc_info=True)
        return None

def generate_price_html_summary(api_response: Dict[str, Any], attachment_filename: str) -> str:
    summary, details = api_response.get("summary", {}), api_response.get("details", [])
    updated_items = [d for d in details if d.get("status") == "success" and d.get("changes")]
    skipped_items = [d for d in details if d.get("status") == "skipped"]
    error_items = [d for d in details if d.get("status") == "error"]
    field_translations = {"price_regular": CSV_PRECIO_BOLIVARES, "price_discount_fx": CSV_PRECIO_DOLARES, "warranty_months": CSV_WARRANTY_MONTHS, "brand": CSV_BRAND}
    html = f"""
    <html><head><style>body{{font-family:sans-serif;line-height:1.6}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:8px}}th{{background-color:#f2f2f2}}h2,h3{{color:#333}}</style></head>
    <body><h2>Resumen de Sincronización de Precios</h2><p><strong>Archivo:</strong> {attachment_filename}</p><p><strong>Resultado:</strong> {api_response.get("message","N/A")}</p>
    <ul><li>Actualizados: {summary.get("success_count",0)}</li><li>Omitidos: {summary.get("skipped_count",0)}</li><li>Errores: {summary.get("error_count",0)}</li></ul>
    """
    if updated_items:
        html += "<h3>✅ Productos Actualizados</h3><table><thead><tr><th>Marca</th><th>Modelo</th><th>Campo</th><th>Anterior</th><th>Nuevo</th></tr></thead><tbody>"
        for item in updated_items:
            for field, change in item.get("changes", {}).items():
                translated_field = field_translations.get(field, field)
                html += f"<tr><td>{item['brand']}</td><td>{item['model_code']}</td><td>{translated_field}</td><td>{change['from']}</td><td>{change['to']}</td></tr>"
        html += "</tbody></table>"
    if skipped_items:
        html += "<h3>⚠️ Productos Omitidos</h3><table><thead><tr><th>Marca</th><th>Modelo</th><th>Motivo</th></tr></thead><tbody>"
        for item in skipped_items: html += f"<tr><td>{item['brand']}</td><td>{item['model_code']}</td><td>{item['message']}</td></tr>"
        html += "</tbody></table>"
    if error_items:
        html += "<h3>❌ Errores</h3><table><thead><tr><th>Marca</th><th>Modelo</th><th>Error</th></tr></thead><tbody>"
        for item in error_items: html += f"<tr><td>{item.get('brand','N/A')}</td><td>{item.get('model_code','N/A')}</td><td>{item['message']}</td></tr>"
        html += "</tbody></table>"
    html += "</body></html>"
    return html

def generate_cashea_html_summary(api_response: Dict[str, Any], attachment_filename: str) -> str:
    """
    Generates an HTML summary for the Cashea rules update, matching the style of the price update summary.
    """
    details = api_response.get("details", {})
    message = api_response.get("message", "N/A")
    status = api_response.get("status", "unknown")
    deleted_count = details.get("deleted", 0)
    inserted_count = details.get("inserted", 0)

    # Use the same HTML structure and CSS as the price summary for consistency.
    html = f"""
    <html><head><style>body{{font-family:sans-serif;line-height:1.6}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:8px}}th{{background-color:#f2f2f2}}h2,h3{{color:#333}}</style></head>
    <body>
    <h2>Resumen de Actualización de Reglas de Cashea</h2>
    <p><strong>Archivo:</strong> {attachment_filename}</p>
    <p><strong>Resultado:</strong> {message}</p>
    """

    # High-level summary list, similar to the price summary.
    html += f"""
    <ul>
        <li>Reglas Anteriores Eliminadas: {deleted_count}</li>
        <li>Reglas Nuevas Insertadas: {inserted_count}</li>
    </ul>
    """

    # Add a detailed table for visual consistency, even with summary data.
    if status == "success":
        html += """
        <h3>✅ Detalles de la Sincronización</h3>
        <table>
            <thead>
                <tr><th>Operación</th><th>Cantidad</th></tr>
            </thead>
            <tbody>
        """
        html += f"<tr><td>Reglas Anteriores Eliminadas</td><td>{deleted_count}</td></tr>"
        html += f"<tr><td>Reglas Nuevas Insertadas</td><td>{inserted_count}</td></tr>"
        html += """
            </tbody>
        </table>
        """
    else:
        html += f"""
        <h3>❌ Error en la Sincronización</h3>
        <p>No se pudo completar la actualización de reglas. Por favor, revise los logs del sistema para más detalles.</p>
        <p><strong>Mensaje del API:</strong> {message}</p>
        """

    html += "</body></html>"
    return html

def send_confirmation_email(html_body: str, subject: str):
    if not all([SMTP_SERVER, SMTP_USER, SMTP_PASS, CONFIRMATION_RECIPIENT]):
        logger.warning("SMTP settings not fully configured. Skipping email.")
        return
    msg = MIMEMultipart('alternative')
    msg['Subject'], msg['From'], msg['To'] = subject, SMTP_USER, CONFIRMATION_RECIPIENT
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, [CONFIRMATION_RECIPIENT], msg.as_string())
        logger.info(f"Successfully sent confirmation email to {CONFIRMATION_RECIPIENT}")
    except Exception as e:
        logger.error(f"Failed to send confirmation email: {e}", exc_info=True)

def process_mailbox(mailbox: MailBox) -> None:
    """
    Fetches all unread emails from the authorized sender and processes them
    based on whether their subject line contains the price or rules update text.
    """
    search_criteria = AND(seen=False)
    if AUTHORIZED_EMAIL_SENDER:
        search_criteria.from_ = AUTHORIZED_EMAIL_SENDER
        logger.info(f"Searching for UNSEEN emails from '{AUTHORIZED_EMAIL_SENDER}'...")
    else:
        logger.info("Searching for ALL UNSEEN emails...")

    found_any_email = False
    for msg in mailbox.fetch(search_criteria, charset="utf-8"):
        found_any_email = True
        subject = (msg.subject or "").lower()
        
        # Prepare search phrases from environment variables, removing quotes and whitespace
        price_subject_phrase = (PRICE_EMAIL_SUBJECT or "").strip('\"\' ').lower()
        rules_subject_phrase = (RULES_EMAIL_SUBJECT or "").strip('\"\' ').lower()

        was_processed = False

        # --- Check for Price Update Subject ---
        if price_subject_phrase and price_subject_phrase in subject:
            logger.info(f"Processing Price Update Email UID: {msg.uid}, Subject: '{msg.subject}'")
            all_updates, attachment_filename = [], "N/A"
            for att in msg.attachments:
                if att.filename and att.filename.lower().endswith('.csv'):
                    attachment_filename = att.filename
                    all_updates.extend(parse_price_csv_payload(att.payload))
            if all_updates:
                api_response = send_price_updates(all_updates)
                if api_response:
                    summary_html = generate_price_html_summary(api_response, attachment_filename)
                    status_tag = "Éxito" if api_response.get("summary", {}).get("error_count", 1) == 0 else "Error Parcial"
                    email_subject = f"Reporte de Sincronización de Precios ({status_tag}) - {datetime.now().strftime('%Y-%m-%d')}"
                    send_confirmation_email(summary_html, email_subject)
            was_processed = True

        # --- Check for Cashea Rules Subject ---
        elif rules_subject_phrase and rules_subject_phrase in subject:
            logger.info(f"Processing Cashea Rules Email UID: {msg.uid}, Subject: '{msg.subject}'")
            all_rules, attachment_filename = [], "N/A"
            for att in msg.attachments:
                if att.filename and att.filename.lower().endswith('.csv'):
                    attachment_filename = att.filename
                    all_rules.extend(parse_cashea_csv_payload(att.payload))
            if all_rules:
                api_response = send_financing_rules_update(all_rules)
                if api_response:
                    summary_html = generate_cashea_html_summary(api_response, attachment_filename)
                    status_tag = "Éxito" if api_response.get("status") == "success" else "Error"
                    email_subject = f"Reporte de Actualización de Reglas de Cashea ({status_tag}) - {datetime.now().strftime('%Y-%m-%d')}"
                    send_confirmation_email(summary_html, email_subject)
            was_processed = True
        
        if was_processed:
            mailbox.flag(msg.uid, MailMessageFlags.SEEN, True)
            logger.info(f"Flagged email UID {msg.uid} as SEEN.")
        else:
            logger.warning(f"Unread email found (UID: {msg.uid}, Subject: '{msg.subject}') but its subject did not match any known processing rules. Leaving it unread.")

    if not found_any_email:
        logger.info("No new unread emails found matching sender criteria.")

def main() -> None:
    logger.info("Starting Email Processor Service...")
    load_dotenv()

    global IMAP_SERVER, EMAIL_USER_IMAP, EMAIL_PASS_IMAP, API_PRICE_URL, API_RULES_URL, API_KEY, POLL_INTERVAL, \
           PRICE_EMAIL_SUBJECT, RULES_EMAIL_SUBJECT, AUTHORIZED_EMAIL_SENDER, SMTP_SERVER, SMTP_PORT, \
           SMTP_USER, SMTP_PASS, CONFIRMATION_RECIPIENT

    IMAP_SERVER, EMAIL_USER_IMAP, EMAIL_PASS_IMAP = os.environ.get('IMAP_SERVER'), os.environ.get('EMAIL_USER_IMAP'), os.environ.get('EMAIL_PASS_IMAP')
    API_PRICE_URL, API_RULES_URL, API_KEY = os.environ.get('NAMFULGOR_API_PRICE_UPDATE_URL'), os.environ.get('NAMFULGOR_API_RULES_UPDATE_URL'), os.environ.get('INTERNAL_SERVICE_API_KEY')
    POLL_INTERVAL = int(os.environ.get('EMAIL_POLLING_INTERVAL_SECONDS', '600'))
    PRICE_EMAIL_SUBJECT, RULES_EMAIL_SUBJECT = os.environ.get('PRICE_EMAIL_SUBJECT'), os.environ.get('RULES_EMAIL_SUBJECT')
    AUTHORIZED_EMAIL_SENDER = os.environ.get('AUTHORIZED_EMAIL_SENDER')
    SMTP_SERVER, SMTP_PORT = os.environ.get('SMTP_SERVER'), int(os.environ.get('SMTP_PORT', 587))
    SMTP_USER, SMTP_PASS, CONFIRMATION_RECIPIENT = os.environ.get('SMTP_USER'), os.environ.get('SMTP_PASS'), os.environ.get('CONFIRMATION_RECIPIENT')

    if not all([IMAP_SERVER, EMAIL_USER_IMAP, EMAIL_PASS_IMAP, API_KEY]):
        logger.critical("CRITICAL: IMAP or API credentials not fully configured. Exiting.")
        sys.exit(1)
    if not API_PRICE_URL and not API_RULES_URL:
        logger.critical("CRITICAL: At least one API URL (prices or rules) must be configured. Exiting.")
        sys.exit(1)
    
    logger.info(f"IMAP Server: {IMAP_SERVER}")
    if PRICE_EMAIL_SUBJECT: logger.info(f"Monitoring for Price Subject containing: '{PRICE_EMAIL_SUBJECT}'")
    if RULES_EMAIL_SUBJECT: logger.info(f"Monitoring for Rules Subject containing: '{RULES_EMAIL_SUBJECT}'")
    if AUTHORIZED_EMAIL_SENDER: logger.info(f"Only processing emails from: '{AUTHORIZED_EMAIL_SENDER}'")
    
    loop_count = 0
    while True:
        loop_count += 1
        logger.info(f"--- Cycle {loop_count}: Checking mailbox {EMAIL_USER_IMAP}...")
        try:
            with MailBox(IMAP_SERVER).login(EMAIL_USER_IMAP, EMAIL_PASS_IMAP) as mbox:
                process_mailbox(mbox)
            logger.info(f"--- Cycle {loop_count}: Mailbox processing complete. ---")
        except Exception as exc:
            logger.error(f"--- Cycle {loop_count}: CRITICAL error in main loop: {exc} ---", exc_info=True)
        logger.info(f"--- Cycle {loop_count}: Sleeping for {POLL_INTERVAL} seconds. ---")
        time.sleep(POLL_INTERVAL)

if __name__ == '__main__':
    main()