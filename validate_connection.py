#!/usr/bin/env python3
"""Validate LibreLinkUp connection and print all patient readings."""
import os
import sys
from pathlib import Path

import yaml
from pylibrelinkup import PyLibreLinkUp


def main():
    config_path = os.environ.get("CONFIG_PATH", str(Path(__file__).resolve().parent / "config.yaml"))
    if not os.path.exists(config_path):
        print(f"Config not found: {config_path}")
        sys.exit(1)
    with open(config_path) as f:
        config = yaml.safe_load(f)
    ll = config.get("librelinkup", {})
    email = ll.get("email") or os.environ.get("LIBRELINKUP_EMAIL", "")
    password = ll.get("password") or os.environ.get("LIBRELINKUP_PASSWORD", "")
    if not email or not password:
        print("Missing LibreLinkUp credentials")
        sys.exit(1)
    print(f"Authenticating as {email}...")
    try:
        client = PyLibreLinkUp(email=email, password=password)
        client.authenticate()
        print("Authentication successful!")
    except Exception as e:
        print(f"Authentication failed: {e}")
        sys.exit(1)
    try:
        patients = client.get_patients()
        print(f"\nFound {len(patients)} patient(s):")
        for patient in patients:
            print(f"\n  Patient: {patient.first_name} {patient.last_name} (ID: {patient.patient_id})")
            try:
                latest = client.latest(patient)
                if latest:
                    trend = latest.trend.indicator if hasattr(latest, 'trend') and latest.trend else "?"
                    print(f"    Glucose: {latest.value} mg/dL {trend}")
                    print(f"    Timestamp: {latest.factory_timestamp}")
                    print(f"    High: {getattr(latest, 'is_high', '?')}, Low: {getattr(latest, 'is_low', '?')}")
                else:
                    print("    No latest reading available")
            except Exception as e:
                print(f"    Error reading: {e}")
    except Exception as e:
        print(f"Failed to get patients: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
