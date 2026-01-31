"""
Yandex Calendar Integration via CalDAV.

This module provides functionality to add tasks as events to Yandex Calendar
using the CalDAV protocol.

Requirements:
    pip install caldav

Setup:
    1. Go to https://id.yandex.ru/security/app-passwords
    2. Create an app password for "Calendar"
    3. Add credentials to config.py:
       - yandex_calendar_username = "your-email@yandex.ru"
       - yandex_calendar_password = "your-app-password"
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass

try:
    import caldav
    from caldav.elements import dav
    CALDAV_AVAILABLE = True
except ImportError:
    CALDAV_AVAILABLE = False

logger = logging.getLogger(__name__)

# Yandex CalDAV endpoint
YANDEX_CALDAV_URL = "https://caldav.yandex.ru/"


@dataclass
class CalendarEvent:
    """Represents a calendar event."""
    title: str
    description: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    all_day: bool = True


@dataclass
class CalendarResult:
    """Result of calendar operation."""
    success: bool
    event_uid: Optional[str] = None
    error: Optional[str] = None


class YandexCalendarClient:
    """
    Client for Yandex Calendar via CalDAV.

    Allows creating events in Yandex Calendar for task tracking.
    """

    def __init__(self, username: str, password: str):
        """
        Initialize the Yandex Calendar client.

        Args:
            username: Yandex email (e.g., user@yandex.ru)
            password: App password created at https://id.yandex.ru/security/app-passwords
        """
        if not CALDAV_AVAILABLE:
            raise ImportError("caldav library not installed. Run: pip install caldav")

        self.username = username
        self.password = password
        self._client = None
        self._principal = None
        self._default_calendar = None

    def _connect(self) -> bool:
        """Establish connection to Yandex CalDAV server."""
        try:
            self._client = caldav.DAVClient(
                url=YANDEX_CALDAV_URL,
                username=self.username,
                password=self.password
            )
            self._principal = self._client.principal()

            # Get calendars
            calendars = self._principal.calendars()
            if calendars:
                self._default_calendar = calendars[0]
                logger.info(f"Connected to Yandex Calendar: {self._default_calendar.name}")
                return True
            else:
                logger.warning("No calendars found in Yandex account")
                return False

        except Exception as e:
            logger.error(f"Failed to connect to Yandex Calendar: {e}")
            return False

    def add_event(self, event: CalendarEvent) -> CalendarResult:
        """
        Add an event to Yandex Calendar.

        Args:
            event: CalendarEvent with event details

        Returns:
            CalendarResult with success status and event UID
        """
        try:
            # Ensure connection
            if self._default_calendar is None:
                if not self._connect():
                    return CalendarResult(
                        success=False,
                        error="Failed to connect to Yandex Calendar"
                    )

            # Set default times if not provided
            if event.start_time is None:
                event.start_time = datetime.now()

            if event.end_time is None:
                if event.all_day:
                    # All-day event: next day
                    event.end_time = event.start_time + timedelta(days=1)
                else:
                    # Default 1 hour duration
                    event.end_time = event.start_time + timedelta(hours=1)

            # Build iCalendar event
            if event.all_day:
                # Format for all-day event (DATE only, no time)
                dtstart = event.start_time.strftime("%Y%m%d")
                dtend = event.end_time.strftime("%Y%m%d")
                vcal = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Telegram Bot//Task Tracker//EN
BEGIN:VEVENT
DTSTART;VALUE=DATE:{dtstart}
DTEND;VALUE=DATE:{dtend}
SUMMARY:{event.title}
DESCRIPTION:{event.description or ''}
STATUS:CONFIRMED
END:VEVENT
END:VCALENDAR"""
            else:
                # Format for timed event
                dtstart = event.start_time.strftime("%Y%m%dT%H%M%S")
                dtend = event.end_time.strftime("%Y%m%dT%H%M%S")
                vcal = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Telegram Bot//Task Tracker//EN
BEGIN:VEVENT
DTSTART:{dtstart}
DTEND:{dtend}
SUMMARY:{event.title}
DESCRIPTION:{event.description or ''}
STATUS:CONFIRMED
END:VEVENT
END:VCALENDAR"""

            # Create event in calendar
            created_event = self._default_calendar.save_event(vcal)

            # Get the UID (may not be available with all CalDAV servers)
            event_uid = None
            if hasattr(created_event, 'vobject_instance') and created_event.vobject_instance is not None:
                vevent = getattr(created_event.vobject_instance, 'vevent', None)
                if vevent is not None and hasattr(vevent, 'uid'):
                    event_uid = str(vevent.uid.value)

            logger.info(f"Created calendar event: {event.title} (UID: {event_uid})")

            return CalendarResult(
                success=True,
                event_uid=event_uid
            )

        except Exception as e:
            error_msg = f"Failed to create calendar event: {e}"
            logger.error(error_msg, exc_info=True)
            return CalendarResult(success=False, error=error_msg)

    def add_task_as_event(self, task_title: str, task_description: Optional[str] = None,
                          reminder_time: Optional[datetime] = None) -> CalendarResult:
        """
        Add a task as a calendar event.

        Args:
            task_title: Task title (becomes event title)
            task_description: Task description
            reminder_time: When to remind (becomes event start time)

        Returns:
            CalendarResult
        """
        # If reminder time is set, create a timed event
        if reminder_time:
            event = CalendarEvent(
                title=f"[Task] {task_title}",
                description=task_description,
                start_time=reminder_time,
                end_time=reminder_time + timedelta(minutes=30),
                all_day=False
            )
        else:
            # Create as all-day task for today
            event = CalendarEvent(
                title=f"[Task] {task_title}",
                description=task_description,
                start_time=datetime.now(),
                all_day=True
            )

        return self.add_event(event)

    def delete_task_event(self, task_title: str) -> CalendarResult:
        """
        Delete a task event from calendar by searching for its title.

        Args:
            task_title: Original task title (without [Task] prefix)

        Returns:
            CalendarResult
        """
        try:
            # Ensure connection
            if self._default_calendar is None:
                if not self._connect():
                    return CalendarResult(
                        success=False,
                        error="Failed to connect to Yandex Calendar"
                    )

            # Search for events with the task title
            search_title = f"[Task] {task_title}"
            logger.info(f"Searching for calendar event: {search_title}")

            # Try to search by text first (more efficient)
            try:
                events = self._default_calendar.search(summary=task_title)
                if not events:
                    events = self._default_calendar.events()
            except Exception:
                # Fallback to getting all events
                events = self._default_calendar.events()

            deleted_count = 0
            events_checked = 0

            for event in events:
                events_checked += 1
                try:
                    # Try to load event data if needed
                    if hasattr(event, 'load') and callable(event.load):
                        try:
                            event.load()
                        except Exception:
                            pass

                    # Get event summary from raw data or vobject
                    event_summary = None

                    # Try vobject_instance first
                    if hasattr(event, 'vobject_instance') and event.vobject_instance is not None:
                        vevent = getattr(event.vobject_instance, 'vevent', None)
                        if vevent is not None:
                            summary_obj = getattr(vevent, 'summary', None)
                            if summary_obj is not None:
                                event_summary = str(summary_obj.value)

                    # Try data attribute as fallback
                    if event_summary is None and hasattr(event, 'data'):
                        data = event.data
                        if data and 'SUMMARY:' in data:
                            for line in data.split('\n'):
                                if line.startswith('SUMMARY:'):
                                    event_summary = line[8:].strip()
                                    break

                    if event_summary and event_summary == search_title:
                        event.delete()
                        deleted_count += 1
                        logger.info(f"Deleted calendar event: {search_title}")

                except Exception as e:
                    logger.warning(f"Error checking/deleting event: {e}")
                    continue

            logger.info(f"Checked {events_checked} events, deleted {deleted_count}")

            if deleted_count > 0:
                return CalendarResult(success=True)
            else:
                return CalendarResult(
                    success=False,
                    error=f"No calendar event found for task: {task_title}"
                )

        except Exception as e:
            error_msg = f"Failed to delete calendar event: {e}"
            logger.error(error_msg, exc_info=True)
            return CalendarResult(success=False, error=error_msg)


# Global client instance
_calendar_client: Optional[YandexCalendarClient] = None


def init_yandex_calendar(username: str, password: str) -> bool:
    """
    Initialize the global Yandex Calendar client.

    Args:
        username: Yandex email
        password: App password

    Returns:
        True if initialization successful
    """
    global _calendar_client

    if not CALDAV_AVAILABLE:
        logger.warning("caldav library not available - Yandex Calendar disabled")
        return False

    if not username or not password:
        logger.warning("Yandex Calendar credentials not configured")
        return False

    try:
        _calendar_client = YandexCalendarClient(username, password)
        logger.info("Yandex Calendar client initialized")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize Yandex Calendar: {e}")
        return False


def get_yandex_calendar() -> Optional[YandexCalendarClient]:
    """Get the global Yandex Calendar client."""
    return _calendar_client


def is_calendar_enabled() -> bool:
    """Check if Yandex Calendar is enabled and configured."""
    return _calendar_client is not None


async def add_task_to_calendar(task_title: str, task_description: Optional[str] = None,
                                reminder_time: Optional[datetime] = None) -> CalendarResult:
    """
    Convenience function to add a task to Yandex Calendar.

    Args:
        task_title: Task title
        task_description: Optional description
        reminder_time: Optional reminder time

    Returns:
        CalendarResult
    """
    client = get_yandex_calendar()

    if client is None:
        return CalendarResult(
            success=False,
            error="Yandex Calendar not configured"
        )

    return client.add_task_as_event(task_title, task_description, reminder_time)


async def delete_task_from_calendar(task_title: str) -> CalendarResult:
    """
    Delete a task event from Yandex Calendar.

    Args:
        task_title: Task title to delete

    Returns:
        CalendarResult
    """
    client = get_yandex_calendar()

    if client is None:
        return CalendarResult(
            success=False,
            error="Yandex Calendar not configured"
        )

    return client.delete_task_event(task_title)
