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
from typing import Callable, Optional, Awaitable, Union

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
            success = await self.send_message(user_id, summary)

            if success:
                # Mark reminder as sent
                if self._use_http:
                    await mcp.mark_reminder_sent(user_id)
                else:
                    await mcp.call_tool("reminder_mark_sent", {"user_id": user_id})
                logger.info(f"Reminder sent to user {user_id}")
            else:
                logger.error(f"Failed to send reminder to user {user_id}")

        except Exception as e:
            logger.error(f"Error sending reminder to user {user_id}: {e}", exc_info=True)

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

        # Schedule the reminder check to run every minute
        self.scheduler.add_job(
            self.check_and_send_reminders,
            CronTrigger(minute="*"),  # Every minute
            id="reminder_check",
            name="Check and send reminders",
            replace_existing=True
        )

        self.scheduler.start()
        self._running = True
        logger.info("Reminder scheduler started")

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
