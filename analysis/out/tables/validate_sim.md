| fw | endpoint | c | metric | sim | real (thesis) | diff, % | cause (INFERRED) |
|---|---|--:|---|--:|--:|--:|---|
| flask | stream | 1 | X, req/s | 0.358 | 0.339 | +5.89 | J |
| flask | stream | 10 | mean, ms | 21,308.4 | 22,492.3 | -5.26 | Q |
| flask | pipeline | 5 | mean, ms | 12,278.3 | 13,096.4 | -6.25 | Q |
| flask | pipeline | 5 | X, req/s | 0.361 | 0.343 | +5.13 | J |
| flask | pipeline | 10 | mean, ms | 21,192.2 | 22,875.4 | -7.36 | Q |
| flask | pipeline | 10 | X, req/s | 0.361 | 0.336 | +7.29 | J |
| django | stream | 1 | mean, ms | 2,789.5 | 2,965.3 | -5.93 | J |
| django | stream | 1 | X, req/s | 0.358 | 0.338 | +6.14 | J |
| django | stream | 1 | TTFT, ms | 566.0 | 673.2 | -15.92 | P |
| django | stream | 5 | mean, ms | 12,347.1 | 13,234.7 | -6.71 | Q |
| django | stream | 5 | X, req/s | 0.359 | 0.334 | +7.34 | J |
| django | stream | 10 | mean, ms | 21,309.5 | 23,054.3 | -7.57 | Q |
| django | stream | 10 | X, req/s | 0.359 | 0.339 | +5.72 | J |
| django | stream | 10 | TTFT, ms | 25,648.4 | 27,115.2 | -5.41 | Q, P |
| django | pipeline | 1 | mean, ms | 2,775.5 | 2,974.5 | -6.69 | J |
| django | pipeline | 1 | X, req/s | 0.360 | 0.333 | +8.02 | J |
| django | pipeline | 5 | mean, ms | 12,282.1 | 13,223.9 | -7.12 | Q |
| django | pipeline | 5 | X, req/s | 0.361 | 0.336 | +7.36 | J |
| django | pipeline | 10 | mean, ms | 21,199.4 | 23,238.2 | -8.77 | Q |
| django | pipeline | 10 | X, req/s | 0.361 | 0.334 | +8.02 | J |
| fastapi | stream | 1 | TTFT, ms | 567.4 | 515.5 | +10.07 | P |
| fastapi | stream | 5 | TTFT, ms | 566.8 | 509.9 | +11.16 | P |
| fastapi | stream | 10 | mean, ms | 2,791.8 | 2,985.3 | -6.48 | J |
| fastapi | stream | 10 | TTFT, ms | 567.0 | 511.2 | +10.92 | P |
| fastapi | pipeline | 1 | X, req/s | 0.360 | 0.342 | +5.45 | J |
| tornado | inference | 1 | mean, ms | 2,888.7 | 3,049.8 | -5.28 | J |
| tornado | inference | 1 | X, req/s | 0.346 | 0.322 | +7.66 | J |
| tornado | inference | 5 | median, ms | 2,887.3 | 2,700.0 | +6.94 | B |
| tornado | inference | 10 | median, ms | 2,886.8 | 2,700.0 | +6.92 | B |
| tornado | stream | 1 | TTFT, ms | 566.3 | 469.9 | +20.50 | P |
| tornado | stream | 5 | TTFT, ms | 565.8 | 517.1 | +9.42 | P |
| tornado | stream | 10 | TTFT, ms | 565.7 | 506.0 | +11.80 | P |
