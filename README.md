# Duplicate & Similar Media Finder

A Windows-friendly Python app that scans folders for exact duplicate files,
visually similar images and videos, and documents with matching text. It shows
the results in a browser and moves selected files into a separate folder
instead of permanently deleting them.

> **New here?** Follow [the beginner setup guide](DESKTOP_APP_SETUP.md). You do
> not need Node.js or `node_modules`; this project uses Python.

> **Just want the ready-to-run Windows app?** Open the repository's
> [Releases page](https://github.com/hemugithub6329/duplicate-media-finder/releases/latest),
> download `DuplicateMediaFinder-Windows.zip`, extract the whole ZIP folder,
> then double-click `DuplicateMediaFinder.exe`. Python is not needed on the
> computer running the released app.

## What it can do

- Find exact duplicates of any file type using SHA-256.
- Group visually similar photos using pHash and dHash.
- Optionally group similar videos by comparing sampled keyframes.
- Group PDF, DOCX, TXT, RTF, Markdown, and CSV files when their extracted text
  matches. Scanned PDFs without selectable text and legacy Office formats
  cannot be compared this way.
- Preview files, inspect a scan summary, and download a JSON report.
- Cache scan results to speed up later scans.
- Move selected files to a timestamped `_duplicates_...` folder. Files are not
  intentionally permanently deleted.

The app runs on the computer that starts it. Scanning and moving files happen
on that computer, even when you view the page from a phone.

## Run on Windows from GitHub

1. Install **Python 3.11** from [python.org](https://www.python.org/downloads/).
   In the installer, select **Add python.exe to PATH**.
2. Install **Git for Windows** from [git-scm.com](https://git-scm.com/download/win).
3. Open **Command Prompt** or **PowerShell** and copy/paste:

   ```text
   git clone https://github.com/hemugithub6329/duplicate-media-finder.git
   cd duplicate-media-finder
   setup_dependencies.bat
   ```

   Wait until the setup window says it is done. It creates a local `venv`
   folder and installs the packages from `requirements.txt`.
4. Start the app by double-clicking `launch_app.bat` in the project folder.
   The app opens in your browser at `http://localhost:8501`.

You can also start it from that folder in a terminal:

```text
venv\Scripts\python.exe -m streamlit run app.py
```

The first setup needs an internet connection to download Python packages.
Normal scans use folders on the computer running the app.

## Make a Windows app folder that does not need Python on the target PC

Python is still required on the computer that builds the app:

1. Complete the Windows setup above.
2. In the project folder, run:

   ```text
   venv\Scripts\python.exe -m pip install -r requirements-build.txt
   ```
3. Double-click `build_windows.bat` and wait for it to finish.
4. Copy the **entire** `dist\DuplicateMediaFinder` folder to the target Windows
   computer. Do not copy only the `.exe`.
5. Double-click `DuplicateMediaFinder.exe` in that folder.

The generated build is not committed to this source repository. New Windows
builds are published on the [GitHub Releases page](https://github.com/hemugithub6329/duplicate-media-finder/releases)
when a project version is released. Rebuild after source changes to include the
newer code. Windows may warn about an unsigned executable; review any warning
in Windows Security and do not disable antivirus protection.

## Open the app on an Android phone

This project does **not** contain a native Android app or APK. Use the phone's
browser to connect to the Windows app over the same private Wi-Fi:

1. Start the app on the Windows PC.
2. For the source project, double-click `start_web_server.bat`. For the
   packaged build, double-click `StartMobile.bat` in the app folder.
3. On the phone, open the PC's Wi-Fi address printed by the launcher, for
   example `http://192.168.1.25:8501`.
4. If Windows asks, allow access on a **private network** only.

Keep the PC on while using the phone. Do not expose this server to the public
internet or a network you do not trust.

## Run tests

After running `setup_dependencies.bat`, run this from the project folder:

```text
venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Project files

- `app.py` — Streamlit interface, settings, results, previews, reports, and
  move confirmation.
- `duplicate_core.py` — folder indexing, hashes, grouping, cache, reports,
  thumbnails, and file moves.
- `file_preview.py` — inline previews and OS file opening.
- `tray_launcher.py` — system tray launcher used by the standalone build.
- `tests\` — automated tests.
- `requirements.txt` — runtime Python packages.
- `requirements-build.txt` — runtime packages plus PyInstaller for Windows
  builds.
- `*.bat` — Windows setup and launch scripts.

## Troubleshooting

- **`python` or `py` is not recognized:** Install Python 3.11 and select
  **Add python.exe to PATH**, then close and reopen the terminal.
- **The app says Streamlit is missing:** Run `setup_dependencies.bat` again
  from the project folder.
- **The browser page does not load:** Keep the launcher window running and
  check whether another app is already using port 8501.
- **The phone cannot connect:** Confirm both devices are on the same private
  Wi-Fi, use the PC's Wi-Fi address, and allow private-network access in
  Windows Firewall.
- **A packaged app does not start:** Copy the complete
  `dist\DuplicateMediaFinder` folder, not only the executable.

See [DESKTOP_APP_SETUP.md](DESKTOP_APP_SETUP.md) for additional build and
mobile-access details.
