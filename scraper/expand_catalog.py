#!/usr/bin/env python3
"""
Expand the Fixer AI material catalog with door/frame/hardware, window/glazing,
stairs, paving, fencing, insulation and HVAC entries that the current 707-key
taxonomy is missing (a door-replacement BOM matched only ~36% of its parts).

New keys are authored here (name/synonyms/unit/coverage/exclude), appended to
estimator_keys.json, then matched against prices.jsonl using the SAME logic as
build_estimator_catalog.py so the new entries get real scraped products. The
existing 707 entries are left byte-identical.

NO prices are fabricated: an entry without a confident scrape match is emitted
with no products and stays "unpriced" (the app flags such lines as unverified).
"""
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_estimator_catalog as bec  # reuse norm/matching exactly

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS_PATH = os.path.join(ROOT, "scraper", "estimator_keys.json")
LATEST = os.path.join(ROOT, "data", "latest")
APP_CATALOG = os.path.join(
    os.path.expanduser("~"), "Desktop", "GIthub", "Fixai", "Fixai", "material_catalog_v1.json"
)

# ---------------------------------------------------------------------------
# NEW ENTRIES. key must be unique; name Danish-first; synonyms include the
# Danish + English wordings the AI material list / camera questions actually
# produce. unit must be one the app's derivedUnitPrice understands
# (pcs/set/m/m2/roll/box/bag/liter/kg). exclude is optional scrape-guard terms.
# ---------------------------------------------------------------------------
NEW = [
    # --- Doors: leaf, frame, hardware (the "36% coverage" gap) ---
    dict(key="door_slab_interior", name="Indvendig dør (dørblad)", unit="pcs",
         synonyms=["indvendig dør", "dørblad", "dørplade", "innerdør", "dør 725x2040",
                   "dør 825x2040", "interior door", "door leaf", "door slab", "indvendig doer"],
         exclude=["låsekasse", "slutblik", "låsecylinder", "cylinder", "dørgreb", "greb",
                  "hængsel", "karm", "skrue", "beslag", "spion", "pumpe", "stopper",
                  "skilt", "lås"]),
    dict(key="door_slab_exterior", name="Yderdør", unit="pcs",
         synonyms=["yderdør", "hoveddør", "entredør", "terrassedør", "yderdor",
                   "front door", "exterior door", "entry door", "terrace door"],
         exclude=["lås", "låsekasse", "cylinder", "greb", "hængsel", "karm", "skrue",
                  "beslag", "dørlås", "terrassedørlås", "spion", "pumpe", "stopper"]),
    dict(key="door_frame_interior", name="Dørkarm (karmtræ)", unit="set",
         synonyms=["dørkarm", "karmtræ", "karmtræ sæt", "dørramme", "karmträ",
                   "door frame", "door casing", "door liner", "doerkarm"],
         exclude=["skrue", "skunklem", "skunk", "lem", "beslag", "skab", "køkken",
                  "hængsel", "greb", "lås", "plug"]),
    dict(key="door_hinge", name="Dørhængsel (sæt)", unit="set",
         synonyms=["dørhængsel", "dørhængsler", "hængsel", "hængsler", "dørhengsel",
                   "door hinge", "door hinges", "butt hinge", "doerhaengsel"],
         exclude=["skab", "køkken", "låge", "møbel", "klaver", "stabel", "smig"]),
    dict(key="door_handle_set", name="Dørgreb sæt (greb + skilte)", unit="set",
         synonyms=["dørgreb", "dørgreb sæt", "dørgrebsgarnitur", "grebgarnitur",
                   "dørgrebssæt", "door handle", "door handle set", "lever handle",
                   "doergreb"],
         exclude=["skab", "køkken", "møbel", "karm", "skrue", "beslag", "cylinder",
                  "indvendig dør", "dørblade", "spion", "låsekasse", "massiv", "solid",
                  "dannebrog", "finland", "ubehandlet"]),
    dict(key="door_lock_case", name="Låsekasse (indstikslås)", unit="pcs",
         synonyms=["låsekasse", "indstikslås", "låsekasse indstik", "lasekasse",
                   "mortise lock", "mortice lock", "lock case", "deadlock"],
         exclude=["greb", "skilt", "cylinder", "slutblik", "dørgreb", "karm"]),
    dict(key="door_cylinder", name="Låsecylinder", unit="pcs",
         synonyms=["låsecylinder", "cylinder", "sikkerhedscylinder", "lasecylinder",
                   "lock cylinder", "euro cylinder", "door cylinder", "profile cylinder"],
         exclude=["låsekasse", "greb", "slutblik", "skilt", "dørgreb"]),
    dict(key="door_strike_plate", name="Slutblik", unit="pcs",
         synonyms=["slutblik", "slutplade", "låseblik", "strike plate", "striker plate",
                   "latch plate"],
         exclude=["ukrudt", "keeper", "cord", "hair", "garden", "magnet", "låsekasse"]),
    dict(key="door_stop", name="Dørstopper", unit="pcs",
         synonyms=["dørstopper", "dørstop", "door stop", "door stopper", "door wedge",
                   "doerstopper"],
         exclude=["greb", "skab", "møbel", "køkken"]),
    dict(key="door_shims", name="Indkiler / sleer (dørkiler)", unit="pack",
         synonyms=["dørkiler", "kiler", "sleer", "indkiler", "doerkiler", "shims",
                   "door shims", "packers", "wedges", "glazing packers"],
         exclude=["tilefix", "nivellering", "flise", "nivelering", "eftermontering",
                  "k-mur", "beslag", "monteringsbeslag"]),
    dict(key="door_closer", name="Dørpumpe (dørlukker)", unit="pcs",
         synonyms=["dørpumpe", "dørlukker", "door closer", "overhead door closer",
                   "doerpumpe"],
         exclude=["checky", "tæppe", "carpet", "tappet", "tegning"]),
    dict(key="door_peephole", name="Dørspion", unit="pcs",
         synonyms=["dørspion", "kighul", "peephole", "door viewer", "doerspion"]),
    dict(key="door_letter_plate", name="Brevklap / brevsprække", unit="pcs",
         synonyms=["brevklap", "brevsprække", "postkasseklap", "letter plate",
                   "letterbox flap", "letter flap"]),

    # --- Windows & glazing ---
    dict(key="window_unit", name="Vindueselement (komplet vindue)", unit="pcs",
         synonyms=["vindueselement", "vinduesparti", "window unit", "window element",
                   "komplet vindue"],
         exclude=["maling", "beskyttelse", "telt", "drivhus", "vitavia", "jalousi",
                  "tagvindue", "partytelt", "gori", "skjuler", "film", "sæt", "bundliste",
                  "dafa", "karmliste", "beslag", "kravler", "kraver", "fluefanger",
                  "fluefælde", "skraber", "pest", "udskiftningsblad", "isolering",
                  "vindueskravler", "sensor", "klistermærke", "nylonvridere", "strips",
                  "greb", "vasker", "refill", "i-profil", "tesamoll", "folie", "insekt",
                  "fugle", "foderhus", "net", "insect", "d-c-fix", "olie", "lys",
                  "figur", "halloween", "deko", "dekoration", "lys"]),
    dict(key="window_glazing_double", name="Termorude (2-lags glas)", unit="pcs",
         synonyms=["termorude", "2-lags glas", "isolerrude", "termoglas", "double glazing",
                   "double glazed unit", "insulated glass unit", "thermopane"],
         exclude=["flagstang", "plasttopbeslag", "beslag", "dano", "mast"]),
    dict(key="window_handle", name="Vinduesgreb", unit="pcs",
         synonyms=["vinduesgreb", "vindueshåndtag", "window handle", "casement handle",
                   "vindueshaandtag", "window lock handle"]),
    dict(key="window_hinge", name="Vindueshængsel", unit="set",
         synonyms=["vindueshængsel", "vindueshængsler", "vinduesbeslag", "window hinge",
                   "casement hinge", "friction stay", "vindueshaengsel"],
         exclude=["dør", "skab", "køkken"]),
    dict(key="window_seal_strip", name="Tætningsliste vindue", unit="roll",
         synonyms=["tætningsliste", "vinduesliste", "window seal", "weatherstrip",
                   "window weather stripping", "tætningsliste vindue"],
         exclude=["dør", "køleskab", "frys"]),
    dict(key="window_sill", name="Vindueskarm / sålbænk", unit="m",
         synonyms=["vindueskarm", "sålbænk", "karmplade", "vinduesplade", "window sill",
                   "window board", "sill board", "vindueskarm træ", "saalbaenk"],
         exclude=["maling", "beskyttelse", "beslag", "skrue"]),
    dict(key="glazing_bead", name="Glasliste", unit="m",
         synonyms=["glasliste", "glasliste træ", "glazing bead", "glass bead",
                   "glasliste pvc", "glass list"]),
    dict(key="glazing_putty", name="Vindueskit", unit="kg",
         synonyms=["vindueskit", "kit", "glaspudser kit", "glazing putty", "glazing compound",
                   "window putty"],
         exclude=["reparation", "reparationskit", "glas", "rude"]),

    # --- Stairs ---
    dict(key="stair_tread", name="Trappetrin", unit="pcs",
         synonyms=["trappetrin", "trin", "stair tread", "step", "trappetrin eg",
                   "trappetrin bøg"]),
    dict(key="stair_handrail", name="Håndliste / gelænder", unit="m",
         synonyms=["håndliste", "gelænder", "håndgelænder", "handrail", "banister",
                   "railing", "haandliste"]),
    dict(key="stair_baluster", name="Baluster (gelænderstolpe)", unit="pcs",
         synonyms=["baluster", "gelænderstolpe", "sprosse", "gelændersprosse", "balusters",
                   "spindles", "stair spindle"]),
    dict(key="stair_stringer", name="Trappevange", unit="pcs",
         synonyms=["trappevange", "vange", "stringer", "stair stringer", "vange trappe"]),

    # --- Paving & hard landscaping ---
    dict(key="paving_slab", name="Belægningsfliser (havelfliser)", unit="m2",
         synonyms=["havelfliser", "belægningsfliser", "betonfliser", "havefliser",
                   "paving slab", "patio slab", "concrete paver"],
         exclude=["rens", "fjern", "rensemiddel", "dyrup", "gori", "væg", "mur", "imprægnering",
                  "dug", "wire", "opbindingswire", "fibertex", "plantex", "membran", "gummi",
                  "kantprofil", "schiene", "handsker", "kantbånd"]),
    dict(key="paving_brick", name="Klinker / brosten", unit="m2",
         synonyms=["klinker", "brosten", "belægningsklinker", "pavers", "brick pavers",
                   "chaussésten", "herregårdssten"]),
    dict(key="kerb_stone", name="Kantsten", unit="m",
         synonyms=["kantsten", "kantblok", "kantsten beton", "kerbstone", "curb stone",
                   "kerb", "curb"]),
    dict(key="paving_subbase", name="Stabilgrus / bundsikringsgrus", unit="bag",
         synonyms=["stabilgrus", "bundsikring", "bærelag", "bundsikringsgrus",
                   "sub base", "base course", "road base", "stabilgrus 25kg"]),
    dict(key="weed_fabric", name="Ukrudtsdug (fiberdug)", unit="roll",
         synonyms=["ukrudtsdug", "fiberdug", "jorddug", "ukrudtsmembran", "weed fabric",
                   "weed barrier", "geotextile", "membran underlag"]),

    # --- Fencing ---
    dict(key="fence_panel", name="Hegnspanel", unit="pcs",
         synonyms=["hegnspanel", "hegnssektion", "fence panel", "privacy panel",
                   "hegnspanel træ", "panelhegn"],
         exclude=["beslag", "l-beslag", "vægbeslag", "stolpespyd", "stolpefod", "skrue",
                  "isolator", "hegnspæl", "maskestørrel", "pileflet", "tråd"]),
    dict(key="fence_post", name="Hegnspæl", unit="pcs",
         synonyms=["hegnspæl", "hegnsstolpe", "hegnspael", "fence post",
                   "fence pole", "stolpe træ", "hegnsstolper"],
         exclude=["beslag", "skrue", "elementbeslag", "l-beslag", "isolator", "skjul",
                  "renovationsskjul"]),
    dict(key="fence_post_foot", name="Stolpespyd (stolpefod)", unit="pcs",
         synonyms=["stolpespyd", "stolpefod", "stolpesko", "post spike", "post anchor",
                   "post support", "stolpe beslag"],
         exclude=["skrue", "møtrik", "bolt"]),
    dict(key="fence_gate", name="Hegnslåge", unit="pcs",
         synonyms=["hegnslåge", "låge", "havelåge", "hegnslaage", "fence gate", "garden gate"],
         exclude=["gateway", "smart", "wifi", "hub", "dæmper", "adapter", "lågedæmper",
                  "lågeadapter"]),
    dict(key="fence_wire", name="Hegnstråd / trådnet", unit="roll",
         synonyms=["hegnstråd", "trådnet", "hegnsnet", "hønsenet", "wire mesh",
                   "fencing wire", "chicken wire", "netting"]),

    # --- Insulation (additional thicknesses + board types) ---
    dict(key="insulation_batts_50mm", name="Mineraluld 50mm", unit="m2",
         synonyms=["mineraluld 50mm", "isolering 50mm", "batts 50", "mineral wool 50mm",
                   "rockwool 50", "glava 50"]),
    dict(key="insulation_batts_150mm", name="Mineraluld 150mm", unit="m2",
         synonyms=["mineraluld 150mm", "isolering 150mm", "batts 150", "mineral wool 150mm",
                   "rockwool 150"]),
    dict(key="insulation_batts_200mm", name="Mineraluld 200mm", unit="m2",
         synonyms=["mineraluld 200mm", "isolering 200mm", "batts 200", "mineral wool 200mm",
                   "rockwool 200"]),
    dict(key="insulation_pir_board", name="PIR isoleringsplade", unit="m2",
         synonyms=["pir plade", "pir", "isoleringsplade pir", "pir board", "pir insulation",
                   "polyiso board", "kingspan"]),
    dict(key="insulation_eps_board", name="EPS / flamingo plade", unit="m2",
         synonyms=["eps plade", "flamingo", "polystyren", "eps", "eps board", "styrofoam",
                   "polystyrenplade"]),
    dict(key="insulation_loose_fill", name="Løsfyld isolering", unit="bag",
         synonyms=["løsfyld", "løsfyldsisolering", "papirisolering", "cellulose insulation",
                   "loose fill insulation", "indblæst isolering"]),
    dict(key="vapor_barrier_tape", name="Damspærretape / isoleringstape", unit="roll",
         synonyms=["damspærretape", "isolationstape", "damspærre tape", "vapor barrier tape",
                   "foil tape", "alutape"]),

    # --- HVAC / radiators ---
    dict(key="radiator_panel", name="Panelradiator", unit="pcs",
         synonyms=["radiator", "panelradiator", "radiatorelement", "panel radiator",
                   "radiator hvid", "convector radiator"],
         exclude=["skjuler", "spray", "maling", "twist", "skjold", "spraymaling", "cover",
                  "skjuler"]),
    dict(key="radiator_towel", name="Håndklædetørrer (radiator)", unit="pcs",
         synonyms=["håndklædetørrer", "håndklæderadiator", "haandklaedetoerrer",
                   "towel warmer", "towel radiator", "håndklædetørrer el"],
         exclude=["spray", "maling", "skjuler"]),
    dict(key="radiator_bracket", name="Radiatorophæng", unit="set",
         synonyms=["radiatorophæng", "radiatorbeslag", "radiator bracket", "radiator mount",
                   "radiator konsol", "vægkonsol radiator"], exclude=["cykel"]),
    dict(key="underfloor_heating_pipe", name="Gulvvarme rør", unit="m",
         synonyms=["gulvvarmerør", "gulvvarme rør", "underfloor heating pipe", "ufh pipe",
                   "gulvvarme slange", "pex gulvvarme"]),

    # --- Masonry extras (glue the existing masonry_xxx slots touch) ---
    dict(key="brick_common", name="Mursten (almindelig)", unit="pcs",
         synonyms=["mursten", "mursten rød", "teglsten", "brick", "common brick",
                   "mursten 228x108"],
         exclude=["rist", "facaderist", "ventil", "afdækning"]),
    dict(key="brick_facing", name="Facadesten / forblender", unit="pcs",
         synonyms=["facadesten", "forblender", "facing brick", "facade brick",
                   "forblendersten"]),
    dict(key="concrete_block", name="Betonblok / lecablok", unit="pcs",
         synonyms=["betonblok", "lecablok", "leca blok", "concrete block", "lightweight block",
                   "gasbetonblok"]),
    dict(key="aerated_block", name="Gasbeton blok (porebeton)", unit="pcs",
         synonyms=["gasbeton", "porebeton", "gasbetonblok", "multipor", "aerated concrete",
                   "autoclaved aerated", "ytong"]),

    # --- Flooring extras ---
    dict(key="parquet_floor_m2", name="Parketgulv (pr m2)", unit="m2",
         synonyms=["parketgulv", "parket", "træparket", "parquet", "parket ege", "parquet floor",
                   "parketgulv eg"]),
    dict(key="engineered_wood_floor_m2", name="Trægulv (lamel / 3-stav)", unit="m2",
         synonyms=["trægulv", "lamelgulv", "3-stav gulv", "engineered wood floor",
                   "traegulv", "plankegulv"]),
    dict(key="carpet_tile", name="Tæppefliser", unit="m2",
         synonyms=["tæppefliser", "tæppeflis", "carpet tile", "carpet tiles", "tæppe gulv",
                   "tæppefliser kontor"],
         exclude=["skåner", "måtte", "gulvmåtte", "fortelt", "gulvtæppe", "løber"]),
 
    # --- Drywall / partition extras ---
    dict(key="gipsboard_9mm", name="Gipsplade 9mm", unit="pcs",
         synonyms=["gipsplade 9mm", "gips 9mm", "gypsum board 9mm", "plasterboard 9mm",
                   "gipsplade tynd"], exclude=["skrue", "spartel"]),
    dict(key="soundproof_gipsboard", name="Lydgips / akustikgips", unit="pcs",
         synonyms=["lydgips", "akustikgips", "lydgipsplade", "soundproof plasterboard",
                   "acoustic plasterboard", "lydplade"], exclude=["skrue", "spartel"]),
    dict(key="ceiling_grid_profile", name="Nedhængt loft profil (akustik)", unit="m",
         synonyms=["loftprofil", "nedhængt loft", "t-profil", "loft skinne",
                   "ceiling grid", "t grid profile", "akustikloft profil"]),

    # --- Exterior / drainage ---
    dict(key="gutter_pvc", name="Tagrende (PVC)", unit="m",
         synonyms=["tagrende", "tagrende pvc", "tagrender", "gutter", "guttering",
                   "rain gutter", "tagrende hvid"]),
    dict(key="gutter_bracket", name="Tagrendebeslag", unit="pcs",
         synonyms=["tagrendebeslag", "tagrendeholder", "gutter bracket", "gutter clip",
                   "tagrende beslag"], exclude=["bil", "cykel"]),
    dict(key="downpipe_pvc", name="Nedløbsrør (tagvand)", unit="m",
         synonyms=["nedløbsrør", "nedløb", "downpipe", "downspout", "tagvand nedløb",
                   "nedløbsrør pvc"]),
]

def main():
    keys = json.load(open(KEYS_PATH, encoding="utf-8"))
    existing = {k["key"] for k in keys}
    dupes = [n["key"] for n in NEW if n["key"] in existing]
    if dupes:
        print("ABORT: duplicate keys already in catalog:", dupes)
        sys.exit(1)
    # sanity: unique among themselves
    new_keys = [n["key"] for n in NEW]
    if len(set(new_keys)) != len(new_keys):
        print("ABORT: duplicate keys within NEW entries")
        sys.exit(1)
    # unit sanity
    ok_units = {"pcs", "set", "m", "m2", "roll", "box", "bag", "liter", "kg", "pack", "pair", "ton", "m3", "job"}
    bad = [n["key"] for n in NEW if n["unit"] not in ok_units]
    if bad:
        print("ABORT: bad units:", bad)
        sys.exit(1)

    # match products against the live scrape (same logic as the nightly build)
    prods = bec.load_products()
    today = date.today().isoformat()
    app_catalog = json.load(open(APP_CATALOG, encoding="utf-8"))

    app_added = []
    keys_added = []
    priced = 0
    for item in NEW:
        entry = dict(item)  # key/name/synonyms/unit/(coverage)/(exclude)
        entry.pop("exclude", None)
        # keys file keeps exclude; app bundle does not use it
        keys_entry = {
            "key": item["key"], "name": item["name"],
            "synonyms": item["synonyms"], "unit": item["unit"],
        }
        if item.get("coverage"):
            keys_entry["coverage"] = item["coverage"]
        if item.get("exclude"):
            keys_entry["exclude"] = item["exclude"]

        hits = bec.match_products(item, prods)
        if hits:
            def rank(h):
                pack = bec.parse_pack(h.get("name", ""))
                return (-h.get("_score", 0),
                        0 if h.get("in_stock") is not False else 1,
                        0 if pack else 1,
                        h["price"])
            hits.sort(key=rank)
            by_chain = {}
            for h in hits:
                by_chain.setdefault(h["chain"], []).append(h)
            picked = []
            for c in list(by_chain):
                if by_chain[c]:
                    picked.append(by_chain[c].pop(0))
                if len(picked) >= bec.MAX_PRODUCTS_PER_KEY:
                    break
            products = []
            for h in picked:
                pk = bec.parse_pack(h.get("name", ""))
                p = {"t": h.get("name", "").strip(), "p": round(h["price"], 2),
                     "c": h["chain"]}
                if h.get("url"):
                    p["u"] = h["url"]
                if pk:
                    p["pack"] = pk
                products.append(p)
            if products:
                entry["products"] = products
                entry["updated"] = today
                priced += 1

        keys_added.append(keys_entry)
        app_added.append(entry)

    keys += keys_added
    json.dump(keys, open(KEYS_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    app_catalog += app_added
    json.dump(app_catalog, open(APP_CATALOG, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))

    print(f"Added {len(NEW)} keys to estimator_keys.json (now {len(keys)} total).")
    print(f"  {priced} of {len(NEW)} got live scraped products.")
    for n in NEW:
        if n["key"] not in [a["key"] for a in app_added]:
            print("  MISSING from app write:", n["key"])

if __name__ == "__main__":
    main()
