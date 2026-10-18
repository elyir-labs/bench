"""Printer or Bench Box on a fresh card's first screen (design/role/, B): how many printer boards are plugged in."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import elyir_bench as a  # noqa: E402


def here(serial=(), can=None, ifaces=(), ace=0, camera=False):
    return {"serial": list(serial), "can": can, "can_ifaces": list(ifaces), "klipper": None, "host_mcu": False,
            "ace": ace, "camera": camera}


def test_nothing_plugged_in_is_no_board_even_with_a_camera_or_a_unit():
    assert a.printer_boards(here(camera=True)) == 0
    assert a.printer_boards(here(serial=["usb-ANYCUBIC_ACE_1-if00"], ace=1)) == 0


def test_klipper_boards_can_boards_and_adapters_count():
    assert a.printer_boards(here(serial=["usb-Klipper_stm32f446xx_2B0035000F51313236343430-if00"])) == 1
    assert a.printer_boards(here(serial=["usb-Klipper_stm32f446xx_X-if00"], can=["6cc850bbec73"], ifaces=["can0"])) == 2
    assert a.printer_boards(here(ifaces=["can0"])) == 1        # an adapter, nothing answering yet


def test_a_board_without_klipper_yet_counts():
    assert a.printer_boards(here(serial=["usb-1a86_USB_Serial-if00-port0"])) == 1
    assert a.printer_boards(here(serial=["usb-Silicon_Labs_CP2102N_USB_to_UART_Bridge_Controller_0001-if00-port0"])) == 1
