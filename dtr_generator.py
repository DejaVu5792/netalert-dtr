#!/usr/bin/env python3

import argparse
import csv
import os
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

import requests
from dotenv import load_dotenv


load_dotenv()

NETALERTX_HOST = os.getenv("NETALERTX_HOST")
NETALERTX_TOKEN = os.getenv("NETALERTX_TOKEN")


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
    headers = {"Authorization": f"Bearer {token}"}

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    days = (end - start).days + 1

    period = f"{days} days"
    params = {"period": period}
    response = requests.get(f"{host}/sessions/{mac}", headers=headers, params=params)
    response.raise_for_status()
    sessions = response.json().get("sessions", [])

    filtered = []
    for session in sessions:
        conn_str = session.get("ses_Connection", "")
        if conn_str and conn_str != "<missing event>":
            try:
                conn_time = datetime.fromisoformat(conn_str.replace("Z", "+00:00"))
                if start_date <= conn_time.strftime("%Y-%m-%d") <= end_date:
                    filtered.append(session)
            except ValueError:
                continue

    return filtered


def process_sessions(sessions: List[Dict]) -> Dict[str, Tuple[str, Optional[str]]]:
    """Process sessions and return daily time in/out."""
    daily_data = {}

    for session in sessions:
        conn_str = session.get("ses_Connection", "")
        disc_str = session.get("ses_Disconnection", "")

        if not conn_str or conn_str == "<missing event>":
            continue

        try:
            conn_time = datetime.fromisoformat(conn_str.replace("Z", "+00:00"))
            date = conn_time.strftime("%Y-%m-%d")

            time_in = conn_time.strftime("%H:%M:%S")

            if disc_str and disc_str != "<missing event>":
                disc_time = datetime.fromisoformat(disc_str.replace("Z", "+00:00"))
                time_out = disc_time.strftime("%H:%M:%S")
            else:
                time_out = None

            if date not in daily_data:
                daily_data[date] = (time_in, time_out)
            else:
                existing_time_in, existing_time_out = daily_data[date]
                if time_in < existing_time_in:
                    daily_data[date] = (time_in, existing_time_out)
                if time_out and (not existing_time_out or time_out > existing_time_out):
                    daily_data[date] = (daily_data[date][0], time_out)
        except ValueError as e:
            print(f"Warning: Could not parse session time: {e}", file=sys.stderr)
            continue

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
    except requests.RequestException as e:
        print(f"Error fetching devices: {e}", file=sys.stderr)
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
            sessions = fetch_sessions(
                args.host, args.token, mac, start_date_str, end_date_str
            )
            all_sessions.extend(sessions)
            print(f"  Retrieved {len(sessions)} sessions")
        except requests.RequestException as e:
            print(f"Warning: Could not fetch sessions for {mac}: {e}", file=sys.stderr)

    if not all_sessions:
        print("No sessions found in the specified date range", file=sys.stderr)
        daily_data = {}
    else:
        print(f"Processing {len(all_sessions)} total sessions...")
        daily_data = process_sessions(all_sessions)

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
