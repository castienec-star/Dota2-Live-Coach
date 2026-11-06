# The paid app: plan

Goal: players download a Windows app with a window (not a console) after
they pay for a subscription. Decided by Castien on 2026-11-06: **$2.50 a
month or $25 a year, through Lemon Squeezy**, no website yet (Lemon
Squeezy's hosted store page is the shop).

## Pieces, in build order

1. **App window** (done in this PR): `coach/app_window.py`, opened by
   `Dota 2 Live Coach.exe` or `py -m coach app`. Start/Stop, a "Dota
   connected" light, what the coach said, and buttons for settings, Dota
   setup and match reviews. The coach runs as its own process
   (`coach/app.py`), unchanged.
2. **Installer**: Inno Setup script that turns the `DotaCoach` folder into
   `DotaCoachSetup.exe` (Start menu and desktop shortcut to the app window,
   uninstaller), built by the existing GitHub Action.
3. **Licence key gate**: on first start the window asks for the key from the
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
