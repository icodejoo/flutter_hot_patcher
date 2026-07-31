import json, os

here = os.path.dirname(os.path.abspath(__file__))
B = os.path.join(here, "_build")


def load(name):
    return json.load(open(os.path.join(B, name)))["objects"]


def index_by_id(objs):
    return {o["id"]: o for o in objs if isinstance(o, dict) and "id" in o}


def cid_map(objs):
    out = {}
    for o in objs:
        if isinstance(o, dict) and o.get("type") == "Class" and o.get("name") in (
            "Sq", "Tri", "Circ", "Extra", "Shape",
        ):
            out[o["name"]] = o["class_id"]
    return out


def area_code(objs, by_id, klass_name):
    for o in objs:
        if (
            isinstance(o, dict)
            and o.get("type") == "Function"
            and o.get("name") == f"{klass_name}.area"
        ):
            code = by_id.get(o.get("code"))
            return code
    return None


base = load("base.json")
patch = load("patch.json")
base_ix = index_by_id(base)
patch_ix = index_by_id(patch)

print("=== class_id (cid) per class ===")
bc = cid_map(base)
pc = cid_map(patch)
print("base :", bc)
print("patch:", pc)
for name in ("Sq", "Tri", "Circ"):
    same = bc.get(name) == pc.get(name)
    print(f"  {name}: base={bc.get(name)} patch={pc.get(name)} SAME={same}")

print()
print("=== area() Code layout per class (section/offset/size) ===")
for name in ("Sq", "Tri", "Circ"):
    bcode = area_code(base, base_ix, name)
    pcode = area_code(patch, patch_ix, name)
    print(f"{name}.area  base={bcode}  patch={pcode}")
