# The paid app: plan

Goal: players download a Windows app with a window (not a console) after
they pay for a subscription. Decided by Castien on 2026-11-06: **$2.50 a
month or $25 a year, through Lemon Squeezy**, no website yet (Lemon
Squeezy's hosted store page is the shop).

## Pieces, in build order

1. **App window** (done): a local web page (`coach/ui/`) in Windows' own
   WebView2 through pywebview (`coach/app_web.py`), opened by
   `Dota 2 Live Coach.exe` or `py -m coach app`. Dashboard (start/stop,
   Dota status, live feed), Reminders (every reminder as a switch, its
   timings editable, beginner/experienced), Voice & questions, Game &
   profile, Licence. Python side: `coach/app_api.py`; what each option means
   and how it is saved: `coach/options.py`. The coach runs as its own process
   (`coach/app.py`), unchanged. `coach/app_window.py` (tkinter) is the
   fallback when pywebview isn't installed.
2. **Installer** (done in this PR): `packaging/installer.iss` (Inno Setup)
   turns the `DotaCoach` folder into `DotaCoachSetup.exe`: per-user install
   (no admin prompt), Start menu and optional desktop shortcut to the app
   window, uninstaller, and it writes Dota's GSI file during setup. Built by
   the "windows app" GitHub Action as the **DotaCoachSetup** download.
3. **Licence key gate** (built: `coach/license.py`, the Licence page and a
   lock screen; off until `STORE_ID`, `PRODUCT_ID` and `STORE_URL` are filled
   in): on first start the window asks for the key from the
   Lemon Squeezy receipt email, activates it with Lemon Squeezy's License API
   (`/v1/licenses/activate`, one PC per key by default), then validates it at
   most once a day. Offline it keeps working for 7 days after the last good
   check. A cancelled or unpaid subscription disables the key, and the app
   shows a "renew" link to the store. No accounts, no server of our own.
4. **Downloads**: the installer is uploaded to both Lemon Squeezy products as
   the paid file, so only buyers get it. Updates: GitHub Releases on a
   private repo is not reachable by buyers, so the app checks Lemon Squeezy's
   file (or a small public version file) and links to the download.
5. **Code signing** before public sale, so Windows SmartScreen doesn't warn.

## What Castien sets up in Lemon Squeezy (about 20 minutes)

1. Sign up at lemonsqueezy.com and create a store (it gives a free
   `yourstore.lemonsqueezy.com` page).
2. Create one product, "Dota 2 Live Coach", with two subscription variants:
   $2.50 monthly and $25 yearly.
3. On the product, turn on **License keys** (activation limit 1 or 2,
   no expiry: the key follows the subscription).
4. Add the installer as the product's file once the installer PR is merged.
5. Complete identity and payout verification so the store can go live.

The app needs only the public License API (no secret key in the app), plus
the store and product ids to make sure a key belongs to this product.
