import streamlit as st
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import json

# Setup for Google Calendar API
SCOPES = ['https://www.googleapis.com/auth/calendar.events']
CLIENT_CONFIG = {
    "web": {
        "client_id": st.secrets["GOOGLE_CLIENT_ID"],
        "client_secret": st.secrets["GOOGLE_CLIENT_SECRET"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost:8501/"],  # Update this with your Streamlit app URL when deploying
    }
}

def get_calendar_service():
    flow = Flow.from_client_config(CLIENT_CONFIG, scopes=SCOPES)
    
    if 'token' not in st.session_state:
        authorization_url, _ = flow.authorization_url(prompt='consent')
        st.markdown(f'Please [click here]({authorization_url}) to authorize this app.')
        code = st.text_input('Enter the authorization code:')
        if code:
            flow.fetch_token(code=code)
            creds = flow.credentials
            st.session_state['token'] = creds.to_json()
            st.experimental_rerun()
    else:
        creds = Credentials.from_authorized_user_info(json.loads(st.session_state['token']), SCOPES)
        
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        st.session_state['token'] = creds.to_json()
    
    return build('calendar', 'v3', credentials=creds)

st.title("Create Google Calendar Event")

if 'token' not in st.session_state:
    st.warning('Please authenticate with Google Calendar first.')
else:
    # Collect event details
    event_title = st.text_input("Event Title")
    event_date = st.date_input("Event Date")
    start_time = st.time_input("Start Time")
    end_time = st.time_input("End Time")
    description = st.text_area("Event Description")

    if st.button("Create Event"):
        try:
            service = get_calendar_service()
            
            event = {
                'summary': event_title,
                'description': description,
                'start': {
                    'dateTime': f"{event_date}T{start_time}:00",
                    'timeZone': 'UTC',  # Replace with your timezone
                },
                'end': {
                    'dateTime': f"{event_date}T{end_time}:00",
                    'timeZone': 'UTC',  # Replace with your timezone
                },
            }

            event = service.events().insert(calendarId='primary', body=event).execute()
            st.success(f"Event created: {event.get('htmlLink')}")
        except Exception as e:
            st.error(f"An error occurred: {str(e)}")

st.write("Note: You may need to authenticate with Google on first use.")
