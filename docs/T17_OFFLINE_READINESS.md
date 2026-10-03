# T17 — M5 readiness offline

T17 verifies the frozen E01–E14 inputs, the 42 planned attempts, model/runtime
version bindings, the existing application call limits, the cost estimate and
output paths. It then runs the deterministic baseline over the frozen scenarios.
This command cannot start an agent or make a provider request.

From the project root, use a fresh directory under `deliverables/verification`:

```powershell
.\.venv\Scripts\python.exe scripts/check_m5_readiness.py `
  --config examples/evaluation/live_config.example.json `
  --output-dir deliverables/verification/t17_offline_readiness_YYYYMMDD
```

The command returns exit code 0 when the offline verification completed. Its
`readiness-report.json` distinguishes `offline_readiness=ready` from
`live_readiness=blocked_live`; a successful deterministic baseline is not live
agent evidence. The report records 42 planned attempts, 39 model-exposed attempts,
zero acceptance attempts, zero provider calls, and zero model calls for this
offline pass. E12 remains preflight-blocked as frozen.

`examples/evaluation/live_config.example.json` is intentionally not runnable
live. `live_enabled` is false. The approved model/config reference, credential
environment-variable name, token rates and both cost ceilings are unset. T17 does
not inspect environment variables or credential values. A future credential
binding is represented only by a variable name; the secret itself must stay out
of the repository, config, command line, report, and logs.

The cost estimator repeats the `AgentRunner` byte-based pre-call reservation using
the configured payload, schema, prompt, output-token and model-call limits. It
multiplies the per-attempt ceiling by the 39 planned model-exposed attempts. It is
a reservation estimate, not a measured token count or live cost. Missing rates or
ceilings keep `live_readiness` blocked. The per-attempt limit cannot exceed the
current 16 model calls, 1,200 output tokens per call, or 32,768 payload bytes.

T17 pins the current runtime version, action schema and agent prompt separately
from the evaluation model. Codex Luna/Astra development routing and reset credits
are not application evaluation settings, API budget, or approval. A future
approved fixed model/config must be versioned against the T17 report and the
frozen manifest before T18 is considered. T18 remains blocked until the user
separately authorizes the model, key handling, rates, budget and live batch.

The offline report also carries a non-secret evaluation-config identity
fingerprint binding the provider/endpoint, model ID, model-config version, and a
SHA256 of the authorization reference. Credential environment-variable values
are never read; the report records only whether a variable name was configured.
Empty or whitespace-only required settings fail closed. Output validation
rejects junctions/symlinks that redirect the verification root or requested
output path and checks resolved paths remain inside the project verification
tree before creating output.
