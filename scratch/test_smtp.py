import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST") or "smtp.gmail.com"
SMTP_PORT = int(os.getenv("SMTP_PORT") or 587)
SMTP_USER = os.getenv("SMTP_USER") or os.getenv("EMAIL_USER")
SMTP_PASS = os.getenv("SMTP_PASS") or os.getenv("EMAIL_PASS")

def test_smtp():
    print(f"Testing SMTP with {SMTP_USER} on {SMTP_HOST}:{SMTP_PORT}...")
    if not SMTP_USER or not SMTP_PASS:
        print("Error: SMTP credentials missing!")
        return

    msg = MIMEMultipart()
    msg["Subject"] = "AgriNex SMTP Test"
    msg["From"] = SMTP_USER
    msg["To"] = SMTP_USER
    msg.attach(MIMEText("This is a test email from AgriNex AI.", "plain"))

    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.set_debuglevel(1)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()
        print("Success: Email sent!")
    except Exception as e:
        print(f"Failure: {e}")

if __name__ == "__main__":
    test_smtp()
