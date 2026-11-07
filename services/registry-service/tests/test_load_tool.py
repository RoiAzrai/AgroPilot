import asyncio
import csv
import json
import random
import socket
import statistics
import threading
import time
from collections import Counter

import httpx
import pytest
import uvicorn

from perf.load_test import (
    ENDPOINTS,
    EXIT_INVALID,
    EXIT_PASS,
    Heartbeat,
    Result,
    bootstrap_ci,
    build_client,
    build_schedule,
    classify_error,
    describe_error,
    detect_suspensions,
    errors_by_detail,
    errors_by_type,
    find_stalls,
    lag_stats,
    littles_law,
    parse_args,
    percentile,
    run,
    time_average_in_flight,
    verdict,
    write_timeline,
)

IDS = {
    "farms": ["farm-a", "farm-b"],
    "plots": ["plot-1", "plot-2", "plot-3", "plot-4"],
    "crops": ["tomato", "bell-pepper"],
    "soils": ["sand", "loam", "clay-loam"],
    "emitters": ["dripnet-pc-0.6", "dripnet-pc-1.0"],
}


def gaps(schedule) -> list[float]:
    times = [arrival.t for arrival in schedule]
    return [b - a for a, b in zip(times, times[1:])]


# --- Schedule -------------------------------------------------------------------


def test_same_seed_gives_identical_schedule():
    assert build_schedule(10, 60, "poisson", 1, IDS) == build_schedule(10, 60, "poisson", 1, IDS)


def test_different_seed_gives_different_schedule():
    assert build_schedule(10, 60, "poisson", 1, IDS) != build_schedule(10, 60, "poisson", 2, IDS)


def test_poisson_and_constant_share_the_request_sequence():
    poisson = build_schedule(10, 60, "poisson", 1, IDS)
    constant = build_schedule(10, 60, "constant", 1, IDS)
    n = min(len(poisson), len(constant))
    assert [(a.endpoint, a.path) for a in poisson[:n]] == [
        (a.endpoint, a.path) for a in constant[:n]
    ]
    assert [a.t for a in poisson[:n]] != [a.t for a in constant[:n]]


def test_poisson_gaps_are_exponential():
    intervals = gaps(build_schedule(10, 2000, "poisson", 1, IDS))
    assert len(intervals) > 19_000
    mean = statistics.fmean(intervals)
    assert mean == pytest.approx(0.1, rel=0.03)
    assert statistics.pstdev(intervals) / mean == pytest.approx(1.0, abs=0.05)


def test_constant_gaps_have_no_variation():
    intervals = gaps(build_schedule(10, 100, "constant", 1, IDS))
    assert len(intervals) == 999
    assert statistics.fmean(intervals) == pytest.approx(0.1)
    assert statistics.pstdev(intervals) / statistics.fmean(intervals) < 1e-9


def test_endpoint_mix_is_uniform():
    schedule = build_schedule(10, 2000, "poisson", 1, IDS)
    counts = Counter(arrival.endpoint for arrival in schedule)
    assert set(counts) == {name for name, _, _ in ENDPOINTS}
    expected = len(schedule) / len(ENDPOINTS)
    assert all(abs(count - expected) <= 0.1 * expected for count in counts.values())


def test_by_id_paths_use_known_ids():
    schedule = build_schedule(10, 200, "poisson", 1, IDS)
    by_farm = {a.path for a in schedule if a.endpoint == "plots_by_farm"}
    assert by_farm == {"/v1/plots?farm_id=farm-a", "/v1/plots?farm_id=farm-b"}
    emitters = {a.path for a in schedule if a.endpoint == "emitter_by_id"}
    assert emitters == {"/v1/emitters/dripnet-pc-0.6", "/v1/emitters/dripnet-pc-1.0"}


# --- Statistics -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("p", "expected"),
    [(0, 15), (30, 20), (40, 20), (50, 35), (95, 50), (100, 50)],
)
def test_nearest_rank_percentile(p, expected):
    assert percentile([50, 15, 40, 20, 35], p) == expected


def test_percentile_edge_cases():
    assert percentile([7.5], 50) == 7.5
    assert percentile([7.5], 99) == 7.5
    assert percentile([], 95) is None


def result(scheduled: float, done: float) -> Result:
    return Result("farms_list", scheduled, scheduled, done, True, 200, None)


def test_littles_law_on_a_hand_built_example():
    # Three requests in [0, 4], each in the system for 2 s: L = 6 / 4 = 1.5, lambda = 3/4, W = 2.
    measured = [result(0, 2), result(1, 3), result(2, 4)]
    little = littles_law(measured, 0, 4)
    assert little["measured_l"] == pytest.approx(1.5)
    assert little["lambda_w"] == pytest.approx(1.5)
    assert little["relative_difference"] == pytest.approx(0)


def test_in_flight_is_clipped_to_the_window():
    # The second request runs from 3 to 6, but only 3..4 is inside the window.
    assert time_average_in_flight([(0, 2), (3, 6)], 0, 4) == pytest.approx(0.75)
    assert time_average_in_flight([(-1, 1)], 0, 4) == pytest.approx(0.25)


# --- Diagnostics ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "status", "expected"),
    [
        (None, 200, None),
        (None, 404, "http_404"),
        (None, 503, "http_503"),
        (httpx.ReadTimeout("slow"), None, "timeout"),
        (httpx.ConnectTimeout("slow connect"), None, "timeout"),
        (httpx.PoolTimeout("no connection"), None, "timeout"),
        (httpx.ConnectError("refused"), None, "connect_error"),
        (httpx.ReadError("reset"), None, "transport_error"),
        (httpx.RemoteProtocolError("bad response"), None, "transport_error"),
    ],
)
def test_classify_error(exc, status, expected):
    assert classify_error(exc, status) == expected


def record(scheduled, sent, done, error=None) -> Result:
    return Result("farms_list", scheduled, sent, done, error is None, 200, error)


def test_errors_by_type_counts_only_failures():
    results = [
        record(0, 0, 0.1),
        record(1, 1, 6, "timeout"),
        record(2, 2, 7, "timeout"),
        record(3, 3, 3.1, "http_503"),
    ]
    assert errors_by_type(results) == {"timeout": 2, "http_503": 1}


def test_find_stalls_groups_consecutive_late_requests():
    results = [
        record(0.0, 0.0, 0.01),     # on time
        record(1.0, 1.25, 1.27),    # 250 ms late: stall 1 starts
        record(1.1, 1.25, 1.30),    # 150 ms late
        record(1.2, 1.25, 1.65),    # 50 ms late: ends stall 1, but it was sent inside it
        record(2.0, 2.0, 2.01),     # on time
        record(3.0, 3.5, 3.52),     # 500 ms late: stall 2, last in the run
    ]
    stalls = find_stalls(results)
    assert len(stalls) == 2
    first, second = stalls
    assert first["start_s"] == pytest.approx(1.0)
    assert first["duration_s"] == pytest.approx(0.25)
    assert first["requests"] == 2
    assert first["max_lag_ms"] == pytest.approx(250)
    assert first["max_service_ms"] == pytest.approx(400)
    assert second["start_s"] == pytest.approx(3.0)
    assert second["duration_s"] == pytest.approx(0.5)
    assert second["requests"] == 1
    assert second["max_lag_ms"] == pytest.approx(500)
    assert second["max_service_ms"] == pytest.approx(20)


def pool_keepalive_expiry(client: httpx.AsyncClient) -> float:
    # httpx passes Limits.keepalive_expiry to the httpcore pool it creates.
    return client._transport._pool._keepalive_expiry


@pytest.mark.parametrize(("argv", "expected"), [([], 4.0), (["--keepalive-expiry", "2.5"], 2.5)])
def test_client_keepalive_comes_from_the_option(argv, expected):
    args = parse_args(argv)
    assert args.keepalive_expiry == expected
    client = build_client(args)
    try:
        assert pool_keepalive_expiry(client) == expected
    finally:
        asyncio.run(client.aclose())


def test_default_client_keepalive_is_shorter_than_uvicorns():
    assert parse_args([]).keepalive_expiry < uvicorn.Config(app=None).timeout_keep_alive


def raised_from(exc: BaseException, cause: BaseException) -> BaseException:
    """Return exc as it looks after `raise exc from cause`."""
    try:
        raise exc from cause
    except BaseException as caught:
        return caught


@pytest.mark.parametrize(
    ("exc", "status", "expected"),
    [
        (None, 200, None),
        (None, 503, "HTTP 503"),
        (
            httpx.RemoteProtocolError("Server disconnected without sending a response."),
            None,
            "RemoteProtocolError: Server disconnected without sending a response.",
        ),
        (
            raised_from(httpx.ReadError(""), ConnectionResetError(104, "Connection reset by peer")),
            None,
            "ReadError: (no message) (caused by ConnectionResetError: "
            "[Errno 104] Connection reset by peer)",
        ),
        (
            raised_from(httpx.ConnectError("All connection attempts failed"), OSError("refused")),
            None,
            "ConnectError: All connection attempts failed (caused by OSError: refused)",
        ),
    ],
    ids=["ok", "http-status", "no-cause", "empty-message-with-cause", "with-cause"],
)
def test_describe_error(exc, status, expected):
    assert describe_error(exc, status) == expected


def test_errors_by_detail_counts_failures_only():
    results = [
        record(0, 0, 0.1),
        Result("farm_by_id", 1, 1, 1.007, False, None, "transport_error",
               "RemoteProtocolError: Server disconnected without sending a response."),
        Result("farm_by_id", 2, 2, 2.007, False, None, "transport_error",
               "RemoteProtocolError: Server disconnected without sending a response."),
        Result("crops_list", 3, 3, 3.01, False, 503, "http_503", "HTTP 503"),
    ]
    assert errors_by_detail(results) == {
        "RemoteProtocolError: Server disconnected without sending a response.": 2,
        "HTTP 503": 1,
    }
    assert errors_by_type(results) == {"transport_error": 2, "http_503": 1}


def test_timeline_has_an_error_detail_column(tmp_path):
    path = tmp_path / "run.csv"
    write_timeline(path, [
        record(0, 0, 0.1),
        Result("farm_by_id", 1, 1, 1.007, False, None, "transport_error", "ReadError: (no message)"),
    ], 0, 10)
    rows = list(csv.DictReader(path.open()))
    assert [row["error_detail"] for row in rows] == ["", "ReadError: (no message)"]


def test_default_lag_bound_is_10_ms():
    assert parse_args([]).max_lag_ms == 10


def test_lag_stats_reports_p50_p99_max_and_validity():
    # 100 requests: 98 sent 1 ms late, one 10 ms late, one 50 ms late.
    lags_s = [0.001] * 98 + [0.010, 0.050]
    # Scheduled at 0 so that sent - scheduled is exactly the lag, with no rounding.
    measured = [record(0, lag, lag + 0.01) for lag in lags_s]
    lag = lag_stats(measured, 10)
    assert lag["p50_ms"] == pytest.approx(1)
    assert lag["p99_ms"] == pytest.approx(10)
    assert lag["max_ms"] == pytest.approx(50)
    assert lag["valid"] is True  # p99 exactly at the bound is still valid
    assert lag_stats(measured, 9.9)["valid"] is False


# --- Suspension detection -------------------------------------------------------

WALL0 = 1_800_000_000.0  # any fixed Unix time


def beats_every_second(n: int, start_mono: float = 0.0, start_wall: float = WALL0) -> list[Heartbeat]:
    return [Heartbeat(start_mono + i, start_wall + i) for i in range(n)]


def test_no_suspension():
    assert detect_suspensions(beats_every_second(330), run_end_s=320) == []


def test_one_suspension_inside_the_run():
    # 8 minutes pass on the wall clock between the beats at 170 s and 171 s.
    beats = beats_every_second(171) + [
        Heartbeat(170 + 1 + i, WALL0 + 170 + 1 + 480 + i) for i in range(150)
    ]
    found = detect_suspensions(beats, run_end_s=320)
    assert len(found) == 1
    assert found[0]["start_s"] == pytest.approx(170)
    assert found[0]["duration_s"] == pytest.approx(480)
    assert found[0]["kind"] == "clock_gap"
    assert found[0]["in_run"] is True


def test_suspension_after_the_run_is_reported_but_not_in_run():
    beats = beats_every_second(325) + [Heartbeat(325, WALL0 + 324 + 60)]
    found = detect_suspensions(beats, run_end_s=320)
    assert len(found) == 1
    assert found[0]["in_run"] is False


def test_small_clock_jitter_does_not_trigger():
    rng = random.Random(3)
    beats, wall = [], WALL0
    for i in range(320):
        beats.append(Heartbeat(float(i), wall))
        wall += 1.0 + rng.uniform(-0.3, 0.3)  # NTP slews and scheduling jitter
    beats.append(Heartbeat(320.0, wall + 0.9))  # wall clock 0.9 s ahead: under the 1 s bound
    assert detect_suspensions(beats, run_end_s=320) == []


def test_missing_heartbeats_count_as_a_suspension():
    # Both clocks moved 3 s, but no heartbeat came: the event loop was not running.
    beats = beats_every_second(10) + [Heartbeat(12.0, WALL0 + 12.0)]
    found = detect_suspensions(beats, run_end_s=320)
    assert [(s["kind"], s["duration_s"]) for s in found] == [("no_heartbeat", pytest.approx(3.0))]


def test_suspension_inside_the_run_makes_it_invalid():
    rows = {"OVERALL": {"errors": 0, "latency_ms": {"p95": 20.0}}}
    lag = {"valid": True, "p99_ms": 2.0, "bound_ms": 10.0}
    inside = {"start_s": 170.0, "duration_s": 480.0, "wall_start": "x", "kind": "clock_gap", "in_run": True}
    code, reasons = verdict(rows, lag, 100, [inside])
    assert code == EXIT_INVALID
    assert "VM suspended for 480.0 s" in reasons[0]
    assert verdict(rows, lag, 100, [{**inside, "in_run": False}]) == (EXIT_PASS, [])


# --- Bootstrap confidence interval -------------------------------------------------


def latencies(n: int, seed: int = 11) -> list[float]:
    rng = random.Random(seed)
    return [rng.lognormvariate(2.5, 0.4) for _ in range(n)]


def test_bootstrap_same_seed_same_interval():
    values = latencies(300)
    assert bootstrap_ci(values, random.Random("1:bootstrap")) == bootstrap_ci(
        values, random.Random("1:bootstrap")
    )


def test_bootstrap_interval_contains_the_point_estimate():
    values = latencies(300)
    low, high = bootstrap_ci(values, random.Random("1:bootstrap"))
    assert low <= percentile(values, 95) <= high
    assert low < high


def test_bootstrap_constant_data_has_zero_width():
    assert bootstrap_ci([12.5] * 200, random.Random("1:bootstrap")) == [12.5, 12.5]


def test_bootstrap_fewer_samples_give_a_wider_interval():
    many = bootstrap_ci(latencies(3000), random.Random("1:bootstrap"))
    few = bootstrap_ci(latencies(100), random.Random("1:bootstrap"))
    assert few[1] - few[0] > many[1] - many[0]


def test_bootstrap_without_values_returns_none():
    assert bootstrap_ci([], random.Random("1:bootstrap")) is None


def test_find_stalls_ignores_lag_at_or_below_the_threshold():
    results = [record(0, 0.1, 0.2), record(1, 1.05, 1.1), record(2, 2.0, 2.1)]
    assert find_stalls(results) == []


# --- End to end against a stub server -------------------------------------------


async def slow_stub(scope, receive, send):
    """Every GET sleeps 50 ms. Paths with two slashes are lists, three are by-id."""
    await asyncio.sleep(0.05)
    path = scope["path"]
    payload = [{"id": "a"}, {"id": "b"}] if path.count("/") == 2 else {"id": "a"}
    body = json.dumps(payload).encode()
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"application/json")],
    })
    await send({"type": "http.response.body", "body": body})


@pytest.fixture
def stub_url():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    config = uvicorn.Config(slow_stub, lifespan="off", log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    # The bound socket itself goes to uvicorn, so no other process can take the port.
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started:
        assert time.monotonic() < deadline, "stub server did not start"
        time.sleep(0.01)
    yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    server.should_exit = True
    thread.join(5)
    sock.close()


def test_measures_a_known_latency(stub_url):
    args = parse_args([
        "--base-url", stub_url, "--rate", "20", "--warmup", "0.5", "--duration", "2.5",
        "--seed", "7",
    ])
    report = run(args)
    overall = report["endpoints"]["OVERALL"]
    assert overall["requests"] > 20
    assert overall["errors"] == 0
    assert 45 <= overall["latency_ms"]["p50"] <= 90
    assert report["errors_by_type"] == {}
    assert report["suspensions"] == []
    assert report["heartbeats"] >= 3
    low, high = overall["latency_ms"]["p95_ci"]
    assert low <= overall["latency_ms"]["p95"] <= high
    assert report["metadata"]["seed"] == 7
