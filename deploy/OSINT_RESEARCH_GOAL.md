Run one bounded batch of the owner's ongoing OSINT tools and techniques research.
Use the existing JARVIS OSINT employee, with Jarvis CEO orchestrating and reviewing
the result. The separate native daily cron job supplies future runs: complete this
batch, report actual results, and remain dormant until Paperclip dispatches work.

Delegate a substantive cumulative-catalog batch to JARVIS OSINT. Copy these
acceptance criteria into its assignment. Read prior catalogs with research_sources
action=knowledge, then retrieve actual official tool documentation using action=fetch
with up to six HTTPS repository/documentation URLs per call. action=search discovers
additional public GitHub tool repositories. The former three-framework restriction
has been removed. No shell, installations, scans or investigations of people or
live targets are requested; this work researches tools and methods.

Maintain a cumulative catalog with at least 15 distinct tools across at least six
categories. OSINT_MIN_TOOLS=15 OSINT_MIN_CATEGORIES=6. Preserve the three documented
AI-assurance entries as adjacent tools, and add real OSINT coverage. On later daily
runs, prioritize at least three previously uncovered tools, expand category gaps,
or refresh changed/outdated documentation using at least three current sources.
Do not repeat an unchanged catalog and call it new work.

Official starting repositories, covering several categories:
- https://github.com/sherlock-project/sherlock
- https://github.com/soxoj/maigret
- https://github.com/smicallef/spiderfoot
- https://github.com/lanmaster53/recon-ng
- https://github.com/laramies/theHarvester
- https://github.com/owasp-amass/amass
- https://github.com/projectdiscovery/subfinder
- https://github.com/exiftool/exiftool
- https://github.com/Exiv2/exiv2
- https://github.com/QGIS/QGIS
- https://github.com/openstreetmap/iD
- https://github.com/apache/tika
- https://github.com/gephi/gephi
- https://github.com/webrecorder/browsertrix
- https://github.com/internetarchive/wayback

Publish the next osint-catalog-vNNN.json. Use preserve_previous=true with new or
updated entries to have the runtime retain complete prior entries automatically.
Follow the prior entry schema: key, name, category, purpose,
documented_capabilities, safe_usage_guidance,
documented_access_and_cost_prerequisites, limitations, sources=[{url,...}],
source_retrieval_date_utc, validation_status=documented_only, actually_tested=false.
Unknown access/cost requirements must be labeled unknown. Sources must be retrieved
now or come from a hash-checked prior native catalog. Deduplicate aliases.

Publish an updated category index and a concise comparison of which tools fit
which jobs and their material limits. In the batch-evidence file, record source
URLs and dates, counts, gaps and proposed next coverage once. Distinguish
documentation review from hands-on testing. The runtime checks schema,
provenance and coverage.

CEO: review signed worker evidence and persisted artifacts. Report what changed,
the actual catalog counts and any material evidence limitation or blocker.
One sentence is enough when it covers those facts.
Do not mark an incomplete or blocked coverage goal as done. The daily schedule is
managed in Cron Jobs; this single batch must not create duplicate schedules or
run a polling loop. Preserve prior research and every batch's native history.
