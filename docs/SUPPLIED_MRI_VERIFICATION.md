# Supplied MRI verification report

Verified 2026-09-24. This report supersedes the earlier missing-DICOM status. Technical execution does not establish clinical accuracy or dataset provenance. No frozen model, preprocessing, inference, Grad-CAM or frontend architecture changes were made. Added an observation-only verification script and optional supplied-ZIP support in the isolated browser test harness.

## A. AI model ? PASS

- Version: KNEE-AI 3.3; learned 5-to-3 projection followed by EfficientNet-B0.
- Actual checkpoint loaded: `E:\Desktop\Hackathon\Technova\KNEURA\.kneura\checkpoints\knee-ai-08b8ade87b11ef2c.pt`.
- Checkpoint SHA-256: `66504783a2ad62d852767db58aa8fde802d6bd71171cd9836d8cdfba66e21611`.
- One series, 40 slices sorted by InstanceNumber 1 through 40, 36 overlapping five-slice windows.
- Frozen preprocessing/window functions and existing backend inference were executed on CPU.
- Aggregation: sigmoid probabilities per window, arithmetic mean across all 36 windows. Exact equality with the observed window-probability mean passed.
- No clinical threshold, tuning, retraining or weight changes.

| Canonical output | Study probability (0?1) |
| --- | ---: |
| ACL | 0.0318167433 |
| MCL | 0.0991299376 |
| Medial Meniscus | 0.9833698273 |
| Lateral Meniscus | 0.9468550086 |
| Medial OA | 0.9909477234 |
| Lateral OA | 0.4130974412 |
| Patellofemoral OA | 0.9646025896 |
| Effusion | 0.3293517232 |
| Synovitis | 0.1969331503 |
| Baker's cyst | 0.7059594393 |
| Contusion | 0.0491674840 |
| Fracture | 0.8151003718 |

## B. Grad-CAM ? PASS

Existing target: `model.backbone.features[-1]` (`Conv2dNormActivation`). All 12 class-specific heatmaps and overlay PNGs were generated. For each class, the selected highest-scoring window tensor was bit-for-bit identical to its inference tensor. All 12 probability vectors were exactly equal during and after Grad-CAM. All heatmaps were finite and 224?224. No linkage mismatch was observed.

Example evidence chain:

- Finding: ACL; study probability: 0.031816743314266205.
- SeriesInstanceUID: `1.2.826.0.1.3680043.8.498.43694888338048703729850099846765930063`.
- Window: 24 (one-based); InstanceNumbers: [24, 25, 26, 27, 28].
- Window probability: 0.10937823355197906; this is distinct from the displayed study mean.
- MRI asset: `/api/cases/VERIFY-M1/images/1075a6fa375841b8813d58e1a076c2dd.png`.
- Grad-CAM asset: `/api/cases/VERIFY-M1/images/finding-0.png`.

These local assets are in `E:\Desktop\Hackathon\Technova\KNEURA\.kneura\m1-verification-8c51bfc67619436f9184a90648a20f27/images`. The direct harness records API-shaped links but does not register a case in the user's database. The separate browser test exercised actual authenticated image endpoints. Grad-CAM is attribution across a five-slice input overlaid on its first slice, not lesion segmentation or per-slice localization.

## C. DICOM ? ingestion PASS; authoritative eligibility/provenance unresolved

Extracted sample path: `E:\Desktop\Hackathon\Technova\KNEURA\.kneura\package-validation\5930e8da615047d898765d3f0df3e3a0\dicom`.

Source archive: `E:/Desktop/Hackathon/Technova/KNEURA_SINGLE_SERIES_DEMO.zip`. The extracted folder was verified to contain 40 actual `.dcm` files. One MR series, 256?256 pixels, InstanceNumbers 1?40, all pixels decoded.

Selected series: `1.2.826.0.1.3680043.8.498.43694888338048703729850099846765930063`, description `AX T2 FS`. Selection was the existing backend description heuristic: T2 matches fluid-sensitive and FS matches fat-suppressed. This does **not** establish authoritative RSNA CSV flags. The frozen CSV-driven top-level `analyze_study` acceptance remains unverified; the backend invoked its unchanged loading, preprocessing and window functions through the existing adapter.

The file `data/series_eligibility.csv` exists but contains only the header. The missing input is an authoritative row for this StudyInstanceUID/SeriesInstanceUID with `Fluid_Sensitive` and `Fat_Suppression`. Expected columns: `StudyInstanceUID,SeriesInstanceUID,Fluid_Sensitive,Fat_Suppression`. Supply the source CSV at that path or configure `KNEURA_SERIES_CSV`; strict selection uses `KNEURA_REQUIRE_SERIES_CSV=1`. No flags were invented and no CSV or DICOM metadata was modified.

**PROVENANCE VERIFICATION REQUIRED.** No supplied file establishes RSNA research provenance or hospital authorization. Missing metadata: `PatientIdentityRemoved`, `DeidentificationMethod`, and `BurnedInAnnotation` declarations. The existing obvious-identifier/private-tag check reported no additional issues. This is a limited metadata inspection, not comprehensive de-identification or pixel-review certification.

## D. Frontend ? supplied-study workflow PASS

One browser test passed against real HTTP sessions, SQLite, the supplied ZIP, actual checkpoint and generated images; no request mocks. It verified 12 canonical findings, MRI navigation, evidence jump, window/level, heatmap opacity, approve/reject persistence, 12/12 progress, draft editing, explicit statement attachment, trace modal, audit-chain verification, final approval, orthopedist evidence access and patient finalized summaries. Restricted image/finalization access was checked. Runtime: 51.1 seconds including startup.

Code inspection confirms frontend probabilities are backend values formatted as percentages (one decimal), not model calculations. Five-slice navigation sorts backend InstanceNumbers. Reports are finalized by an authenticated backend endpoint, not independent client state. Approved-only IDs are submitted through the workflow helper; no frontend Grad-CAM generation or 0.5 clinical decision threshold was introduced.

The browser test uses deliberate fixture approvals (first three approved, nine rejected), not clinical interpretation. Its manually authored test impression retains the pre-existing synthetic-verification wording even in supplied-ZIP mode; that text is a test fixture, not evidence about this study's origin. The study is not represented as clinically reviewed.

## E. LLM ? NOT CONFIGURED

Checked process environment, repository environment files, backend narrative client and report service. `.env` is absent; `.env.example` contains commented examples only; no LLM environment variables are populated. No existing provider/model can be used.

Required: `KNEURA_LLM_URL` (chat-completions endpoint) and `KNEURA_LLM_MODEL` (actual model identifier). Set `KNEURA_LLM_KEY` only if the provider requires authentication. Supported aliases: `LLM_URL`, `LLM_MODEL`, `LLM_API_KEY`. Optional: `LLM_PROVIDER`, `LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`. Export these into the backend process; the application does not automatically load `.env`. Credentials remain server-side.

The input allowlist includes approved finding IDs/names and permitted clinical context only. It excludes raw MRI, probabilities, raw AI outputs and rejected findings. Live narrative generation and narrative quality remain unverified. The tested report was explicitly the template fallback, not LLM output.

## F. End-to-end status by layer

| Layer | Result |
| --- | --- |
| AI | Supplied-study technical inference passed; 12 outputs and 36-window aggregation verified |
| Grad-CAM | All 12 classes passed tensor, probability invariance and evidence-link checks |
| DICOM | Ingestion passed; authoritative CSV selection and provenance unresolved |
| Backend | Supplied-study workflow passed; five targeted report/gate tests passed |
| Frontend | Real-backend supplied-ZIP browser test passed |
| LLM | Blocked on endpoint/model configuration; no live-provider claim |
| Deployment | Isolated localhost test servers ran successfully; presentation-machine HTTPS/readiness not reverified |

All-rejected special case: reconstructed all 12 supplied-study findings with explicit test rejection decisions. Narrative input contained zero approved findings; the template contained no abnormality claims and stated that this does not establish a normal examination. A fabricated fracture narrative was rejected by validation. Five targeted backend tests passed, including all-rejected behavior, approved-only narrative contracts and finalization gates (one dependency deprecation warning). Provider contract tests use a response double, not a live LLM.

No AI or Grad-CAM execution failure occurred. The complete live-LLM chain remains blocked at the LLM layer; authoritative source selection remains unresolved at the DICOM metadata layer. Neither blocked technical M1 execution.

Machine-readable evidence: `E:\Desktop\Hackathon\Technova\KNEURA\.kneura\m1-verification-8c51bfc67619436f9184a90648a20f27\verification.json`. Frozen inference SHA-256 remained `4a86a64aba740089f03c2a169c89d8f612731bd43e45591963532e191d27a677` before and after execution; the existing backend inference file was also unchanged.
