#!/usr/bin/env python3

import argparse
import csv
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple

import requests
from dotenv import load_dotenv


load_dotenv()

NETALERTX_HOST = os.getenv("NETALERTX_HOST")
NETALERTX_TOKEN = os.getenv("NETALERTX_TOKEN")


class DTRGeneratorError(Exception):
    """Base exception for DTR generator errors."""

    pass


class NetworkError(DTRGeneratorError):
    """Network-related errors."""

    pass


class APIError(DTRGeneratorError):
    """API-related errors."""

    pass


class DataProcessingError(DTRGeneratorError):
    """Data processing errors."""

    pass


def fetch_devices(host: str, token: str) -> List[Dict]:
    """Fetch all devices from NetAlertX API."""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{host}/devices", headers=headers)
    response.raise_for_status()
    return response.json().get("devices", [])


def find_devices(
    devices: List[Dict],
    device_name: Optional[str] = None,
    owner: Optional[str] = None,
    group: Optional[str] = None,
) -> List[Dict]:
    """Filter devices by name, owner, and/or group."""
    filtered = []
    for device in devices:
        name_match = (
            not device_name or device_name.lower() in device.get("devName", "").lower()
        )
        owner_match = not owner or owner.lower() in device.get("devOwner", "").lower()
        group_match = not group or group.lower() in device.get("devGroup", "").lower()

        if name_match and owner_match and group_match:
            filtered.append(device)

    return filtered


def fetch_sessions(
    host: str, token: str, mac: str, start_date: str, end_date: str
) -> List[Dict]:
    """Fetch sessions for a device within date range."""
    if not mac:
        raise DataProcessingError("MAC address is empty")

    if len(mac) < 10:
        raise DataProcessingError(f"Invalid MAC address: '{mac}' is too short")

    headers = {"Authorization": f"Bearer {token}"}
    url = f"{host}/sessions/list"

    params = {"mac": mac, "start_date": start_date, "end_date": end_date}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
    except requests.exceptions.Timeout:
        raise NetworkError(
            f"Connection timeout while fetching sessions for {mac}: API did not respond within 30 seconds"
        )
    except requests.exceptions.ConnectionError as e:
        if "Connection refused" in str(e):
            raise NetworkError(
                f"Connection refused while fetching sessions for {mac}: API not accepting connections"
            )
        raise NetworkError(f"Connection error while fetching sessions for {mac}: {e}")
    except requests.exceptions.RequestException as e:
        raise NetworkError(f"Request failed while fetching sessions for {mac}: {e}")

    status_code = response.status_code

    if status_code == 401:
        raise APIError(
            "Authentication failed while fetching sessions (HTTP 401). Check your NETALERTX_TOKEN"
        )
    elif status_code == 403:
        raise APIError(
            "Access forbidden while fetching sessions (HTTP 403). API token lacks required permissions"
        )
    elif status_code == 404:
        raise APIError(
            f"Sessions endpoint not found (HTTP 404): /sessions/list may not exist. Check NetAlertX API version"
        )
    elif status_code == 429:
        raise APIError(
            "Rate limit exceeded while fetching sessions (HTTP 429). Too many requests, please wait"
        )
    elif status_code >= 500:
        raise APIError(
            f"NetAlertX server error while fetching sessions (HTTP {status_code})"
        )
    elif status_code >= 400:
        raise APIError(
            f"Client error while fetching sessions (HTTP {status_code}): {response.text}"
        )

    try:
        response_json = response.json()
    except ValueError as e:
        raise APIError(f"Invalid JSON response while fetching sessions: {e}")

    if not isinstance(response_json, dict):
        raise APIError(
            "Unexpected response format while fetching sessions: expected JSON object"
        )

    if "sessions" not in response_json:
        raise APIError(
            "API response missing 'sessions' key while fetching sessions. API version may be incompatible"
        )

    sessions = response_json.get("sessions", [])

    if not isinstance(sessions, list):
        raise APIError(
            "Unexpected format while fetching sessions: 'sessions' field is not a list"
        )

    return sessions


def normalize_session_fields(session: Dict) -> Dict:
    """Normalize session field names between API versions."""
    normalized = session.copy()

    # NetAlertX API uses sesDateTimeConnection / sesDateTimeDisconnection
    if "sesDateTimeConnection" in normalized and "ses_Connection" not in normalized:
        normalized["ses_Connection"] = normalized["sesDateTimeConnection"]

    if (
        "sesDateTimeDisconnection" in normalized
        and "ses_Disconnection" not in normalized
    ):
        normalized["ses_Disconnection"] = normalized["sesDateTimeDisconnection"]

    # Also handle alternative naming with underscores for compatibility
    if "ses_DateTimeConnection" in normalized and "ses_Connection" not in normalized:
        normalized["ses_Connection"] = normalized["ses_DateTimeConnection"]

    if (
        "ses_DateTimeDisconnection" in normalized
        and "ses_Disconnection" not in normalized
    ):
        normalized["ses_Disconnection"] = normalized["ses_DateTimeDisconnection"]

    return normalized


def parse_datetime(dt_str: str) -> Optional[datetime]:
    """Parse datetime string from various formats."""
    if not dt_str or dt_str == "<missing event>":
        return None

    # Remove Z suffix and replace with timezone if present
    dt_str = dt_str.replace("Z", "+00:00")

    # Try common formats
    formats = [
        "%Y-%m-%d %H:%M:%S",  # "2025-08-01 10:00:00"
        "%Y-%m-%d %H:%M",  # "2025-08-01 10:00" (NetAlertX format)
        "%Y-%m-%dT%H:%M:%S%z",  # ISO with timezone
        "%Y-%m-%dT%H:%M:%S",  # ISO without timezone
        "%Y-%m-%dT%H:%M",  # ISO with minutes only
    ]

    for fmt in formats:
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue

    # Fallback to fromisoformat for ISO formats
    try:
        return datetime.fromisoformat(dt_str)
    except ValueError:
        pass

    return None


def process_sessions(sessions: List[Dict]) -> Dict[str, Tuple[str, Optional[str]]]:
    """Process sessions and return daily time in/out."""
    daily_data = {}

    for session in sessions:
        conn_str = session.get("ses_Connection", "")
        disc_str = session.get("ses_Disconnection", "")

        if not conn_str or conn_str == "<missing event>":
            continue

        conn_time = parse_datetime(conn_str)
        if conn_time is None:
            print(
                f"Warning: Could not parse connection time: {conn_str}", file=sys.stderr
            )
            continue

        # NetAlertX returns UTC times (often as naive strings).
        # Assume naive datetimes are in UTC and convert to local time.
        if conn_time.tzinfo is None:
            conn_time = conn_time.replace(tzinfo=timezone.utc)
        conn_time = conn_time.astimezone()

        date = conn_time.strftime("%Y-%m-%d")
        time_in = conn_time.strftime("%H:%M:%S")

        disc_time = parse_datetime(disc_str)
        if disc_time:
            if disc_time.tzinfo is None:
                disc_time = disc_time.replace(tzinfo=timezone.utc)
            disc_time = disc_time.astimezone()

        time_out = disc_time.strftime("%H:%M:%S") if disc_time else None

        if date not in daily_data:
            daily_data[date] = (time_in, time_out)
        else:
            existing_time_in, existing_time_out = daily_data[date]
            if time_in < existing_time_in:
                daily_data[date] = (time_in, existing_time_out)
            if time_out and (not existing_time_out or time_out > existing_time_out):
                daily_data[date] = (daily_data[date][0], time_out)

    return daily_data


def write_csv(data: Dict[str, Tuple[str, Optional[str]]], output_path: str):
    """Write daily time records to CSV."""
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "time_in", "time_out"])

        for date, (time_in, time_out) in sorted(data.items()):
            writer.writerow([date, time_in, time_out or ""])


def main():
    parser = argparse.ArgumentParser(
        description="NetAlertX Daily Time Record Generator"
    )
    parser.add_argument("--device", help="Device name filter")
    parser.add_argument("--owner", help="Device owner filter (consolidates by default)")
    parser.add_argument("--group", help="Device group filter (consolidates by default)")
    parser.add_argument(
        "--start-date", help="Start date (YYYY-MM-DD, default: 30 days ago)"
    )
    parser.add_argument("--end-date", help="End date (YYYY-MM-DD, default: today)")
    parser.add_argument("--output", "-o", help="Output CSV path")
    parser.add_argument(
        "--consolidate", action="store_true", help="Consolidate multiple device matches"
    )
    parser.add_argument("--host", default=NETALERTX_HOST, help="NetAlertX host")
    parser.add_argument("--token", default=NETALERTX_TOKEN, help="API token")

    args = parser.parse_args()

    if not any([args.device, args.owner, args.group]):
        parser.error("At least one of --device, --owner, or --group must be specified")

    try:
        today = datetime.now()

        if args.start_date:
            start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
        else:
            start_date = (today - timedelta(days=30)).date()

        if args.end_date:
            end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()
        else:
            end_date = today.date()
    except ValueError as e:
        parser.error(f"Invalid date format: {e}. Use YYYY-MM-DD.")

    print(f"Fetching devices from {args.host}...")
    try:
        devices = fetch_devices(args.host, args.token)
        print(f"Found {len(devices)} devices")
    except (NetworkError, APIError) as e:
        print(f"Error fetching devices: {e}", file=sys.stderr)
        sys.exit(1)
    except DTRGeneratorError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    matching_devices = find_devices(devices, args.device, args.owner, args.group)

    if not matching_devices:
        print(f"No matching devices found", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(matching_devices)} matching device(s):")
    for device in matching_devices:
        print(
            f"  - {device.get('devName', 'Unknown')} (MAC: {device.get('devMac', 'N/A')}, Owner: {device.get('devOwner', 'N/A')}, Group: {device.get('devGroup', 'N/A')})"
        )

    if len(matching_devices) > 1:
        consolidate_by_default = args.owner or args.group
        if args.consolidate or consolidate_by_default:
            print(f"Consolidating {len(matching_devices)} devices...")
        else:
            print(
                "Error: Multiple devices found. Use --consolidate to combine them.",
                file=sys.stderr,
            )
            sys.exit(1)

    all_sessions = []
    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")

    for device in matching_devices:
        mac = device.get("devMac")
        if not mac:
            print(
                f"Warning: Device {device.get('devName', 'Unknown')} has no MAC address, skipping",
                file=sys.stderr,
            )
            continue

        print(
            f"Fetching sessions for {device.get('devName', mac)} ({start_date_str} to {end_date_str})..."
        )
        try:
            # Add 1 day to the end_date sent to NetAlertX to ensure the full end_date day is included.
            # NetAlertX filters end_date as YYYY-MM-DD 00:00:00 (exclusive of that day's sessions).
            api_end_date = end_date + timedelta(days=1)
            api_end_date_str = api_end_date.strftime("%Y-%m-%d")
            sessions = fetch_sessions(
                args.host, args.token, mac, start_date_str, api_end_date_str
            )
            normalized_sessions = [normalize_session_fields(s) for s in sessions]
            all_sessions.extend(normalized_sessions)
            print(f"  Retrieved {len(sessions)} sessions")
        except (NetworkError, APIError, DataProcessingError) as e:
            print(f"Warning: Could not fetch sessions for {mac}: {e}", file=sys.stderr)
        except DTRGeneratorError as e:
            print(f"Warning: Could not fetch sessions for {mac}: {e}", file=sys.stderr)

    if not all_sessions:
        print("No sessions found in the specified date range", file=sys.stderr)
        daily_data = {}
    else:
        print(f"Processing {len(all_sessions)} total sessions...")
        daily_data = process_sessions(all_sessions)
        # Filter to requested date range (inclusive) to omit any sessions from the next day (api_end_date_str)
        daily_data = {
            d: val for d, val in daily_data.items()
            if start_date_str <= d <= end_date_str
        }

    if args.output:
        output_path = args.output
    else:
        identifier = args.owner or args.group or args.device or "devices"
        identifier = identifier.replace(" ", "_")
        start_ymd = start_date.strftime("%y%m%d")
        end_ymd = end_date.strftime("%y%m%d")
        output_path = f"{identifier}_{start_ymd}-{end_ymd}.csv"

    write_csv(daily_data, output_path)
    print(f"\nGenerated DTR with {len(daily_data)} days of data: {output_path}")


if __name__ == "__main__":
    main()
