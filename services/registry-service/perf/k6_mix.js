// k6 cross-check of load_test.py (NFR-1.1 measurement tool), written for k6 v2.3.0.
//
// The same 11 GET endpoints with equal weight and the same tag names as
// load_test.py, sent at a constant arrival rate (open model). Only the
// "measure" scenario counts; "warmup" runs first and is excluded.
//
// Usage, from services/registry-service (the harness run_k6_crosscheck.sh does this):
//   k6 run --no-usage-report -e BASE_URL=http://127.0.0.1:8000 -e WARMUP=20 \
//     -e DURATION=300 -e SUMMARY_OUT=perf/results/k6-run1.json perf/k6_mix.js
//
// Differences from load_test.py that are deliberate or unavoidable:
// - No seed. k6 picks endpoints and ids with Math.random, so it does not send the
//   same request sequence as our tool. We compare latency DISTRIBUTIONS per
//   endpoint, not individual requests.
// - Constant rate only (constant-arrival-rate), so compare with our
//   --arrival constant runs, not Poisson.
// - http_req_duration = sending + waiting + receiving, measured from the actual
//   send. It excludes http_req_blocked (waiting for a free connection, DNS) and
//   http_req_connecting (TCP setup). The matching number in our report is
//   "Service time from actual send time", which does include pool waiting and
//   connection setup when they happen.
//   The report also keeps http_req_blocked and http_req_connecting, so the time
//   k6 leaves out is visible.
// - Percentiles: k6 interpolates between values; load_test.py uses nearest rank.
//   Both use successful requests (status 200) only.
// - Connection reuse: k6 defaults (keep-alive on, connections reused). Each VU
//   has its own connections, so k6 may hold several where our tool mostly holds
//   one. k6 keeps idle connections longer than uvicorn's 5 s keep-alive, so the
//   keep-alive race found in our tool (judgment log 19) may appear here. Errors
//   are NOT hidden: each one is logged with its scenario, k6 error_code and
//   message (see logError), and counted.

import exec from 'k6/execution';
import http from 'k6/http';
import { Counter } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL;
const WARMUP = parseInt(__ENV.WARMUP || '20', 10);
const DURATION = parseInt(__ENV.DURATION || '300', 10);
const RATE = 10; // requests per second, as NFR-1.1 and load_test.py
const SUMMARY_OUT = __ENV.SUMMARY_OUT || 'perf/results/k6-summary.json';
const K6_VERSION = __ENV.K6_VERSION || 'unknown (pass -e K6_VERSION)';

// One iteration = one request, so at 10/s with ~10-20 ms responses fewer than one
// VU is busy on average. 10 pre-allocated VUs (one second's worth of arrivals) and
// a ceiling of 50 leave a wide margin without being wasteful; if k6 ever needs
// more than it has, it drops the iteration and dropped_iterations counts it.
const PRE_ALLOCATED_VUS = 10;
const MAX_VUS = 50;

// Same names, paths and id sources as ENDPOINTS in load_test.py.
const ENDPOINTS = [
  ['farms_list', '/v1/farms', null],
  ['farm_by_id', '/v1/farms/{id}', 'farms'],
  ['plots_list', '/v1/plots', null],
  ['plot_by_id', '/v1/plots/{id}', 'plots'],
  ['plots_by_farm', '/v1/plots?farm_id={id}', 'farms'],
  ['crops_list', '/v1/crops', null],
  ['crop_by_id', '/v1/crops/{id}', 'crops'],
  ['soils_list', '/v1/soils', null],
  ['soil_by_id', '/v1/soils/{id}', 'soils'],
  ['emitters_list', '/v1/emitters', null],
  ['emitter_by_id', '/v1/emitters/{id}', 'emitters'],
];
const ID_SOURCES = {
  farms: '/v1/farms',
  plots: '/v1/plots',
  crops: '/v1/crops',
  soils: '/v1/soils',
  emitters: '/v1/emitters',
};

// Like load_test.py: only 200 is a success (k6's default accepts 200-399).
http.setResponseCallback(http.expectedStatuses(200));

const requestErrors = new Counter('request_errors');

const measure = 'scenario:measure';
// Durations of successful requests only (status 200), as load_test.py's percentiles.
const ok = 'expected_response:true';
const thresholds = {
  [`http_req_failed{${measure}}`]: ['rate==0'],
  [`dropped_iterations{${measure}}`]: ['count==0'],
  [`http_req_duration{${measure},${ok}}`]: ['p(95)<100'],
  [`http_reqs{${measure}}`]: ['count>=0'], // reporting only: makes k6 export the count
  [`request_errors{${measure}}`]: ['count>=0'], // reporting only
  [`http_req_blocked{${measure}}`]: ['max>=0'], // reporting only: time k6 leaves out
  [`http_req_connecting{${measure}}`]: ['max>=0'], // reporting only
};
for (const [name] of ENDPOINTS) {
  const tags = `${measure},endpoint:${name}`;
  thresholds[`http_req_duration{${tags},${ok}}`] = ['p(95)<100'];
  thresholds[`http_req_failed{${tags}}`] = ['rate==0'];
  thresholds[`http_reqs{${tags}}`] = ['count>=0']; // reporting only
}

const scenario = (startTime, duration) => ({
  executor: 'constant-arrival-rate',
  rate: RATE,
  timeUnit: '1s',
  duration: `${duration}s`,
  preAllocatedVUs: PRE_ALLOCATED_VUS,
  maxVUs: MAX_VUS,
  startTime: `${startTime}s`,
});

export const options = {
  scenarios: {
    warmup: scenario(0, WARMUP),
    measure: scenario(WARMUP, DURATION), // starts right after the warm-up
  },
  thresholds,
  summaryTrendStats: ['count', 'min', 'med', 'avg', 'p(50)', 'p(95)', 'p(99)', 'max'],
};

export function setup() {
  if (!BASE_URL) {
    throw new Error('BASE_URL is not set (pass -e BASE_URL=http://host:port)');
  }
  // Ids through the API's own list endpoints (black-box), once, like discover_ids().
  const ids = {};
  for (const [source, path] of Object.entries(ID_SOURCES)) {
    const res = http.get(`${BASE_URL}${path}`, { tags: { endpoint: 'setup' } });
    if (res.status !== 200) {
      throw new Error(`GET ${path} returned ${res.status} ${res.error || ''}`);
    }
    ids[source] = res.json().map((item) => item.id);
    if (ids[source].length === 0) {
      throw new Error(`GET ${path} returned no rows; cannot request by id`);
    }
  }
  return ids;
}

function pick(list) {
  return list[Math.floor(Math.random() * list.length)]; // unseeded, see the header
}

function logError(name, res) {
  // One line per failed request, on stderr: the harness keeps it in <run>.log.
  console.error(
    `request_error scenario=${exec.scenario.name} endpoint=${name} status=${res.status} ` +
      `error_code=${res.error_code} ` +
      `error=${JSON.stringify(res.error || '')}`,
  );
}

export default function (ids) {
  const [name, template, source] = pick(ENDPOINTS);
  const path =
    source === null ? template : template.replace('{id}', encodeURIComponent(pick(ids[source])));
  // `name` groups the URL by template so k6 does not create one series per id.
  const res = http.get(`${BASE_URL}${path}`, {
    tags: { endpoint: name, name: template },
    timeout: '5s', // same per-request timeout as load_test.py
  });
  if (res.status !== 200) {
    requestErrors.add(1, { endpoint: name, error_code: String(res.error_code) });
    logError(name, res);
  }
}

// --- Summary ---------------------------------------------------------------------

function trend(metrics, key) {
  const m = metrics[key];
  // k6 reports 0 for every stat of an empty submetric; null says "no data".
  if (!m || !m.values.count) return null;
  const v = m.values;
  return { p50: v['p(50)'], p95: v['p(95)'], p99: v['p(99)'], max: v.max, mean: v.avg };
}

function count(metrics, key) {
  const m = metrics[key];
  return m ? m.values.count : 0;
}

function failed(metrics, key) {
  // http_req_failed is a Rate: "passes" counts the true values, i.e. failed requests.
  const m = metrics[key];
  return m ? m.values.passes : 0;
}

function buildReport(data) {
  const metrics = data.metrics;
  const endpoints = {};
  for (const [name] of ENDPOINTS) {
    const tags = `${measure},endpoint:${name}`;
    endpoints[name] = {
      requests: count(metrics, `http_reqs{${tags}}`),
      errors: failed(metrics, `http_req_failed{${tags}}`),
      http_req_duration_ms: trend(metrics, `http_req_duration{${tags},${ok}}`),
    };
  }
  endpoints.OVERALL = {
    requests: count(metrics, `http_reqs{${measure}}`),
    errors: failed(metrics, `http_req_failed{${measure}}`),
    http_req_duration_ms: trend(metrics, `http_req_duration{${measure},${ok}}`),
  };
  const thresholdsFailed = Object.entries(metrics)
    .filter(([, m]) => m.thresholds && Object.values(m.thresholds).some((t) => !t.ok))
    .map(([key]) => key);
  return {
    tool: 'k6',
    metadata: {
      k6_version: K6_VERSION,
      base_url: BASE_URL,
      executor: 'constant-arrival-rate',
      rate: RATE,
      warmup_s: WARMUP,
      duration_s: DURATION,
      pre_allocated_vus: PRE_ALLOCATED_VUS,
      max_vus: MAX_VUS,
      timeout_s: 5,
      seed: null,
    },
    endpoints,
    // Time outside http_req_duration: waiting for a connection, and TCP setup.
    http_req_blocked_ms: trend(metrics, `http_req_blocked{${measure}}`),
    http_req_connecting_ms: trend(metrics, `http_req_connecting{${measure}}`),
    dropped_iterations: count(metrics, `dropped_iterations{${measure}}`),
    request_errors: count(metrics, `request_errors{${measure}}`),
    thresholds_failed: thresholdsFailed,
    valid: count(metrics, `dropped_iterations{${measure}}`) === 0,
    k6_summary: data, // the full k6 summary, unmodified
  };
}

function fmt(value) {
  return value === null || value === undefined ? '-' : value.toFixed(1);
}

function formatText(report) {
  const lines = [
    `k6 ${report.metadata.k6_version}, measurement scenario only (http_req_duration, ms)`,
    `${'endpoint'.padEnd(15)}${'requests'.padStart(9)}${'errors'.padStart(7)}` +
      ['p50', 'p95', 'p99', 'max'].map((k) => k.padStart(8)).join(''),
  ];
  for (const [name, row] of Object.entries(report.endpoints)) {
    const d = row.http_req_duration_ms || {};
    lines.push(
      `${name.padEnd(15)}${String(row.requests).padStart(9)}${String(row.errors).padStart(7)}` +
        [d.p50, d.p95, d.p99, d.max].map((v) => fmt(v).padStart(8)).join(''),
    );
  }
  const blocked = report.http_req_blocked_ms || {};
  const connecting = report.http_req_connecting_ms || {};
  lines.push(
    `outside http_req_duration: http_req_blocked p95 ${fmt(blocked.p95)} max ${fmt(blocked.max)}, ` +
      `http_req_connecting p95 ${fmt(connecting.p95)} max ${fmt(connecting.max)}`,
  );
  lines.push(`dropped_iterations: ${report.dropped_iterations}`);
  lines.push(
    'thresholds failed: ' +
      (report.thresholds_failed.length ? report.thresholds_failed.join(', ') : 'none'),
  );
  return lines.join('\n') + '\n';
}

export function handleSummary(data) {
  const report = buildReport(data);
  return {
    stdout: formatText(report),
    [SUMMARY_OUT]: JSON.stringify(report, null, 2) + '\n',
  };
}
