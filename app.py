import streamlit as st
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError
import json
from datetime import datetime, timedelta
import openai
import logging
import pytz
from dateutil import parser

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

# Set the time zone to GMT+8 (Malaysia)
malaysia_tz = pytz.timezone('Asia/Kuala_Lumpur')

def get_current_time():
    return datetime.now(malaysia_tz)

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
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that extracts event details from user input. Respond with a JSON object containing title, date (YYYY-MM-DD), start_time (HH:MM), end_time (HH:MM), and description. If any information is missing, use reasonable defaults. Assume the user is in Malaysia (GMT+8)."},
                {"role": "user", "content": f"Extract the event details from: {text}"}
            ]
        )
        logger.info(f"OpenAI Response: {response.choices[0].message.content}")
        event_details = json.loads(response.choices[0].message.content)
        
        # Set defaults if missing
        now = get_current_time()
        if 'title' not in event_details:
            event_details['title'] = "Untitled Event"
        if 'date' not in event_details:
            event_details['date'] = now.strftime("%Y-%m-%d")
        if 'start_time' not in event_details:
            event_details['start_time'] = now.strftime("%H:%M")
        if 'end_time' not in event_details:
            event_details['end_time'] = (now + timedelta(hours=1)).strftime("%H:%M")
        if 'description' not in event_details:
            event_details['description'] = ""
        
        # Parse the date
        parsed_date = parser.parse(event_details['date'], dayfirst=False, yearfirst=True)
        event_details['date'] = parsed_date.strftime("%Y-%m-%d")
        
        return event_details
    except Exception as e:
        logger.error(f"Error in parse_event_details: {str(e)}")
        return None

def create_event(service, event_details):
    try:
        start_datetime = malaysia_tz.localize(datetime.strptime(f"{event_details['date']} {event_details['start_time']}", "%Y-%m-%d %H:%M"))
        end_datetime = malaysia_tz.localize(datetime.strptime(f"{event_details['date']} {event_details['end_time']}", "%Y-%m-%d %H:%M"))
        
        event = {
            'summary': event_details['title'],
            'description': event_details.get('description', ''),
            'start': {
                'dateTime': start_datetime.isoformat(),
                'timeZone': 'Asia/Kuala_Lumpur',
            },
            'end': {
                'dateTime': end_datetime.isoformat(),
                'timeZone': 'Asia/Kuala_Lumpur',
            },
        }
        logger.info(f"Creating event: {event}")
        created_event = service.events().insert(calendarId='primary', body=event).execute()
        return f"Event created: {created_event.get('htmlLink')}"
    except HttpError as e:
        logger.error(f"HttpError in create_event: {str(e)}")
        error_details = json.loads(e.content.decode())
        return f"An error occurred: {error_details}"
    except Exception as e:
        logger.error(f"Error in create_event: {str(e)}")
        return f"An unexpected error occurred: {str(e)}"

def get_events(service, start_date, end_date):
    try:
        start_datetime = malaysia_tz.localize(datetime.combine(start_date, datetime.min.time()))
        end_datetime = malaysia_tz.localize(datetime.combine(end_date, datetime.max.time()))
        
        events_result = service.events().list(calendarId='primary', 
                                              timeMin=start_datetime.isoformat(),
                                              timeMax=end_datetime.isoformat(), 
                                              singleEvents=True,
                                              orderBy='startTime').execute()
        events = events_result.get('items', [])
        return events
    except Exception as e:
        logger.error(f"Error in get_events: {str(e)}")
        return []

def process_query(service, query):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful calendar assistant. Determine if the user wants to create an event, retrieve events, or do something else. Respond with 'create', 'retrieve', or 'other'."},
                {"role": "user", "content": query}
            ]
        )
        intent = response.choices[0].message.content.lower()
        logger.info(f"Detected intent: {intent}")

        if "create" in intent:
            event_details = parse_event_details(query)
            if event_details:
                return create_event(service, event_details)
            else:
                return "I'm sorry, I couldn't understand the event details. Could you please provide them in a clearer format?"
        elif "retrieve" in intent:
            today = get_current_time().date()
            tomorrow = today + timedelta(days=1)
            events = get_events(service, today, tomorrow)
            if events:
                event_list = []
                for event in events:
                    start = event['start'].get('dateTime', event['start'].get('date'))
                    if isinstance(start, str):
                        start_time = datetime.fromisoformat(start).astimezone(malaysia_tz)
                        event_list.append(f"- {event['summary']} on {start_time.strftime('%Y-%m-%d')} at {start_time.strftime('%I:%M %p')}")
                    else:
                        event_list.append(f"- {event['summary']} (all-day event on {start})")
                return "Here are your events:\n" + "\n".join(event_list)
            else:
                return "You have no events scheduled."
        else:
            return "I'm sorry, I didn't understand that. You can ask me to create an event or ask about your scheduled events."
    except Exception as e:
        logger.error(f"Error in process_query: {str(e)}")
        return f"An error occurred while processing your request: {str(e)}"

# Streamlit app
st.title("Malaysia Timezone Calendar Assistant")

# Display current time
st.write(f"Current time in Malaysia: {get_current_time().strftime('%Y-%m-%d %I:%M %p')}")


# Authentication flow
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
            logger.error(f"Error in authentication: {str(e)}")
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
        logger.error("Failed to create calendar service")
        st.error("Failed to create calendar service. Please try logging in again.")
        del st.session_state.credentials
        st.experimental_rerun()

st.write("Note: This app is in testing mode. If you're having trouble accessing it, please contact the developer.")

# Add a debug section
if st.checkbox("Show debug info"):
    st.write("Session State:", st.session_state)
    st.write("OpenAI API Key status:", "Set" if openai.api_key else "Not set")
    st.write("Google Client ID status:", "Set" if st.secrets.get("GOOGLE_CLIENT_ID") else "Not set")
    st.write("Google Client Secret status:", "Set" if st.secrets.get("GOOGLE_CLIENT_SECRET") else "Not set")
