"""
daily_report_bot.py

A PyAutoGUI-driven desktop bot that prepares a daily status report by
physically controlling the mouse/keyboard, exactly like a human operator:

    1. Opens Chrome and navigates to a public stock-quote page (TSLA on Nasdaq).
    2. Selects and copies the page text, then extracts the stock price.
    3. Opens Notepad and types a new line: timestamp, price, comment.
    4. Saves the text file as daily_report_<YYYY-MM-DD>.txt.
    5. Takes a screenshot of the final Notepad window and saves it as a PNG.

Only PyAutoGUI (+ pyperclip for clipboard access, pygetwindow for window
focus, and the standard library) is used to drive the UI. No file is ever
written programmatically - everything on-screen is produced via simulated
keystrokes/mouse actions, as required.

Run this on a Windows machine that has Google Chrome and Notepad available
(Notepad ships with Windows). Keep your hands off the mouse/keyboard while
it runs, and do not let other windows steal focus. Moving the mouse to a
screen corner will trigger PyAutoGUI's fail-safe and abort the script.
"""

import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime

import pyautogui
import pyperclip
import pyscreeze

try:
    import pygetwindow as gw
except ImportError:  # pragma: no cover - pygetwindow is optional at runtime
    gw = None


# --------------------------------------------------------------------------
# Configuration - adjust these if your environment differs.
# --------------------------------------------------------------------------
STOCK_URL = "https://www.nasdaq.com/market-activity/stocks/tsla"
STOCK_TICKER = "TSLA"
REPORT_COMMENT = "Checked TSLA stock price for daily tracking"

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]
NOTEPAD_PATHS = [
    r"C:\Windows\System32\notepad.exe",
    r"C:\Windows\notepad.exe",
]

# Generous pauses so slow app/page loads don't derail the automation.
PAGE_LOAD_WAIT = 8
APP_LAUNCH_WAIT = 6
SHORT_WAIT = 1.5

# Give PyAutoGUI a small natural delay between actions and keep the
# corner-of-screen fail-safe enabled (move mouse to a corner to abort).
pyautogui.PAUSE = 0.4
pyautogui.FAILSAFE = True


def find_executable(candidates):
    """Return the first existing path from a list of candidate locations."""
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def focus_window(title_substring, timeout=10):
    """Best-effort: bring the first window whose title contains the given
    substring to the foreground. Silently does nothing if pygetwindow is
    unavailable or no matching window is found - the caller should still
    rely on generous wait times as a fallback.
    """
    if gw is None:
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        matches = [w for w in gw.getAllWindows() if title_substring.lower() in w.title.lower() and w.title.strip()]
        if matches:
            win = matches[0]
            try:
                if win.isMinimized:
                    win.restore()
                win.activate()
            except Exception:
                pass
            return
        time.sleep(0.5)


def open_chrome_and_get_stock_price(url, ticker):
    """Launch Chrome pointed at `url`, copy the visible page text, and
    extract a stock price near the ticker symbol. Returns a price string
    such as "248.50", or "N/A" if nothing could be parsed.
    """
    print(f"[1/5] Opening Chrome -> {url}")
    chrome_path = find_executable(CHROME_PATHS)
    if not chrome_path:
        raise FileNotFoundError("Could not locate chrome.exe. Update CHROME_PATHS.")

    # Launch with a clean temporary profile + maximized window so the page
    # layout (and therefore our click coordinates) is predictable, and so
    # existing browser state (extensions, saved logins, open tabs) can't
    # introduce unexpected popups.
    temp_profile = tempfile.mkdtemp(prefix="daily_report_bot_chrome_")
    subprocess.Popen([
        chrome_path,
        f"--user-data-dir={temp_profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-notifications",
        "--start-maximized",
        "--new-window",
        url,
    ])

    time.sleep(APP_LAUNCH_WAIT)
    focus_window("Chrome")
    time.sleep(PAGE_LOAD_WAIT)

    # Click into the middle of the page (below the toolbar) so keyboard
    # focus is on the page content, not the address bar, then select all
    # visible text and copy it to the clipboard.
    width, height = pyautogui.size()
    pyautogui.click(width // 2, height // 2)
    time.sleep(SHORT_WAIT)
    pyautogui.hotkey("ctrl", "a")
    time.sleep(SHORT_WAIT)
    pyautogui.hotkey("ctrl", "c")
    time.sleep(SHORT_WAIT)

    page_text = pyperclip.paste()
    price = extract_price(page_text, ticker)
    print(f"    Extracted price for {ticker}: {price}")

    # Close this Chrome instance (and its temp profile window); we're done
    # with the browser for this run.
    pyautogui.hotkey("ctrl", "w")
    time.sleep(SHORT_WAIT)
    return price


def extract_price(page_text, ticker):
    """Pull a dollar-amount stock price out of copied page text.

    Strategy: look for a "$123.45"-style amount that appears reasonably
    close to the ticker symbol (the quote pages we target show the current
    price right next to/near the ticker). Fall back to the first dollar
    amount found anywhere on the page if that search comes up empty.
    """
    near_ticker = re.search(
        rf"{re.escape(ticker)}.{{0,400}}?\$([\d,]+\.\d{{2}})",
        page_text,
        re.IGNORECASE | re.DOTALL,
    )
    if near_ticker:
        return near_ticker.group(1)

    anywhere = re.search(r"\$([\d,]+\.\d{2})", page_text)
    if anywhere:
        return anywhere.group(1)

    return "N/A"


def fill_and_save_notepad_report(timestamp_str, price, comment, date_str):
    """Launch Notepad, type the header + data line, and save the text file
    as daily_report_<date_str>.txt in OUTPUT_DIR. Returns the saved file path.
    """
    print("[2/5] Opening Notepad")
    notepad_path = find_executable(NOTEPAD_PATHS)
    if not notepad_path:
        raise FileNotFoundError("Could not locate notepad.exe. Update NOTEPAD_PATHS.")

    subprocess.Popen([notepad_path])
    time.sleep(APP_LAUNCH_WAIT)
    focus_window("Notepad")
    time.sleep(SHORT_WAIT)

    print("[3/5] Typing header + data line")
    # Header line, comma-separated.
    header_line = f"Date & Time, Stock Price ({STOCK_TICKER}), Comment"
    pyautogui.typewrite(header_line, interval=0.02)
    pyautogui.press("enter")
    time.sleep(SHORT_WAIT)

    # Data line, comma-separated: timestamp, price, comment.
    data_line = f"{timestamp_str}, {price}, {comment}"
    pyautogui.typewrite(data_line, interval=0.02)
    time.sleep(SHORT_WAIT)

    print("[4/5] Saving text file")
    filename = f"daily_report_{date_str}.txt"
    full_path = os.path.join(OUTPUT_DIR, filename)

    # Ctrl+S opens the "Save As" dialog for a not-yet-saved Notepad document.
    pyautogui.hotkey("ctrl", "s")
    time.sleep(SHORT_WAIT * 2)
    pyautogui.hotkey("ctrl", "a")  # select any existing text in the filename box
    pyautogui.typewrite(full_path, interval=0.02)
    time.sleep(SHORT_WAIT)
    pyautogui.press("enter")
    time.sleep(SHORT_WAIT * 2)
    # If a "confirm overwrite" prompt appears (re-running the bot same day),
    # Enter accepts the default "Yes" option.
    pyautogui.press("enter")
    time.sleep(SHORT_WAIT * 2)

    # Confirm the save actually landed on disk before moving on; poll
    # briefly rather than trusting a fixed pause.
    deadline = time.time() + 15
    while time.time() < deadline and not os.path.isfile(full_path):
        time.sleep(0.5)
    if not os.path.isfile(full_path):
        print("    Warning: text file not found on disk yet; it may still be saving.")

    return full_path


def take_screenshot(date_str):
    """Capture the full screen (showing the final Notepad window) and save
    it as a PNG alongside the text file. Returns the saved screenshot path.
    """
    print("[5/5] Taking screenshot of the final Notepad window")
    screenshot_path = os.path.join(OUTPUT_DIR, f"daily_report_{date_str}_screenshot.png")
    time.sleep(SHORT_WAIT)
    screenshot = pyautogui.screenshot()
    screenshot.save(screenshot_path)
    return screenshot_path


def main():
    now = datetime.now()
    timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
    date_str = now.strftime("%Y-%m-%d")

    try:
        price = open_chrome_and_get_stock_price(STOCK_URL, STOCK_TICKER)
        report_path = fill_and_save_notepad_report(timestamp_str, price, REPORT_COMMENT, date_str)
        screenshot_path = take_screenshot(date_str)
    except Exception as exc:
        print(f"Bot failed: {exc}", file=sys.stderr)
        raise

    print("\nDone.")
    print(f"  Timestamp : {timestamp_str}")
    print(f"  Price     : {price}")
    print(f"  Comment   : {REPORT_COMMENT}")
    print(f"  Text file : {report_path}")
    print(f"  Screenshot: {screenshot_path}")


if __name__ == "__main__":
    main()
