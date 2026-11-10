"""Tests for the pure-Python logic (no Home Assistant needed). Run with pytest or any runner that calls test_*()."""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta

try:
    from custom_components.photo_slideshow import const, library, manifest_out, report, rules, state, sync, title
except ImportError:                                           # the in-browser runner flattens the package
    from photo_slideshow import const, library, manifest_out, report, rules, state, sync, title

CFG = dict(
    const.DEFAULT_OPTIONS,
    exclude_folders=["Resources", "Intros", "temp", "tmp", "Motion Graphics Template Media"],     # a travel library
)
NOW = datetime(2026, 11, 4, 12, 0, 0)
MB = 1024 * 1024


# ----------------------------------------------------------------------------- rules
def ev(parts, **kw):
    return rules.evaluate(parts, CFG, **kw)


def test_photo_in_year_folder_is_included():
    d = ev(["2022 Spain", "Montserrat", "20220814_173106055_iOS.heic"])
    assert d.included and d.kind == "photo" and d.reason == "ok", d


def test_extension_is_case_insensitive():
    assert ev(["2022 Spain", "x", "IMG_1.JPG"]).included


def test_unsupported_formats_are_out():
    for name in ("IMG.dng", "IMG.rw2", "design.psd", "notes.txt", "noext"):
        d = ev(["2022 Spain", "x", name])
        assert not d.included and d.reason == "format", (name, d)


def test_supported_extra_formats():
    for name in ("a.tif", "a.TIFF", "a.bmp", "a.gif", "a.png", "a.jpeg"):
        assert ev(["2022 Spain", "x", name]).included, name


def test_top_level_folders():
    for top in ("Me", "Family", "1999 France", "2000 Germany", "Misc", "2100 Future"):
        assert ev([top, "a.jpg"]).included, top                  # every top-level folder is in unless excluded by name
    for top in ("Resources", "Intros", "aaaa temp"):
        d = ev([top, "a.jpg"])
        assert not d.included and d.reason == "excluded-folder", (top, d)


def test_root_files_are_never_shown():
    d = ev(["Photo.jpg"])
    assert not d.included and d.reason == "root-file"


def test_excluded_folders_inside_year_folders():
    d = ev(["2014 South Africa", "Johannesburg", "Motion Graphics Template Media", "a.jpg"])
    assert not d.included and d.reason == "excluded-folder"
    d = ev(["2020 Italy", "temp_old", "a.jpg"])
    assert not d.included and d.reason == "excluded-folder"
    d = ev(["2020 Italy", "Old TMP", "a.jpg"])
    assert not d.included and d.reason == "excluded-folder"


def test_temple_is_not_temp():
    assert ev(["2021 Spain", "Temple", "a.jpg"]).included
    assert ev(["2021 Spain", "Template shots", "a.jpg"]).included


def test_hidden_name_suffix():
    d = ev(["2020 Italy", "Rome", "IMG_1_hide.jpg"])
    assert not d.included and d.reason == "excluded-name"
    assert ev(["2020 Italy", "Rome", "IMG_1.jpg"]).included
    assert not ev(["2020 Italy", "Rome", "IMG_1_HIDE.JPG"]).included    # case-insensitive


def test_custom_patterns_from_options():
    cfg = dict(CFG, exclude_files=["*-skip.*", "DSC_9*"], exclude_folders=["Screenshots"])
    assert not rules.evaluate(["2020 Italy", "a-skip.jpg"], cfg).included
    assert not rules.evaluate(["2020 Italy", "DSC_9001.jpg"], cfg).included
    assert not rules.evaluate(["2020 Italy", "My Screenshots", "a.jpg"], cfg).included
    assert rules.evaluate(["2020 Italy", "temp", "a.jpg"], cfg).included   # no longer excluded


def test_video_limits():
    p = ["2021 Spain", "clip.mov"]
    d = ev(p, size=10 * MB, duration_ms=20000)
    assert d.included and d.kind == "video"
    assert ev(p, size=10 * MB, duration_ms=40000).reason == "video-too-long"
    assert ev(p, size=70 * MB, duration_ms=20000).reason == "video-too-big"
    assert ev(p, size=10 * MB, duration_ms=None).included                         # no length from Google: judged by size
    assert ev(p, size=70 * MB, duration_ms=None).reason == "video-too-big"
    assert ev(p, size=None, duration_ms=None).reason == "video-unknown-length"
    cfg = dict(CFG, max_video_seconds=60, max_video_mb=100)
    assert rules.evaluate(p, cfg, size=90 * MB, duration_ms=50000).included


def test_dry_run_counts():
    rows = [
        (["2022 Spain", "a.jpg"], None, None),
        (["2022 Spain", "b.jpg"], None, None),
        (["Resources", "c.jpg"], None, None),
        (["2022 Spain", "d.dng"], None, None),
        (["2022 Spain", "e_hide.jpg"], None, None),
    ]
    c = rules.dry_run(rows, CFG)
    assert c["photo:ok"] == 2 and c["photo:excluded-folder"] == 1 and c["other:format"] == 1 and c["photo:excluded-name"] == 1, c


def test_clean_patterns_tolerates_commas_and_semicolons():
    typed = ["00 Resources,", "03 Intros,", "temp,", "tmp,", "Motion Graphics Template Media"]
    assert rules.clean_patterns(typed) == ["00 Resources", "03 Intros", "temp", "tmp", "Motion Graphics Template Media"]
    assert rules.clean_patterns(["a; b ;c;", "", "  "]) == ["a", "b", "c"]
    assert rules.clean_patterns(["*_hide.*"]) == ["*_hide.*"]
    cfg = dict(CFG, exclude_folders=rules.clean_patterns(typed))
    assert not rules.evaluate(["2020 Italy", "03 Intros", "a.jpg"], cfg).included
    assert not rules.evaluate(["00 Resources", "x", "a.jpg"], cfg).included
    assert rules.evaluate(["2020 Italy", "Temple", "a.jpg"], cfg).included


def test_suggest_hidden_name():
    assert rules.suggest_hidden_name("IMG_1.jpg", ["*_hide.*"]) == "IMG_1_hide.jpg"
    assert rules.suggest_hidden_name("IMG_1.jpg", ["*-skip.*"]) == "IMG_1-skip.jpg"
    assert rules.suggest_hidden_name("noext", ["*_hide.*"]) == "noext_hide"
    assert rules.suggest_hidden_name("a.b.jpg", ["DSC*"]) == "a.b_hide.jpg"      # falls back to the default suffix


def test_folder_glob_in_include_list():
    assert rules.match_glob("[12][09][0-9][0-9] *", "2022 Spain")
    assert not rules.match_glob("[12][09][0-9][0-9] *", "2022")
    assert rules.match_segment("Resources", "00 resources")
    assert not rules.match_segment("", "anything")


# ----------------------------------------------------------------------------- titles
def test_title_matches_old_page():
    t = title.title_from_path(["2019 United States", "Los Angeles", "IMG_7092.JPG"])
    assert t.lines == ["Year: 2019", "Location: United States, Los Angeles"], t.lines
    assert t.html() == "Year: 2019<br>Location: United States, Los Angeles"


def test_title_without_subfolder_keeps_top_secret():
    assert title.title_from_path(["2013 France", "x.jpg"]).lines == ["Year: 2013", "Location: France, Top Secret"]


def test_title_without_year():
    assert title.title_from_path(["Me", "Album", "x.jpg"]).lines == ["Location: Me, Album"]


def test_title_uses_first_subfolder_only():
    assert title.title_from_path(["2022 Spain", "Montserrat", "Day 2", "x.jpg"]).place == "Montserrat"


def test_enrich_with_date():
    t = title.enrich(title.title_from_path(["2022 Spain", "Montserrat", "x.heic"]), {"time": "2022:08:04 17:31:06"})
    assert t.lines[-1] == "Date: 4 Aug 2022", t.lines
    t = title.enrich(title.title_from_path(["2022 Spain", "x.heic"]), {"time": "1970:01:01 00:00:00"})
    assert len(t.lines) == 2                                   # nonsense dates are ignored
    t = title.enrich(title.title_from_path(["2022 Spain", "x.heic"]), None)
    assert len(t.lines) == 2
    assert title.parse_exif_time("garbage") is None


# ----------------------------------------------------------------------------- library / pick
def make_library(n_photos=100, n_videos=20, new_photos=0):
    lib = {}
    for i in range(n_photos):
        added = NOW if i < new_photos else NOW - timedelta(days=100)
        lib[f"p{i}"] = library.Item(f"p{i}", ("2022 Spain", f"f{i}.jpg"), "photo", added)
    for i in range(n_videos):
        lib[f"v{i}"] = library.Item(f"v{i}", ("2022 Spain", f"f{i}.mp4"), "video", NOW - timedelta(days=100), duration_ms=10000)
    return lib


def test_pick_is_unique_filtered_and_kind_correct():
    lib = make_library()
    used = {f"p{i}" for i in range(20)}
    hidden = {f"p{i}" for i in range(20, 30)}
    r = library.pick(lib, "photo", 47, used, hidden, random.Random(1))
    ids = [i.id for i in r.items]
    assert len(ids) == 47 == len(set(ids)) and not r.cycle_reset and r.short == 0
    assert not (set(ids) & used) and not (set(ids) & hidden)
    assert all(i.kind == "photo" for i in r.items)
    rv = library.pick(lib, "video", 3, set(), set(), random.Random(2))
    assert len(rv.items) == 3 and all(i.kind == "video" for i in rv.items)


def test_pick_exclude_for_replacements():
    lib = make_library(n_photos=10)
    r = library.pick(lib, "photo", 5, set(), set(), random.Random(3), exclude={"p0", "p1", "p2"})
    assert not ({i.id for i in r.items} & {"p0", "p1", "p2"})


def test_cycle_reset_when_pool_runs_out():
    lib = make_library(n_photos=10)
    used = {f"p{i}" for i in range(7)}
    r = library.pick(lib, "photo", 5, used, set(), random.Random(4))
    ids = [i.id for i in r.items]
    assert r.cycle_reset and r.short == 0 and len(ids) == 5 == len(set(ids)), r
    assert {"p7", "p8", "p9"} <= set(ids)                      # the unused ones come first


def test_pick_short_when_library_is_tiny():
    lib = make_library(n_photos=3)
    r = library.pick(lib, "photo", 5, set(), set(), random.Random(5))
    assert len(r.items) == 3 and r.short == 2 and r.cycle_reset


def test_new_items_get_no_preference():
    lib = make_library(n_photos=100, new_photos=10)
    rng = random.Random(7)
    total_new = 0
    for _ in range(400):
        r = library.pick(lib, "photo", 10, set(), set(), rng)
        total_new += sum(1 for i in r.items if i.added >= NOW - timedelta(days=7))
    mean = total_new / 400
    assert 0.75 < mean < 1.25, mean                            # uniform: 10 new of 100, 10 picked -> 1.0 on average


def test_merge_scan_keeps_first_seen_time():
    old_item = library.Item("a", ("2022 Spain", "a.jpg"), "photo", NOW - timedelta(days=50))
    old = {"a": old_item, "gone": library.Item("gone", ("2022 Spain", "g.jpg"), "photo", NOW)}
    found = [library.Item("a", ("2022 Spain", "a.jpg"), "photo", NOW), library.Item("b", ("2022 Spain", "b.jpg"), "photo", NOW)]
    lib, summary = library.merge_scan(old, found, NOW)
    assert lib["a"].added == NOW - timedelta(days=50) and lib["b"].added == NOW
    assert summary == {"new": 1, "removed": 1, "total": 2}, summary


def test_item_roundtrip():
    it = library.Item("a", ("2022 Spain", "a.jpg"), "photo", NOW, size=5, modified="2026-01-01T00:00:00Z", meta={"time": "2022:08:14 17:31:06"})
    assert library.Item.from_dict(json.loads(json.dumps(it.to_dict()))) == it


# ----------------------------------------------------------------------------- state
def item(i="a"):
    return library.Item(i, ("2022 Spain", "Montserrat", f"{i}.jpg"), "photo", NOW)


def test_marks_and_today_list():
    s = state.State()
    s.today = ["a", "b", "c"]
    assert s.mark("like", item("a"), NOW) and not s.mark("like", item("a"), NOW)     # duplicates ignored
    assert s.today == ["a", "b", "c"]                                                  # a like changes nothing
    assert s.mark("fix", item("b"), NOW) and "b" not in s.today
    assert s.mark("hide", item("c"), NOW) and "c" not in s.today and "c" in s.hidden_ids()
    assert s.pending_counts() == {"like": 1, "fix": 1, "hide": 1}
    assert s.totals["like"] == 1 and s.totals["fix"] == 1 and s.totals["hide"] == 1
    try:
        s.mark("bogus", item("x"), NOW)
        assert False, "should raise"
    except ValueError:
        pass


def test_drain_pending_clears_marks_but_not_hidden():
    s = state.State()
    s.mark("like", item("a"), NOW)
    s.mark("hide", item("c"), NOW)
    out = s.drain_pending()
    assert len(out["like"]) == 1 and len(out["hide"]) == 1
    assert s.pending_counts() == {"like": 0, "fix": 0, "hide": 0} and "c" in s.hidden


def test_prune_hidden_after_scan():
    s = state.State()
    s.mark("hide", item("c"), NOW)
    s.mark("hide", item("d"), NOW)
    assert s.prune_hidden({"d", "z"}) == ["c"] and s.hidden_ids() == {"d"}
    assert s.unhide("d") and not s.unhide("d")


def test_used_cycle_and_progress():
    s = state.State()
    s.mark_used("photo", ["a", "b"])
    assert s.progress("photo", 8) == 25.0 and s.cycles["photo"] == 1
    s.mark_used("photo", ["x"], cycle_reset=True)
    assert s.used["photo"] == {"x"} and s.cycles["photo"] == 2
    assert s.progress("photo", 0) == 0.0


def test_state_roundtrip_through_json():
    s = state.State()
    s.mark_used("photo", ["a", "b"])
    s.mark("like", item("a"), NOW)
    s.mark("hide", item("c"), NOW)
    s.today = ["a"]
    s.fails_in_row = 2
    s.last_sync = {"ok": True}
    s2 = state.State.from_dict(json.loads(json.dumps(s.to_dict())))
    assert s2.used == s.used and s2.hidden == s.hidden and s2.pending == s.pending and s2.fails_in_row == 2 and s2.today == ["a"]
    assert state.State.from_dict(None).pending_counts() == {"like": 0, "fix": 0, "hide": 0}


# ----------------------------------------------------------------------------- report
def test_no_marks_no_report():
    assert report.build_report({"like": [], "fix": [], "hide": []}, {}, CFG, NOW) is None


def test_report_content():
    items = {"a": item("a"), "b": library.Item("b", ("2019 France", "Lyon", "R&D <x>.jpg"), "photo", NOW), "c": item("IMG_2")}
    pending = {
        "like": [{"id": "a", "path": "x", "at": ""}],
        "fix": [{"id": "b", "path": "x", "at": ""}],
        "hide": [{"id": "c", "path": "x", "at": ""}, {"id": "gone", "path": "2020 Italy/Rome/old.jpg", "at": ""}],
    }
    r = report.build_report(pending, items, CFG, NOW)
    assert r.subject == "Travel Slideshow: 1 liked, 1 to fix, 2 hidden", r.subject
    assert "https://drive.google.com/file/d/a/view" in r.text and "https://drive.google.com/file/d/gone/view" in r.text
    assert "IMG_2_hide.jpg" in r.html and "IMG_2_hide.jpg" in r.text
    assert "R&amp;D &lt;x&gt;.jpg" in r.html and "<x>" not in r.html                # HTML is escaped
    assert "Year: 2019\nLocation: France, Lyon" in r.text and "Year: 2019<br>Location: France, Lyon" in r.html
    assert "Open in Google Drive" in r.html and r.html.startswith("<div")
    assert r.counts == {"like": 1, "fix": 1, "hide": 2}


# ----------------------------------------------------------------------------- manifest
def test_local_name_matches_old_script():
    assert manifest_out.local_name(3, ["2022 Spain", "Montserrat", "IMG_1.heic"], "jpg") == "3_2022_Spain_AAA_Montserrat_AAA_IMG_1.jpg"
    assert manifest_out.local_name(10, ["Me", "a b.png"], "png") == "10_Me_AAA_a_b.png"


def test_manifest_has_titles_and_legacy_list():
    it = library.Item("a", ("2022 Spain", "Montserrat", "x.heic"), "photo", NOW, meta={"time": "2022:08:14 17:31:06"})
    files = [(it, manifest_out.local_name(1, it.parts, "jpg"))]
    m = manifest_out.build_manifest(files)
    assert m["count"] == 1 and m["items"][0]["lines"] == ["Year: 2022", "Location: Spain, Montserrat", "Date: 14 Aug 2022"]
    assert m["items"][0]["file"] == "1_2022_Spain_AAA_Montserrat_AAA_x.jpg"
    assert manifest_out.build_legacy_manifest(files) == "1_2022_Spain_AAA_Montserrat_AAA_x.jpg\n"


def run_all():
    """Used by the in-browser runner: returns (passed, failed, lines)."""
    lines, passed, failed = [], 0, 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                passed += 1
                lines.append("PASS " + name)
            except Exception as e:                           # noqa: BLE001
                failed += 1
                lines.append(f"FAIL {name}: {type(e).__name__}: {e}")
    return passed, failed, lines


# ----------------------------------------------------------------------------- the daily sync
def run(coro):
    """Drive a coroutine that never really suspends (the fakes below do not)."""
    try:
        coro.send(None)
    except StopIteration as stop:
        return stop.value
    raise RuntimeError("coroutine suspended")


def lib_of(n_photos, n_videos=0):
    lib = {}
    for i in range(n_photos):
        lib[f"p{i}"] = library.Item(f"p{i}", ("2022 Spain", f"IMG_{i}.jpg"), "photo", NOW)
    for i in range(n_videos):
        lib[f"v{i}"] = library.Item(f"v{i}", ("2022 Spain", f"MOV_{i}.mp4"), "video", NOW)
    return lib


def empty_used():
    return {"photo": set(), "video": set()}


def test_build_day_gets_the_wanted_numbers():
    async def fetch(item, n):
        return f"{n}_{item.id}.jpg"
    res = run(sync.build_day(lib_of(60, 5), empty_used(), set(), {"photo": 47, "video": 3}, fetch, random.Random(1)))
    assert len(res.ids["photo"]) == 47 and len(res.ids["video"]) == 3 and not res.failed
    assert [e[0].kind for e in res.done] == ["photo"] * 47 + ["video"] * 3
    assert len({e[1] for e in res.done}) == 50                      # all file names differ


def test_failed_items_are_replaced():
    bad = {"p0", "p1", "p2"}

    async def fetch(item, n):
        if item.id in bad:
            raise RuntimeError("broken file")
        return f"{n}.jpg"
    res = run(sync.build_day(lib_of(20), empty_used(), set(), {"photo": 10, "video": 0}, fetch, random.Random(2)))
    assert len(res.ids["photo"]) == 10 and not (set(res.ids["photo"]) & bad)
    assert all(f["error"].startswith("RuntimeError") for f in res.failed)


def test_hidden_and_used_are_never_picked():
    async def fetch(item, n):
        return f"{n}.jpg"
    used = {"photo": {f"p{i}" for i in range(10)}, "video": set()}
    hidden = {f"p{i}" for i in range(10, 20)}
    res = run(sync.build_day(lib_of(30), used, hidden, {"photo": 10, "video": 0}, fetch, random.Random(3)))
    assert set(res.ids["photo"]) == {f"p{i}" for i in range(20, 30)} and not res.cycle_reset["photo"]


def test_cycle_restarts_when_unused_run_out():
    async def fetch(item, n):
        return f"{n}.jpg"
    used = {"photo": {f"p{i}" for i in range(8)}, "video": set()}
    res = run(sync.build_day(lib_of(10), used, set(), {"photo": 5, "video": 0}, fetch, random.Random(4)))
    assert len(res.ids["photo"]) == 5 and res.cycle_reset["photo"]
    assert {"p8", "p9"} <= set(res.ids["photo"])                    # what was left comes first


def test_gives_up_when_everything_fails():
    async def fetch(item, n):
        raise OSError("disk full")
    res = run(sync.build_day(lib_of(100), empty_used(), set(), {"photo": 10, "video": 0}, fetch, random.Random(5)))
    assert not res.ids["photo"] and len(res.failed) == 30           # 3 x the wanted number, then stop
    ok, why = sync.day_is_acceptable(res, {"photo": 10, "video": 0})
    assert not ok and "0 of 10" in why


def test_day_needs_half_of_the_photos_but_videos_are_optional():
    async def fetch(item, n):
        if item.kind == "video":
            raise RuntimeError("no ffmpeg")
        return f"{n}.jpg"
    res = run(sync.build_day(lib_of(10, 3), empty_used(), set(), {"photo": 10, "video": 3}, fetch, random.Random(6)))
    assert sync.day_is_acceptable(res, {"photo": 10, "video": 3})[0] and res.short["video"] == 3


def test_local_copy_extensions():
    assert [sync.photo_target_ext(e) for e in ("JPG", "jpeg", "png", "heic", "tif", "bmp", "gif")] == \
        ["jpg", "jpeg", "png", "jpg", "jpg", "jpg", "jpg"]


def test_used_is_recorded_only_through_the_state():
    async def fetch(item, n):
        return f"{n}.jpg"
    res = run(sync.build_day(lib_of(6), empty_used(), set(), {"photo": 4, "video": 0}, fetch, random.Random(7)))
    st = state.State()
    assert not st.used["photo"]                                      # building a day does not touch the state
    for kind, ids, reset in sync.used_ids_to_record(res):
        st.mark_used(kind, ids, cycle_reset=reset)
    assert len(st.used["photo"]) == 4


def test_manifest_carries_the_show_options_and_nav_keys_are_hidden_by_default():
    it = library.Item("a", ("2022 Spain", "x.jpg"), "photo", NOW)
    m = manifest_out.build_manifest([(it, "1_x.jpg")], 12, {"date": False, "like": True})
    assert m["photo_seconds"] == 12 and m["show"] == {"date": False, "like": True}
    assert manifest_out.build_manifest([(it, "1_x.jpg")])["show"] == {}                 # no options: the page shows everything
    for k in const.SHOW_KEYS:
        assert const.DEFAULT_OPTIONS[const.show_option(k)] is (k not in ("prev", "pause", "next", "counter")), k


def test_path_from_local_name_recovers_a_readable_drive_path():
    assert manifest_out.path_from_local_name("3_2022_Spain_AAA_Montserrat_AAA_IMG_1.jpg") == "2022 Spain/Montserrat/IMG 1"
    assert manifest_out.path_from_local_name("12_2021_Spain_AAA_Tenerife_AAA_Fills_AAA_x_AAA_112.png").startswith("2021 Spain/Tenerife/Fills/")
    it = library.Item("a", ("2022 Spain", "x.heic"), "photo", NOW)
    assert manifest_out.build_manifest([(it, "1_x.jpg")])["items"][0]["path"] == "2022 Spain/x.heic"


def test_seen_is_never_reset_but_used_is():
    st = state.State()
    st.mark_used("photo", ["a", "b"])
    st.mark_used("photo", ["c"], cycle_reset=True)                 # a new cycle: 'used' restarts, 'seen' keeps everything
    assert st.used["photo"] == {"c"} and st.seen["photo"] == {"a", "b", "c"}
    back = state.State.from_dict(st.to_dict())
    assert back.seen["photo"] == {"a", "b", "c"} and back.used["photo"] == {"c"}
    old = state.State.from_dict({"used": {"photo": ["x", "y"]}})   # saved before 'seen' existed
    assert old.seen["photo"] == {"x", "y"}


def test_page_extras_are_off_by_default():
    d = const.DEFAULT_OPTIONS
    assert d[const.OPT_MODE_ENTITY] == "" and d[const.OPT_EXIT_HELPER] == "" and d[const.OPT_CLEAN_ENTITIES] == []
    assert d[const.OPT_MODE_FOLDER] == "/local/webmedia/" and d[const.OPT_EXIT_MINUTES] == 10
