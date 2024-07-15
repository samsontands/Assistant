import streamlit as st
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError
import json
from datetime import datetime, timedelta
import openai

# Setup for Google Calendar API
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

# Setup OpenAI
openai.api_key = st.secrets["OPENAI_API_KEY"]

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

def parse_event_details(text):
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful assistant that extracts event details from user input."},
            {"role": "user", "content": f"Extract the event title, date, start time, end time, and description from the following text: {text}"}
        ]
    )
    return json.loads(response.choices[0].message.content)

def create_event(service, event_details):
    event = {
        'summary': event_details['title'],
        'description': event_details.get('description', ''),
        'start': {
            'dateTime': f"{event_details['date']}T{event_details['start_time']}:00",
            'timeZone': 'UTC',
        },
        'end': {
            'dateTime': f"{event_details['date']}T{event_details['end_time']}:00",
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
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful calendar assistant. Determine the user's intent and respond accordingly."},
            {"role": "user", "content": query}
        ]
    )
    
    intent = response.choices[0].message.content

    if "create event" in intent.lower():
        event_details = parse_event_details(query)
        return create_event(service, event_details)
    elif "retrieve events" in intent.lower():
        # For simplicity, we're just retrieving today's events
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)
        events = get_events(service, today, tomorrow)
        if events:
            return "Here are your events for today:\n" + "\n".join([f"- {event['summary']} at {event['start'].get('dateTime', event['start'].get('date'))}" for event in events])
        else:
            return "You have no events scheduled for today."
    else:
        return "I'm sorry, I didn't understand that. You can ask me to create an event or ask about your scheduled events."

st.title("OpenAI-Powered Calendar Assistant")

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
