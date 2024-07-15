import streamlit as st
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError
import json
from datetime import datetime, timedelta
import re

# Setup for Google Calendar API (unchanged)
SCOPES = ['https://www.googleapis.com/auth/calendar.events', 'https://www.googleapis.com/auth/calendar.readonly']
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
    flow = Flow.from_client_config(CLIENT_CONFIG, scopes=SCOPES, redirect_uri=REDIRECT_URI)
    return flow

def get_calendar_service():
    if 'credentials' not in st.session_state:
        return None
    credentials = Credentials.from_authorized_user_info(st.session_state.credentials, SCOPES)
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        st.session_state.credentials = json.loads(credentials.to_json())
    return build('calendar', 'v3', credentials=credentials)

def parse_date_time(text):
    # This is a simple date/time parser. You might want to use a more robust solution like dateparser in a real app.
    now = datetime.now()
    if "today" in text.lower():
        return now.date()
    elif "tomorrow" in text.lower():
        return (now + timedelta(days=1)).date()
    elif "next week" in text.lower():
        return (now + timedelta(weeks=1)).date()
    else:
        # Try to parse a date in the format YYYY-MM-DD
        try:
            return datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            return None

def create_event(service, title, start_date, start_time, end_time, description=""):
    start_datetime = datetime.combine(start_date, start_time)
    end_datetime = datetime.combine(start_date, end_time)
    
    event = {
        'summary': title,
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

    try:
        event = service.events().insert(calendarId='primary', body=event).execute()
        return f"Event created: {event.get('htmlLink')}"
    except HttpError as e:
        error_details = json.loads(e.content.decode())
        return f"An error occurred: {error_details}"

def get_events(service, start_date, end_date):
    events_result = service.events().list(calendarId='primary', timeMin=start_date.isoformat() + 'Z',
                                          timeMax=end_date.isoformat() + 'Z', singleEvents=True,
                                          orderBy='startTime').execute()
    events = events_result.get('items', [])
    return events

def process_query(service, query):
    query = query.lower()
    
    if "create" in query or "add" in query or "schedule" in query:
        return "Sure, I can help you create an event. What's the title of the event?"
    
    elif "what" in query and "events" in query:
        match = re.search(r'what events (do I have |are there )?(today|tomorrow|next week|on \d{4}-\d{2}-\d{2})', query)
        if match:
            date_str = match.group(2)
            start_date = parse_date_time(date_str)
            if start_date:
                end_date = start_date + timedelta(days=1)
                events = get_events(service, start_date, end_date)
                if events:
                    return "Here are your events:\n" + "\n".join([f"- {event['summary']} at {event['start']['dateTime']}" for event in events])
                else:
                    return f"You have no events scheduled for {date_str}."
            else:
                return "I'm sorry, I couldn't understand the date you specified."
    
    return "I'm sorry, I didn't understand that. You can ask me to create an event or ask about your scheduled events."

st.title("NLP Calendar Assistant")

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
        if 'messages' not in st.session_state:
            st.session_state.messages = []

        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        if prompt := st.chat_input("What would you like to do?"):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            response = process_query(service, prompt)
            st.session_state.messages.append({"role": "assistant", "content": response})
            with st.chat_message("assistant"):
                st.markdown(response)

        if st.button("Log out"):
            del st.session_state.credentials
            st.experimental_rerun()
    else:
        st.error("Failed to create calendar service. Please try logging in again.")
        del st.session_state.credentials
        st.experimental_rerun()

st.write("Note: This app is in testing mode. If you're having trouble accessing it, please contact the developer.")
