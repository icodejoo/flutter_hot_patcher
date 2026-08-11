import json, os

here = os.path.dirname(os.path.abspath(__file__))
B = os.path.join(here, "_build")
d = json.load(open(os.path.join(B, "probe.json")))
objs = d["objects"]


def by_id(oid):
    for o in objs:
        if isinstance(o, dict) and o.get("id") == oid:
            return o
    return None


for o in objs:
    if isinstance(o, dict) and o.get("type") == "Function" and o.get("name") in (
        "functionA", "functionB", "functionC",
    ):
        code = by_id(o.get("code"))
        print(o.get("name"), "-> Function id", o.get("id"), "-> Code id", o.get("code"), "->", code)
