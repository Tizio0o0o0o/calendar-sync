import datetime
import os.path
import pytz # For handling timezones
from dateutil.relativedelta import relativedelta
import time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ==============================================================================
# S E T T I N G S  -  F I L L  T H I S  I N
# ==============================================================================

# IMPORTANT: We need to write to calendars, so we change the scope.
# You MUST delete your old 'token.json' file after this change.
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Add your source calendar IDs and the nicknames you want for them.
# Find the ID in your Google Calendar settings (e.g., "xxxxxxxx@group.calendar.google.com")
# 'primary' is a shortcut for your main calendar.
SOURCE_CALENDARS = {
    'gugliandolosergio@gmail.com': 'Personal',
    'sergio.gugliandolo@braintex.it': 'BrainTex',
    'b8c9b03051d2400cce98ed2904876c36759a53e00f0629ef9f3c5371b8a35b23@group.calendar.google.com': 'Casa',
    '0a16175adc7bc5699d3dd5217fa471b34e3a4cc37f6c12315d075ccb2a15c04f@group.calendar.google.com': 'ISAAC',
    's439fgnchup0hmn05k30cp6l4c@group.calendar.google.com': 'PoliTO',
    #'9bac4fa7c58aae0ea60e94e7e54f16ab4e878a943eaebfb10603a643476c5acb@group.calendar.google.com': 'Nanna',
    # Add more calendars here
}

# The ID of the calendar that will contain all the merged events (Impegni).
MASTER_CALENDAR_ID = 'a85d350856e26774e614b80a8aedb08fc1a18e4d5bb3b93ebe7486273eb81bc4@group.calendar.google.com'

# The ID of the calendar where your free time slots will be created (ISAAC for meetings)
FREE_TIME_CALENDAR_ID = 'acb4983d11ca05818fb09c1fbf8711c60afb201da57f6befbdc9d0bc3d2e85b6@group.calendar.google.com'
# The name for the events created in your free time calendar.
FREE_TIME_EVENT_TITLE = "Sergio Gugliandolo"

# The timezone for your server and calendars.
TIMEZONE = pytz.timezone('Europe/Rome')

# Your working hours (24-hour format). Gaps will only be found within this window.
WORKING_HOURS = {'start': 9, 'end': 23}
# ==============================================================================


def get_calendar_service():
    """Authenticates with the Google Calendar API and returns a service object."""
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            # This is the corrected line
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


def sync_master_calendar(service):
    """
    Syncs events from source calendars to the master calendar.
    Handles creation, updates, and deletion for events in the next 6 months.
    """
    print("Starting sync to master calendar...")

    # Define the 6-month time window
    today = datetime.datetime.now(tz=TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    time_min = today.isoformat()
    months_later = today + relativedelta(months=+6)
    time_max = months_later.isoformat()
    print(f"  - Syncing events from {today.date()} to {months_later.date()}")

    # 1. Get all events from all source calendars within the window
    source_events = {}
    for cal_id, nickname in SOURCE_CALENDARS.items():
        try:
            events_result = service.events().list(
                calendarId=cal_id,
                timeMin=time_min,
                timeMax=time_max, # Only get events in our window
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            for event in events_result.get('items', []):
                event['x_nickname'] = nickname
                source_events[event['id']] = event
        except HttpError as error:
            print(f"  - Could not fetch events from {nickname}: {error}")

    # 2. Get all synced events from the master calendar within the window
    master_events = {}
    page_token = None
    while True:
        events_result = service.events().list(
            calendarId=MASTER_CALENDAR_ID,
            timeMin=time_min,
            timeMax=time_max, # Only get events in our window
            pageToken=page_token
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
    # Check for new events to create or update
    for source_id, source_event in source_events.items():
        master_event = master_events.get(source_id)

        event_body = {
            'summary': f"[{source_event['x_nickname']}] {source_event.get('summary', 'No Title')}",
            'description': source_event.get('description', ''),
            'location': source_event.get('location', ''),
            'start': source_event['start'],
            'end': source_event['end'],
            'reminders': {'useDefault': False},
            'extendedProperties': {
                'private': {
                    'sourceEventId': source_id,
                    'sourceCalendarId': source_event['organizer'].get('email')
                }
            }
        }

        if not master_event:
            print(f"  - Creating: {event_body['summary']}")
            service.events().insert(calendarId=MASTER_CALENDAR_ID, body=event_body).execute()
            time.sleep(0.25) # --- ADDED DELAY ---
        elif master_event['updated'] < source_event['updated']:
            print(f"  - Updating: {event_body['summary']}")
            service.events().update(calendarId=MASTER_CALENDAR_ID, eventId=master_event['id'], body=event_body).execute()
            time.sleep(0.25) # --- ADDED DELAY ---

    # Check for events to delete (only within our 3-month window)
    for source_id, master_event in master_events.items():
        if source_id not in source_events:
            print(f"  - Deleting: {master_event['summary']}")
            service.events().delete(calendarId=MASTER_CALENDAR_ID, eventId=master_event['id']).execute()
            time.sleep(0.25) # --- ADDED DELAY ---

    print("Master calendar sync finished.")

def update_free_time_calendar(service):
    """
    calculates and syncs free time from the master calendar
    for the next 6 months by only creating/deleting what has changed.
    """
    print("Updating free time calendar...")

    # --- Define the 6-month time window ---
    today = datetime.datetime.now(tz=TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    time_min = today.isoformat()
    months_later = today + relativedelta(months=+6)
    time_max = months_later.isoformat()
    print(f"  - Processing free time from {today.date()} to {months_later.date()}")

    # ==============================================================================
    # STEP 1: CALCULATE THE "IDEAL" STATE (all the slots that SHOULD exist)
    # ==============================================================================
    
    # Get all busy events from the master calendar for our time window
    events_result = service.events().list(
        calendarId=MASTER_CALENDAR_ID,
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy='startTime'
    ).execute()
    busy_events = events_result.get('items', [])
    
    calculated_slots = []
    total_days = (months_later - today).days
    for i in range(total_days):
        day = today + datetime.timedelta(days=i)
        day_start = TIMEZONE.localize(datetime.datetime(day.year, day.month, day.day, WORKING_HOURS['start']))
        day_end = TIMEZONE.localize(datetime.datetime(day.year, day.month, day.day, WORKING_HOURS['end']))
        
        time_cursor = day_start
        day_events = [
            e for e in busy_events 
            if 'dateTime' in e['start'] and datetime.datetime.fromisoformat(e['start'].get('dateTime')).date() == day.date()
        ]

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
            
    # ==============================================================================
    # STEP 2: GET THE "CURRENT" STATE (all the slots that ALREADY exist)
    # ==============================================================================
    
    print("  - Fetching existing free slots...")
    existing_slots = []
    page_token = None
    while True:
        events_result = service.events().list(
            calendarId=FREE_TIME_CALENDAR_ID,
            timeMin=time_min,
            timeMax=time_max,
            pageToken=page_token
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

    # ==============================================================================
    # STEP 3: COMPARE AND SYNC (only delete/create what's necessary)
    # ==============================================================================
    
    # Use sets for efficient comparison
    calculated_set = {(s['start'], s['end']) for s in calculated_slots}
    existing_set = {(s['start'], s['end']) for s in existing_slots}

    # Determine what to delete and what to create
    slots_to_delete = existing_set - calculated_set
    slots_to_create = calculated_set - existing_set

    # Delete obsolete events
    if slots_to_delete:
        print(f"  - Deleting {len(slots_to_delete)} obsolete slot(s)...")
        for slot in existing_slots:
            if (slot['start'], slot['end']) in slots_to_delete:
                try:
                    service.events().delete(calendarId=FREE_TIME_CALENDAR_ID, eventId=slot['id']).execute()
                    time.sleep(0.25)
                except HttpError as e:
                    if e.resp.status == 410: pass
                    else: raise e
    
    # Create new events
    if slots_to_create:
        print(f"  - Creating {len(slots_to_create)} new slot(s)...")
        for start, end in slots_to_create:
            print(f"    - Found new slot on {start.date()}: {start.time()} to {end.time()}")
            service.events().insert(calendarId=FREE_TIME_CALENDAR_ID, body={
                'summary': FREE_TIME_EVENT_TITLE,
                'start': {'dateTime': start.isoformat()},
                'end': {'dateTime': end.isoformat()},
            }).execute()
            time.sleep(0.25)

    if not slots_to_delete and not slots_to_create:
        print("  - No changes needed. Free time calendar is already up to date.")
            
    print("Free time calendar update finished.")


def main():
    """Main function to run the sync process."""
    service = get_calendar_service()
    sync_master_calendar(service)
    update_free_time_calendar(service)
    print("\nScript finished successfully.")


if __name__ == "__main__":
    main()