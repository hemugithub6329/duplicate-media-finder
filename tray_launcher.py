"""
System tray launcher for Duplicate Media Finder
Creates a system tray icon that can launch the Streamlit app
"""
import os
import sys
import subprocess
import threading
import webbrowser
from pathlib import Path

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    print("pystray or PIL not found. Please install: pip install pystray Pillow")
    sys.exit(1)


class TrayLauncher:
    def __init__(self, mobile_mode=False):
        self.streamlit_process = None
        self.mobile_mode = mobile_mode
        self.server_network = False
        self.app_dir = (
            Path(sys.executable).parent
            if getattr(sys, "frozen", False)
            else Path(__file__).parent.absolute()
        )
        self.resource_dir = Path(getattr(sys, "_MEIPASS", self.app_dir))
        self.icon_image = self.load_icon()

        # Create menu items
        self.menu = pystray.Menu(
            pystray.MenuItem("Open App", self.open_app),
            pystray.MenuItem("Start Server", self.start_server),
            pystray.MenuItem("Start Mobile Server", self.start_mobile_server),
            pystray.MenuItem("Stop Server", self.stop_server),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self.exit_app)
        )

        # Create the system tray icon
        self.icon = pystray.Icon("DuplicateMediaFinder", self.icon_image, "Duplicate Media Finder", self.menu)

    def load_icon(self):
        """Load the icon file for the system tray"""
        icon_path = self.resource_dir / "app_icon.ico"
        if icon_path.exists():
            return Image.open(icon_path)
        else:
            # Fallback: create a simple icon
            return self.create_fallback_icon()

    def create_fallback_icon(self):
        """Create a simple icon for the system tray"""
        # Create a simple image with a "D" for Duplicate
        image = Image.new('RGB', (64, 64), color='darkblue')
        draw = ImageDraw.Draw(image)
        draw.text((20, 10), "DM", fill='white')
        return image

    def open_app(self, icon, item):
        """Open the Streamlit app in browser"""
        if self.streamlit_process and self.streamlit_process.poll() is None:
            # Server is running, open browser
            webbrowser.open('http://localhost:8501')
        else:
            # Start server and open browser
            self.start_server(icon, item)
            threading.Timer(2.0, lambda: webbrowser.open('http://localhost:8501')).start()

    def start_server(self, icon, item, network=False):
        """Start the Streamlit server"""
        if self.streamlit_process and self.streamlit_process.poll() is None:
            if not network or self.server_network:
                print("Streamlit server is already running")
                return
            self.stop_server(icon, item)

        try:
            if getattr(sys, "frozen", False):
                command = [
                    sys.executable,
                    "--server-network" if network else "--server",
                ]
            elif os.name == "nt":
                venv_python = self.app_dir / "venv" / "Scripts" / "python.exe"
                command = [
                    str(venv_python),
                    "-m",
                    "streamlit",
                    "run",
                    str(self.app_dir / "app.py"),
                    f"--server.address={'0.0.0.0' if network else '127.0.0.1'}",
                    "--server.headless=true",
                ]
            else:
                venv_python = self.app_dir / "venv" / "bin" / "python"
                command = [
                    str(venv_python),
                    "-m",
                    "streamlit",
                    "run",
                    str(self.app_dir / "app.py"),
                    f"--server.address={'0.0.0.0' if network else '127.0.0.1'}",
                    "--server.headless=true",
                ]

            if (
                not getattr(sys, "frozen", False)
                and not venv_python.exists()
            ):
                print(f"Virtual environment not found at {venv_python}")
                return

            self.streamlit_process = subprocess.Popen(
                command,
                cwd=self.app_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.server_network = network
            print("Streamlit server started")

        except Exception as e:
            print(f"Error starting server: {e}")

    def start_mobile_server(self, icon, item):
        """Start the server so other devices on the local network can connect."""
        self.start_server(icon, item, network=True)

    def stop_server(self, icon, item):
        """Stop the Streamlit server"""
        if self.streamlit_process:
            self.streamlit_process.terminate()
            try:
                self.streamlit_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.streamlit_process.kill()
            self.server_network = False
            print("Streamlit server stopped")

    def exit_app(self, icon, item):
        """Exit the tray application"""
        self.stop_server(icon, item)
        icon.stop()

    def run(self):
        """Run the tray application"""
        # Auto-start server when tray launches
        self.start_server(None, None, network=self.mobile_mode)

        # Run the system tray icon
        self.icon.run()


if __name__ == "__main__":
    if "--server" in sys.argv or "--server-network" in sys.argv:
        from streamlit.web import cli

        bundled = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
        app_script = bundled / "app.py"
        address = "0.0.0.0" if "--server-network" in sys.argv else "127.0.0.1"
        extra_args = [
            arg for arg in sys.argv[1:] if arg.startswith("--server.port=")
        ]
        cli.main(
            args=[
                "run",
                str(app_script),
                f"--server.address={address}",
                "--server.headless=true",
                "--global.developmentMode=false",
                "--browser.gatherUsageStats=false",
                *extra_args,
            ],
            prog_name="streamlit",
            standalone_mode=False,
        )
    else:
        app = TrayLauncher(mobile_mode="--mobile" in sys.argv)
        app.run()