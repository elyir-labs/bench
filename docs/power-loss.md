# Power cuts

What Bench does when the power goes mid-print (`design/power-loss/`, A, picked 21 October 2026).

## With a UPS: the print holds

The printer component asks NUT about the UPS every 5 seconds (`upsc`). After 30 seconds on battery a print holds:
Klipper's idle timeout is raised (it would turn the motors off 10 minutes into a pause), then `PAUSE`, the nozzle down
to 150° and the bed 15° cooler (never under 40°). The motors stay on, so nothing loses its place. Once the power has
been back 30 seconds it heats back up and carries on by itself; Pause on Now keeps it paused instead. A print someone
had already paused only gets its idle timeout raised.

A flicker shorter than 30 seconds changes nothing. The phone is told when it holds and when the power is back.

### Setting up the UPS

Any UPS with a USB port that NUT knows. A pure-sine one of about 1500 VA suits a Voron with an AC bed: holding takes
about a fifth of printing's power, so it holds for roughly 50 minutes with the bed warm. Plug the router into it too,
or the phone can't be told.

```bash
sudo apt install nut
# /etc/nut/nut.conf
MODE=standalone
# /etc/nut/ups.conf
[ups]
  driver = usbhid-ups
  port = auto
# /etc/nut/upsd.users
[upsmon]
  password = <password>
  upsmon primary
# /etc/nut/upsmon.conf: shut the Pi down cleanly when the battery is low (protects the SD card)
MONITOR ups@localhost 1 upsmon <password> primary
sudo systemctl restart nut-server nut-monitor
upsc ups            # ups.status: OL on mains, OB on battery, LB low
```

The component finds the first UPS by itself. Name one in `moonraker.conf` if there are several:

```ini
[printer_intent]
ups: ups
```

## Without one, or past the battery: print the rest

On every layer the component saves where the print is to Moonraker's database (`elyir-bench/checkpoint`). If that is
still there when the component starts again and Klipper isn't printing that file, the power took the print. Ready
shows it as "Stopped by a power cut", with Print the rest and Start over, and the phone is told.

Print the rest asks the slicer to cut each part of the plate at the height the print reached
(`POST /slice/models/{id}/cut`), then opens Ready with the top parts, to print on a clean plate and glue on. It needs
the models, so it's offered for prints Bench sliced, while the slicer still has them (it keeps them a day). Carrying
on on top of the part isn't offered: without its motors a gantry printer can't find its height again over the part.

Nothing heats or moves by itself after a power cut without a UPS.

## Trying it on the Mac

```bash
cd simulator && python3 sim.py --scenario power_out    # also power_back, power_lost
```
