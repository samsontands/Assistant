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
logging.basicConfig(filename='streamlit.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')
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
                {"role": "system", "content": "You are a helpful assistant that extracts event details from user input. Respond with a JSON object containing title, time (HH:MM), duration_minutes, and description. If any information is missing, use reasonable defaults. Assume the user is in Malaysia (GMT+8) and the event is for today unless explicitly stated otherwise."},
                {"role": "user", "content": f"Extract the event details from: {text}"}
            ]
        )
        logger.info(f"OpenAI Response: {response.choices[0].message.content}")
        event_details = json.loads(response.choices[0].message.content)
        
        # Set defaults if missing
        now = get_current_time()
        if 'title' not in event_details:
            event_details['title'] = "Untitled Event"
        if 'time' not in event_details or not event_details['time']:
            event_details['time'] = now.strftime("%H:%M")
        if 'duration_minutes' not in event_details or not event_details['duration_minutes']:
            event_details['duration_minutes'] = 60
        if 'description' not in event_details:
            event_details['description'] = ""
        
        # Parse the time and set the date to today
        today = now.date()
        event_time = datetime.strptime(event_details['time'], "%H:%M").time()
        event_datetime = malaysia_tz.localize(datetime.combine(today, event_time))
        
        # If the event time is earlier than now, assume it's for tomorrow
        if event_datetime < now:
            event_datetime += timedelta(days=1)
        
        event_details['start_datetime'] = event_datetime
        event_details['end_datetime'] = event_datetime + timedelta(minutes=int(event_details['duration_minutes']))
        
        logger.info(f"Parsed event details: {event_details}")
        logger.info(f"Event start time: {event_details['start_datetime']}")
        logger.info(f"Event end time: {event_details['end_datetime']}")
        return event_details
    except Exception as e:
        logger.error(f"Error in parse_event_details: {str(e)}")
        return None

def create_event(service, event_details):
    try:
        event = {
            'summary': event_details['title'],
            'description': event_details.get('description', ''),
            'start': {
                'dateTime': event_details['start_datetime'].isoformat(),
                'timeZone': 'Asia/Kuala_Lumpur',
            },
            'end': {
                'dateTime': event_details['end_datetime'].isoformat(),
                'timeZone': 'Asia/Kuala_Lumpur',
            },
        }
        logger.info(f"Creating event: {event}")
        created_event = service.events().insert(calendarId='primary', body=event).execute()
        logger.info(f"Event created: {created_event.get('htmlLink')}")
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

def get_events_for_date(service, date):
    try:
        start_datetime = malaysia_tz.localize(datetime.combine(date, datetime.min.time()))
        end_datetime = malaysia_tz.localize(datetime.combine(date, datetime.max.time()))
        
        events_result = service.events().list(calendarId='primary', 
                                              timeMin=start_datetime.isoformat(),
                                              timeMax=end_datetime.isoformat(), 
                                              singleEvents=True,
                                              orderBy='startTime').execute()
        events = events_result.get('items', [])
        return events
    except Exception as e:
        logger.error(f"Error in get_events_for_date: {str(e)}")
        return []

def format_events(events):
    if not events:
        return "You have no events scheduled."
    
    event_list = []
    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date'))
        if isinstance(start, str):
            start_time = datetime.fromisoformat(start).astimezone(malaysia_tz)
            event_list.append(f"- {event['summary']} at {start_time.strftime('%I:%M %p')}")
        else:
            event_list.append(f"- {event['summary']} (all-day event)")
    return "Here are your events:\n" + "\n".join(event_list)

def dispatch_query(query, context):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an intelligent assistant that determines which function to call based on user input. Respond with a JSON object containing 'agent' (create_event, retrieve_events, or general_query) and any relevant parameters."},
                {"role": "user", "content": f"Previous context: {context}\nCurrent query: {query}"}
            ]
        )
        result = json.loads(response.choices[0].message.content)
        logger.info(f"Dispatch result: {result}")
        return result
    except Exception as e:
        logger.error(f"Error in dispatch_query: {str(e)}")
        return {"agent": "general_query"}

def create_event_agent(service, query):
    event_details = parse_event_details(query)
    if event_details:
        return create_event(service, event_details)
    else:
        return "I'm sorry, I couldn't understand the event details. Could you please provide them in a clearer format?"

def retrieve_events_agent(service, date_str):
    now = get_current_time()
    if date_str == 'today':
        target_date = now.date()
    elif date_str == 'tomorrow':
        target_date = (now + timedelta(days=1)).date()
    else:
        try:
            target_date = parser.parse(date_str).date()
        except:
            target_date = now.date()

    events = get_events_for_date(service, target_date)
    return f"Events for {target_date.strftime('%Y-%m-%d')}:\n" + format_events(events)

def general_query_agent(query):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant. Provide a friendly and informative response to the user's query."},
                {"role": "user", "content": query}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error in general_query_agent: {str(e)}")
        return "I'm sorry, I encountered an error while processing your request."

def process_query(service, query):
    try:
        context = st.session_state.get('context', {})
        dispatch_result = dispatch_query(query, context)

        agent = dispatch_result.get('agent', 'general_query')
        if agent == 'create_event':
            response = create_event_agent(service, query)
        elif agent == 'retrieve_events':
            date_str = dispatch_result.get('date', 'today')
            response = retrieve_events_agent(service, date_str)
        else:
            response = general_query_agent(query)

        st.session_state['context'] = {'last_query': query, 'last_response': response}
        return response
    except Exception as e:
        logger.error(f"Error in process_query: {str(e)}")
        return f"An error occurred while processing your request: {str(e)}"

if 'context' not in st.session_state:
    st.session_state['context'] = {}

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

# Modify the debug log display section
if st.checkbox("Show debug logs"):
    log_contents = st.session_state.get('log_contents', [])
    for log_entry in log_contents:
        st.text(log_entry)

# Add this at the end of your main loop
if 'log_contents' not in st.session_state:
    st.session_state.log_contents = []
st.session_state.log_contents.append(f"Current time: {get_current_time()}")
