# B segmentation-v1 implementation plan

> Execution: inline, as explicitly requested in the B assignment. Specification: frozen `docs/line-drawing-contract-v1.md` at `986fd0594150dce96b3255c8cc77ff54e8174620` and coordination package `02-B-分割模型与离线基准.md`.

Goal: provide an optional local box-prompt segmentation runtime and reproducible offline mask comparison, without changing A's integration files.

Architecture: immutable contract records, a serialized runtime owning one predictor and one in-memory embedding, and a lazy local-only MobileSAM backend. Native inference has cooperative stage-boundary deadlines, explicitly not hard cancellation. No result cache, downloads, fallback or model training in the runtime.

Constraints: RGB uint8, 8x8 through 4,000,000 pixels; 1–4 unique object1..object6; normalized XYXY, minimum 4 input pixels each axis; one model/slot/embedding, queue <=0.5s; exact fixed failures and six timing keys. Zero cloud requests. Only B-owned paths. Photos/weights/environments/evidence stay in ignored `.tmp/B-segmentation/`.

Review focus: caller mutation and stale embeddings; simultaneous requests and close; partly invalid batches/order; corrupt/missing weights and unavailable device; hole/disconnected preservation and invalid candidate scores.

## Task 1 — contract and lifecycle
- [x] Write tests for input/failure codes, order, holes/multiple components, cache isolation, queue deadline and close; run RED (25 expected missing-module failures).
- [x] Implement records, backend protocol, candidate validation and bounded serialized runtime; run GREEN (25 passed).
- [x] Commit only module and independent tests, plus this B-owned plan (`d8ec3ed`).

## Task 2 — optional model backend
- [x] Initial RED includes missing-weight lazy loading; supplementary corrupt/hash/device tests now actually pass in the independent model environment. Supplementary tests were added after backend implementation, not claimed as RED-first.
- [x] Implement MobileSAM vit_t, local weights SHA-256 and one-image multi-prompt reuse; document exact preprocessing and native timeout boundary.
- [x] Use isolated environment only; record actual versions, hardware, startup/installation costs and weight hash. One candidate run; SAM 2 deferred with rationale.
- [x] Backend/tests committed in task 1; integration example in `7a71a9e`.

## Task 3 — offline comparison and handoff
- [x] Test reproducible GrabCut extraction/visualization before implementation (2 RED then 2 GREEN). Ledger durability inspected in real 32-attempt run.
- [x] Compare old/checkpoint GrabCut and MobileSAM on identical RGB/boxes at 720 and 1280, using frozen manual boxes for dog/cup; scene masks are applicability observations only.
- [x] Save all attempts, raw masks, overlays, contour-only previews, focused dog/cup crops, timing stages, process RSS; GPU not tested and no invented IoU.
- [x] Independent tests, existing pixel tests and whole Python suite executed offline; launch check executed, no shared service restart. Sole environment failure documented.
- [x] Final report and full-range handoff prepared; final commit and coordination-package copy executed as the closing transaction. Inference/download processes checked: none remain; no GPU inference used.

## Execution ledger
- Initial evidence: original repository clean at checkpoint; native worktree tool failed to resolve ref in calling chat repository; verified CLI worktree created at the explicit checkpoint.
- Design decision: frozen task/contract is the supplied specification; execute continuously under user's explicit instruction, without additional design approval gates.
- Environment issue: ensurepip failed because sandbox TEMP cannot be written. Reproduce with direct ensurepip; use a task-local writable TEMP directory.
- Preflight: tasks 2/3 consume task 1 records/runtime, no signature changes. Synchronous timeout allowed by frozen contract only with explicit disclosure; no claim of hard interruption.
- Lifecycle follow-up: cleanup exception and failed candidate denominator tests RED (2 failures), GREEN after implementation; close-during-inference protection passed as an additional test.
- Environment ruling: discontinue the 3.46 GB CUDA dependency download, install CPU-only Torch (619 MB) in the same independent environment. GPU hardware is detected but no GPU performance claim will be made.
- Contract boundary: official continuous-logit interpolation is retained and disclosed; B binary-mask resizing uses nearest-neighbor. A must resolve if its frozen wording intended to prohibit interpolation of continuous logits too.
- Whole-branch read-only review (`b_segmentation_review`): 3 Important runtime issues fixed together using 7 failing regressions then GREEN (42 passed, 1 optional dependency skip); one review Minor (lost attempt on PNG failure) regraded Important because denominator integrity is required, fixed with a real filesystem failure test. GPU memory reporting on non-default CUDA device remains deferred; this run is CPU only.
- Review rulings: native hard cancellation and product geometry remain outside B implementation as explicitly frozen; actual model quality is judged only after real benchmark; logits interpolation boundary remains explicitly handed to A.
- Full-suite blocker: Windows asyncio `_fallback_socketpair -> accept` hangs entering existing `test_api_streaming.py::test_complete_composition_partial_is_forwarded_before_final[False]`. Three full-suite diagnostics retained; stopped own processes, no product edit. 18 preceding physics tests passed; full suite must not be reported green. First targeted collection contained 1480 items before later B additions.
- Final environment: discovered existing detector venv has Torch 2.10.0+cpu / torchvision 0.25.0+cpu. Copied explicit dependency RECORD files into B venv (535,665,981 bytes / 33.19s for initial Torch closure); local OpenCV/pytest/HF dependency copies followed. No system-site-packages or shared source imports. Installed timm 0.9.12 and local MobileSAM 1.0. All earlier wheel downloads were stopped; no fabricated GPU timings.
- Final verification: isolated model environment 43 passed (24 upstream warnings), related shared-dependency regression 117 passed/1 optional-backend skip. Approved unsandboxed full pytest resolves socketpair obstruction: 1485 passed, 3 skipped, 1 failed in 122.32s. Sole failure is `test_launch_apps.py::test_forwarding_cmd_works_from_a_unicode_desktop_folder` because this isolated worktree has no mobile/node_modules; same reason for launcher --check. Do not edit A launchers or install frontend for B's mask work; report the environmental failure.
- Real evidence: 32 preliminary GrabCut masks + 48 final single-region comparisons + 4 model outputs in 2 multi-object batches = 84 mask-region attempts; 20 actual MobileSAM outputs in 18 calls. Zero cloud calls. No model masks failed contract checks; quality is separately limited by cup bottom 2/3-row losses and rim holes, unresolved dog identity details, and scene structures.
