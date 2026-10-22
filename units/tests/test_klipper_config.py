"""The Klipper config the installer writes for the service: the sensor's push, ELYIR_TOOL, and T0..T7."""
import os

HERE = os.path.dirname(__file__)


def render(pin="EBBCan:PB8", tools=8, head_sensor=""):
    with open(os.path.join(HERE, "..", "klipper", "elyir_units.cfg")) as f:
        text = f.read()
    return text.format(sensor_pin=pin, sensor_bare=pin.lstrip("^~!"), head_sensor=head_sensor,
                       tool_macros="".join(f"\n[gcode_macro T{i}]\ngcode: ELYIR_TOOL T={i}\n" for i in range(tools)))


def test_the_sensor_pin_is_shared_and_each_edge_is_pushed():
    cfg = render()
    assert "[duplicate_pin_override]\npins: EBBCan:PB8" in cfg and "[gcode_button elyir_units_sensor]\npin: EBBCan:PB8" in cfg
    assert 'press_gcode: {action_call_remote_method("elyir_sensor", state="pressed")}' in cfg
    assert 'release_gcode: {action_call_remote_method("elyir_sensor", state="released")}' in cfg


def test_a_tool_change_in_a_print_pauses_the_file_and_calls_the_service():
    cfg = render()
    macro = cfg[cfg.index("[gcode_macro ELYIR_TOOL]"):cfg.index("[gcode_macro T0]")]
    assert ('action_call_remote_method("elyir_tool", tool=params.T|int, in_print=printing, '
            'purge=printer["gcode_macro ELYIR_PURGE"].length)') in macro
    assert "SET_GCODE_VARIABLE MACRO=ELYIR_PURGE VARIABLE=length VALUE=-1" in macro      # one change's length, never the next
    purge = cfg[cfg.index("[gcode_macro ELYIR_PURGE]"):cfg.index("[gcode_macro ELYIR_TOOL]")]
    assert "variable_length: -1" in purge and "VALUE={params.LENGTH|default(-1)|float}" in purge
    assert macro.index("action_call_remote_method") < macro.index("PAUSE_BASE")
    assert all(f"[gcode_macro T{i}]\ngcode: ELYIR_TOOL T={i}" in cfg for i in range(8))
    assert "{{" not in cfg and "{sensor_pin}" not in cfg
