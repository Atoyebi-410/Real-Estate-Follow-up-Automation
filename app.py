from flask import Flask, request, jsonify
import os, base64, pickle, logging, json
import pandas as pd
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from email.mime.text import MIMEText

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ---------- GOOGLE AUTH ----------
def get_sheet_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly"
    ]
    service_account_info = json.loads(os.getenv("SERVICE_ACCOUNT"))
    creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
    return gspread.authorize(creds)

def get_gmail_service():
    SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
    creds = None

    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)

    return build("gmail", "v1", credentials=creds)

# ---------- EMAIL UTILITIES ----------
def send_email(service, to, subject, message_text):
    try:
        message = MIMEText(message_text)
        message["to"] = to
        message["subject"] = subject
        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        create_message = {"raw": encoded_message}
        service.users().messages().send(userId="me", body=create_message).execute()
        logging.info(f"Email sent to {to}")
    except Exception as e:
        logging.error(f"Failed to send email to {to}: {e}")

def send_welcome_email(service, name, email):
    subject = "Welcome! Let’s Get Started with Your Property Search"
    message_text = f"""
    Hi {name},

    Thank you for showing interest in our property listings!
    We're excited to help you find your ideal home or investment opportunity.

    Our agent will reach out to you shortly to discuss your preferences and next steps.
    Meanwhile, feel free to reply directly to this email if you already have a property in mind.

    Best regards,  
    Your Real Estate Team
    """
    send_email(service, email, subject, message_text)

def send_daily_summary(service, agent_email, df):
    today = datetime.now()
    df["Last Contact Date"] = pd.to_datetime(df["Last Contact Date"], errors="coerce")
    total_leads = len(df)
    pending = len(df[df["Lead Status"].isin(["New Lead", "Follow-up"])])
    contacted_today = len(df[df["Last Contact Date"].dt.date == today.date()])

    message = f"""
    Daily Lead Summary

    Total Leads: {total_leads}
    Pending Follow-ups: {pending}
    Leads Contacted Today: {contacted_today}

    Keep pushing! Every follow-up increases your conversion.
    """
    send_email(service, agent_email, "Daily Lead Summary", message)

# ---------- MAIN LOGIC ----------
def process_leads():
    client = get_sheet_client()
    service = get_gmail_service()

    SHEET_ID = os.getenv("SHEET_ID")
    AGENT_EMAIL = os.getenv("AGENT_EMAIL")

    sheet = client.open_by_key(SHEET_ID).worksheet("Sheet1")
    values = sheet.get_all_values()
    df = pd.DataFrame(values[1:], columns=values[0])

    today = datetime.today()
    # df["Last Contact Date"] = pd.to_datetime(df["Last Contact Date"], errors="coerce")
    df["Last Contact Date"] = df["Last Contact Date"].astype(str).str.strip()
    df["Days Since Last Contact"] = (today - df["Last Contact Date"]).dt.days.fillna(999)
    df["Lead Status"] = df["Lead Status"].astype(str).str.lower().str.strip()

    # ---------- SEND WELCOME EMAIL TO NEW LEADS ----------
    # new_leads = df[
    #     (df["Lead Status"] == "new" or df["Lead Status"] == "") &
    #     (df["Last Contact Date"].isin(["", "nan", "none", "NaT"])
    # ]
    new_leads = df[
        (df["Lead Status"].str.contains("new", "")) &
        (df["Last Contact Date"].isin(["", "nan", "none", "NaT"]))
    ]

    logging.info(f"Detected {len(new_leads)} new leads")
    if not new_leads.empty:
        for i, lead in new_leads.iterrows():
            email = lead.get("Email", "").strip()
            name = lead.get("Lead Name", "").strip()
            if email:
                send_welcome_email(service, name, email)
                df.loc[i, "Last Contact Date"] = today.strftime("%Y-%m-%d")
                df.loc[i, "Notes"] = "Welcome email sent"
                logging.info(f"Welcome email sent to {name} ({email})")

    # ---------- FOLLOW-UP EMAILS ----------
    follow_up_list = df[
        (df["Lead Status"].isin(["new lead", "follow-up"])) &
        (df["Days Since Last Contact"] > 2)
    ]

    for i, lead in follow_up_list.iterrows():
        email = lead.get("Email", "").strip()
        name = lead.get("Lead Name", "").strip()
        if not email:
            continue

        subject = "Quick Follow-Up Regarding Your Property Interest"
        message_text = f"""
        Hi {name},

        Hope you’re doing well. Just following up on your interest in our property listings.
        We'd love to help you find the perfect place.

        When can we hop on a quick call?

        Kind regards,  
        Your Real Estate Agent
        """
        send_email(service, email, subject, message_text)
        df.loc[i, "Last Contact Date"] = today.strftime("%Y-%m-%d")
        df.loc[i, "Lead Status"] = "Follow-up"
        df.loc[i, "Notes"] = "Follow-up email sent"

    # ---------- UPDATE SHEET & SEND SUMMARY ----------
    df = df.astype(str)
    sheet.update([df.columns.values.tolist()] + df.values.tolist())
    send_daily_summary(service, AGENT_EMAIL, df)
    logging.info("Google Sheet updated and daily summary sent.")

# ---------- FLASK ENDPOINT ----------
@app.route("/run", methods=["POST"])
def run_automation():
    try:
        logging.info("Trigger received from Google Sheets")
        process_leads()
        return jsonify({"status": "success", "message": "Automation executed"}), 200
    except Exception as e:
        logging.error(f"Automation failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/", methods=["GET"])
def home():
    return "Lead Automation is live"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))







