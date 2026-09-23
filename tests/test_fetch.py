import json
from pathlib import Path

import pytest

from bases_engine import config
from bases_engine.fetch import FetchError, ResultsClient, _downloads_today, _record_download, download_raw
from bases_engine.util import sha256_json_compact


class _Resp:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload

    def json(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_content(self, n):
        yield json.dumps(self._payload).encode()


class _Session:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def get(self, url, **kw):
        self.calls.append(url)
        return self.responses[Path(url).name]


def test_download_budget_is_enforced(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    for _ in range(config.DOWNLOAD_BUDGET_PER_DAY):
        _record_download(cache, "turf_bench.db", "abc")
    assert _downloads_today(cache, "turf_bench.db") == config.DOWNLOAD_BUDGET_PER_DAY
    assert _downloads_today(cache, "benchmark_report.json") == 0
    with pytest.raises(FetchError, match="budget"):
        download_raw("abc", "turf_bench.db", cache / "abc" / "turf_bench.db", cache_dir=cache, session=_Session({}))


def test_download_uses_sha_not_main(tmp_path):
    cache = tmp_path / "cache"
    s = _Session({"benchmark_report.json": _Resp(200, {"historical_logs": []})})
    dest = download_raw("deadbeef", "benchmark_report.json", cache / "deadbeef" / "benchmark_report.json", cache_dir=cache, session=s, base_url="https://raw.example/repo")
    assert s.calls == ["https://raw.example/repo/deadbeef/benchmark_report.json"]
    assert json.loads(dest.read_text()) == {"historical_logs": []}


def test_results_client_throttles_to_one_request_per_minute():
    sleeps, clock = [], [0.0]
    courses = [{"course_id": "R1C1_20092026_X"}]
    day = {"courses": courses, "empreinte_sha256": sha256_json_compact(courses)}
    s = _Session({"index.json": _Resp(200, {"empreinte_sha256": "x"}), "2026-09-20.json": _Resp(200, day)})
    c = ResultsClient(session=s, sleep=sleeps.append, clock=lambda: clock[0])
    c.manifest()
    clock[0] += 10
    c.day("2026-09-20")
    assert sleeps == [50.0]
    assert c.requests_made == 2


def test_results_client_rejects_bad_fingerprint():
    s = _Session({"2026-09-20.json": _Resp(200, {"courses": [{"a": 1}], "empreinte_sha256": "0" * 64})})
    c = ResultsClient(session=s, sleep=lambda x: None)
    with pytest.raises(FetchError, match="empreinte"):
        c.day("2026-09-20")


def test_results_client_reads_local_fixture(fixtures_dir):
    c = ResultsClient(base_url=f"file://{fixtures_dir / 'resultats'}")
    man = c.manifest()
    assert "2026-09-20" in man["journees"] and man["journees"]["2026-09-20"]["empreinte_sha256"]
    day = c.day("2026-09-20", expected_fingerprint=man["journees"]["2026-09-20"]["empreinte_sha256"])
    assert day["nb_courses"] == 72 and day["courses"][0]["statut"]["definitive"]
    with pytest.raises(FetchError, match="≠ manifeste"):
        c.day("2026-09-19", expected_fingerprint="0" * 64)


def test_day_read_recovers_from_manifest_race(tmp_path, fixtures_dir):
    """Manifeste lu, puis journée régénérée par le producteur avant notre lecture : on relit le manifeste et la journée."""
    import json, shutil
    from bases_engine.pipeline import _read_day_coherent
    d = tmp_path / "res"; shutil.copytree(fixtures_dir / "resultats", d)
    c = ResultsClient(base_url=f"file://{d}")
    man = c.manifest()
    stale_fp = "0" * 64                                   # empreinte périmée (celle du manifeste lu avant la régénération)
    data, fp = _read_day_coherent(c, "2026-09-20", stale_fp)
    assert data is not None and fp == man["journees"]["2026-09-20"]["empreinte_sha256"] and data["nb_courses"] == 72
    # écart persistant : on renonce sans lever
    m = json.loads((d / "index.json").read_text(encoding="utf-8")); m["journees"]["2026-09-20"]["empreinte_sha256"] = "1" * 64
    (d / "index.json").write_text(json.dumps(m), encoding="utf-8")
    assert _read_day_coherent(c, "2026-09-20", "2" * 64) == (None, None)
