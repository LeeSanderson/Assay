# L6 record: the local setup for `phase0-local.yaml`

PRD section 5, "Model tiers, and the local tier", requirement L6. Fill in every field before the local trial runs, and commit this file with the results. A model name alone is not a stable identifier: a different quantization, build option, or thinking setting is a different model, and it needs its own record.

Do not write the server address here. It lives only in `ASSAY_LOCAL_BASE_URL` on the host (L10).

The reference setup (PRD, "The reference setup") is guidance. Write the values of the setup that actually ran.

| Field | Value |
|---|---|
| Model file (name and SHA-256) | |
| Quantization | |
| Chat template (the model file's own, or the changed template in full) | |
| Inference server and version (for a build: repository, branch, commit) | |
| Full server command line, with its environment flags | |
| Thinking setting | |
| Hardware (CPU or GPU, memory) | |
| Operating system and version | |
| WSL mode (WSL version, and NAT or mirrored networking) | |
| Docker engine version (`docker version`, server) | |
| `model_name` in `phase0-local.yaml` (the server must accept this exact name) | |
| Date of the trial | |
