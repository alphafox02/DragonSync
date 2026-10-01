"""Regression guard for the arg/config precedence bug on boolean MQTT flags.

The pattern used throughout dragonsync.py is:

    "mqtt_tls": args.mqtt_tls if ... and args.mqtt_tls is not None
                else get_bool(config_values.get("mqtt_tls", False)),

That only lets the config file win when args.<name> is None. For a
store_true flag, argparse's native default is False, not None, so
without an explicit default=None the config value is silently
discarded. --mqtt-tls and --mqtt-tls-insecure were missing that
default and ignored config.ini entirely. This test parses dragonsync.py
and asserts every store_true MQTT flag opts in to None defaulting.
"""
import ast
import pathlib


_SRC = pathlib.Path(__file__).resolve().parent.parent / "dragonsync.py"

# Flags that resolve against config.ini via the "args.X is not None
# else config value" idiom. If someone adds a new one here, add it
# below so this test keeps pulling the thread.
_FLAGS_REQUIRING_NONE_DEFAULT = {
    "--mqtt-enabled",
    "--mqtt-tls",
    "--mqtt-tls-insecure",
    "--mqtt-retain",
    "--mqtt-per-drone-enabled",
    "--mqtt-ha-enabled",
}


def _store_true_calls():
    tree = ast.parse(_SRC.read_text())
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "add_argument"):
            continue
        # First positional arg is the flag name
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        flag = node.args[0].value
        kwargs = {k.arg: k.value for k in node.keywords}
        action = kwargs.get("action")
        if isinstance(action, ast.Constant) and action.value == "store_true":
            out[flag] = kwargs
    return out


def test_mqtt_tls_defaults_to_none_so_config_file_wins():
    calls = _store_true_calls()
    assert "--mqtt-tls" in calls, "parser lost the --mqtt-tls flag"
    default = calls["--mqtt-tls"].get("default")
    assert isinstance(default, ast.Constant) and default.value is None, (
        "--mqtt-tls is store_true without default=None; argparse will "
        "set args.mqtt_tls to False, which the config-resolution logic "
        "then prefers over config.ini's mqtt_tls = true"
    )


def test_mqtt_tls_insecure_defaults_to_none_so_config_file_wins():
    calls = _store_true_calls()
    assert "--mqtt-tls-insecure" in calls
    default = calls["--mqtt-tls-insecure"].get("default")
    assert isinstance(default, ast.Constant) and default.value is None, (
        "--mqtt-tls-insecure is store_true without default=None; "
        "the config-resolution logic will silently ignore config.ini"
    )


def test_all_config_backed_store_true_flags_opt_in_to_none():
    """One assertion per flag -- catches any new MQTT bool flag that
    forgets default=None."""
    calls = _store_true_calls()
    offenders = []
    for flag in _FLAGS_REQUIRING_NONE_DEFAULT:
        if flag not in calls:
            offenders.append(f"{flag}: not found in parser")
            continue
        default = calls[flag].get("default")
        if not (isinstance(default, ast.Constant) and default.value is None):
            offenders.append(f"{flag}: default is not None")
    assert not offenders, (
        "store_true flags that resolve against config.ini must set "
        "default=None, or config values are silently ignored: "
        + ", ".join(offenders)
    )
