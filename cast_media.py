"""Simple script to attempt casting media to a Vizio device using pyvizio.

This script offers two approaches:
 - If you know an app's APP_ID and namespace that accepts a launch message (e.g. some streaming apps), use --app-id and --namespace to call launch_app_config(APP_ID, NAMESPACE, MESSAGE)
 - Otherwise, try to launch a known app by name via launch_app(app_name) (may not accept a direct media URL)

Usage examples:
  python cast_media.py --ip 192.168.1.55:9000 --auth ABCDEF --device-type tv --app-id com.example.app --namespace 0 --media-url "https://example.com/video.mp4"
  python cast_media.py --ip 192.168.1.55 --auth ABCDEF --device-type tv --app-name "YouTube" --media-url "https://youtu.be/xyz"

Notes:
 - Many SmartCast apps require app-specific message formats; this script can't guarantee playback for every app.
 - For DLNA/UPnP casting you may need a dedicated DLNA renderer client library; pyvizio does not currently implement a full DLNA renderer.
"""

import argparse
import sys
from pyvizio import Vizio


def main():
    p = argparse.ArgumentParser(description="Cast media URL to a Vizio device using pyvizio")
    p.add_argument("--ip", required=True, help="IP[:PORT] of the device")
    p.add_argument("--auth", default="", help="Auth token (if required)")
    p.add_argument("--device-type", default="tv", help="device type: tv, speaker, crave360")
    p.add_argument("--media-url", required=True, help="HTTP(S) URL to audio/video to attempt to play on device")
    p.add_argument("--app-id", help="Optional app APP_ID to use with launch_app_config")
    p.add_argument("--namespace", type=int, default=0, help="Optional namespace integer for launch_app_config (default 0)")
    p.add_argument("--app-name", help="Optional app name to launch (fallback)")

    args = p.parse_args()

    try:
        viz = Vizio("cast-script", args.ip, "cast-script", args.auth or "", args.device_type)
    except Exception as e:
        print(f"Failed to create Vizio instance: {e}")
        sys.exit(1)

    # Try app_id + namespace path first
    if args.app_id:
        try:
            res = viz.launch_app_config(args.app_id, args.namespace, args.media_url)
            print(f"launch_app_config({args.app_id}, {args.namespace}, message) -> {res}")
            return
        except Exception as e:
            print(f"launch_app_config failed: {e}")

    # Fallback: try launching app by name then optionally send message via launch_app_config if app_id known
    if args.app_name:
        try:
            res = viz.launch_app(args.app_name)
            print(f"launch_app({args.app_name}) -> {res}")
        except Exception as e:
            print(f"launch_app failed: {e}")

    print("If playback did not start, the target app may not accept direct URL launch messages or may require a different message format.")
    print("For more robust casting (DLNA/UPnP), consider using a dedicated DLNA client library or inspect the target app's expected launch payload.")


if __name__ == '__main__':
    main()
