# Beginner Setup Guide

Follow the steps in order. The app is a Python project: you do **not** need
Node.js, npm, or a `node_modules` folder.

## Part 1: Install the two tools (one time)

### Install Python

1. On your Windows PC, go to [python.org/downloads](https://www.python.org/downloads/)
   and download Python 3.11 for Windows.
2. Open the downloaded installer.
3. Before clicking Install, tick **Add python.exe to PATH**.
4. Finish the installation.

### Install Git

1. Go to [git-scm.com/download/win](https://git-scm.com/download/win).
2. Download and install Git for Windows. The normal suggested installer choices
   are fine.

## Part 2: Download the project from GitHub

1. Open **Command Prompt**. To find it, open the Windows Start menu, type
   `Command Prompt`, then open it.
2. Copy and paste these commands, one line at a time:

   ```text
   cd %USERPROFILE%\Desktop
   git clone https://github.com/hemugithub6329/duplicate-media-finder.git
   cd duplicate-media-finder
   ```

   The `git clone` command downloads the project into a new folder on your
   Desktop. If you already have that folder, use a different place or rename
   the old folder before cloning.

## Part 3: Install the app's Python packages

In the same Command Prompt window, run:

```text
setup_dependencies.bat
```

Wait while Python creates the `venv` folder and installs packages. The first
time needs an internet connection. If Windows shows a security prompt, only
allow software you intentionally downloaded from this repository.

## Part 4: Start using the app

1. Open the `duplicate-media-finder` folder on your Desktop.
2. Double-click `launch_app.bat`.
3. Wait for the browser to open. If it does not open automatically, go to
   `http://localhost:8501`.
4. Choose a folder, press **Scan folder**, and review the results.
5. Before moving anything, check the selected files and confirm the move in
   the app. Moved files go into a timestamped `_duplicates_...` folder.

Keep the launcher window open while you use the app. Closing it stops the app.

## What is in this project?

- `app.py` displays the app in a browser and handles scan settings and results.
- `duplicate_core.py` scans folders, compares files, and moves selected files.
- `file_preview.py` displays previews for supported files.
- `tests\` contains automated checks for the scanning utilities.
- `requirements.txt` lists Python packages used by the app.
- `requirements-build.txt` adds the Windows executable builder.
- `build_windows.bat` creates a standalone Windows app folder.
- `launch_app.bat` starts the app from source.
- `launch_tray.bat` starts the system tray launcher from source.
- `start_web_server.bat` starts the app for browser access from a phone.

The project is Python; there are no Node packages or `node_modules` to install.

## Optional: create a standalone Windows app

This makes a Windows app folder that can run on a target Windows PC without
Python installed there. You still need Python on the computer that builds it.

1. Finish Parts 1–3 above.
2. In Command Prompt, make sure you are in the `duplicate-media-finder`
   project folder, then run:

   ```text
   venv\Scripts\python.exe -m pip install -r requirements-build.txt
   build_windows.bat
   ```

3. Wait for the build to finish.
4. Copy the complete `dist\DuplicateMediaFinder` folder to the other PC.
   Do not copy only `DuplicateMediaFinder.exe`; the folder contains the
   application files it needs.
5. On the other PC, open the folder and double-click
   `DuplicateMediaFinder.exe`.

Build again after updating the source if you want the executable to include
the latest changes. The executable is unsigned, and Windows Security may show a
warning. Review Protection History; do not turn off antivirus protection.

## Optional: open it from an Android phone

There is **no Android APK** in this project. The phone uses its web browser to
control the app running on the Windows PC.

1. Connect the phone and PC to the same trusted, private Wi-Fi network.
2. On the PC, double-click `start_web_server.bat` in the source folder.
   If you built the standalone app, you can instead double-click
   `StartMobile.bat` in `dist\DuplicateMediaFinder`.
3. The window prints one or more addresses. On the phone, open the address
   belonging to the shared Wi-Fi network, for example
   `http://192.168.1.25:8501`.
4. If Windows Firewall asks, allow access on a **private network** only.

The PC must stay on. The PC does the scanning and file moving; the phone is
only another screen. Do not share the server on public Wi-Fi or expose it to
the public internet.

## Run the tests (optional)

Open Command Prompt in the project folder and run:

```text
venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Get project updates later

Open Command Prompt, go into the downloaded project, and run:

```text
cd %USERPROFILE%\Desktop\duplicate-media-finder
git pull
```

If you edited project files yourself, save your work before updating. After an
update, run `setup_dependencies.bat` if package requirements changed. Rebuild
the standalone app if you use one.

## Troubleshooting

- **`git` is not recognized:** Install Git for Windows, close Command Prompt,
  open it again, then retry.
- **`python` or `py` is not recognized:** Install Python 3.11, select **Add
  python.exe to PATH**, and reopen Command Prompt.
- **The installer window closes or reports an error:** Open Command Prompt in
  the project folder and run `setup_dependencies.bat` there to see the error.
- **Streamlit is missing:** Run `setup_dependencies.bat` again from the
  project folder.
- **Port 8501 is already in use:** Close another copy of this app or another
  Streamlit app before starting this one.
- **The phone cannot connect:** Check that both devices are on the same
  private Wi-Fi, use the PC's Wi-Fi address, and allow private-network access
  in Windows Firewall.
- **The standalone app does not open:** Make sure you copied the whole
  `DuplicateMediaFinder` folder, not only the `.exe`.
