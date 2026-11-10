# Sahl privacy policy

Effective: 2026-11-10

Sahl is a desktop app and a Chrome extension ("Sahl browser companion") that help you fill in forms. Your documents and details stay on your computer. There are no Sahl servers, accounts, analytics or ads.

## What the app keeps

- Documents are read on your computer, with local text recognition and local AI. Files you add are copied to `~/Documents/Sahl`, unless you pick your own folder.
- What Sahl reads from them (with a small image of where each value came from), your corrections, and details you tell it are stored in a local SQLite file, `vault.db`, in Sahl's folder: `~/Library/Application Support/Sahl` on macOS, `%APPDATA%\Sahl` on Windows. Settings, the pairing token and AI models are kept there too.
- To read a form on screen, the app takes a screenshot when you ask. It is not saved.

## What the extension reads

Only when you open the Sahl popup on a tab, it reads the form on that page and its frames:

- each box's label, name, placeholder, type, autocomplete hint and position;
- the choices in menus and radio groups, and which menu choice is selected;
- the page title, up to ten headings, and the page address without its query string or fragment.

It does not send what is already typed in the boxes. It never reads or fills password, PIN, one-time code or card security code boxes, nor hidden, file or button elements.

## Where the extension sends it

Only to the Sahl app on the same computer, at `127.0.0.1` on a port from 8765 to 8774. Nothing goes anywhere else.

You pair the extension once, with a six-digit, one-time code shown in the app's Settings. Before each request the app must prove it holds the same pairing token, by signing a random challenge; only then does the extension send the token and page details. The app keeps page details in memory until the next read and does not save them.

The app returns values for the boxes you choose, and the extension types them in. A detail you type into the popup for an unknown box is saved in the vault, with the box's label, for next time.

Sahl never submits a form and never ticks a checkbox. You check and submit.

## What the extension stores

In `chrome.storage.local`, on your computer:

- `token`: the pairing token;
- `declined`: your "No, it's different" answers (box label and the suggestion you turned down, the latest 200).

## Network use

Sahl connects to nothing outside your computer, except:

- **AI model download.** Only after you agree, Sahl downloads model files from Hugging Face and checks each against the SHA-256 hash Hugging Face gives. Nothing about you is sent.
- **Dictation.** The mic button hands over to your operating system's own dictation (macOS Dictation, Windows Voice Typing). Sahl never handles the audio. For some languages, Apple or Microsoft may process the speech on their servers.

No analytics, tracking, crash reports, ads or accounts. We never receive your data, so we never sell or share it.

## Help improve Sahl

Off unless you turn it on (Settings, Privacy & reports). When on, Sahl saves a short report per form in Sahl's `reports` folder: which boxes it found or missed, the labels it matched, short unrecognised labels (never with digits or your values) and box positions. Never your details. Sahl sends nothing; you choose whether to share a report.

## Deleting your data

- **Settings, Documents, Forget all** deletes every reading, person and told detail, and moves Sahl's copies of your documents to the Trash or Recycle Bin. A folder you chose yourself is left alone.
- **Settings, Browser extension, Unpair** cuts off every paired browser.
- **Removing the extension** deletes its stored token and answers.
- **Deleting Sahl's folder** and documents folder after uninstalling removes everything else, including models and reports.

## Chrome Web Store Limited Use

The use of information received from Chrome APIs adheres to the Chrome Web Store User Data Policy, including the Limited Use requirements. Page information is used only to fill the form you are on, goes only to the Sahl app on your computer, and is never used for ads or read by people.

## Children

Sahl is not directed at children under 13 and collects nothing from anyone. Documents a parent adds for a child stay on the computer like any others.

## Changes

Changes are made in this file in the Sahl repository, with a new effective date.

## Contact

Open an issue at <https://github.com/gabriel-gy-tan/sahl/issues>. Please leave personal details out.
