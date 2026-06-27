# Security Review

**Project:** AI Case Sorter (OSS client)
**Review date:** 2026-06-27
**Reviewer role:** Application Security (Sr.)
**Scope:** Static review of the Python client in this repository (`sorter/`,
`main.py`, launch scripts). The closed-source `reloadingrecipes.com` backend and
the device firmware are out of scope.

> This is an **actionable report for a later remediation session**. Nothing here
> has been fixed. Findings are ordered by severity. Each has a location, the
> issue, the impact, and a concrete recommendation. Severity uses the project's
> realistic threat model: a desktop app whose users **import third-party model
> archives** and **download models from a shared community library** that any
> account with the *Contribute* role can publish to. Under that model, "community
> content is trusted" is **not** a safe assumption.

## Severity summary

| # | Severity | Finding | Location |
|---|----------|---------|----------|
| 1 | **Critical** | Arbitrary code execution via untrusted model deserialization (`torch.load(weights_only=False)`) | `sorter/local_inference.py:329` |
| 2 | **Medium** | Path traversal / arbitrary file write from unsanitized classification labels used as filenames | `sorter/training/dataset.py`, `sorter/run_controller.py`, `sorter/feedback.py` |
| 3 | **Medium** | Stored XSS in generated HTML evaluation report | `sorter/eval_report.py:827-850` |
| 4 | **Medium** | Unbounded ZIP extraction (decompression bomb / disk exhaustion) on model import | `sorter/model_io.py:351-453` |
| 5 | **Medium** | Secrets stored at rest in plaintext (API key in SQLite, token cache) | `sorter/config.py`, `sorter/repository.py`, `sorter/auth.py` |
| 6 | **Low** | API key + images sent over cleartext HTTP when endpoint uses `http://` | `sorter/api_client.py:98-103` |
| 7 | **Low** | SQL identifier injection in debug helper `dump_table` | `sorter/db.py:295-297` |
| 8 | **Low** | Verbose feedback/community debug logging enabled by default | `sorter/feedback.py`, `sorter/community_api.py` |
| 9 | **Low** | `start.sh --auto` performs unattended `sudo` package installs | `start.sh:74-107` |
| 10 | **Info** | JWT signature intentionally not verified (display-only) | `sorter/auth.py:242-260` |
| 11 | **Info** | Subprocess usage reviewed — safe (list argv, no shell) | `training/manager.py`, `ui/dialog_install_torch.py`, `gpu_detect.py`, `ui/sysutil.py` |

---

## 1. Critical — Arbitrary code execution via untrusted model deserialization [PARTIAL]

**Location:** `sorter/local_inference.py:329`
```python
ckpt = torch.load(str(path), map_location="cpu", weights_only=False)
```

**Issue.** PyTorch `.pth` checkpoints are Python **pickle** archives. With
`weights_only=False`, `torch.load` will execute arbitrary code embedded in the
archive during unpickling (via `__reduce__`). The model files reaching this code
path are **not all locally produced**:

- **Community downloads** — `community_api.request_download` → `download_to`
  streams a model ZIP from a server-provided Azure SAS URL; `model_io.import_model`
  extracts `model/<id>.pth`; `classifier.classify_active` later calls
  `local_inference.classify` → `torch.load(...)`. Anyone with the *Contribute*
  role can publish a model, so the `.pth` is **attacker-controllable**.
- **Manual import** — Models tab → "Import" accepts an arbitrary `.zip` chosen by
  the user (e.g. received from another hobbyist), same code path.

**Impact.** Loading a malicious model results in **remote code execution** on the
operator's machine with the user's privileges — the moment they run, train
against, or evaluate the imported model. The current inline comment asserts this
is "acceptable because models are trusted"; that assumption does not hold once
the project is open source and models circulate freely.

**Recommendation (in priority order).**
1. Load with `weights_only=True` (PyTorch ≥ 2.6 defaults to this). The checkpoints
   this project saves are plain dicts of tensors + JSON-able metadata
   (`model_state_dict`, `classes`, `base`, `image_size`), which are fully
   loadable under `weights_only=True`. Use `torch.serialization.add_safe_globals`
   only if a specific safe type is genuinely required.
2. Validate the checkpoint shape **before** trusting it (already partially done:
   `classes`, `base` checks) and reject anything unexpected.
3. Consider migrating the on-disk format to **safetensors** for weights + a
   sidecar JSON for metadata, eliminating pickle entirely.
4. [FIX] Until fixed, surface a clear warning in the import/download UI that models run 
   code, and prefer models from known authors.

---

## 2. Medium — Path traversal / arbitrary file write from classification labels [FIX]

**Locations:**
- `sorter/training/dataset.py:40` `training_filename` → `f"{label}__{...}{ext}"`
- `sorter/training/dataset.py:69` `feedback_filename` → `f"{safe}__{...}"` (`safe = label or "unknown"` — only guards *empty*, not *malicious*)
- `sorter/run_controller.py` `_maybe_store_run_image` (run-image capture)
- `sorter/feedback.py` `capture` → `save_feedback_image`

**Issue.** Filenames are built by string-interpolating the predicted `label` with
no sanitization. In **AI Config mode** the label is the **raw text returned by the
remote HTTP classification server** (`api_client.classify` returns
`choices[0].message.content` essentially verbatim). A server (malicious,
compromised, or simply misconfigured) can return a label such as
`../../../../home/<user>/.bashrc` or an absolute-style path. When run-image
storage or the feedback loop then writes `out_dir / training_filename(label)`,
`pathlib` join with a traversal component escapes the intended directory →
**arbitrary file write** (of attacker-influenced JPEG bytes, with an attacker-chosen
name/location).

**Impact.** Write/overwrite files outside `data/models/<id>/...`. Combined with a
predictable home path this can clobber dotfiles or drop files into autostart/`cron`
locations. Even absent traversal, labels containing slashes create unexpected
nested directories or fail writes.

**Recommendation.**
- Sanitize labels before they are ever used as a path component: strip/replace
  path separators, `..`, control chars, and reserved Windows names; cap length.
  Centralize this in `dataset.py` (e.g. a `safe_label()` used by every
  `*_filename` builder).
- After building `dest`, assert `dest.resolve().is_relative_to(out_dir.resolve())`
  and refuse otherwise.
- Apply the same treatment to labels written into ZIP manifests/headstamp rows on
  import.

---

## 3. Medium — Stored XSS in generated HTML evaluation report [IGNORE]

**Location:** `sorter/eval_report.py:827-829`
```python
def render_html(rows):
    return _HTML_HEAD + json.dumps(rows) + _HTML_TAIL   # rows embedded in <script>
```
and `report_rows` (`:832-850`) populates each row's `filename`, `filepath`,
`classification`, `original_classification`, `raw_original_classification` from
the evaluated images / model output.

**Issue.** The results are serialized with `json.dumps` and concatenated into a
`<script> const data = ... </script>` block. `json.dumps` does **not** escape `/`
or `<`, so any string value containing `</script>` terminates the script element
early; the remainder is parsed as HTML. A filename or predicted label like
`a</script><img src=x onerror=alert(document.domain)>` yields executable markup in
the report. Filenames come from arbitrary user-selected folders and labels can
come from a remote server (see #2).

**Impact.** Script execution in the browser context when the (self-contained,
often-shared) HTML report is opened. Because reports embed base64 images and are
designed to be passed around, the blast radius extends beyond the operator.

**Recommendation.**
- Escape the JSON for safe `<script>` embedding: replace `<`, `>`, `&`, and the
  line/para separators, e.g. produce `json.dumps(rows).replace("<", "\\u003c")`
  (also `>` → `>`, `&` → `&`). This is the standard server-side-render
  mitigation and keeps the data valid JSON.
- Alternatively embed the data as a `<script type="application/json">` block read
  via `textContent`, or render values through `textContent`/`createElement`
  rather than the existing `innerHTML` template literals (`:717-734`).

---

## 4. Medium — Unbounded ZIP extraction (decompression bomb) [FIX]

**Location:** `sorter/model_io.py:351-453` (`import_model` / `_extract_to`)

**Issue.** Path traversal is correctly handled (entries with `..` are rejected at
`:376-382`, and only `posix.parts[-1]` basenames are used for the destination).
However extraction (`shutil.copyfileobj`, `:449-452`) imposes **no limit** on
per-entry uncompressed size, total uncompressed size, or entry count. A small
malicious archive can expand to many GB ("zip bomb"), and there is no cap on the
number of image entries written.

**Impact.** Disk exhaustion / denial of service from a community or hand-shared
model archive.

**Recommendation.**
- Enforce ceilings before/while extracting: max total uncompressed bytes, max per
  entry, max entry count. `ZipInfo.file_size` gives the declared uncompressed
  size; also bound the bytes actually copied (don't trust the header) and abort if
  exceeded. [IGNORE]
- Reject archives whose compression ratio is implausibly high. [FIX]
- Validate that model/image entries have expected extensions before writing. [FIX]

---

## 5. Medium — Secrets stored at rest in plaintext [IGNORE]

**Locations:**
- `sorter/config.py:44-52` (`api_key` default), persisted via
  `sorter/repository.py` `SettingsRepo` into the `settings` table as plaintext JSON.
- `sorter/auth.py:55-79` (`_FileTokenCache`) — MSAL token cache written verbatim
  to `data/config/msal_cache.bin`. `chmod 0600` is applied on POSIX (good); on
  Windows it relies on default ACLs only.

**Issue.** The OpenAI-compatible **API key** is stored unencrypted in the SQLite
DB, and OAuth tokens (access + refresh) sit unencrypted in the cache file. Any
process running as the user, a backup, or an exfiltrated `data/` folder discloses
these.

**Impact.** Credential theft → access to the user's classification server and
community account.

**Recommendation.**
- At minimum, document that `data/config/` holds credentials and must be
  protected; ensure the DB file is created `0600` too.
- Prefer OS-native secret storage (Windows DPACI/Credential Manager, macOS
  Keychain, libsecret) or the `keyring` library for the API key and token cache.
- Note (positive): `model_io.model_to_export_dict` already strips `api_key` and
  paths from exported manifests — keep that.

---

## 6. Low — API key sent over cleartext HTTP [IGNORE]

**Location:** `sorter/api_client.py:71-103`

The endpoint default is `http://localhost:8000` and the client sends
`Authorization: Bearer {api_key}` plus the base64 image to **whatever**
`endpoint_url` is configured. If a user points the client at a remote `http://`
host, the key and image traverse the network in cleartext.

**Recommendation.** Warn (or require confirmation) when `endpoint_url` is non-local
and not `https://`. Localhost http is fine.

## 7. Low — SQL identifier injection in `dump_table` [IGNORE]

**Location:** `sorter/db.py:295-297`
```python
rows = self.conn.execute(f"SELECT * FROM {table}").fetchall()
```
`table` is interpolated into the SQL string. All current callers pass constants,
and the rest of the data layer is correctly parameterized, so this is **not**
currently exploitable — but it's a latent identifier-injection footgun in a
"debug" helper. Recommend allow-listing table names or removing the helper.
(The f-strings in `db.transaction` SAVEPOINT/PRAGMA statements use
internally-generated values and are safe.)

## 8. Low — Verbose debug logging on by default [FIX]

**Locations:** `sorter/feedback.py` (`debug_log`, gated by
`CASESORTER_FEEDBACK_DEBUG`, **default on**) and its callers in
`sorter/community_api.py`, which log HTTP statuses, container URIs, blob paths,
and response-body snippets to stderr.

These are not secrets (SAS *tokens* are not logged), but the default-on verbosity
leaks operational detail and clutters output. Recommend defaulting the flag
**off** and ensuring no token/credential ever reaches a log line.

## 9. Low — Unattended `sudo` in the bootstrap launcher [FIX] [Add Warnings]

**Location:** `start.sh:74-107`

`./start.sh --auto` (or `AUTO_INSTALL=1`) runs `sudo apt-get/dnf/pacman install`
without prompting. The packages are fixed, well-known distro packages (tkinter,
libGL, glib, venv), so risk is limited, but unattended `sudo` is worth a clear
warning in docs and an explicit "this will install system packages" notice.
(Positive: without `--auto` and without a TTY, the script declines to run `sudo`
silently — good default.)

## 10. Info — JWT signature not verified (by design) [IGNORE]

**Location:** `sorter/auth.py:242-260` (`_decode_jwt_claims`)

The ID token is base64-decoded **without** verifying its signature, and the code
comments clearly state this is for **display only** (name/email) on a token MSAL
already validated, never for authorization. This is acceptable. Flagged so a
future change does not accidentally promote these claims to a trust/authz
decision.

## 11. Info — Subprocess usage reviewed and safe [IGNORE]

`training/manager.py` (`build_command` + `Popen`), `ui/dialog_install_torch.py`
(pip install of pinned torch/torchvision), `gpu_detect.py` (`nvidia-smi`), and
`ui/sysutil.py` (`open`/`xdg-open`/`os.startfile`) all use **list-form argv with
no `shell=True`**, so there is no shell-injection surface. The training argv is
built from typed config values (epochs/lr/etc.), not free text. No `eval`/`exec`,
no `os.system`, no `pickle`/`yaml.load` of untrusted data were found elsewhere.

---

## Recommended remediation order

1. **#1** (Critical) — switch to `weights_only=True` / validate checkpoints. Highest impact, smallest change.
2. **#2 and #3** — sanitize labels (fixes the path-write *and* feeds the report-escaping fix). Add the `<script>` JSON escaping.
3. **#4** — add extraction limits to `import_model`.
4. **#5/#6** — credential storage + HTTP warning.
5. **#7–#9** — hardening cleanups.

## Positive observations

- All data-layer SQL is parameterized (`sorter/repository.py`).
- ZIP **path traversal** is explicitly rejected on import (`model_io._is_traversal`).
- Atomic writes (`.tmp` + `os.replace`) are used consistently for DB/config/model files.
- Exported manifests strip API keys and absolute paths.
- Token cache is `0600` on POSIX.
- No use of `eval`/`exec`/`os.system`/`shell=True`; no committed secrets or data
  files in the git history.
