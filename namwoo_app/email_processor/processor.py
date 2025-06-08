import csv
import io
import os
import sys
import time
from typing import List, Dict, Any

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


# Environment variables loaded later in main()
IMAP_SERVER = None
EMAIL_USER_IMAP = None
EMAIL_PASS_IMAP = None
API_URL = None
API_KEY = None
POLL_INTERVAL = 600
EXPECTED_EMAIL_SUBJECT = None
AUTHORIZED_EMAIL_SENDER = None


# CSV header constants
CSV_BRAND = 'brand'
CSV_MODEL_CODE = 'model_code'
CSV_PRICE_FULL = 'price_full'
CSV_PRICE_DISCOUNTED_USD = 'price_discounted_usd'
CSV_WARRANTY_MONTHS = 'warranty_months'

# Keys for payload sent to API
API_BRAND = 'brand'
API_MODEL_CODE_KEY = 'model_code'
API_PRICE_REGULAR = 'price_regular'
API_PRICE_DISCOUNT_FX = 'price_discount_fx'
API_WARRANTY_MONTHS = 'warranty_months'


def parse_csv_attachment_payload(payload: bytes) -> List[Dict[str, Any]]:
    """Parse CSV payload from an email attachment and prepare update items."""
    logger.info("Parsing CSV attachment payload...")
    text = payload.decode(errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
    logger.debug(f"Detected CSV headers: {reader.fieldnames}")

    required_headers = [CSV_BRAND, CSV_MODEL_CODE, CSV_PRICE_FULL,
                        CSV_PRICE_DISCOUNTED_USD, CSV_WARRANTY_MONTHS]
    if reader.fieldnames is None or not all(h in reader.fieldnames for h in required_headers):
        logger.error("CSV missing required headers. Expected: %s", required_headers)
        return []

    updates: List[Dict[str, Any]] = []
    for row in reader:
        model_code_val = row.get(CSV_MODEL_CODE)
        if not model_code_val or not str(model_code_val).strip():
            logger.warning("Skipping row with missing model_code: %s", row)
            continue

        update_item: Dict[str, Any] = {API_MODEL_CODE_KEY: model_code_val.strip()}

        brand_val = row.get(CSV_BRAND)
        if brand_val and str(brand_val).strip():
            update_item[API_BRAND] = str(brand_val).strip()

        price_full_str = row.get(CSV_PRICE_FULL)
        if price_full_str and str(price_full_str).strip():
            cleaned = str(price_full_str).replace(',', '.').strip()
            cleaned = ''.join(ch for ch in cleaned if ch.isdigit() or ch == '.')
            try:
                update_item[API_PRICE_REGULAR] = float(cleaned)
            except ValueError:
                logger.warning("Invalid price_full '%s' for model %s", price_full_str, model_code_val)

        price_fx_str = row.get(CSV_PRICE_DISCOUNTED_USD)
        if price_fx_str and str(price_fx_str).strip():
            cleaned_fx = str(price_fx_str).replace(',', '.').strip()
            cleaned_fx = ''.join(ch for ch in cleaned_fx if ch.isdigit() or ch == '.')
            try:
                update_item[API_PRICE_DISCOUNT_FX] = float(cleaned_fx)
            except ValueError:
                logger.warning("Invalid price_discounted_usd '%s' for model %s", price_fx_str, model_code_val)

        warranty_str = row.get(CSV_WARRANTY_MONTHS)
        if warranty_str and str(warranty_str).strip():
            try:
                update_item[API_WARRANTY_MONTHS] = int(float(str(warranty_str).strip()))
            except ValueError:
                logger.warning("Invalid warranty_months '%s' for model %s", warranty_str, model_code_val)

        if len(update_item) > 1:
            updates.append(update_item)

    logger.info("Parsed %d update items from CSV attachment", len(updates))
    return updates


def send_price_updates(rows: List[Dict[str, Any]]) -> None:
    logger.info(f"Sending {len(rows)} price updates to API...")
    if not API_URL or not API_KEY:
        logger.error("API_URL or API_KEY missing. Skipping update.")
        return
    try:
        resp = requests.post(
            API_URL,
            json={"updates": rows},
            headers={"X-Internal-API-Key": API_KEY},
            timeout=15,
        )
        logger.info(
            f"API response from {API_URL} - Status: {resp.status_code}. Response body: {resp.text}"
        )
    except requests.RequestException as exc:
        logger.error(f"Error sending updates: {exc}", exc_info=True)


def process_mailbox(mailbox: MailBox) -> None:
    logger.info("Processing mailbox for new emails...")
    criteria = AND(seen=False)
    if EXPECTED_EMAIL_SUBJECT:
        criteria &= AND(subject=EXPECTED_EMAIL_SUBJECT)
    if AUTHORIZED_EMAIL_SENDER:
        criteria &= AND(from_=AUTHORIZED_EMAIL_SENDER)
    logger.debug(f"IMAP search criteria: {criteria}")

    found = False
    for msg in mailbox.fetch(criteria):
        found = True
        logger.info(
            f"Processing email UID: {msg.uid}, From: {msg.from_}, Subject: {msg.subject}"
        )
        updates: List[Dict[str, Any]] = []
        for att in msg.attachments:
            if att.filename and att.filename.lower().endswith('.csv'):
                logger.info(f"Found CSV attachment: {att.filename}")
                updates.extend(parse_csv_attachment_payload(att.payload))
        if not updates:
            logger.info("No valid CSV attachments found for this email.")
        else:
            send_price_updates(updates)
        mailbox.flag(msg.uid, MailMessageFlags.SEEN, True)
        logger.info(f"Flagged email UID {msg.uid} as SEEN")

    if not found:
        logger.info("No new emails matching criteria found.")


def main() -> None:
    logger.info("Starting Email Processor Service...")

    load_dotenv()

    global IMAP_SERVER, EMAIL_USER_IMAP, EMAIL_PASS_IMAP
    global API_URL, API_KEY, POLL_INTERVAL, EXPECTED_EMAIL_SUBJECT, AUTHORIZED_EMAIL_SENDER

    IMAP_SERVER = os.environ.get('IMAP_SERVER')
    EMAIL_USER_IMAP = os.environ.get('EMAIL_USER_IMAP')
    EMAIL_PASS_IMAP = os.environ.get('EMAIL_PASS_IMAP')
    API_URL = os.environ.get('NAMFULGOR_API_PRICE_UPDATE_URL')
    API_KEY = os.environ.get('INTERNAL_SERVICE_API_KEY') or os.environ.get('NAMFULGOR_INTERNAL_API_KEY')
    POLL_INTERVAL = int(os.environ.get('EMAIL_POLLING_INTERVAL_SECONDS', '600'))
    EXPECTED_EMAIL_SUBJECT = os.environ.get('EXPECTED_EMAIL_SUBJECT')
    AUTHORIZED_EMAIL_SENDER = os.environ.get('AUTHORIZED_EMAIL_SENDER')

    if not IMAP_SERVER or not EMAIL_USER_IMAP or not EMAIL_PASS_IMAP:
        logger.critical("CRITICAL: IMAP credentials not fully configured. Exiting.")
        sys.exit(1)
    if not API_URL or not API_KEY:
        logger.critical("CRITICAL: API connection details not configured. Exiting.")
        sys.exit(1)

    logger.info(f"IMAP Server: {IMAP_SERVER}")
    logger.info(f"API URL for updates: {API_URL}")
    logger.info(f"Polling interval: {POLL_INTERVAL} seconds")
    if EXPECTED_EMAIL_SUBJECT:
        logger.info(f"Expected subject: {EXPECTED_EMAIL_SUBJECT}")
    if AUTHORIZED_EMAIL_SENDER:
        logger.info(f"Authorized sender: {AUTHORIZED_EMAIL_SENDER}")

    loop_count = 0
    while True:
        loop_count += 1
        logger.info(
            f"--- Cycle {loop_count}: Checking mailbox {EMAIL_USER_IMAP} on {IMAP_SERVER}... ---"
        )
        try:
            with MailBox(IMAP_SERVER).login(EMAIL_USER_IMAP, EMAIL_PASS_IMAP) as mbox:
                process_mailbox(mbox)
            logger.info(f"--- Cycle {loop_count}: Mailbox processing complete. ---")
        except Exception as exc:
            logger.error(
                f"--- Cycle {loop_count}: CRITICAL error in main processing loop: {exc} ---",
                exc_info=True,
            )
        logger.info(f"--- Cycle {loop_count}: Sleeping for {POLL_INTERVAL} seconds. ---")
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    logger.info(f"--- processor.py executed under __main__ (PID: {os.getpid()}) ---")
    main()
