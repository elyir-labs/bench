import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from elyir_bench_intent import IntentTracker, plan_action, ActionPlan, _pretty_job_name  # noqa: E402

T0 = 1_757_000_000.0  # fixed "now" so ETAs are deterministic


def ready_tracker(state="standby"):
    t = IntentTracker("Workshop", now=T0)
    t.set_klippy_state("ready", now=T0)
    t.update_status({
        "print_stats": {"state": state, "filename": "", "print_duration": 0, "total_duration": 0, "message": "", "info": {}},
        "pause_resume": {"is_paused": False},
        "display_status": {"message": "", "progress": 0},
        "virtual_sdcard": {"progress": 0.0},
        "heater_bed": {"temperature": 24.0, "target": 0.0},
        "extruder": {"temperature": 24.0, "target": 0.0, "can_extrude": False},
        "ace": {
            "status": "ready",
            "gate_color": ["D9534F", "F1F1F1", "2B2B2B", "F1F1F1"],
            "gate_material": ["PLA", "PLA", "PLA", "PLA"],
            "selected_gate": 1,
            "slots": [{"status": "ready"}, {"status": "ready"}, {"status": "ready"}, {"status": "ready"}],
        },
    }, now=T0)
    return t


def test_ready_lists_spools():
    t = ready_tracker()
    i = t.intent(T0)
    assert i["state"] == "ready"
    assert i["headline"] == "Ready"
    assert "4 spools loaded" in i["detail"]
    assert [s["color"] for s in i["spools"]] == ["#D9534F", "#F1F1F1", "#2B2B2B", "#F1F1F1"]
    assert i["spools"][1]["in_use"] is True


def test_starting_up_then_offline_problem():
    t = IntentTracker("Workshop", now=T0)
    assert t.intent(T0 + 5)["state"] == "preparing"
    assert t.intent(T0 + 5)["phase"] == "starting_up"
    late = t.intent(T0 + 120)
    assert late["state"] == "problem"
    assert late["phase"] == "offline"
    assert late["actions"][0]["id"] == "restart_firmware"


def test_long_startup_says_a_board_may_not_be_answering_not_offline():
    # Klipper up but retrying a silent CAN toolhead: Moonraker reports "startup" for minutes
    t = IntentTracker("Studio", now=T0)
    t.set_klippy_state("startup", now=T0 + 2)
    early = t.intent(T0 + 30)
    assert (early["state"], early["phase"]) == ("preparing", "starting_up")
    assert "About a minute" in early["detail"]
    late = t.intent(T0 + 400)
    assert (late["state"], late["phase"]) == ("preparing", "starting_up")
    assert "brain" not in late["headline"]
    assert "boards may not be answering" in late["detail"]
    t.set_klippy_state("error", "mcu 'EBBCan': Unable to connect", now=T0 + 500)
    assert t.intent(T0 + 500)["headline"] == "The print head lost contact for a moment."


def test_preparing_follows_print_start_messages():
    t = ready_tracker()
    t.update_status({"print_stats": {"state": "printing", "filename": "phone_stand_0.2mm_PLA_2h10m.gcode"},
                     "heater_bed": {"temperature": 30.0, "target": 60.0}}, now=T0)
    i = t.intent(T0)
    assert i["state"] == "preparing"
    assert i["headline"] == "Getting ready for Phone stand"
    assert i["steps"][0]["status"] == "now"

    t.update_status({"display_status": {"message": "Heat-soaking bed to 60C for 10 min..."}}, now=T0 + 60)
    i = t.intent(T0 + 60)
    assert i["phase"] == "soaking"
    assert [s["status"] for s in i["steps"]] == ["done", "now", "todo", "todo"]

    t.update_status({"display_status": {"message": "Leveling Gantry ........"}}, now=T0 + 500)
    assert t.intent(T0 + 500)["phase"] == "leveling"

    t.update_status({"display_status": {"message": "Printing, good luck!"}}, now=T0 + 700)
    i = t.intent(T0 + 700)
    assert i["state"] == "printing"
    assert i["headline"] == "Phone stand"
    assert i["actions"][0]["id"] == "pause"


def test_printing_eta_blends_slicer_and_measured_pace():
    t = ready_tracker()
    t.set_metadata("phone_stand.gcode", {"estimated_time": 6000, "filament_colors": ["#D9534F", "#F1F1F1"], "filament_type": "PLA",
                                          "filament_weight_total": 33.4,
                                          "thumbnails": [{"width": 32, "height": 32, "relative_path": ".thumbs/phone_stand-32x32.png"},
                                                         {"width": 400, "height": 300, "relative_path": ".thumbs/phone_stand-400x300.png"}]})
    t.update_status({"print_stats": {"state": "printing", "filename": "phone_stand.gcode", "print_duration": 3000,
                                     "info": {"current_layer": 58, "total_layer": 140}},
                     "virtual_sdcard": {"progress": 0.5}}, now=T0)
    i = t.intent(T0)
    assert i["state"] == "printing"
    job = i["job"]
    assert job["layer"] == 58 and job["layers"] == 140
    # slicer says 3000 left, measured pace says 3000 left: blend is 3000
    assert abs(job["remaining_s"] - 3000) < 5
    assert job["eta_clock"]
    assert job["colors"] == ["#D9534F", "#F1F1F1"]
    assert job["thumbnail"] == ".thumbs/phone_stand-400x300.png"
    assert job["grams"] == 33
    assert "Done at about" in i["detail"]


def test_thumbnail_path_keeps_subfolder():
    from elyir_bench_intent import _best_thumbnail
    assert _best_thumbnail("toys/Benchy.gcode", {"thumbnails": [{"width": 300, "height": 300, "relative_path": ".thumbs/Benchy-300x300.png"}]}) == "toys/.thumbs/Benchy-300x300.png"
    assert _best_thumbnail("x.gcode", {}) is None


def test_runout_offers_matching_spool():
    t = ready_tracker()
    t.update_status({"print_stats": {"state": "printing", "filename": "phone_stand.gcode", "info": {"current_layer": 20}}}, now=T0)
    # ACE reports slot 1 (white) empty, macro says "Spool is empty", print pauses
    t.on_gcode_response("Spool is empty", now=T0 + 10)
    t.update_status({"ace": {"slots": [{"status": "ready"}, {"status": "empty"}, {"status": "ready"}, {"status": "ready"}]},
                     "pause_resume": {"is_paused": True},
                     "print_stats": {"state": "paused"}}, now=T0 + 11)
    i = t.intent(T0 + 12)
    assert i["state"] == "needs_you"
    assert i["phase"] == "runout"
    assert i["headline"] == "White PLA ran out."
    assert "slot 4" in i["detail"]          # the other white spool, counted from 1
    primary = i["actions"][0]
    assert primary["id"] == "swap_slot" and primary["args"]["slot"] == 3 and primary["primary"]
    assert i["actions"][1]["id"] == "loaded"
    assert i["expires"] is not None
    plan = plan_action("swap_slot", primary["args"], t)
    assert plan == [(ActionPlan.GCODE, "ACE_CHANGE_TOOL TOOL=3"), (ActionPlan.RESUME, None)]


def test_runout_without_alternative():
    t = ready_tracker()
    t.update_status({"ace": {"selected_gate": 0}, "print_stats": {"state": "printing", "filename": "x.gcode", "info": {"current_layer": 3}}}, now=T0)
    t.on_gcode_response("Spool is empty", now=T0)
    t.update_status({"ace": {"slots": [{"status": "empty"}, {"status": "ready"}, {"status": "ready"}, {"status": "ready"}]},
                     "pause_resume": {"is_paused": True}}, now=T0)
    i = t.intent(T0)
    assert i["headline"] == "Red PLA ran out."
    assert i["actions"][0]["id"] == "loaded"


def test_plain_pause_and_resume_clears_reason():
    t = ready_tracker()
    t.update_status({"print_stats": {"state": "printing", "filename": "x.gcode", "info": {"current_layer": 3}}}, now=T0)
    t.update_status({"pause_resume": {"is_paused": True}}, now=T0)
    i = t.intent(T0)
    assert i["state"] == "needs_you" and i["phase"] == "paused"
    t.update_status({"pause_resume": {"is_paused": False}}, now=T0 + 5)
    assert t.intent(T0 + 5)["state"] == "printing"


def test_problem_translates_klipper_error():
    t = ready_tracker()
    t.set_klippy_state("shutdown", "Heater extruder not heating at expected rate\nSee the 'verify_heater' section", now=T0)
    i = t.intent(T0)
    assert i["state"] == "problem"
    assert i["headline"] == "The nozzle or bed isn't heating properly."
    assert i["phase"] == "heater_fault"
    assert i["actions"][0]["id"] == "try_again"
    assert "not heating" in i["raw"]


def test_problem_fallback_stays_human():
    t = ready_tracker()
    t.set_klippy_state("error", "Some brand new failure nobody has seen", now=T0)
    i = t.intent(T0)
    assert i["state"] == "problem"
    assert i["headline"].endswith("not sure why.")


def test_finished_counts_down_then_ready_to_lift():
    t = ready_tracker()
    t.set_metadata("x.gcode", {"filament_type": "PLA"})
    t.update_status({"print_stats": {"state": "printing", "filename": "x.gcode", "info": {"current_layer": 5}}}, now=T0)
    t.update_status({"print_stats": {"state": "complete"}, "heater_bed": {"temperature": 50.0, "target": 0.0}}, now=T0 + 100)
    i = t.intent(T0 + 100)
    assert i["state"] == "finished" and i["phase"] == "cooling"
    assert "10 more minutes" in i["detail"]
    t.update_status({"heater_bed": {"temperature": 34.0}}, now=T0 + 700)
    i = t.intent(T0 + 700)
    assert i["phase"] == "ready_to_lift"
    t.acknowledge_finished()
    assert t.intent(T0 + 701)["state"] == "ready"


def test_finished_promises_a_phone_message_only_when_one_will_come():
    t = ready_tracker()
    t.update_status({"print_stats": {"state": "printing", "filename": "x.gcode"}}, now=T0)
    t.update_status({"print_stats": {"state": "complete"}, "heater_bed": {"temperature": 50.0, "target": 0.0}}, now=T0 + 100)
    assert "phone" not in t.intent(T0 + 100)["detail"]
    t.phones_notified = True
    assert t.intent(T0 + 100)["detail"].endswith("I'll tell your phone.")


def test_finished_offers_the_plate_that_didnt_fit():
    """design/plate/, A: 30 bushings, 25 on the first plate; when it's done, Now offers the other 5."""
    t = ready_tracker()
    first, second = "bushing_x25_1of2_PETG_2h26m.gcode", "bushing_x5_2of2_PETG_29m15s.gcode"
    t.next_plates = [{"after": first, "file": second, "count": 5, "what": "5 bushings"}]
    t.update_status({"print_stats": {"state": "printing", "filename": first}}, now=T0)
    t.update_status({"print_stats": {"state": "complete"}, "heater_bed": {"temperature": 50.0, "target": 0.0}}, now=T0 + 100)
    i = t.intent(T0 + 100)
    assert i["state"] == "finished"
    assert "The other 5 bushings are on a second plate, ready when the bed is clear." in i["detail"]
    act = i["actions"][0]
    assert act["label"] == "Print the other 5" and act["primary"] and act["args"]["filename"] == second
    assert plan_action("start_file", act["args"], t) == [(ActionPlan.START_FILE, second)]
    # the second plate printed: nothing follows it, so it's Print another again
    t.acknowledge_finished()
    t.update_status({"print_stats": {"state": "printing", "filename": second}}, now=T0 + 200)
    t.update_status({"print_stats": {"state": "complete"}}, now=T0 + 300)
    assert t.intent(T0 + 300)["actions"][0]["id"] == "print_another"


def test_cancelled_shows_note_then_ready():
    t = ready_tracker()
    t.update_status({"print_stats": {"state": "printing", "filename": "x.gcode"}}, now=T0)
    t.update_status({"print_stats": {"state": "cancelled"}}, now=T0 + 10)
    assert t.intent(T0 + 11)["headline"] == "Print stopped."
    assert t.intent(T0 + 1000)["headline"] == "Ready"


def test_a_restart_doesnt_bring_back_an_old_cancel():
    # found on desk: Moonraker restarted (a deploy) and the panel said "Print stopped." for
    # five minutes about a print cancelled hours before, because Klipper still says cancelled
    t = ready_tracker(state="cancelled")
    assert t.intent(T0 + 1)["headline"] == "Ready"


def test_job_names_read_like_names():
    assert _pretty_job_name("gcodes/phone_stand_0.2mm_PLA_MK4_2h10m.gcode") == "Phone stand"
    assert _pretty_job_name("Benchy.gcode") == "Benchy"
    assert _pretty_job_name("buildplate_bushing_open_x25_1of2_PETG_2h26m.gcode") == "Buildplate bushing open × 25 (plate 1 of 2)"
    assert _pretty_job_name("cutting_arm_g2e_and_2_more_PETG_20m42s.gcode") == "Cutting arm g2e and 2 more"
    assert _pretty_job_name("cable-clip_x4.gcode") == "Cable clip × 4"
    assert _pretty_job_name("Body80_ASA_41m9s.gcode") == "Body80"
    assert _pretty_job_name("[a]_front_bearing_holder_ASA_14m2s.gcode") == "Front bearing holder"


def test_used_extruders_drive_colors_and_material():
    from elyir_bench_intent import job_colors, job_material, _color_name
    meta = {"filament_type": "ASA;PETG;PETG;PETG;PETG;ASA;ASA;ASA",
            "filament_colors": ["#21FF06", "#0000FF", "#999999", "#CC66FF", "#333333", "#4C4C4C", "#333333", "#FB0207"],
            "filament_weights": [0.0, 0.0, 0.0, 0.0, 0.0, 9.8, 0.0, 0.0]}
    assert job_colors(meta) == ["#4C4C4C"]
    assert job_material(meta) == "ASA"
    assert job_colors({"filament_colors": ["#FF0000", "#00FF00"]}) == ["#FF0000", "#00FF00"]   # no weights: keep all
    assert _color_name("#800080") == "Purple" and _color_name("#CC66FF") == "Purple" and _color_name("#FB0207") == "Red"


def test_chamber_sensor_is_found_by_name():
    t = ready_tracker()
    assert t.intent(T0)["printer"]["chamber"] is None
    t.update_status({"temperature_sensor Chamber": {"temperature": 41.26}}, now=T0)
    assert t.intent(T0)["printer"]["chamber"] == {"temperature": 41.3}
    assert IntentTracker.chamber_sensor_name(["heater_bed", "temperature_sensor MCU", "temperature_sensor Chamber"]) == "temperature_sensor Chamber"
    assert IntentTracker.chamber_sensor_name(["temperature_sensor MCU"]) is None


def test_spools_from_real_ace_device_shape():
    """Shape observed on Workshop: top-level lists plus a devices[] entry with per-slot RFID data."""
    t = IntentTracker("Workshop", now=T0)
    t.set_klippy_state("ready", now=T0)
    t.update_status({"print_stats": {"state": "standby", "filename": ""}, "ace": {
        "total_gates": 4, "num_devices": 1, "selected_gate": 0,
        "active_gate": ["ready", "ready", "ready", "ready"],
        "gate_color": ["00FF00", "0000FF", "FFFFFF", "800080"],
        "gate_material": ["PETG", "PETG", "", "PETG"],
        "devices": [{"name": "ACE_1", "gate_offset": 0, "gates": [0, 1, 2, 3], "status": {
            "status": "ready", "active_gate": ["ready", "ready", "ready", "ready"],
            "slots": [
                {"index": 0, "status": "ready", "sku": "", "type": "", "color": [0, 0, 0], "rfid": 1},
                {"index": 1, "status": "ready", "sku": "", "type": "", "color": [0, 0, 0], "rfid": 1},
                {"index": 2, "status": "ready", "sku": "AHPEGY-101", "type": "PETG", "color": [117, 120, 123], "rfid": 1},
                {"index": 3, "status": "empty", "sku": "", "type": "", "color": [0, 0, 0], "rfid": 1},
            ]}}],
    }}, now=T0)
    sp = t.intent(T0)["spools"]
    assert [s["color"] for s in sp] == ["#00FF00", "#0000FF", "#75787B", "#800080"]
    assert [s["material"] for s in sp] == ["PETG", "PETG", "PETG", "PETG"]
    assert [s["status"] for s in sp] == ["ready", "ready", "ready", "empty"]
    assert [s["rfid"] for s in sp] == [False, False, True, False]
    assert sp[0]["in_use"] is True


def test_print_start_pause_is_getting_ready_not_paused():
    # The shared PRINT_START pauses the file while it heats so Cancel works at once.
    t = ready_tracker()
    t.update_status({"print_stats": {"state": "paused", "filename": "x.gcode", "info": {}},
                     "pause_resume": {"is_paused": True},
                     "gcode_macro _PRINT_START": {"stage": "soaking"},
                     "heater_bed": {"temperature": 108.0, "target": 110.0}}, now=T0)
    i = t.intent(T0)
    assert i["state"] == "preparing" and i["phase"] == "soaking"
    assert [a["id"] for a in i["actions"]] == ["cancel", "stop_now"]
    assert [s["status"] for s in i["steps"]] == ["done", "now", "todo", "todo"]
    t.update_status({"gcode_macro _PRINT_START": {"stage": "qgl"}}, now=T0 + 60)
    assert t.intent(T0 + 60)["phase"] == "leveling"
    # Getting ready is done: the file resumes and the print starts
    t.on_gcode_response("Printing, good luck!", now=T0 + 120)
    t.update_status({"print_stats": {"state": "printing"}, "pause_resume": {"is_paused": False},
                     "gcode_macro _PRINT_START": {"stage": ""},
                     "display_status": {"message": "Printing, good luck!"}}, now=T0 + 120)
    assert t.intent(T0 + 120)["state"] == "printing"


def test_print_start_seen_straight_from_standby_resets_the_job():
    t = ready_tracker()
    t.update_status({"print_stats": {"state": "printing", "filename": "x.gcode", "info": {"current_layer": 9}}}, now=T0)
    t.update_status({"print_stats": {"state": "complete", "info": {}}}, now=T0 + 10)
    t.update_status({"print_stats": {"state": "standby"}}, now=T0 + 20)
    # Same file again; the poll never saw "printing" before PRINT_START paused
    t.update_status({"print_stats": {"state": "paused", "filename": "x.gcode", "info": {}},
                     "pause_resume": {"is_paused": True},
                     "gcode_macro _PRINT_START": {"stage": "warming"}}, now=T0 + 30)
    i = t.intent(T0 + 30)
    assert i["state"] == "preparing" and i["phase"] == "warming"


def test_pause_after_print_start_still_needs_you():
    t = ready_tracker()
    t.update_status({"print_stats": {"state": "printing", "filename": "x.gcode", "info": {"current_layer": 3}},
                     "gcode_macro _PRINT_START": {"stage": ""}}, now=T0)
    t.update_status({"pause_resume": {"is_paused": True}, "print_stats": {"state": "paused"}}, now=T0 + 5)
    assert t.intent(T0 + 5)["state"] == "needs_you"


def test_ending_a_print_is_held_not_tapped():
    """3 October 2026: a brush against the panel must never end a long print. Everything that throws
    away printed work, or hits the emergency stop, is marked hold; Cancel while getting ready stays a tap."""
    t = ready_tracker()
    t.update_status({"print_stats": {"state": "printing", "filename": "x.gcode", "info": {"current_layer": 30}}}, now=T0)
    acts = {a["id"]: a for a in t.intent(T0)["actions"]}
    assert acts["cancel"].get("hold") is True and not acts["pause"].get("hold")
    t.update_status({"print_stats": {"state": "paused"}, "pause_resume": {"is_paused": True}}, now=T0 + 10)
    assert {a["id"]: a.get("hold", False) for a in t.intent(T0 + 10)["actions"]}["cancel"] is True
    t2 = ready_tracker()
    t2.update_status({"print_stats": {"state": "paused", "filename": "x.gcode", "info": {}},
                      "pause_resume": {"is_paused": True},
                      "gcode_macro _PRINT_START": {"stage": "soaking"}}, now=T0)
    prep = {a["id"]: a.get("hold", False) for a in t2.intent(T0)["actions"]}
    assert prep == {"cancel": False, "stop_now": True}


def test_stop_now_is_an_emergency_stop():
    # the component restarts Klipper afterwards, in the background
    t = ready_tracker()
    assert plan_action("stop_now", {}, t) == [(ActionPlan.EMERGENCY_STOP, None)]


def test_stop_now_shows_stopping_not_a_problem_until_klipper_is_back():
    t = ready_tracker()
    t.update_status({"print_stats": {"state": "paused", "filename": "x.gcode", "info": {}},
                     "pause_resume": {"is_paused": True},
                     "gcode_macro _PRINT_START": {"stage": "qgl"}}, now=T0)
    t.begin_stop(now=T0)
    t.set_klippy_state("ready", now=T0)          # a late "ready" from before the stop landed
    assert t.intent(T0)["phase"] == "stopping"
    t.set_klippy_state("shutdown", "Shutdown due to webhooks request", now=T0 + 1)
    i = t.intent(T0 + 1)
    assert i["state"] == "preparing" and i["phase"] == "stopping" and i["actions"] == []
    t.set_klippy_state("startup", now=T0 + 3)
    assert t.intent(T0 + 3)["phase"] == "stopping"
    t.set_klippy_state("ready", now=T0 + 20)
    t.update_status({"print_stats": {"state": "standby", "filename": ""}, "pause_resume": {"is_paused": False},
                     "gcode_macro _PRINT_START": {"stage": ""}}, now=T0 + 20)
    i = t.intent(T0 + 20)
    assert i["state"] == "ready" and i["headline"] == "Print stopped."


def test_stop_now_that_never_restarts_becomes_a_problem():
    t = ready_tracker()
    t.begin_stop(now=T0)
    t.set_klippy_state("shutdown", "Shutdown due to webhooks request", now=T0 + 1)
    assert t.intent(T0 + 130)["state"] == "problem"


# ── a fresh card: no printer.cfg yet (design/printer-setup/, A; docs/bring-it-over.md) ──

NO_CONFIG = ('Unable to open config file /home/pi/printer_data/config/printer.cfg\n'
             'Once the underlying issue is corrected, use the "RESTART"\ncommand to reload the config and restart the host software.\n'
             'Printer is halted\n')


def test_a_fresh_card_without_printer_cfg_is_setup_not_a_problem():
    t = IntentTracker("Workshop", now=T0)
    t.set_klippy_state("error", NO_CONFIG, now=T0)
    i = t.intent(T0)
    assert (i["state"], i["phase"], i["headline"]) == ("setup", "no_config", "Now the printer itself.")
    assert i["detail"] == "It can't see how the printer is wired, so it needs a config, once."
    assert [(a["id"], a["label"], a["primary"]) for a in i["actions"]] == [
        ("bring_open", "Bring it over", True), ("write_own", "Write my own", False)]
    assert "printer.cfg" in i["raw"] and i["printer"]["connected"] is False
    t.setup_found = ["Main board · STM32F446 on USB", "Toolhead board · on CAN"]
    assert t.intent(T0)["detail"] == "It found these. It can't see how they're wired, so it needs a config, once."
    # the screens open both themselves: nothing is sent to the printer
    assert plan_action("bring_open", {}, t) == [(ActionPlan.NONE, None)]
    assert plan_action("write_own", {}, t) == [(ActionPlan.NONE, None)]


def test_any_other_config_error_is_still_a_problem():
    t = IntentTracker("Workshop", now=T0)
    t.set_klippy_state("error", "Unable to open config file /home/pi/printer_data/config/macros.cfg", now=T0)
    assert t.intent(T0)["state"] == "problem"
    t.set_klippy_state("error", "Section 'ace' is not a valid config section", now=T0)
    assert t.intent(T0)["state"] == "problem"


def test_a_start_routine_that_names_no_step_is_followed_by_what_the_printer_does():
    # The Kobra 3's own start (Anycubic's GoKlipper through Rinkhals), recorded 6 October 2026: no M117, no macro stage.
    t = IntentTracker("Kobra 3", now=T0)
    t.has_unit = False
    t.set_klippy_state("ready", now=T0)
    t.update_status({"print_stats": {"state": "complete", "filename": "base.gcode", "info": {"current_layer": 62}},
                     "display_status": {}, "toolhead": {"homed_axes": ""},
                     "heater_bed": {"temperature": 25.0, "target": 0.0}, "extruder": {"temperature": 26.0, "target": 0.0}}, now=T0)
    t.set_metadata("base_PETG.gcode", {"first_layer_extr_temp": 230.0, "first_layer_bed_temp": 45.0, "estimated_time": 1250})

    def at(dt, **status):
        t.update_status(status, now=T0 + dt)
        i = t.intent(T0 + dt)
        return i["state"], i["phase"], [s["status"] for s in i["steps"]]

    start = {"print_stats": {"state": "printing", "filename": "base_PETG.gcode", "info": {"current_layer": 0, "total_layer": 62}},
             "heater_bed": {"temperature": 25.0, "target": 45.0}, "extruder": {"temperature": 26.0, "target": 170.0}}
    assert at(0, **start) == ("preparing", "warming", ["now", "todo", "todo", "todo"])
    # bed and the cleaning heat there before homing: past warming
    assert at(70, heater_bed={"temperature": 45.0}, extruder={"temperature": 170.0})[1] == "leveling"
    assert at(72, toolhead={"homed_axes": "z"})[1] == "leveling"
    assert at(95, toolhead={"homed_axes": "xyz"})[1] == "leveling"
    # the nozzle cools to 140 to probe: still leveling, never back to warming
    assert at(125, extruder={"temperature": 160.0, "target": 140.0})[1] == "leveling"
    # heating to print: the file's first-layer temperature
    assert at(210, extruder={"temperature": 140.0, "target": 230.0}) == ("preparing", "heating", ["done", "done", "done", "now"])
    assert t.intent(T0 + 210)["detail"] == "Nozzle at 140° of 230°."
    assert at(287, print_stats={"info": {"current_layer": 1}}, extruder={"temperature": 230.0})[0] == "printing"


def test_named_steps_still_win_over_what_the_printer_does():
    t = ready_tracker()
    t.update_status({"print_stats": {"state": "printing", "filename": "phone_stand.gcode"}, "toolhead": {"homed_axes": ""},
                     "heater_bed": {"temperature": 60.0, "target": 60.0}}, now=T0)
    t.update_status({"display_status": {"message": "Heat-soaking bed to 60C for 10 min..."}, "toolhead": {"homed_axes": "xyz"}}, now=T0 + 30)
    assert t.intent(T0 + 30)["phase"] == "soaking"         # the message says soaking, though the bed is warm and it homed
