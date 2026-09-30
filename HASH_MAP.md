# HASH_MAP: old and new commit ids

On 30 Sep 2026 the history was rewritten to edit commit messages only; the code and data are unchanged, as the identical tree hashes show. Run metadata and reports written before that date refer to the old commit ids listed here.

The 19 commits after 0fac7af were rewritten, oldest first. 0fac7af and all older commits, and the tag thesis-v1, keep their ids.

| Old commit | New commit | Tree (unchanged) | Branch head or tag at the rewrite | Date (UTC) | Subject |
|---|---|---|---|---|---|
| `d786de1b9de0c1ffb3694f3660392afade598a0c` | `fe3548be2976fd03314639122d626f2b4ba76974` | `e6a70d7664a1f81a49c32cb49c43f858da97ee6a` |  | 2026-09-23 07:44 | Add data-derived simulator calibration (calibration_v2.json) |
| `99e97a4e7fe1392d6a2107ded86d48c4ea0e65af` | `899be1a12320dad00586742dc4d72bb1ad1bcf76` | `a91a09430cf0f4063c03c5c78a53159931c53a5f` |  | 2026-09-23 07:47 | Simulator serves the Anthropic Messages API (/v1/messages) |
| `58358f254f844b00ceb122b51ff1fdbd40a2456c` | `3d32d9dbf3e4e0457133caef42d97080b65f3e7e` | `85a9e6943e042a542d797f8afb1f519d67fc3298` |  | 2026-09-23 07:47 | Use the same SDK singletons in real and simulated mode |
| `c133cd17bc5d850db1d0e711a8a913ba71b6df8a` | `63b696e8b7cf7500eacc6f563a4a6d967ec2f2d4` | `e195cf5859bc09c6a6182482eb572aeaa2fb34c1` |  | 2026-09-23 07:47 | Guard calibrate_simulator.py behind ALLOW_REAL_API=1 |
| `c3f283cb99b33f80bc453b2d471949c34734994d` | `3a0d67143aab7d00e2d57bbd834b615bda37b717` | `066e2a54a7408a454635ac8c85fbed753ff5f905` |  | 2026-09-23 07:47 | Add SDK contract tests against the simulator (T1) |
| `067fd788a758a3461c5a55a9424a5cdb54c86457` | `c8a8098f1fe521b152997ec4f8ad9bd18546282b` | `ced955538b16cf446c87165f487d0e6a06ee425c` |  | 2026-09-23 07:52 | Add per-request Locust log, in-flight tracking, uniform spawn and 250 ms monitor |
| `b9403800548f2b977c6a089206951410c7826f50` | `be2bf5e3cfda8d30288153e581505062b89a9111` | `6e62ec6d6679abbf1fd0d99911f5f6b6185545d3` |  | 2026-09-23 07:52 | Add multi-worker Gunicorn configurations (flask_mw, django_mw) |
| `64d35729818691d62ae3585ec5483b9a81163431` | `94c531774c10d1c99defa25d614bd2cb1a14cfbc` | `20dab28e87562a646770287a01de4862363a5e90` |  | 2026-09-23 07:55 | Add run_matrix.py orchestrator with server restart per run |
| `21a28680d19354fda4b077bdbfa2c3d4d1c4709a` | `3349f5f08ccf1e4fbaf9d15c818e26002fa20c08` | `7b5d98291aa9c97624cb04368daf6ce23d6c9bec` |  | 2026-09-23 08:07 | Simulator: schedule stream chunks on absolute deadlines |
| `f2483c2826ebb901151854d51f9c6fd5de3506e5` | `95943c358e236699dc74190ed042f234e41473f3` | `a35267064ee4e69b0e14327dabd953f3ed1fd147` |  | 2026-09-23 08:16 | Add server-path tests: client lifetime, SSE framing, c = 1 timing (T2 to T4) |
| `fc921031788e8cc9ba91333fcff918b531a48b9a` | `9eac3ec88484de9f3ff9bdffae9fa807a83002e5` | `69973607e1efec8535b4a29db0fdc79262ba8d9c` |  | 2026-09-23 08:26 | Add aggregate_v2.py (results_v2/) |
| `d42fff2f58c8cfb4772cc3e6542dd15ded760dc5` | `e085d0ce284d262f64e6acf01e4e2882bef53914` | `b627c1fd4194700e83b8c79914e4124071270397` |  | 2026-09-23 08:26 | Add validate_sim.py: simulated vs real at c = 1, 5, 10 |
| `2240d4e1fc372373ddd8065a3e5cfe748516001d` | `970111a57ea8bc210102f2a2bb7951ff01dca1a8` | `ed38544c94585c69ec7453ba8730ef8f8ca7218b` |  | 2026-09-23 08:27 | Add run_real_validation.sh (not run): FastAPI inference c = 25, real API |
| `10488bb877f8f1daaa1df59cf92d50ccd4bcfcaf` | `cf1e47e4e3661d30f264ca01f146dc4219c06d00` | `fa15da10c4f636c9f39bca0ab404a315a4c0f787` |  | 2026-09-23 09:50 | Real-API validation: same-day c = 1 anchors, phases, retry guard, budget |
| `ada7ab16b70a67c57c21c4235d95c1270f00236b` | `14f5663226f15467517d1d8f5a5f987a0c09f6da` | `d58bde152542d16763cb003c9eeeee6e6528cbb5` | tag v2-freeze | 2026-09-26 18:07 | v2-freeze: monotonic clock, clock guards, host clock rate, missing metrics |
| `14938f523b4cf9ef62c13e51b344465602f53a60` | `57ed3eb6014d20252f55bf005aee28dde5dba9c9` | `de45bd0c7a184d741ddc5212d34480cfc395ad0d` | tag v2-analysis | 2026-09-29 06:00 | Add v2 analysis and paper-preparation scripts (analysis only, no harness change) |
| `55237594e82d3dfa67a5f767a8c56e400913ef9a` | `a96228deb1ef1c6f8016ce50c8e229a5c57f3ce0` | `591b51ef47da03f37cb9f39072c2ee66f7ad054a` |  | 2026-09-30 10:53 | Add v2 data, aggregates, analysis outputs and audit scripts (unchanged) |
| `1e59517a5b61269397008b95a837795c3f23a4f5` | `af0eae6dab4aa9e19d3da9cb474411f2d1fc368f` | `189a3beeb4c97cc592f6fe82d12b885a934d8851` | branch rerun-v2 | 2026-09-30 10:53 | Add release documentation, licences and citation metadata |
| `5ea879267ade3ae786d4a5cfa1d824ac06ef4c29` | `9e0b840c7e71f2000f8af6c199edf506ed06c2a7` | `189a3beeb4c97cc592f6fe82d12b885a934d8851` | branch main | 2026-09-30 10:54 | Merge branch 'rerun-v2': v2 harness, data, analysis and release documentation |
