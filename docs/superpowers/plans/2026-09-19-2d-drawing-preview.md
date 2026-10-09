# 2D Drawing Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the offline 3.2 preview path by emitting a deterministic 2D drawing artifact from the same semantic annotations used by the 3D model review.

**Architecture:** Extend `PreviewDrawingAdapter.generate_annotations()` to return a vendor-neutral SVG drawing artifact built from model bounding boxes and the already-generated `DrawingAnnotation` objects. `DesignReviewService` already stores adapter artifacts, so the artifact will automatically flow into review records, PhysicalBlock payloads, SysML round-trip, and `detail-design.json` without creating a second annotation source.

**Tech Stack:** Python 3.12, standard-library SVG string generation, existing CAD/Drawing ports, SQLite audit records, pytest.

## Global Constraints

- Do not run a server, local model, remote model, SSH, FreeCAD, CFD, or FEA experiment.
- The preview artifact is `source_kind=development`; it is not a formal engineering drawing or manufacturing approval.
- Dimensions, datum, tolerance, and GD&T values must come from the shared `DrawingAnnotation` objects.
- Preserve existing CAD plan routes, review status rules, and artifact hashes; new artifact fields are additive.

---

### Task 1: Generate a deterministic 2D drawing artifact

**Files:**
- Modify: `src/rflp_lite/adapters/drawing_preview.py`
- Test: `tests/adapters/test_drawing_preview.py`

**Interfaces:**
- `PreviewDrawingAdapter.generate_annotations(model, context) -> AnnotationResult` continues returning the same annotations and diagnostics, and additionally returns `artifacts["drawing_svg"]`, `artifacts["drawing_hash"]`, `artifacts["drawing_backend"]`, and `artifacts["source_kind"]`.

- [x] **Step 1: Add regression tests** asserting a box model produces top/side views, shared dimension/datum/GD&T annotation text, a stable SVG hash, and development source metadata.
- [x] **Step 2: Implement `_drawing_svg(model, annotations)`** with escaped IDs/text, millimetre labels, deterministic top and side outlines, and annotation callouts. Invalid/missing bounding boxes remain diagnostics and do not raise outside the adapter boundary.
- [x] **Step 3: Return the SVG and its canonical hash** from `PreviewDrawingAdapter` while keeping the existing annotation placement/collision diagnostics unchanged.
- [x] **Step 4: Run the adapter tests.**

### Task 2: Carry the drawing artifact through review, UI, and deliverables

**Files:**
- Modify: `src/rflp_lite/interface/web/templates/cad-design.html`
- Modify: `tests/application/test_cad_workflow.py`
- Modify: `tests/interface/web/test_cad_design.py`
- Modify: `tests/e2e/test_local_product_acceptance.py`
- Modify: `tests/application/test_deliverables.py`
- Modify: `README.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`

**Interfaces:**
- Existing review responses retain `annotations`, `findings`, `diagnostics`, and `artifacts`, with `drawing_svg` available in the same artifact map.
- Existing `detail-design.json` carries the review artifact through the audit projection; no new persistence source is introduced.

- [x] **Step 1: Add review/API/e2e assertions** that the preview review contains `drawing_svg`, `drawing_hash`, and the same annotation values used by the review.
- [x] **Step 2: Render the drawing SVG in the CAD workbench** after review, with a visible “development preview” label and no automatic formal approval.
- [x] **Step 3: Add deliverable assertions and update documentation** to distinguish the offline 2D drawing preview from a formal CAD drawing.
- [x] **Step 4: Run focused CAD, Web, deliverable, and local product tests.**

### Task 3: Full offline verification and delivery

**Files:**
- Modify: `docs/superpowers/README.md`
- Modify: `docs/superpowers/plans/2026-09-19-2d-drawing-preview.md`

- [x] **Step 1: Run `scripts/verify_full.py` with an isolated config and `AI4MBSE_CAD_BACKEND=preview`.**
- [x] **Step 2: Run `git diff --check`, review the final diff, and mark this plan complete.**
- [ ] **Step 3: Commit and push to `codex/web-audit-2026-08-18`.**
