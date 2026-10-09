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

const fn_figlet = {
  method: "POST",
  url: "http://10.83.80.151:31112/function/figlet",
  body: "Hello DFaaS!",
  headers: {"Content-Type": "text/plain"},
};
const success_rate_figlet = new Rate("success_rate_figlet");
const latency_figlet = new Trend("latency_figlet");
const request_count_figlet = new Counter("request_count_figlet");

export function exec_figlet() {
  const res = http.request(fn_figlet.method, fn_figlet.url, fn_figlet.body, { headers: fn_figlet.headers });
  const ok = res.status >= 200 && res.status < 300;
  success_rate_figlet.add(ok);
  latency_figlet.add(res.timings.duration);
  request_count_figlet.add(1);
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
    figlet: {
      executor: "constant-arrival-rate",
      rate: 5,
      timeUnit: "1s",
      duration: "20s",
      preAllocatedVUs: 5,
      maxVUs: 5,
      exec: "exec_figlet",
      tags: { function: "figlet" },
    },
  },
}
