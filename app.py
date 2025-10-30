from flask import Flask, request, jsonify
import base64, os, pickle, logging, json
import pandas as pd
from datetime import datetime
import gspread
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from email.mime.text import MIMEText

app = Flask(__name__)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ---------- GOOGLE AUTH ----------
def get_sheet_client():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly"
    ]
    service_account_info = json.loads(os.getenv("SERVICE_ACCOUNT"))
    creds = service_account.Credentials.from_service_account_info(service_account_info, scopes=scope)
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
            client_secret_info = json.loads(os.getenv("CLIENT_SECRET"))

            flow = InstalledAppFlow.from_client_config(
                {"installed": client_secret_info}, SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)

    return build("gmail", "v1", credentials=creds)

# ---------- INSTANT WELCOME EMAIL ----------
def send_welcome_email(service, name, email):
    subject = "Welcome! Let's Get Started with Your Property Search 🏡"
    message_text = f"""
    Hi {name},

    Thank you for showing interest in our property listings! 🎉 
    We're excited to help you find your ideal home or investment opportunity.

    Our agent will contact you shortly to discuss your preferences and next steps.
    Meanwhile, feel free to reply directly to this email if you have any specific property in mind.

    Best regards,  
    Your Real Estate Team
    """

    send_email(service, email, subject, message_text)



# ---------- EMAIL SENDER ----------
def send_email(service, to, subject, message_text):
    try:
        message = MIMEText(message_text)
        message["to"] = to
        message["subject"] = subject
        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

        create_message = {"raw": encoded_message}
        service.users().messages().send(userId="me", body=create_message).execute()
        logging.info(f"✅ Email sent to {to}")
    except Exception as e:
        logging.error(f"❌ Failed to send email to {to}: {e}")


# ---------- DAILY SUMMARY ----------
def send_daily_summary(service, agent_email, df):
    today = datetime.now()

    df["Last Contact Date"] = pd.to_datetime(df["Last Contact Date"], errors="coerce")
    total_leads = df.shape[0]
    pending_count = len(df[df["Lead Status"].isin(["New Lead", "Follow-up"])])
    contacted_today = len(df[df["Last Contact Date"].dt.date == today.date()])

    summary_msg = f"""
    Daily Lead Summary

    Total Leads: {total_leads}
    Pending Follow-ups: {pending_count}
    Leads Contacted Today: {contacted_today}

    Keep pushing! Each follow-up increases your conversion.
    """

    send_email(service, agent_email, "Daily Lead Summary", summary_msg)
    logging.info("📧 Daily summary email sent to agent")


# ---------- MAIN WORKFLOW ----------
def process_leads():
    client = get_sheet_client()
    service = get_gmail_service()

    SHEET_ID = os.getenv("SHEET_ID")
    AGENT_EMAIL = os.getenv("AGENT_EMAIL")

    sheet = client.open_by_key(SHEET_ID).worksheet("Sheet1")
    values = sheet.get_all_values()
    df = pd.DataFrame(values[1:], columns=values[0])

    df["Last Contact Date"] = pd.to_datetime(df["Last Contact Date"], errors="coerce")
    today = datetime.today()
    df["Days Since Last Contact"] = (today - df["Last Contact Date"]).dt.days
    df["Days Since Last Contact"] = df["Days Since Last Contact"].fillna(999)

        # ---------- DETECT NEW LEADS AND SEND WELCOME EMAIL ----------
    new_leads = df[
        (df["Lead Status"].str.lower().str.strip() == "new lead") &
        (df["Last Contact Date"].isna() | (df["Last Contact Date"].astype(str).str.strip() == ""))
    ]

    if not new_leads.empty:
        logging.info(f"Found {len(new_leads)} new leads. Sending welcome emails...")
    else:
        logging.info("No new leads found for welcome email.")
        
    for i, lead in new_leads.iterrows():
        name = lead.get("Lead Name", "there")
        email = lead.get("Email", "").strip()
        
        if email:
            try:
                logging.info(f"Sending instant welcome email to {name} ({email})")
                send_welcome_email(service, name, email)
                df.loc[i, "Last Contact Date"] = today
                df.loc[i, "Notes"] = "Welcome email sent"
            except Exception as e:
                logging.error(f"Failed to send welcome email to {email}: {e}")


    follow_up_list = df[
        (df["Lead Status"].isin(["New Lead", "Follow-up"])) &
        (df["Days Since Last Contact"] > 2)
    ]

    for i, lead in follow_up_list.iterrows():
        email = lead["Email"]
        name = lead["Lead Name"]

        subject = "Quick Follow-Up Regarding Your Property Interest"
        message_text = f"""
        Hi {name},

        Hope you're doing well. I just wanted to follow up on your interest in our property listings.
        We'd love to help you find the perfect place.

        When can we hop on a quick call?

        Kind regards,
        Your Real Estate Agent
        """

        if pd.notna(email) and email.strip() != "":
            send_email(service, email, subject, message_text)
            df.loc[i, "Last Contact Date"] = today
            df.loc[i, "Lead Status"] = "Follow-up"
            df.loc[i, "Notes"] = "Auto-email sent"

    df = df.astype(str)
    sheet.update([df.columns.values.tolist()] + df.values.tolist())
    send_daily_summary(service, AGENT_EMAIL, df)
    logging.info("✅ Google Sheet updated successfully!")


# ---------- FLASK ENDPOINT ----------
@app.route("/run", methods=["POST"])
def run_automation():
    try:
        logging.info("🚀 Trigger received from Google Sheets")
        process_leads()
        return jsonify({"status": "success", "message": "Automation executed"}), 200
    except Exception as e:
        logging.error(f"Automation failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/", methods=["GET"])
def home():
    return "Lead Automation is live 🚀"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))





