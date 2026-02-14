"""CloudTrail tools for Strands agents.

New in v2 - critical for RCA: 80% of issues are caused by changes.
"""

import json
import logging
from datetime import datetime, timedelta

from botocore.exceptions import ClientError
from strands import tool

from agenticops.tools.aws_tools import _get_client

logger = logging.getLogger(__name__)


@tool
def lookup_cloudtrail_events(
    resource_id: str, region: str, hours: int = 2
) -> str:
    """Look up recent CloudTrail events for a resource.

    This is CRITICAL for RCA - 80% of production issues are caused by changes.
    Returns recent API calls that modified the resource or its configuration.

    Args:
        resource_id: AWS resource name or ID (e.g., i-1234567890abcdef0)
        region: AWS region
        hours: Hours of history to search (1-24)

    Returns:
        JSON list of recent change events with: event_name, time, user, source_ip, resources.
    """
    try:
        client = _get_client("cloudtrail", region)
    except RuntimeError as e:
        return str(e)

    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=min(hours, 24))

    try:
        response = client.lookup_events(
            LookupAttributes=[
                {
                    "AttributeKey": "ResourceName",
                    "AttributeValue": resource_id,
                }
            ],
            StartTime=start_time,
            EndTime=end_time,
            MaxResults=50,
        )

        events = []
        for event in response.get("Events", []):
            # Parse CloudTrailEvent JSON for detailed info
            event_detail = {}
            try:
                event_detail = json.loads(event.get("CloudTrailEvent", "{}"))
            except json.JSONDecodeError:
                pass

            events.append({
                "event_name": event.get("EventName"),
                "event_time": str(event.get("EventTime", "")),
                "username": event.get("Username"),
                "source_ip": event_detail.get("sourceIPAddress"),
                "user_agent": event_detail.get("userAgent", "")[:100],
                "event_source": event_detail.get("eventSource"),
                "resources": [
                    {"type": r.get("ResourceType"), "name": r.get("ResourceName")}
                    for r in event.get("Resources", [])
                ],
                "error_code": event_detail.get("errorCode"),
                "error_message": event_detail.get("errorMessage", "")[:200],
            })

        if not events:
            return f"No CloudTrail events found for {resource_id} in {region} (last {hours}h)."

        return json.dumps(events, default=str)

    except ClientError as e:
        return f"Error looking up CloudTrail events for {resource_id}: {e}"
