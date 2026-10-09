import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Trend, Counter } from "k6/metrics";

const fn_env = {
  method: "GET",
  url: "http://10.83.80.151:31112/function/env",
  body: "",
  headers: {},
};
const success_rate_env = new Rate("success_rate_env");
const latency_env = new Trend("latency_env");
const request_count_env = new Counter("request_count_env");

export function exec_env() {
  const res = http.request(fn_env.method, fn_env.url, fn_env.body, { headers: fn_env.headers });
  const ok = res.status >= 200 && res.status < 300;
  success_rate_env.add(ok);
  latency_env.add(res.timings.duration);
  request_count_env.add(1);
  check(res, { "status is 2xx": (r) => r.status >= 200 && r.status < 300 });
}

export const options = {
  scenarios: {
    env: {
      executor: "constant-arrival-rate",
      rate: 1,
      timeUnit: "1s",
      duration: "20s",
      preAllocatedVUs: 1,
      maxVUs: 1,
      exec: "exec_env",
      tags: { function: "env" },
    },
  },
}
