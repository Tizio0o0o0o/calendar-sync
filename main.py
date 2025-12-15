import datetime
import os.path
import pytz
from dateutil.relativedelta import relativedelta
import time
import json
import logging

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='calendar_sync.log',
    filemode='a'
)

# --- Load Configuration from config.json ---
try:
    with open('config.json', 'r') as f:
        config = json.load(f)
except FileNotFoundError:
    logging.error("FATAL: config.json not found. Please create it.")
    exit()

SCOPES = ["https://www.googleapis.com/auth/calendar"]
SOURCE_CALENDARS = config['source_calendars']
MASTER_CALENDAR_ID = config['master_calendar_id']
FREE_TIME_CALENDAR_ID = config.get('free_time_calendar_id')
FREE_TIME_EVENT_TITLE = config['free_time_event_title']
TIMEZONE = pytz.timezone(config['timezone'])
WORKING_HOURS = config['working_hours']
SYNC_MONTHS = config.get('sync_months', 3) # Default to 3 months if not specified


def get_calendar_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)

            auth_url, _ = flow.authorization_url(prompt='consent')
            print('Please go to this URL and authorize the application:')
            print(auth_url)

            code = input('Enter the authorization code here: ')
            flow.fetch_token(code=code)
            creds = flow.credentials
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


def sync_master_calendar(service):
    logging.info("Starting sync to master calendar...")
    today = datetime.datetime.now(tz=TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    time_min = today.isoformat()
    months_later = today + relativedelta(months=+SYNC_MONTHS)
    time_max = months_later.isoformat()
    logging.info(f"Syncing events from {today.date()} to {months_later.date()}")

    # 1. Get all events from source calendars
    source_events = {}
    for cal_id, nickname in SOURCE_CALENDARS.items():
        try:
            events_result = service.events().list(
                calendarId=cal_id, timeMin=time_min, timeMax=time_max,
                singleEvents=True, orderBy='startTime'
            ).execute()
            for event in events_result.get('items', []):
                event['x_nickname'] = nickname
                source_events[event['id']] = event
        except HttpError as error:
            logging.error(f"Could not fetch events from {nickname}: {error}")

    # 2. Get all synced events from master calendar
    master_events = {}
    page_token = None
    while True:
        events_result = service.events().list(
            calendarId=MASTER_CALENDAR_ID, timeMin=time_min,
            timeMax=time_max, pageToken=page_token
        ).execute()
        for event in events_result.get('items', []):
            if 'extendedProperties' in event and 'private' in event['extendedProperties']:
                if 'sourceEventId' in event['extendedProperties']['private']:
                    source_id = event['extendedProperties']['private']['sourceEventId']
                    master_events[source_id] = event
        page_token = events_result.get('nextPageToken')
        if not page_token:
            break

    # 3. Compare and sync
    for source_id, source_event in source_events.items():
        master_event = master_events.get(source_id)
        event_body = {
            'summary': f"[{source_event['x_nickname']}] {source_event.get('summary', 'No Title')}",
            'description': source_event.get('description', ''), 'location': source_event.get('location', ''),
            'start': source_event['start'], 'end': source_event['end'],
            'reminders': {'useDefault': False},
            'extendedProperties': {'private': {'sourceEventId': source_id}}
        }
        if not master_event:
            logging.info(f"Creating: {event_body['summary']}")
            service.events().insert(calendarId=MASTER_CALENDAR_ID, body=event_body).execute()
            time.sleep(0.25)
        elif master_event['updated'] < source_event['updated']:
            logging.info(f"Updating: {event_body['summary']}")
            service.events().update(calendarId=MASTER_CALENDAR_ID, eventId=master_event['id'], body=event_body).execute()
            time.sleep(0.25)

    for source_id, master_event in master_events.items():
        if source_id not in source_events:
            logging.info(f"Deleting: {master_event['summary']}")
            service.events().delete(calendarId=MASTER_CALENDAR_ID, eventId=master_event['id']).execute()
            time.sleep(0.25)
    logging.info("Master calendar sync finished.")


def update_free_time_calendar(service):
    if not FREE_TIME_CALENDAR_ID:
        logging.info("Free time calendar not configured; skipping update.")
        return
    logging.info("Efficiently updating free time calendar...")
    today = datetime.datetime.now(tz=TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    time_min = today.isoformat()
    months_later = today + relativedelta(months=+SYNC_MONTHS)
    time_max = months_later.isoformat()
    logging.info(f"Processing free time from {today.date()} to {months_later.date()}")

    # 1. Calculate ideal state
    events_result = service.events().list(
        calendarId=MASTER_CALENDAR_ID, timeMin=time_min, timeMax=time_max,
        singleEvents=True, orderBy='startTime'
    ).execute()
    busy_events = events_result.get('items', [])
    
    calculated_slots = []
    total_days = (months_later - today).days
    for i in range(total_days):
        day = today + datetime.timedelta(days=i)
        day_start = TIMEZONE.localize(datetime.datetime(day.year, day.month, day.day, WORKING_HOURS['start']))
        day_end = TIMEZONE.localize(datetime.datetime(day.year, day.month, day.day, WORKING_HOURS['end']))
        
        time_cursor = day_start
        day_events = [e for e in busy_events if 'dateTime' in e['start'] and datetime.datetime.fromisoformat(e['start'].get('dateTime')).date() == day.date()]

        for event in day_events:
            event_start = datetime.datetime.fromisoformat(event['start'].get('dateTime'))
            event_end = datetime.datetime.fromisoformat(event['end'].get('dateTime'))
            gap = event_start - time_cursor
            if gap.total_seconds() > 60:
                calculated_slots.append({'start': time_cursor, 'end': event_start})
            time_cursor = max(time_cursor, event_end)

        final_gap = day_end - time_cursor
        if final_gap.total_seconds() > 60:
            calculated_slots.append({'start': time_cursor, 'end': day_end})
            
    # 2. Get current state
    logging.info("Fetching existing free slots...")
    existing_slots = []
    page_token = None
    while True:
        events_result = service.events().list(
            calendarId=FREE_TIME_CALENDAR_ID, timeMin=time_min,
            timeMax=time_max, pageToken=page_token
        ).execute()
        for event in events_result.get('items', []):
            existing_slots.append({
                'id': event['id'],
                'start': datetime.datetime.fromisoformat(event['start']['dateTime']),
                'end': datetime.datetime.fromisoformat(event['end']['dateTime'])
            })
        page_token = events_result.get('nextPageToken')
        if not page_token:
            break

    # 3. Compare and sync
    calculated_set = {(s['start'], s['end']) for s in calculated_slots}
    existing_set = {(s['start'], s['end']) for s in existing_slots}

    slots_to_delete = existing_set - calculated_set
    slots_to_create = calculated_set - existing_set

    if slots_to_delete:
        logging.info(f"Deleting {len(slots_to_delete)} obsolete slot(s)...")
        for slot in existing_slots:
            if (slot['start'], slot['end']) in slots_to_delete:
                try:
                    service.events().delete(calendarId=FREE_TIME_CALENDAR_ID, eventId=slot['id']).execute()
                    time.sleep(0.25)
                except HttpError as e:
                    if e.resp.status == 410: logging.warning(f"Tried to delete an already-deleted event (ID: {slot['id']}). Ignoring.")
                    else: raise e
    
    if slots_to_create:
        logging.info(f"Creating {len(slots_to_create)} new slot(s)...")
        for start, end in sorted(list(slots_to_create)): # sorted() for chronological logging
            logging.info(f"  - Found new slot on {start.date()}: {start.time()} to {end.time()}")
            service.events().insert(calendarId=FREE_TIME_CALENDAR_ID, body={
                'summary': FREE_TIME_EVENT_TITLE,
                'start': {'dateTime': start.isoformat()},
                'end': {'dateTime': end.isoformat()},
            }).execute()
            time.sleep(0.25)

    if not slots_to_delete and not slots_to_create:
        logging.info("No changes needed. Free time calendar is already up to date.")
            
    logging.info("Free time calendar update finished.")


def main():
    """Main function to run the sync process."""
    logging.info("================== SCRIPT START ==================")
    try:
        service = get_calendar_service()
        sync_master_calendar(service)
        update_free_time_calendar(service)
        logging.info("================== SCRIPT END: SUCCESS ===============")
    except Exception as e:
        logging.error("An uncaught error occurred: ", exc_info=True)
        logging.info("================== SCRIPT END: FAILED ================")


if __name__ == "__main__":
    main()
