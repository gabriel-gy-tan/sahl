# Demo run-sheet

Everything on screen is invented: the documents, the person and the portal. Nothing is sent or submitted.

## Before you go on

1. Quit your own Sahl (menu bar), so the demo one is the only one running.
2. `sh demo/pitch.sh reset` starts Sahl on a clean demo vault with one invented resident (passport and Emirates ID),
   and serves the sample portal. Use `sh demo/pitch.sh reset dev` to run it from the checkout instead of
   `/Applications/Sahl.app`.
3. The Documents page shows Mohammed Rafeeq Kunnummal with a passport and an Emirates ID, read in a few seconds and
   confirmed by their check digits, with no AI model needed.
4. In Chrome, open `http://127.0.0.1:8077/refund-portal.html`, open the Sahl extension and pair it once
   (Settings → Browser extension shows the code). Pairing is per browser, so do it before the pitch.
5. If the Arabic name should be filled, the local text model has to be downloaded already (Settings → General).
6. Reload the portal page so it starts empty.

## On stage (about 90 seconds)

1. **The problem.** Scroll the portal: 20 boxes, half of them copied from a passport and an Emirates ID, in two
   languages, with a bank form inside it.
2. **One click.** Open the extension. It reads the page, the frame included, in under a second. "Ready to fill" lists
   what it can fill from the documents; "New boxes" lists what it doesn't know yet, numbered on the page.
3. **Fill.** Press *Fill selected*. Watch the boxes tick one after another: the name in English and in Arabic, the date
   of birth across three menus, the nationality in the searchable menu, the passport, its expiry, the Emirates ID.
4. **It knows what isn't yours.** Point at *Father's name*, *Sponsor name* and *Account owner name*: Sahl left them
   empty and asks, because they are about someone else.
5. **It never crosses the line.** Point at the password, the SMS code, the declaration tick and *Submit*: Sahl never
   types a password or a code, never ticks a declaration and never presses Submit.
6. **It learns.** Tell it the IBAN once (open *IBAN*, type it, *Remember*). Read again: IBAN is now in "Ready to fill",
   and it will be on every form that asks for it.
7. **Private by design.** Everything ran on this laptop: reading the documents, matching the boxes, the Arabic name.
   Turn the Wi-Fi off and do it again if there is time.

## If something goes wrong

- The extension says Sahl isn't running: check that only one Sahl is open, then *Try again*.
- A box isn't filled: *Read again*, then *Fill selected*. Boxes that already hold a value are left alone unless
  *Replace values already in the boxes* is ticked.
- Start over: `sh demo/pitch.sh reset`.
