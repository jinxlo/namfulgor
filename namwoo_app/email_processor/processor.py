import csv
import io
import os
import sys
import time
from typing import List, Dict

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


def parse_csv_attachment_payload(payload: bytes) -> List[Dict[str, float]]:
    """Parse CSV payload from an email attachment.

    Expects headers named ``model_code`` and ``price_full`` exactly. All other
    columns are ignored. Returns a list of dictionaries each containing
    ``model_code`` and ``new_price`` (mapped from ``price_full``).
    """
    logger.info("Parsing CSV attachment payload...")
    text = payload.decode(errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
    logger.debug(f"Detected CSV headers: {reader.fieldnames}")

    updates: List[Dict[str, float]] = []
    for row in reader:
        model_code = row.get('model_code')
        price_val = row.get('price_full')

        if not model_code or price_val is None:
            logger.debug("Skipping row with missing model_code or price_full")
            continue

        cleaned = ''.join(ch for ch in str(price_val).replace(',', '') if ch.isdigit() or ch == '.')
        try:
            price_float = float(cleaned)
        except ValueError:
            logger.debug(
                f"Skipping row for model '{model_code}' due to invalid price: {price_val}"
            )
            continue

        updates.append({'model_code': model_code.strip(), 'new_price': price_float})

    logger.info(f"Parsed {len(updates)} price update items from CSV attachment")
    return updates


def send_price_updates(rows: List[Dict[str, float]]) -> None:
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
        updates: List[Dict[str, float]] = []
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
