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
        "redirect_uris": [st.secrets["REDIRECT_URI"]],  # Use the deployed Streamlit app URL
    }
}

def get_calendar_service():
    flow = Flow.from_client_config(CLIENT_CONFIG, scopes=SCOPES)
    flow.redirect_uri = CLIENT_CONFIG['web']['redirect_uris'][0]

    if 'token' not in st.session_state:
        if 'code' not in st.experimental_get_query_params():
            authorization_url, _ = flow.authorization_url(prompt='consent')
            st.markdown(f'Please [click here]({authorization_url}) to authorize this app.')
            return None
        else:
            code = st.experimental_get_query_params()['code'][0]
            flow.fetch_token(code=code)
            creds = flow.credentials
            st.session_state['token'] = creds.to_json()
    else:
        creds = Credentials.from_authorized_user_info(json.loads(st.session_state['token']), SCOPES)
        
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        st.session_state['token'] = creds.to_json()
    
    return build('calendar', 'v3', credentials=creds)

st.title("Create Google Calendar Event")

service = get_calendar_service()

if service:
    # Collect event details
    event_title = st.text_input("Event Title")
    event_date = st.date_input("Event Date")
    start_time = st.time_input("Start Time")
    end_time = st.time_input("End Time")
    description = st.text_area("Event Description")

    if st.button("Create Event"):
        try:
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
else:
    st.warning('Please authenticate with Google Calendar using the link above.')

st.write("Note: You may need to authenticate with Google on first use.")
