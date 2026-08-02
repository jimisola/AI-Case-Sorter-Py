# Security Policy

## Reporting a vulnerability

Please report security vulnerabilities **privately**. Do **not** open a public
issue, pull request, or discussion for a suspected vulnerability.

**Preferred:** use GitHub's private vulnerability reporting on this repository —
the **Security** tab → **Report a vulnerability**. This opens a private advisory
visible only to the maintainers. (Maintainers: enable this under
*Settings → Code security and analysis → Private vulnerability reporting*.)

**Alternative:** email the maintainers at
**seth@sjseth.com**.

Please include as much as you can:

- a description of the issue and its impact,
- steps to reproduce, or a proof of concept,
- the affected version or commit, and your platform (Windows / Linux).

## What to expect

- We aim to acknowledge your report within a few days.
- We'll investigate, keep you informed of progress, and credit you (if you'd
  like) when a fix is released.
- Please give us a reasonable window to ship a fix before any public disclosure.

## Scope

This policy covers the **desktop application** in this repository. The
[hardware/firmware](https://github.com/sjseth/AI-Case-Sorter-CS7.2), the
[local model server](https://github.com/sjseth/AI-Case-Sorter-Server), and the
hosted community backend are separate projects — report issues in those to their
respective maintainers.

## Notes for users on untrusted content

A few things worth knowing about how the app handles content from others:

- **Models can run code when loaded.** The app loads PyTorch checkpoints with
  `weights_only=True` and warns before importing or downloading a model, but you
  should still only load models from sources you trust.
- **Evaluation reports embed external data.** The model evaluator generates a
  self-contained HTML report from the image folder you point it at; open reports
  only for folders you trust.
- **Community sign-in is optional.** The app runs fully offline; community
  features (sharing, downloads, the feedback loop) are the only network-gated
  surface and require you to sign in.
