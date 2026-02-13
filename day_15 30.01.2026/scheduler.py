"""
Background Scheduler for Telegram Bot.

This module provides a scheduler that runs continuously and triggers
reminder notifications via MCP at scheduled times.

Features:
- APScheduler-based background scheduling
- Minute-by-minute checks for scheduled reminders
- Integration with MCP server for user preferences
- Graceful recovery after restarts
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Callable, Optional, Awaitable, Union, Dict

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from mcp_http_client import get_mcp_http_client, MCPHttpClient
from task_tracker_client import get_task_tracker_client, TaskTrackerMCPClient

logger = logging.getLogger(__name__)

# Check which MCP mode to use
USE_HTTP_MCP = os.getenv("USE_HTTP_MCP", "false").lower() == "true"


class ReminderScheduler:
    """
    Background scheduler for sending task reminders.

    Integrates with the MCP server to:
    - Fetch users scheduled for reminders
    - Generate summaries via MCP
    - Send notifications via Telegram
    """

    def __init__(self, send_message_callback: Callable[[str, str], Awaitable[bool]]):
        """
        Initialize the scheduler.

        Args:
            send_message_callback: Async function to send Telegram messages.
                                   Signature: (user_id: str, message: str) -> bool
        """
        self.scheduler = AsyncIOScheduler()
        self.send_message = send_message_callback
        self._running = False
        self._mcp_client: Optional[Union[MCPHttpClient, TaskTrackerMCPClient]] = None
        self._use_http = USE_HTTP_MCP

    def _get_mcp_client(self) -> Union[MCPHttpClient, TaskTrackerMCPClient]:
        """Get the MCP client, with lazy initialization."""
        if self._mcp_client is None:
            if self._use_http:
                self._mcp_client = get_mcp_http_client()
            else:
                self._mcp_client = get_task_tracker_client()
        if self._mcp_client is None:
            client_type = "HTTP" if self._use_http else "Task Tracker"
            raise RuntimeError(f"MCP {client_type} client not initialized")
        return self._mcp_client

    async def check_and_send_reminders(self) -> None:
        """
        Check for scheduled reminders and send them.

        This is called every minute by the scheduler.
        """
        now = datetime.now()
        current_hour = now.hour
        current_minute = now.minute

        logger.debug(f"Checking reminders for {current_hour:02d}:{current_minute:02d}")

        try:
            mcp = self._get_mcp_client()

            # Get users scheduled for this time
            if self._use_http:
                result = await mcp.get_scheduled_users(current_hour, current_minute)
            else:
                result = await mcp.call_tool("reminder_get_scheduled_users", {
                    "hour": current_hour, "minute": current_minute
                })

            if not result.success:
                logger.error(f"Failed to get scheduled users: {result.error}")
                return

            users = result.data.get("users", [])

            if not users:
                return

            logger.info(f"Sending reminders to {len(users)} users at {current_hour:02d}:{current_minute:02d}")

            # Send reminders to each user
            for user_id in users:
                await self._send_reminder_to_user(user_id)

        except Exception as e:
            logger.error(f"Error in reminder check: {e}", exc_info=True)

    async def _send_reminder_to_user(self, user_id: str) -> None:
        """
        Generate and send a reminder to a specific user.

        Sends via Telegram and optionally via email if configured.

        Args:
            user_id: Telegram user ID
        """
        try:
            mcp = self._get_mcp_client()

            # Generate summary via MCP
            if self._use_http:
                result = await mcp.generate_summary(user_id, include_completed=True)
            else:
                result = await mcp.call_tool("reminder_generate_summary", {
                    "user_id": user_id, "include_completed": True
                })

            if not result.success:
                logger.error(f"Failed to generate summary for user {user_id}: {result.error}")
                return

            summary = result.data.get("summary", "No summary available")

            # Send via Telegram
            telegram_success = await self.send_message(user_id, summary)

            if telegram_success:
                # Mark reminder as sent
                if self._use_http:
                    await mcp.mark_reminder_sent(user_id)
                else:
                    await mcp.call_tool("reminder_mark_sent", {"user_id": user_id})
                logger.info(f"Telegram reminder sent to user {user_id}")
            else:
                logger.error(f"Failed to send Telegram reminder to user {user_id}")

            # Send email notification if configured (non-blocking)
            await self._send_email_notification(user_id, summary)

        except Exception as e:
            logger.error(f"Error sending reminder to user {user_id}: {e}", exc_info=True)

    async def _send_email_notification(self, user_id: str, summary: str) -> None:
        """
        Send email notification if configured for user.

        This is non-blocking - failures don't affect Telegram delivery.

        Args:
            user_id: User identifier
            summary: Summary text to send
        """
        try:
            mcp = self._get_mcp_client()

            # Check email preferences
            if self._use_http:
                prefs_result = await mcp.get_email_preferences(user_id)
            else:
                prefs_result = await mcp.call_tool("notification_get_email_preferences", {
                    "user_id": user_id
                })

            if not prefs_result.success:
                logger.debug(f"Could not get email preferences for user {user_id}")
                return

            email_enabled = prefs_result.data.get("email_enabled", False)
            email_recipient = prefs_result.data.get("email_recipient")

            if not email_enabled or not email_recipient:
                logger.debug(f"Email notifications not configured for user {user_id}")
                return

            # Send email via MCP
            if self._use_http:
                email_result = await mcp.send_email(
                    recipient_email=email_recipient,
                    subject="New Reminder",
                    message_text=summary
                )
            else:
                email_result = await mcp.call_tool("notification_send_email", {
                    "recipient_email": email_recipient,
                    "subject": "New Reminder",
                    "message_text": summary
                })

            if email_result.success:
                logger.info(f"Email reminder sent to user {user_id} ({email_recipient})")
            else:
                logger.warning(f"Failed to send email to user {user_id}: {email_result.error}")

        except Exception as e:
            # Email failure should not break reminder flow
            logger.warning(f"Email notification failed for user {user_id}: {e}")

    async def check_task_reminders(self) -> None:
        """
        Check for task-specific reminders that are due and send them.

        This is called every minute by the scheduler.
        """
        now = datetime.now()
        current_time_iso = now.strftime("%Y-%m-%dT%H:%M:%S")

        logger.debug(f"Checking task reminders at {current_time_iso}")

        try:
            mcp = self._get_mcp_client()

            # Get due task reminders
            if self._use_http:
                # HTTP client would need a new method
                return  # Not implemented for HTTP mode yet
            else:
                result = await mcp.call_tool("task_reminder_get_due", {
                    "current_time": current_time_iso
                })

            if not result.success:
                logger.error(f"Failed to get due task reminders: {result.error}")
                return

            reminders = result.data.get("reminders", [])

            if not reminders:
                return

            logger.info(f"Found {len(reminders)} due task reminders")

            # Send each reminder
            for reminder in reminders:
                await self._send_task_reminder(reminder)

        except Exception as e:
            logger.error(f"Error in task reminder check: {e}", exc_info=True)

    async def _send_task_reminder(self, reminder: Dict) -> None:
        """
        Send a task-specific reminder notification.

        Args:
            reminder: Reminder dict with task info
        """
        try:
            user_id = reminder["user_id"]
            task_id = reminder["task_id"]
            task_title = reminder.get("task_title", "Task")
            task_description = reminder.get("task_description", "")
            custom_message = reminder.get("message")
            reminder_id = reminder["id"]

            # Build Telegram message
            message_lines = [
                f"⏰ DO NOT FORGET - {task_title}",
            ]
            if task_description:
                message_lines.append(f"\n{task_description}")
            if custom_message:
                message_lines.append(f"\n{custom_message}")

            message = "\n".join(message_lines)

            # Send via Telegram
            success = await self.send_message(user_id, message)

            if success:
                # Mark reminder as sent
                mcp = self._get_mcp_client()
                if not self._use_http:
                    await mcp.call_tool("task_reminder_mark_sent", {
                        "reminder_id": reminder_id
                    })
                logger.info(f"Task reminder {reminder_id} sent to user {user_id}")
            else:
                logger.error(f"Failed to send task reminder {reminder_id} to user {user_id}")

            # Send email notification for this task
            await self._send_task_email_notification(user_id, task_title, task_description)

        except Exception as e:
            logger.error(f"Error sending task reminder: {e}", exc_info=True)

    async def _send_task_email_notification(self, user_id: str, task_title: str,
                                            task_description: str = "") -> None:
        """
        Send email notification for a specific task.

        Args:
            user_id: User identifier
            task_title: Task title (used as email subject)
            task_description: Task description (included in body if not empty)
        """
        try:
            mcp = self._get_mcp_client()

            # Check email preferences
            if self._use_http:
                prefs_result = await mcp.get_email_preferences(user_id)
            else:
                prefs_result = await mcp.call_tool("notification_get_email_preferences", {
                    "user_id": user_id
                })

            if not prefs_result.success:
                logger.debug(f"Could not get email preferences for user {user_id}")
                return

            email_enabled = prefs_result.data.get("email_enabled", False)
            email_recipient = prefs_result.data.get("email_recipient")

            if not email_enabled or not email_recipient:
                logger.debug(f"Email notifications not configured for user {user_id}")
                return

            # Build email content
            subject = task_title

            body_lines = [f"DO NOT FORGET - {task_title}"]
            if task_description:
                body_lines.append("")
                body_lines.append(task_description)

            message_text = "\n".join(body_lines)

            # Send email via MCP
            if self._use_http:
                email_result = await mcp.send_email(
                    recipient_email=email_recipient,
                    subject=subject,
                    message_text=message_text
                )
            else:
                email_result = await mcp.call_tool("notification_send_email", {
                    "recipient_email": email_recipient,
                    "subject": subject,
                    "message_text": message_text
                })

            if email_result.success:
                logger.info(f"Task email sent to user {user_id} ({email_recipient}): {task_title}")
            else:
                logger.warning(f"Failed to send task email to user {user_id}: {email_result.error}")

        except Exception as e:
            logger.warning(f"Task email notification failed for user {user_id}: {e}")

    async def send_immediate_reminder(self, user_id: str) -> tuple[bool, str]:
        """
        Send an immediate reminder to a user.

        Args:
            user_id: Telegram user ID

        Returns:
            Tuple of (success, message/error)
        """
        try:
            mcp = self._get_mcp_client()

            # Generate summary
            if self._use_http:
                result = await mcp.generate_summary(user_id, include_completed=True)
            else:
                result = await mcp.call_tool("reminder_generate_summary", {
                    "user_id": user_id, "include_completed": True
                })

            if not result.success:
                return False, f"Failed to generate summary: {result.error}"

            summary = result.data.get("summary", "No summary available")
            return True, summary

        except Exception as e:
            error_msg = f"Error generating reminder: {e}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg

    def start(self) -> None:
        """Start the scheduler."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        # Schedule the daily reminder check to run every minute
        self.scheduler.add_job(
            self.check_and_send_reminders,
            CronTrigger(minute="*"),  # Every minute
            id="reminder_check",
            name="Check and send daily reminders",
            replace_existing=True
        )

        # Schedule task-specific reminder check to run every minute
        self.scheduler.add_job(
            self.check_task_reminders,
            CronTrigger(minute="*"),  # Every minute
            id="task_reminder_check",
            name="Check and send task reminders",
            replace_existing=True
        )

        self.scheduler.start()
        self._running = True
        logger.info("Reminder scheduler started (daily + task reminders)")

    def stop(self) -> None:
        """Stop the scheduler."""
        if not self._running:
            return

        self.scheduler.shutdown(wait=False)
        self._running = False
        logger.info("Reminder scheduler stopped")

    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._running


# Global scheduler instance
_scheduler: Optional[ReminderScheduler] = None


def init_scheduler(send_message_callback: Callable[[str, str], Awaitable[bool]]) -> ReminderScheduler:
    """
    Initialize the global scheduler.

    Args:
        send_message_callback: Async function to send Telegram messages

    Returns:
        ReminderScheduler instance
    """
    global _scheduler
    _scheduler = ReminderScheduler(send_message_callback)
    return _scheduler


def get_scheduler() -> Optional[ReminderScheduler]:
    """Get the global scheduler instance."""
    return _scheduler


def start_scheduler() -> None:
    """Start the global scheduler."""
    if _scheduler:
        _scheduler.start()
    else:
        logger.error("Scheduler not initialized")


def stop_scheduler() -> None:
    """Stop the global scheduler."""
    if _scheduler:
        _scheduler.stop()
