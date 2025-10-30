import base64

import gspread
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from email.mime.text import MIMEText
import pandas as pd
import pickle, os.path
from datetime import datetime

# Google Sheets connection setup
scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly"
]
creds = service_account.Credentials.from_service_account_file(
    "service_account.json",
    scopes=scope,
)
client = gspread.authorize(creds)

# gmail API setup
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
# gmail_creds = service_account.Credentials.from_service_account_file(
#     "service_account.json",
#     scopes=gmail_scope
# )

creds = None
if os.path.exists("token.pickle"):
    with open("token.pickle", "rb") as token:
        creds = pickle.load(token)

if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(
            "client_secret_587796029879-kemth0if3e615c3r7i758knkqavdta2v.apps.googleusercontent.com.json", SCOPES
        )
        creds = flow.run_local_server(port=0)
    with open("token.pickle", "wb") as token:
        pickle.dump(creds, token)

service = build("gmail", "v1", credentials=creds)

# function to send emails
def send_email(to, subject, message_text):
    message = MIMEText(message_text)
    message["to"] = to
    message["subject"] = subject

    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    create_message = {"raw": encoded_message}
    send_message = service.users().messages().send(userId="me", body=create_message).execute()

    print(f"Email sent to {to}")
    return send_message

def send_daily_summary(agent_email):

    global df
    today = datetime.now()
    # convert the date column to a datetime format
    df["Last Contact Date"] = pd.to_datetime(df["Last Contact Date"], errors="coerce")

    # Summary stats
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

    send_email(agent_email, "Daily Lead Summary", summary_msg)
    print("Daily summary email sent to agent!")
# you can get sheet ID from https://docs.google.com/spreadsheets/d/<THIS_PART>/edit
spreadsheet_id = "1dR9ZXvcJe5q92tWczPzvlmuWyjXX9eqPggQ5v7eOr20"

# use print([ws.title for ws in spreadsheet.worksheets()]) to get the sheet name
sheet = client.open_by_key(spreadsheet_id).worksheet("Sheet1")
values = sheet.get_all_values()

df = pd.DataFrame(values[1:], columns=values[0])

df["Last Contact Date"] = pd.to_datetime(df["Last Contact Date"], errors="coerce")

# calculate days since last contact
today = datetime.today()
df["Days Since Last Contact"] = (today - df["Last Contact Date"]).dt.days

# replace NaN (no contact yet) with large number so they become priority
df["Days Since Last Contact"] = df["Days Since Last Contact"].fillna(999)

# Filter leads that need follow up
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
    
    Hope you're doing well. I just wanted to follow up on your interest in real opportunities.
    we would love to help you find the perfect place.
    
    When can we hop on a quick call?
    
    Kind regards,
    Your Real Estate Agent
"""

    if pd.notna(email) and email.strip() != "":
        send_email(email, subject, message_text)
        df.loc[i, "Last Contact Date"] = today
        df.loc[i, "Lead Status"] = "Follow-up"
        df.loc[i, "Notes"] = "Auto-email sent"

# convert to string before updating the google sheet
df = df.astype(str)
sheet.update([df.columns.values.tolist()] + df.values.tolist())
send_daily_summary("ibrahimolanrewaju2@gmail.com")



print("Google Sheet updated successfully!")

