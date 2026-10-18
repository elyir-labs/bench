# A new printer's first Wi-Fi

A printer that has never been on a network gets there from its own screen, with or without a phone. The design
is `design/setup/`, direction C (picked 4 October 2026): both ways from the first screen, the printer is never the
only place to pick the Wi-Fi, and both ways meet while it joins.

## What a person sees

1. **The panel offers two ways**, side by side. *With your phone*: a QR code (the Wi-Fi sign in its middle) that
   the phone's camera turns into "Join network?". *Without one*: Set up here, a list of the networks the printer
   hears and a keyboard.
2. **With a phone**, joining the printer's setup Wi-Fi opens the phone page by itself (the "sign in to this
   network" sheet). It asks which network and its password, then says the printer is joining and the rest is on
   the printer's screen. The phone drops the setup Wi-Fi when the printer switches.
3. **While it joins** (about 20 seconds), the panel asks the printer's name: a tap on Workshop, Studio, Desk,
   Garage, Office, or Another name… with the keyboard.
4. **Connected**: a green check, then the phone code inside a drawing of a phone (the eye in its middle). With a
   door, that's today's pairing (Add a phone), and a phone asking to connect is answered right there. Without
   one, it's the printer's own address at home (`http://workshop.local:8088/`). Done (or Skip for now) hands over
   to the app.
5. **A wrong password** brings the setup Wi-Fi back with the same code, and the panel says what went wrong: Type
   it here instead, or Another network.

Steps across the top say where you are: Wi-Fi, Name, Phone.

## When it happens

Only when the printer has no network: no Wi-Fi saved in NetworkManager, no cable, no default route by any other
means, and a Wi-Fi chip NetworkManager manages and isn't using. A card written with Wi-Fi in Raspberry Pi Imager,
or a cable, skips all of it. Once set up (`done`), it never opens again by itself.

After a restart part-way through, it picks up where it was: once joined, the panel still has the name and the
phone to do.

## How it works

`setup/wifi_setup.py`, standard library only, runs as the printer's user (`elyir-bench-wifi.service`) and listens on
`127.0.0.1:8097`.

- **Look, then open.** One Wi-Fi chip can't easily look around while it's a hotspot, so the printer lists the
  networks first, then opens **Elyir Bench XXXX** (the end of its serial number), WPA2 with CCMP only (what phones
  join reliably on the Pi's chip), at `10.42.0.1`, NetworkManager's shared mode handing out addresses. Look again
  closes it for a few seconds.
- **The password is only in the QR code.** Random, three groups of four from letters and digits that can't be
  misread. Standing at the printer is the permission.
- **Every name is the printer** on the setup Wi-Fi (`/etc/NetworkManager/dnsmasq-shared.d/elyir-bench-setup.conf`),
  so a phone's sign-in check (`captive.apple.com`, `connectivitycheck.gstatic.com`, …) reaches the phone page. nginx
  sends port 80 of `10.42.0.1` to the service (the `elyir-bench-setup` site). Where Mainsail already serves port 80,
  that site names the address, so it never becomes the house's default.
- **Joining** writes the network's keyfile through stdin (`sudo install -m 600 /dev/stdin …`), never a command
  line, since sudo logs those. It closes the setup Wi-Fi, brings the network up, and keeps it only if it worked; a
  failure reopens the setup Wi-Fi and says why (`password`, `not_found`, `timeout`).
- **The name** is applied once the printer is on the network, the installer's way: `elyir-bench rename "<name>"`
  saves it, sets its name on the network (`workshop.local`: hostname, `/etc/hosts`, avahi), then runs apply.

| Request | What |
|---|---|
| `GET /wifi/state` | `mode` (`off`, `looking`, `open`, `joining`, `failed`, `connected`), the networks, the network it's on or trying, `reason`, `name`, `renaming`, `host`, `port`, and while it's open `setup: {ssid, qr}` |
| `POST /wifi/scan` | look again |
| `POST /wifi/join` | `{ssid, password?, hidden?}`; refuses a password Wi-Fi never accepts before closing anything |
| `POST /wifi/name` | `{name}` |
| `POST /wifi/done` | finished on the panel |
| any other `GET` | the phone page (`setup/phone.html`) |

The panel follows `/wifi/state` (`app/src/setup/`) and shows `SetupScreen` instead of the app while the mode isn't
`off`, on the panel only. `screenFor` (pure, `app/tests/wifi-setup.test.ts`) decides the screen from the printer's
step and where the person is. The service is pinned by `setup/tests/test_wifi_setup.py`, the installer's parts
by `installer/tests/test_installer.py` (the site never takes port 80, the sudo rule, the name).

## On a laptop

```bash
python3 setup/wifi_setup.py --fake --port 8097        # pretend NetworkManager; "wrong…" passwords fail, "Nowhere" isn't found
cd app && npm run dev:sim                             # Vite sends /wifi to it (WIFI_URL to change)
#   panel: http://localhost:3000/?screen=panel        phone page: http://localhost:8097/
```

## Not yet

- Tried on a real Pi with a real phone (iPhone and Android sign-in sheets, the Pi's chip as a hotspot).
- The Wi-Fi country: a Pi with none set keeps its Wi-Fi blocked; the service unblocks it, and the hotspot uses the
  world channels. The image should set the country, or setup should ask.
- When the Wi-Fi it knows is gone for good (a new router, a move): Care should offer Set up Wi-Fi again.
- A Bench Box without a screen, and "Bring things over from another printer" on Connected.
- WPA2/3 Enterprise networks (a username too) are listed but can't be chosen.
