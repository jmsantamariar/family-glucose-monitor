"""Validate LibreLinkUp connection and list all patients with current glucose readings."""
import sys

from pylibrelinkup import PyLibreLinkUp
from pylibrelinkup.api_url import APIUrl
from pylibrelinkup.exceptions import RedirectError

REGION_MAP = {
    "US": APIUrl.US,
    "EU": APIUrl.EU,
    "EU2": APIUrl.EU2,
    "DE": APIUrl.DE,
    "FR": APIUrl.FR,
    "JP": APIUrl.JP,
    "AP": APIUrl.AP,
    "AU": APIUrl.AU,
    "AE": APIUrl.AE,
    "CA": APIUrl.CA,
    "LA": APIUrl.LA,
    "RU": APIUrl.RU,
}


def main() -> None:
    try:
        import yaml
    except ImportError:
        print("ERROR: PyYAML not installed. Run: pip install PyYAML")
        sys.exit(1)

    try:
        with open("config.yaml") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        print("ERROR: config.yaml not found. Copy config.example.yaml to config.yaml")
        sys.exit(1)

    ll_cfg = config.get("librelinkup", {})
    email = ll_cfg.get("email", "")
    password = ll_cfg.get("password", "")
    region = ll_cfg.get("region", "US")

    if not email or not password:
        print("ERROR: Missing email or password in config.yaml [librelinkup] section")
        sys.exit(1)

    print(f"Connecting to LibreLinkUp ({region})...")
    api_url = REGION_MAP.get(region.upper(), APIUrl.US)
    client = PyLibreLinkUp(email=email, password=password, api_url=api_url)
    try:
        client.authenticate()
    except RedirectError as e:
        print(f"Redirected to region {e.api_url}, re-authenticating...")
        client = PyLibreLinkUp(email=email, password=password, api_url=e.api_url)
        client.authenticate()

    print("✓ Authentication successful\n")

    patients = client.get_patients()
    if not patients:
        print("No patients found in your LibreLinkUp account.")
        sys.exit(0)

    print(f"Found {len(patients)} patient(s):\n")
    for patient in patients:
        name = f"{patient.first_name} {patient.last_name}"
        try:
            latest = client.latest(patient)
            if latest is None:
                print(f"  {name}: No data available")
                continue
            value = int(latest.value)
            arrow = latest.trend.indicator
            if latest.is_low:
                status = "LOW"
            elif latest.is_high:
                status = "HIGH"
            else:
                status = "NORMAL"
            print(f"  {name}: {value} mg/dL {arrow} [{status}]")
        except Exception as e:
            print(f"  {name}: ERROR — {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
