import csv
import io
import os
import time
from typing import List, Dict

import requests
from dotenv import load_dotenv
from imap_tools import MailBox, AND, MailMessageFlags


load_dotenv()

IMAP_SERVER = os.environ.get('IMAP_SERVER')
EMAIL_USER_IMAP = os.environ.get('EMAIL_USER_IMAP')
EMAIL_PASS_IMAP = os.environ.get('EMAIL_PASS_IMAP')
API_URL = os.environ.get('NAMFULGOR_API_PRICE_UPDATE_URL')
API_KEY = os.environ.get('NAMFULGOR_INTERNAL_API_KEY') or os.environ.get('INTERNAL_SERVICE_API_KEY')
POLL_INTERVAL = int(os.environ.get('EMAIL_POLLING_INTERVAL_SECONDS', '600'))
EXPECTED_EMAIL_SUBJECT = os.environ.get('EXPECTED_EMAIL_SUBJECT')
AUTHORIZED_EMAIL_SENDER = os.environ.get('AUTHORIZED_EMAIL_SENDER')


def parse_csv_payload(payload: bytes) -> List[Dict[str, str]]:
    text = payload.decode()
    reader = csv.DictReader(io.StringIO(text))
    return [row for row in reader]


def send_price_updates(rows: List[Dict[str, str]]) -> None:
    if not API_URL or not API_KEY:
        print("API_URL or API_KEY missing. Skipping update.")
        return
    try:
        resp = requests.post(
            API_URL,
            json=rows,
            headers={"X-API-KEY": API_KEY},
            timeout=15,
        )
        print(f"Sent {len(rows)} updates. Status: {resp.status_code}")
    except requests.RequestException as exc:
        print(f"Error sending updates: {exc}")


def process_mailbox(mailbox: MailBox) -> None:
    criteria = AND(seen=False)
    if EXPECTED_EMAIL_SUBJECT:
        criteria &= AND(subject=EXPECTED_EMAIL_SUBJECT)
    if AUTHORIZED_EMAIL_SENDER:
        criteria &= AND(from_=AUTHORIZED_EMAIL_SENDER)

    for msg in mailbox.fetch(criteria):
        updates: List[Dict[str, str]] = []
        for att in msg.attachments:
            if att.filename and att.filename.lower().endswith('.csv'):
                updates.extend(parse_csv_payload(att.payload))
        if updates:
            send_price_updates(updates)
        mailbox.flag(msg.uid, MailMessageFlags.SEEN, True)


def main() -> None:
    if not IMAP_SERVER or not EMAIL_USER_IMAP or not EMAIL_PASS_IMAP:
        raise RuntimeError("IMAP credentials are not fully configured")
    while True:
        try:
            with MailBox(IMAP_SERVER).login(EMAIL_USER_IMAP, EMAIL_PASS_IMAP) as mbox:
                process_mailbox(mbox)
        except Exception as exc:
            print(f"Error processing mailbox: {exc}")
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
