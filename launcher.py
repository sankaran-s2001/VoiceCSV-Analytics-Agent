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
    port = settings.port
    app_url = f"http://{host}:{port}"

    print("=" * 60)
    print("      VoiceCSV Analytics Agent - AI Business Intelligence      ")
    print("=" * 60)
    print(f"Target URL: {app_url}")
    print(f"Gemini Configured: {'Yes (' + settings.gemini_model + ')' if settings.is_gemini_configured else 'No (set GOOGLE_API_KEY in .env)'}")
    print(f"Database Path: {settings.resolved_db_path}")
    print("=" * 60)

    # Check for port conflict
    if is_port_in_use(host, port):
        # Check if it's already VoiceCSV running
        try:
            with urlopen(f"{app_url}/api/health", timeout=1.5) as res:
                if res.status == 200:
                    print(f"\nVoiceCSV is already running on {app_url}!")
                    webbrowser.open(app_url)
                    return
        except Exception:
            pass
        print(f"\n[ERROR] Port {port} on {host} is already in use by another application.")
        print("Please terminate that application or change PORT in .env.")
        sys.exit(1)

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
            port=port,
            log_level="info",
            access_log=True
        )
        server = uvicorn.Server(config)
        server.run()
    except KeyboardInterrupt:
        print("\nStopping VoiceCSV Analytics Agent server... Done.")
    except Exception as e:
        logger.error("Failed to run server: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
