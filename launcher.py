"""Launcher supervisor for VoiceCSV Analytics Agent.

Checks environment, starts the Uvicorn server, polls health readiness,
opens the default web browser, and handles clean Ctrl+C shutdown.
"""

import sys
import time
import socket
import logging
import threading
import webbrowser
from urllib.request import urlopen, Request
from urllib.error import URLError

import uvicorn
from backend.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("VoiceCSV-Launcher")


def is_port_in_use(host: str, port: int) -> bool:
    """Check if the target port is already bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) == 0


def find_available_port(host: str, starting_port: int, max_attempts: int = 20) -> int:
    """Find starting_port or the next available open port."""
    for p in range(starting_port, starting_port + max_attempts):
        if not is_port_in_use(host, p):
            return p
    return starting_port


def wait_for_server_and_open_browser(url: str, timeout: int = 25):
    """Poll health endpoint until server is ready, then launch browser."""
    health_url = f"{url}/api/health"
    start_time = time.time()
    logger.info("Waiting for VoiceCSV server to become ready at %s...", url)

    while time.time() - start_time < timeout:
        try:
            req = Request(health_url, headers={"User-Agent": "VoiceCSV-Launcher"})
            with urlopen(req, timeout=2) as response:
                if response.status == 200:
                    logger.info("Server is ready! Opening dashboard in your default browser...")
                    time.sleep(0.5)
                    webbrowser.open(url)
                    return
        except URLError:
            pass
        except Exception as e:
            logger.debug("Health poll notice: %s", e)
        time.sleep(0.5)

    logger.warning("Server took longer than %s seconds to report healthy. You can manually visit: %s", timeout, url)


def main():
    host = settings.host
    target_port = settings.port
    app_url = f"http://{host}:{target_port}"

    # Check for port conflict
    active_port = target_port
    if is_port_in_use(host, target_port):
        # Check if VoiceCSV is already running on this port
        try:
            with urlopen(f"{app_url}/api/health", timeout=1.5) as res:
                if res.status == 200:
                    print("=" * 60)
                    print(f"[*] VoiceCSV is already running on {app_url}!")
                    print("[*] Opening dashboard in your default browser...")
                    print("=" * 60)
                    webbrowser.open(app_url)
                    return
        except Exception:
            pass

        print(f"\n[NOTICE] Port {target_port} on {host} is currently in use by another program.")
        fallback_port = find_available_port(host, target_port + 1)
        if fallback_port != target_port and not is_port_in_use(host, fallback_port):
            print(f"[*] Automatically switching to available open port: {fallback_port}")
            active_port = fallback_port
            app_url = f"http://{host}:{active_port}"
        else:
            print(f"\n[ERROR] Port {target_port} is in use and no alternative port was found.")
            print("Please terminate the conflicting application or change PORT in .env.")
            sys.exit(1)

    print("=" * 60)
    print("      VoiceCSV Analytics Agent - AI Business Intelligence      ")
    print("=" * 60)
    print(f"Target URL:        {app_url}")
    print(f"Gemini Configured: {'Yes (' + settings.gemini_model + ')' if settings.is_gemini_configured else 'No (set GOOGLE_API_KEY in .env)'}")
    print(f"Database Path:     {settings.resolved_db_path}")
    print("=" * 60)

    # Start browser opener in background daemon thread
    browser_thread = threading.Thread(
        target=wait_for_server_and_open_browser,
        args=(app_url,),
        daemon=True
    )
    browser_thread.start()

    # Run Uvicorn server in foreground
    try:
        config = uvicorn.Config(
            app="backend.main:app",
            host=host,
            port=active_port,
            log_level="info",
            access_log=True
        )
        server = uvicorn.Server(config)
        server.run()
    except KeyboardInterrupt:
        print("\n[*] Stopping VoiceCSV Analytics Agent server... Done.")
    except Exception as e:
        logger.error("Failed to run server: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
