from waitwhy.settings import get_config


def test_config_edits_do_not_leak_between_calls():
    a = get_config()
    a["platforms"]["youtube"]["enabled"] = "mutated"
    a["operating_mode"] = "mutated"
    b = get_config()
    assert b["platforms"]["youtube"]["enabled"] is True and b["operating_mode"] != "mutated"
