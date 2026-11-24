"""화면용 한 줄 조건 요약(한국어). 문구는 config/summary_ko.yaml."""
from __future__ import annotations
from .common import load_yaml


def summary_ko(state: dict) -> str:
    K = load_yaml("summary_ko.yaml")
    L, d = state["light"], state["direction"]
    if L["stage"] == "L0":
        sun = K["sun"]["night"]
    elif L["stage"] == "L1":
        morning = int(state["datetime_local"][11:13]) < 12
        sun = K["sun"]["twilight_morning" if morning else "twilight_evening"]
    elif d["spot_shaded"]:
        sun = K["sun"]["shaded"]
    elif state["direct_sun"]["stage"] == "D0":
        sun = K["sun"]["up_no_direct"].format(elev=int(round(L["elev"])))
    else:
        sun = K["sun"]["up"].format(elev=int(round(L["elev"])), direction=K["direction"][d["light_direction"]])
    items = [sun]
    ly = ((state.get("source") or {}).get("weather") or {}).get("last_year_date")
    if ly:
        items.insert(0, K["last_year"].format(date=f"{int(ly[5:7])}/{int(ly[8:10])}", year=ly[:4]))
    pf = state["precip"]["form"]
    items.append(K["precip"][pf] if pf in K["precip"] else K["sky"].get(state["sky"], ""))
    if state["haze"]["stage"] != "H4" or state["sky"] != "fog":
        items.append(K["haze"][state["haze"]["stage"]])
    items += [K["ground"][g] for g in state["ground"] if g in K["ground"]]
    if (state.get("lamps") or {}).get("state") == "on" and K.get("lamps_on"):
        items.append(K["lamps_on"])
    items += [K["tree"].format(name=t["name_ko"], stage=t["stage_ko"]) for t in state["trees"]]
    return K["joiner"].join(i for i in items if i)
