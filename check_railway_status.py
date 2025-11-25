#!/usr/bin/env python3
import requests
import sys

STATUS_URL = "https://status.railway.com/summary.json"

def check_railway_status():
    try:
        resp = requests.get(STATUS_URL, timeout=5)
        resp.raise_for_status()
        data = resp.json()

        page_status = data.get("page", {}).get("status", "UNKNOWN")
        active_incidents = data.get("activeIncidents", [])
        active_maintenance = data.get("activeMaintenances", [])

        print(f"Railway status: {page_status}")
        if active_incidents:
            print(f"⚠️ Active incidents: {len(active_incidents)}")
            for i, incident in enumerate(active_incidents, 1):
                print(f"  {i}. {incident.get('name')} - {incident.get('impact')}")

        if active_maintenance:
            print(f"🛠 Active maintenance: {len(active_maintenance)}")
            for i, maint in enumerate(active_maintenance, 1):
                print(f"  {i}. {maint.get('name')} - {maint.get('impact')}")

        # Exit with code 0 only if UP and no active incidents/maintenance
        if page_status.upper() == "UP" and not active_incidents and not active_maintenance:
            print("✅ Railway is fully operational")
            sys.exit(0)
        else:
            print("⚠️ Railway has issues, proceed with caution")
            sys.exit(1)

    except requests.RequestException as e:
        print(f"❌ Failed to reach Railway status API: {e}")
        sys.exit(2)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(3)

if __name__ == "__main__":
    check_railway_status()
