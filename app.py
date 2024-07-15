import streamlit as st
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError
import json
from datetime import datetime, timezone

# Setup for Google Calendar API
SCOPES = ['https://www.googleapis.com/auth/calendar.events']
REDIRECT_URI = 'https://samsonassistant.streamlit.app/'

CLIENT_CONFIG = {
    "web": {
        "client_id": st.secrets["GOOGLE_CLIENT_ID"],
        "client_secret": st.secrets["GOOGLE_CLIENT_SECRET"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [REDIRECT_URI],
    }
}

def create_flow():
    flow = Flow.from_client_config(
        CLIENT_CONFIG,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    return flow

def get_calendar_service():
    if 'credentials' not in st.session_state:
        return None

    credentials = Credentials.from_authorized_user_info(st.session_state.credentials, SCOPES)
    
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        st.session_state.credentials = json.loads(credentials.to_json())

    return build('calendar', 'v3', credentials=credentials)

st.title("Create Google Calendar Event")

# Authentication flow (unchanged)
if 'credentials' not in st.session_state:
    flow = create_flow()
    authorization_url, _ = flow.authorization_url(prompt='consent')
    
    st.write("This app is currently in testing mode. Only approved test users can access it.")
    st.write("If you're an approved tester, please log in to your Google account to continue.")
    if st.button("Log in to Google"):
        st.markdown(f'Click [here]({authorization_url}) to authorize this app.')
        
    params = st.experimental_get_query_params()
    if 'code' in params:
        try:
            code = params['code'][0]
            flow = create_flow()
            flow.fetch_token(code=code)
            credentials = flow.credentials
            st.session_state.credentials = json.loads(credentials.to_json())
            st.experimental_rerun()
        except Exception as e:
            if 'access_denied' in str(e):
                st.error("Access denied. You may not be an approved tester for this app.")
            else:
                st.error(f"An error occurred during authentication: {str(e)}")

else:
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
                # Combine date and time, and format correctly
                start_datetime = datetime.combine(event_date, start_time).replace(tzinfo=timezone.utc)
                end_datetime = datetime.combine(event_date, end_time).replace(tzinfo=timezone.utc)
                
                event = {
                    'summary': event_title,
                    'description': description,
                    'start': {
                        'dateTime': start_datetime.isoformat(),
                        'timeZone': 'UTC',
                    },
                    'end': {
                        'dateTime': end_datetime.isoformat(),
                        'timeZone': 'UTC',
                    },
                }

                st.write("Sending the following event data to Google Calendar API:")
                st.json(event)  # Display the event data for debugging

                event = service.events().insert(calendarId='primary', body=event).execute()
                st.success(f"Event created: {event.get('htmlLink')}")
            except HttpError as e:
                error_details = json.loads(e.content.decode())
                st.error(f"An HTTP error occurred: {e.resp.status} {e.resp.reason}")
                st.error(f"Error details: {error_details}")
            except Exception as e:
                st.error(f"An unexpected error occurred: {str(e)}")

        if st.button("Log out"):
            del st.session_state.credentials
            st.experimental_rerun()
    else:
        st.error("Failed to create calendar service. Please try logging in again.")
        del st.session_state.credentials
        st.experimental_rerun()

st.write("Note: This app is in testing mode. If you're having trouble accessing it, please contact the developer.")
