# Escalation and evidence bundles

**Owner:** M0005. **Status:** the technical bundle is implemented and tested on synthetic data.
Everything about *who* may approve it, *where* it may go, and *for how long* it may be kept is
**owner-supplied and not defined here** (see "Not defined").

## What a bundle is

A directory that lets someone else reproduce and judge a finding about memory behaviour, with the
least data that does that. It is not a diagnosis and it is not reviewed by the tool.

```bash
axis-memlab bundle --run runs/<run_id> --config configs/default.toml --out bundle/ \
    [--alloc-report sites.json] [--evidence evidence.json] \
    [--plan plan.md] [--reproducer repro.md] \
    [--server-report serverreport.txt --redact-server-report] \
    [--include-records] [--reviewed]
axis-memlab bundle --verify bundle/
```

| File | Content |
| --- | --- |
| `manifest.json` | The run manifest (pseudonymous device label, device facts, consent or incident reference, config hash) |
| `analysis/report.json`, `report.md` | The analysis (or a report you supply), with limitations |
| `limitations.md` | What the data cannot show, in the analysis's words |
| `context/capabilities-errors-events.json` | What could and could not be read, errors, and events (phase markers, triggers); boot id hashed |
| `allocation/report.*` | Optional allocation-site report from `symbolize` |
| `context/compatibility-evidence.json` | Optional evidence record for the advanced diagnostics gate |
| `context/test-plan.md`, `reproducer.md` | Optional operator text, scanned (and redacted with `--redact-context`) |
| `context/server-report.txt` | Optional Axis server report, text only, redacted with `--redact-server-report` |
| `records.jsonl` | Only with `--include-records`; boot id hashed |
| `BUNDLE.json`, `README.txt` | File list with SHA-256 and sizes, tool version, redaction counts, review status, what is **not** included |

**Never included:** images, video, plate text, payloads, command lines, environment, memory
contents, fd targets, file paths, host names, IP or MAC addresses, serial numbers, credentials,
core dumps, contact details.

## Safeguards

* Every text file is scanned before anything is written. If addresses, serial numbers, e-mail,
  credentials, key material, or labelled host names remain, the build is **refused**, naming the
  file and the kind and never the matched text. Nothing is written on refusal.
* A run classified `sensitive` is refused until you pass `--reviewed`, which asserts that a person
  has read the bundle contents. Redaction is a best-effort safety net, not a guarantee.
* Output goes to a new directory; an existing one is never overwritten. `--verify` reports files
  that changed, are missing, or are not listed.
* The server report is accepted as a plain text file up to 5 MiB. If yours is an archive, extract
  the text files you mean to share and pass them one at a time. The firmware, software, SDK, and
  build versions recorded in the manifest are protected from address-style redaction, so that a
  four-part version number is not mistaken for an IPv4 address.

## Before sharing

1. Read every file. 2. Confirm the consent or incident reference is the approved one.
3. Re-run `--verify`. 4. Use only the channel the owner has approved.

## Not defined (owner-supplied, TODO)

* Who may approve a bundle for release, and the consent wording.
* The contact point, the transfer channel, and encryption in transit and at rest.
* The retention period and deletion duty for bundles and for the source runs.
* Vendor-specific submission formats. This repository invents no contact or customer workflow.
