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
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
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

def parse_date_time(date_str, time_str=None, context_date=None):
    now = get_current_time()
    if date_str.lower() == 'today':
        date = now.date()
    elif date_str.lower() == 'tomorrow':
        date = (now + timedelta(days=1)).date()
    else:
        try:
            date = parser.parse(date_str).date()
        except:
            date = context_date if context_date else now.date()

    if time_str:
        try:
            time = parser.parse(time_str).time()
        except:
            time = now.time()
    else:
        time = now.time()

    return malaysia_tz.localize(datetime.combine(date, time))

def parse_event_details(text, context):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that extracts event details from user input. Respond with a JSON object containing title, date, time, duration_minutes, and description. If any information is missing, use reasonable defaults. Pay close attention to the context."},
                {"role": "user", "content": f"Context: {json.dumps(context)}\nExtract the event details from: {text}"}
            ]
        )
        event_details = json.loads(response.choices[0].message.content)
        
        # Set defaults and parse date/time
        now = get_current_time()
        event_details['title'] = event_details.get('title', "")
        event_details['duration_minutes'] = int(event_details.get('duration_minutes', 60))
        event_details['description'] = event_details.get('description', "")
        
        start_datetime = parse_date_time(
            event_details.get('date', context.get('last_mentioned_date', now.strftime('%Y-%m-%d'))),
            event_details.get('time'),
            context.get('last_mentioned_date')
        )
        
        event_details['start_datetime'] = start_datetime
        event_details['end_datetime'] = start_datetime + timedelta(minutes=event_details['duration_minutes'])
        
        logger.info(f"Parsed event details: {event_details}")
        return event_details
    except Exception as e:
        logger.error(f"Error in parse_event_details: {str(e)}")
        return None
        
def prompt_for_title():
    st.session_state.waiting_for_title = True
    st.session_state.temp_event_details = st.session_state.get('temp_event_details', {})
    return "What is this event about? Please provide a title for the event."

def check_for_clash(service, start_time, end_time):
    events_result = service.events().list(
        calendarId='primary',
        timeMin=start_time.isoformat(),
        timeMax=end_time.isoformat(),
        singleEvents=True,
        orderBy='startTime'
    ).execute()
    events = events_result.get('items', [])
    return events

def create_event(service, event_details):
    try:
        event = {
            'summary': event_details['title'],
            'description': event_details['description'],
            'start': {
                'dateTime': event_details['start_datetime'].isoformat(),
                'timeZone': 'Asia/Kuala_Lumpur',
            },
            'end': {
                'dateTime': event_details['end_datetime'].isoformat(),
                'timeZone': 'Asia/Kuala_Lumpur',
            },
        }
        created_event = service.events().insert(calendarId='primary', body=event).execute()
        
        response = f"Event created successfully!\n"
        response += f"Title: {event_details['title']}\n"
        response += f"Date: {event_details['start_datetime'].strftime('%Y-%m-%d')}\n"
        response += f"Time: {event_details['start_datetime'].strftime('%I:%M %p')} - {event_details['end_datetime'].strftime('%I:%M %p')}\n"
        response += f"Duration: {event_details['duration_minutes']} minutes\n"
        response += f"Description: {event_details['description']}\n"
        response += f"Calendar link: {created_event.get('htmlLink')}"
        
        return response
    except HttpError as e:
        error_details = json.loads(e.content.decode())
        return f"An error occurred while creating the event: {error_details}"
    except Exception as e:
        return f"An unexpected error occurred while creating the event: {str(e)}"

def modify_event(service, event_id, updates):
    try:
        event = service.events().get(calendarId='primary', eventId=event_id).execute()
        for key, value in updates.items():
            if key in event:
                event[key] = value
        updated_event = service.events().update(calendarId='primary', eventId=event_id, body=event).execute()
        return f"Event updated successfully. New details:\n{format_event(updated_event)}"
    except HttpError as e:
        error_details = json.loads(e.content.decode())
        return f"An error occurred while modifying the event: {error_details}"
    except Exception as e:
        return f"An unexpected error occurred while modifying the event: {str(e)}"

def get_events_for_date(service, date):
    try:
        start_datetime = malaysia_tz.localize(datetime.combine(date, datetime.min.time()))
        end_datetime = malaysia_tz.localize(datetime.combine(date, datetime.max.time()))
        
        events_result = service.events().list(calendarId='primary', 
                                              timeMin=start_datetime.isoformat(),
                                              timeMax=end_datetime.isoformat(), 
                                              singleEvents=True,
                                              orderBy='startTime').execute()
        return events_result.get('items', [])
    except Exception as e:
        logger.error(f"Error in get_events_for_date: {str(e)}")
        return []

def format_event(event):
    start = event['start'].get('dateTime', event['start'].get('date'))
    if isinstance(start, str):
        start_time = datetime.fromisoformat(start).astimezone(malaysia_tz)
        return f"- {event['summary']} at {start_time.strftime('%I:%M %p')}"
    else:
        return f"- {event['summary']} (all-day event)"

def format_events(events):
    if not events:
        return "No events scheduled."
    event_list = []
    locations = Counter()
    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date'))
        start_time = datetime.fromisoformat(start).astimezone(malaysia_tz)
        event_str = f"{event['summary']} at {start_time.strftime('%I:%M %p')}"
        if 'location' in event:
            event_str += f" ({event['location']})"
            locations[event['location']] += 1
        event_list.append(event_str)
    
    response = "Events:\n" + "\n".join(event_list)
    if locations:
        response += "\n\nLocations summary:\n" + "\n".join(f"{loc}: {count}" for loc, count in locations.most_common())
    return response

def get_event_details(service, event_summary):
    try:
        now = get_current_time()
        events_result = service.events().list(calendarId='primary', 
                                              timeMin=now.isoformat(),
                                              maxResults=10,
                                              singleEvents=True,
                                              orderBy='startTime').execute()
        events = events_result.get('items', [])
        for event in events:
            if event['summary'].lower() == event_summary.lower():
                return event
        return None
    except Exception as e:
        logger.error(f"Error in get_event_details: {str(e)}")
        return None

def dispatch_query(query, context):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an intelligent calendar assistant that determines the user's intent based on their input. Respond with a JSON object containing 'intent' (create_event, retrieve_events, get_event_details, or general_query), 'date' (if mentioned), and any other relevant parameters. Pay close attention to the context from previous queries."},
                {"role": "user", "content": f"Context: {json.dumps(context)}\nCurrent query: {query}"}
            ]
        )
        result = json.loads(response.choices[0].message.content)
        logger.info(f"Dispatch result: {result}")
        return result
    except Exception as e:
        logger.error(f"Error in dispatch_query: {str(e)}")
        return {"intent": "general_query"}
        
def create_event_agent(service, query, context):
    event_details = parse_event_details(query, context)
    if not event_details:
        return "Please provide event details."

    if not event_details['title']:
        return prompt_for_title()

    if 'waiting_for_title' in st.session_state and st.session_state.waiting_for_title:
        event_details = st.session_state.temp_event_details
        event_details['title'] = query
        st.session_state.waiting_for_title = False
        del st.session_state.temp_event_details

    clashing_events = check_for_clash(service, event_details['start_datetime'], event_details['end_datetime'])
    if clashing_events:
        clash_info = "\n".join([f"{event['summary']} ({event['start']['dateTime']})" for event in clashing_events])
        st.session_state.pending_event = event_details
        st.session_state.waiting_for_clash_confirmation = True
        return f"Clashing events:\n{clash_info}\nCreate anyway? (Yes/No)"

    return create_event(service, event_details)

def format_event_details(event):
    start = event['start'].get('dateTime', event['start'].get('date'))
    end = event['end'].get('dateTime', event['end'].get('date'))
    start_time = datetime.fromisoformat(start).astimezone(malaysia_tz)
    end_time = datetime.fromisoformat(end).astimezone(malaysia_tz)
    
    details = f"Event: {event['summary']}\n"
    details += f"Date: {start_time.strftime('%Y-%m-%d')}\n"
    details += f"Time: {start_time.strftime('%I:%M %p')} - {end_time.strftime('%I:%M %p')}\n"
    if 'location' in event:
        details += f"Location: {event['location']}\n"
    if 'description' in event:
        details += f"Description: {event['description']}\n"
    return details

def process_query(service, query):
    try:
        context = st.session_state.get('context', {})
        context['conversation_history'] = st.session_state.get('messages', [])

        if 'waiting_for_title' in st.session_state and st.session_state.waiting_for_title:
            event_details = st.session_state.temp_event_details
            event_details['title'] = query
            st.session_state.waiting_for_title = False
            del st.session_state.temp_event_details
            return create_event_agent(service, json.dumps(event_details), context)

        if 'waiting_for_clash_confirmation' in st.session_state and st.session_state.waiting_for_clash_confirmation:
            if query.lower() in ['yes', 'y']:
                st.session_state.waiting_for_clash_confirmation = False
                event_details = st.session_state.pending_event
                del st.session_state.pending_event
                return create_event(service, event_details)
            elif query.lower() in ['no', 'n']:
                st.session_state.waiting_for_clash_confirmation = False
                del st.session_state.pending_event
                return "Event creation cancelled."
            else:
                return "Please respond with Yes or No."

        dispatch_result = dispatch_query(query, context)

        intent = dispatch_result.get('intent', 'general_query')
        date_str = dispatch_result.get('date')

        if intent == 'create_event':
            return create_event_agent(service, query, context)
        elif intent == 'retrieve_events':
            date = parse_date_time(date_str, context_date=context.get('last_mentioned_date')).date()
            events = get_events_for_date(service, date)
            return f"Events for {date.strftime('%Y-%m-%d')}:\n" + format_events(events)
        elif intent == 'get_event_details':
            event_summary = dispatch_result.get('event_summary')
            if event_summary:
                event = get_event_details(service, event_summary)
                if event:
                    return format_event_details(event)
                else:
                    return f"No event found with title '{event_summary}'."
            else:
                return "Which event are you asking about?"
        else:
            return general_query_agent(query)

    except Exception as e:
        logger.error(f"Error in process_query: {str(e)}")
        return f"Error processing request: {str(e)}"


def get_events_for_period(service, start_date, end_date):
    try:
        start_datetime = malaysia_tz.localize(datetime.combine(start_date, datetime.min.time()))
        end_datetime = malaysia_tz.localize(datetime.combine(end_date, datetime.max.time()))
        
        events_result = service.events().list(calendarId='primary', 
                                              timeMin=start_datetime.isoformat(),
                                              timeMax=end_datetime.isoformat(), 
                                              singleEvents=True,
                                              orderBy='startTime').execute()
        return events_result.get('items', [])
    except Exception as e:
        logger.error(f"Error in get_events_for_period: {str(e)}")
        return []

def general_query_agent(query):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful calendar assistant. Provide a friendly and informative response to the user's query."},
                {"role": "user", "content": query}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error in general_query_agent: {str(e)}")
        return "I'm sorry, I encountered an error while processing your request."

# Streamlit app
st.title("Smart Calendar Assistant (Malaysia Timezone)")

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
        if 'context' not in st.session_state:
            st.session_state.context = {}

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

            # Update context
            context = st.session_state.get('context', {})
            context['last_query'] = prompt
            context['last_response'] = response
            st.session_state['context'] = context

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
    for log_entry in st.session_state.get('log_contents', []):
        st.text(log_entry)

# Update log contents
if 'log_contents' not in st.session_state:
    st.session_state.log_contents = []
st.session_state.log_contents.append(f"Current time: {get_current_time()}")
