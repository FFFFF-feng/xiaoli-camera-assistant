# B segmentation-v1 implementation plan

> Execution: inline, as explicitly requested in the B assignment. Specification: frozen `docs/line-drawing-contract-v1.md` at `986fd0594150dce96b3255c8cc77ff54e8174620` and coordination package `02-B-分割模型与离线基准.md`.

Goal: provide an optional local box-prompt segmentation runtime and reproducible offline mask comparison, without changing A's integration files.

Architecture: immutable contract records, a serialized runtime owning one predictor and one in-memory embedding, and a lazy local-only MobileSAM backend. Native inference has cooperative stage-boundary deadlines, explicitly not hard cancellation. No result cache, downloads, fallback or model training in the runtime.

Constraints: RGB uint8, 8x8 through 4,000,000 pixels; 1–4 unique object1..object6; normalized XYXY, minimum 4 input pixels each axis; one model/slot/embedding, queue <=0.5s; exact fixed failures and six timing keys. Zero cloud requests. Only B-owned paths. Photos/weights/environments/evidence stay in ignored `.tmp/B-segmentation/`.

Review focus: caller mutation and stale embeddings; simultaneous requests and close; partly invalid batches/order; corrupt/missing weights and unavailable device; hole/disconnected preservation and invalid candidate scores.

## Task 1 — contract and lifecycle
- [ ] Write tests for input/failure codes, order, holes/multiple components, cache isolation, queue deadline and close; run RED.
- [ ] Implement records, backend protocol, candidate validation and bounded serialized runtime; run GREEN.
- [ ] Commit only module and independent tests.

## Task 2 — optional model backend
- [ ] Test lazy import, missing/corrupt weights, truthful metadata and safe device failures before implementation.
- [ ] Implement MobileSAM vit_t, local weights SHA-256 and one-image multi-prompt reuse; document exact preprocessing and native timeout boundary.
- [ ] Use isolated environment only; record actual versions, hardware, startup/installation costs and weight hash. At most two candidates; begin with MobileSAM, SAM 2 is deferred unless justified.
- [ ] Commit backend, tests and integration example.

## Task 3 — offline comparison and handoff
- [ ] Test reproducible GrabCut extraction/visualization and ledger behavior before implementation.
- [ ] Compare old/checkpoint GrabCut and MobileSAM on identical RGB/boxes at 720 and 1280, using frozen manual boxes for dog/cup; scene masks are applicability observations only.
- [ ] Save all attempts, raw masks, overlays, contour-only previews, focused dog/cup crops, timing stages, process/GPU memory and no invented IoU.
- [ ] Run independent tests, relevant existing pixel tests and whole Python suite offline; inspect launch check without restarting services.
- [ ] Review complete diff, record all ordered SHAs and evidence in `reports/B-交付报告.md`; copy B report to coordination package. Release inference resources. Commit.

## Execution ledger
- Initial evidence: original repository clean at checkpoint; native worktree tool failed to resolve ref in calling chat repository; verified CLI worktree created at the explicit checkpoint.
- Design decision: frozen task/contract is the supplied specification; execute continuously under user's explicit instruction, without additional design approval gates.
- Environment issue: ensurepip failed because sandbox TEMP cannot be written. Reproduce with direct ensurepip; use a task-local writable TEMP directory.
- Preflight: tasks 2/3 consume task 1 records/runtime, no signature changes. Synchronous timeout allowed by frozen contract only with explicit disclosure; no claim of hard interruption.
