import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from dotenv import load_dotenv; load_dotenv('.env')
import os, imaplib, email as emaillib
from pathlib import Path

addr = os.getenv('GMAIL_ADDRESS','')
pwd  = os.getenv('GMAIL_APP_PASSWORD','').replace(' ','')
processed = json.loads(Path('state/processed_command_uids.json').read_text()) if Path('state/processed_command_uids.json').exists() else []

c = imaplib.IMAP4_SSL('imap.gmail.com', 993)
c.login(addr, pwd)

for folder in ['INBOX', '"[Gmail]/Sent Mail"', '"[Gmail]/All Mail"']:
    c.select(folder)
    status, data = c.search(None, f'FROM "{addr}"')
    all_uids = data[0].split() if data[0] else []
    unproc = [u for u in all_uids if u.decode() not in processed]
    print(f"\n{folder}: {len(all_uids)} FROM-self  |  {len(unproc)} unprocessed")

    # Show most recent 3 unprocessed
    for uid in unproc[-3:]:
        s2, mdata = c.fetch(uid, '(RFC822)')
        msg = emaillib.message_from_bytes(mdata[0][1])
        subj = msg.get('Subject','(no subject)')
        date = msg.get('Date','')
        body = ''
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == 'text/plain':
                    body = part.get_payload(decode=True).decode('utf-8','replace'); break
        else:
            body = msg.get_payload(decode=True).decode('utf-8','replace')
        print(f"  UID={uid.decode()} | {date[:30]} | Subj: {subj[:60]}")
        print(f"    Body: {repr(body[:150])}")

c.logout()
