# Dental Desk — offline shell for Dentist Plus

A Windows desktop app that keeps a dental clinic working when the internet or the power goes down —
an offline shell over the clinic's cloud system, **Dentist Plus**.

Built for a private dental clinic that loses electricity and connectivity several times a month.
One `.exe`, installs itself, no admin rights, no server.

![Calendar](docs/screenshots/01-calendar.png)

---

## The problem

The clinic runs everything in Dentist Plus, a cloud MIS: schedule, patient cards, documents, payments.
When the connection drops, the whole front desk stops. Nobody can see who is booked to which doctor,
open a patient's allergy list, or print a consent form — while patients are already in the chair.

Paper backups go stale within a day. Exports are manual and nobody remembers to make them.

## The solution

A local app on the reception laptop that silently mirrors Dentist Plus every five minutes and keeps
working without it.

- **While online** it pulls the schedule (30 days back, 30 ahead), doctors, branches and full patient
  cards through the Dentist Plus partner API into a local database.
- **While offline** staff work as usual: book and move appointments, fill in the medical record,
  print contracts and consent forms, take payments. The top bar shows how fresh the data is.
- **When the link is back** it syncs again within 30 seconds, and everything done offline is waiting
  in one checklist — or is sent to Dentist Plus automatically, if the clinic switches that on.

## What's inside

| | |
|---|---|
| **Calendar** | Day / 2 days / week, by doctor or by chair, doctor filter, click an empty slot to book, drag a visit to another time, doctor or day, recurring visits (weekly to monthly, cancel the rest of a series), overlap warnings, print the day |
| **Waiting list** | Patients who want an earlier or a specific time, with a count above the calendar and a hint when a visit of that doctor is cancelled |
| **Visit reminders** | One click opens WhatsApp with a ready reminder text (name, date, time, doctor, clinic) or copies it for Telegram; editable template; sent reminders are marked for the whole team |
| **Patient card** | Visits, dental formula (permanent and milk teeth), treatments, payments, treatment plans, documents, notes, full history feed |
| **Medical record** | Complaints, anamnesis, examination, treatment with one-click phrase templates, ICD-10 dental codes, interactive tooth chart: several states per tooth, caries / filling / temporary filling on each of the five surfaces, filled canals and posts, implants with crowns, bridges joined across abutments and pontics |
| **X-rays and files** | X-rays (DICOM included, windowing and MONOCHROME1 handled), photos, scans and PDFs in the patient card; add by button, drag & drop, Ctrl+V or from the visiograph's export folder; viewer with zoom, pan, brightness, contrast, invert, rotate and a before/after split comparison; files mirrored to the backup flash drive |
| **Periodontal chart** | Pocket depth, recession, bleeding, mobility and furcation for 32 teeth; fast keyboard entry, voice entry ("tooth sixteen, three two four, bleeding, palatal…"), colour-coded depths, mean depth / CAL / % ≥ 4 mm / BOP and the change since the previous chart |
| **Allergy check** | The patient's allergies (card and anamnesis) against the treatment, recommendations and billed services: same substance is a stop, same group (e.g. amide anaesthetics, penicillins) is a warning |
| **Visit templates and prescriptions** | 17 visit templates (protocols) for therapy, surgery, prosthetics, orthodontics, periodontics and pediatrics fill the record fields with the chosen tooth, ICD-10 diagnoses, the tooth state and prescriptions in one click; any visit can be saved as a template; a medicines list with dose, how to take and duration; prescriptions are checked against the patient's allergies |
| **Documents** | 15 templates (consents, consent to record a visit, contract, plan, act, extract, form 043/u, receipt, prescription form 107-1/u, referral, patient memo) filled from patient, doctor, clinic and invoice data; edit in preview, print or save as PDF |
| **Signatures** | Documents signed with a mouse, pen or finger on this screen or on the patient tablet; signer, time, place and a hash of the text are kept, an edit after signing is flagged, signatures print under the document |
| **Patient tablet** | Any tablet browser on the clinic Wi-Fi, paired once with a 6-digit code (no login); staff send a document or the questionnaire from the card and see "done" when the patient signs; the tablet key opens only its own task |
| **Health questionnaire** | Yes/no questions with details, signed by the patient; saved as a signed document, key answers shown on the card, allergies fed into the allergy check |
| **Tax deduction certificate** | Certificate of paid medical services for the tax office: year totals from payments, payer other than the patient, numbering per year, saved to the card, yearly register |
| **Excel export** | Report, accounting, CRM and sterilization tables saved as .xlsx with numbers kept as numbers (built without extra libraries) |
| **Money** | Invoices from the price list with per-line discounts, partial payments, staged treatment plans billed step by step, daily cash report |
| **Advance, refunds, installments** | Patient advance without an invoice and paying invoices from it (a linked pair of «from advance» rows, so the day's cash is not doubled and the doctor gets the payment), overpayments count as advance; refunds as negative payments with a return receipt for the refunded sum and bonuses taken back; payment schedules with paid / waiting / overdue instalments, a printable schedule, overdue payments in the debts report, on the director's screen and as front-desk tasks |
| **Memberships** | Membership types (services × count, price, months); selling one bills an invoice; «by membership» lines cost 0 and use up visits, checked against the patient, the expiry and what is left |
| **Cash drawer by shifts** | Open a shift with the cash in the drawer; expected cash = opening + cash payments − cash refunds + certificates sold for cash + cash in − cash out; cash in/out with reasons (a cash expense goes to accounting); closing with counted cash, card terminal and SBP reconciliation, the difference and a printable shift report |
| **Voluntary health insurance (ДМС)** | Insurers, patients' policies and letters of guarantee with limits; an invoice paid by the insurer is not the patient's debt; monthly registries in Excel, «sent» and «paid» (refused invoices go back to the patient), insurers' debt in the debts report |
| **Treatment plan options** | One plan with «economy / standard / premium» options: common items plus each option's own services, warranty, term and a note; the patient's choice confirms the plan and only the chosen option can be billed; analytics count an undecided plan once, at its cheapest option. 3.6: proposed / sold / in work / finished / abandoned / refused with history, a call list for abandoned plans and a report by status and doctor |
| **Plan presentation** | A patient-facing page: clinic header, the tooth chart with plan teeth and stage numbers, options side by side, stages and prices, signatures; print, a real PDF (headless Edge, no extra software), save to the patient's documents, or send to the patient tablet where the patient picks an option and signs |
| **Director's screen** | The director lands on it: today's and the month's payments against the same days of last month, a forecast from the pace of working days, plan completion, average check, new patients, cancellations and no-shows; doctors with plan, a «where we should be today» tick, forecast and load by the work schedule; plain-language hints (behind plan and by how much a day, free slots in the next days, the weekday and time of day with most no-shows, plans not started, debts) that open the right screen; the week ahead |
| **Plan vs fact** | Monthly targets for payments, visits and new patients for the clinic and every doctor, fact, percent and forecast (visits count what is already booked), copy last month's plan; synced between laptops |
| **CRM** | Front-desk tasks with due dates and assignees, a menu badge and one-click call results; tasks made by rules — a call the day after an extraction, an implant check-up, a hygiene recall in six months, an agreed or started plan with no visits, a low visit score for the director — with ids built from rule, patient and date so two offline laptops make the same task; requests on a board «new → contacted → booked → came / lost» that move on by themselves from the schedule, phone matching against existing cards, a funnel by source and channel; patient segments (lapsed, unfinished plan, service long ago, birthday, age, source, doctor, debt) with a WhatsApp mailing queue |
| **Visit scores and reviews** | After-visit NPS 0–10 on the patient tablet, by WhatsApp or phone; a high score shows QR codes of the clinic's Yandex Maps and 2GIS pages on the tablet, a low one opens a task for the director; NPS by doctor |
| **Advertising payback** | «Advertising» expenses name the source they paid for; the sources report shows requests, new patients, payments, spend, cost of a new patient and payback |
| **Analytics** | New vs repeat patients and revenue from new ones, retention cohorts (returned within 3 and 6 months), patients who stopped coming; chair and doctor load, free and lost hours, a weekday × hour heat map; conversion consultation → plan → treatment per doctor with plan sums, refusals and amounts billed from plans; material cost and its share of revenue per service |
| **Dental lab orders** | Work orders with teeth, shade, fitting and due dates, statuses and the lab's price; overdue highlighted, printable order form, paying a lab records an expense, lab cost can be subtracted from a doctor's pay, orders visible in treatment plans |
| **Certificates, bonuses, families** | Gift certificates sold at the cash desk and redeemed by code with a remaining balance; bonus points as a percent of money payments with a cap per invoice; families share bonuses and get a discount offered in every invoice; deleting a payment gives everything back |
| **SBP and terminal** | The clinic's static SBP QR code with the amount on screen or on the patient tablet; an optional terminal operation number on card payments; the day's cash counts real money only |
| **Transfer to Dentist Plus** | A checklist of everything created offline — or automatic sending of new patients and appointments |
| **Dictation** | The doctor dictates the visit; speech is recognized on the laptop (Whisper, no internet), split into record fields, ICD-10 codes and tooth states by offline rules, optionally tidied by any OpenAI-compatible model with the patient's name and phone removed; a record shows whether it was made by dictation, a visit recording or with the AI |
| **AI assistant** | A chat in the top bar (and by voice): «who do I have tomorrow», «revenue of Dr. Guseva in October», «patients without hygiene for 6 months», «book Petrova on Thursday with Guseva at 15:00», «remind me to call Ivanov in a week», «translate into English: …». Answers come from the program's own data with the rights of the employee who asks (the same permissions as the screens); bookings, tasks and notes are only proposed and done by the usual method after «Yes». Simple rules understand dates in any form and surnames in any grammatical case (Petrovu after «book» is Petrova, after «call» — Petrov) without the AI; with the AI the model picks a tool from the question only — it never sees patient data |
| **Texts in seconds** | From the record: a memo for the patient in plain words, an explanation of the diagnosis, an extract, a letter to the insurer; a plan option described for the patient; any document or message translated (English, Turkish, Georgian, Armenian, Kazakh, Uzbek, Kyrgyz, German, Chinese) with the layout kept. Without the AI the same drafts are written by rules; with it the model retells the record and the clinic's standard advice, with the patient's name, phone and dates removed. Each kind of text has a length: the model gets as many tokens, the reply loses a greeting and is cut at whole sentences (a plan option — one or two sentences) |
| **Record check** | Live hints in the record form and on the patient card: no ICD-10 diagnosis or tooth, no examination, an extraction or root canal without an X-ray, anaesthesia without the drug and dose, a medicine without a dose, no consent to treatment or to personal data, an old health questionnaire, an insurer's invoice without a record — rules, not AI |
| **Weekly summary** | The director's screen: last week against the week before — payments, visits, no-shows and their worst time slot, new patients, load per doctor, unfinished plans per doctor, overdue CRM tasks, debts, the next 7 days; optionally retold by the AI as a short note (figures only, no patient data) |
| **Voice tooth chart and notes** | «Eighteen missing, seventeen crown, from twenty-six to twenty-eight missing, crown on thirty-six» marks the chart after a check; a spoken note goes to the patient's notes and «call back in a week» becomes a CRM task |
| **Consent to record a visit** | A visit is recorded only after the patient's consent is noted (aloud, on paper or on the printed form); the consent is kept in the card, can be withdrawn and syncs to the other laptops; the server refuses a visit recording without it |
| **The clinic's own local model** | On top of the downloaded Gemma 3 / Qwen 2.5 the program builds «dental-desk» (Ollama Modelfile: the program's rules, dental terms, settings tuned on the quality check) in seconds; a quality check runs 11 real tasks of the program and scores accuracy, Russian and speed; `tools/ai_dataset.py` prepares an anonymous training set for a later LoRA |
| **Double bookings** | Overlaps between laptops that worked offline are flagged in the calendar and the transfer list, and are not sent to Dentist Plus until resolved |
| **Fiscal receipts** | 54-FZ receipts on ATOL (DTO 10 web server) or Shtrih-M (COM driver) registers, or a test mode: receipt on payment, partial payment and credit rules, returns, shifts, X/Z reports, failed receipts kept for retry |
| **Stock** | Materials with minimum levels, supplier invoices, write-offs with a printed act, stock counts, consumption norms per service — billing a service or (3.5) a finished Dentist Plus visit writes its materials off; cabinets and branches with transfers; the cost of every service. A receipt, write-off or count can go without documents: the actual balance moves, the balance «by documents» (seen with the accounting right only) does not, act numbers stay without gaps, a receipt can be written down as an expense of the day |
| **Expiry dates and lots** | Lot number and expiry date on every receipt line; lots on hand worked out from the move ledger first-expired-first-out (nothing stored, so edited invoices never break them); expired and soon-to-expire materials highlighted with a filter and a counter on the menu badge; one-click write-off of everything expired |
| **Purchase list** | One button: everything below the minimum or lasting under 14 days, quantity from the last 60 days' use to cover 30 days, the cheapest supplier by last purchase price with the other offers alongside, grouped by supplier with a printed request, Excel and a pre-filled receipt |
| **Barcode scanner** | Keyboard-mode USB scanners in the receipt form: a known code adds a line or +1, an unknown one offers to create the material; GS1 / «Честный знак» DataMatrix codes fill the lot and expiry date |
| **Equipment** | Register with inventory numbers, location, warranty and service dates, service history, write-off with a commission and a printed act |
| **Sterilization journal** | Autoclave and dry-heat cycles with mode, chemical and biological indicators, load and operator; cycle numbers per sterilizer and year, failed cycles flagged, printable for inspections |
| **Clinic network** | One computer is the server; reception, surgeries and the director's PC connect over the local network and find it automatically |
| **Staff accounts** | Self-registration, director approval, password sign-in, positions with per-person permission overrides, action journal |
| **Positions and rights** | The director makes positions («Senior administrator», «Accountant»…) and ticks what each may see and do, built-in positions included, in six groups of rights; a change works at once for everyone in the position on every laptop (the menu of a signed-in employee follows it), synced; rights added by later versions reach saved positions from the position's default; separate rights for the expenses of the day and for Excel export |
| **Expenses of the day** | Administrators write down every expense of the day — with a receipt or without a document — and see only today's own entries (next morning the list is empty); cash «from the drawer» goes into the open cash shift; the history and every employee's entries only with the «Accounting» right |
| **Day report in Telegram and by e-mail** | At the set time, when the cash shift is closed or by a button the owner gets the report in Telegram (through the clinic's own bot made at @BotFather; the program finds the owner's chat after «Start», Bot API over HTTPS, no server of ours) and/or by e-mail: payments by method, every expense of the day (with and without documents), the cash shift, and an Excel file; mail goes through an ordinary mailbox with an application password, the bot token and the password are stored with DPAPI; the channels are separate — a failed one is retried alone; without internet the report waits and goes later; the sent day is synced so a second computer does not send it again |
| **Backups** | A verified, compressed copy of the whole database at start, every 2 hours and on exit, made with SQLite's online backup while the app keeps working; rotation (everything for 2 days, one per day for 30); an optional second folder on a flash drive; one-click restore that first saves the current data and then restarts the app |
| **Cloud sync** | Every laptop keeps working on its own; when there is internet, changes meet through a multi-clinic cloud server. Row-level replication with a three-way merge: edits of different fields both survive, a clash of one field keeps the later edit and saves the other value in a journal with a «bring back» button, a row deleted on one laptop and edited on another is kept. End-to-end encrypted (AES-256-GCM, clinic key never leaves the clinic), X-rays included |
| **Subscriptions** | Clinics (tenants) with a 30-day trial, three plans by number of computers, grace period; an expired subscription pauses the sync, never the work on the laptops |
| **One-click updates** | Once a minute the program checks a signed `latest.json` (Ed25519, public key built in) in a GitHub release feed; «Вышла новая версия» pops up bottom right for every employee, «Обновить» downloads the installer, checks size and SHA-256 and runs it; the installer closes the program, which makes a backup on exit |
| **PIN sign-in** | On a shared computer staff pick themselves and type a 4–6-digit PIN; five mistakes lock the PIN until a password sign-in |
| **Moving a base in** | Patients from IDENT, Dentist Plus or any table (.xlsx / CSV, Windows-1251 too): columns recognised by their titles, editable mapping, preview, duplicates by phone or name + birth date skipped |
| **Settings by sections** | Seven sections in a list (general, Dentist Plus, voice and AI, cash and payments, X-rays and tablet, data and protection, help) and a search across all of them; the last section is remembered |
| **Disk encryption check** | Settings show whether the drive with the database is protected by BitLocker / Device Encryption (read without admin rights) and how to turn it on |

| Patient card | Dental formula |
|---|---|
| ![Patient card](docs/screenshots/04-patient-card.png) | ![Dental formula](docs/screenshots/05-dental-formula.png) |

| Medical record | Document from a template |
|---|---|
| ![Medical record](docs/screenshots/07-medical-record.png) | ![Contract](docs/screenshots/08-document.png) |

| Invoice | Transfer checklist |
|---|---|
| ![Invoice](docs/screenshots/09-invoice.png) | ![Transfer](docs/screenshots/10-transfer-journal.png) |

## Three decisions worth explaining

**A tolerant reader instead of a fixed schema.** The partner API documents only its login endpoint.
Rather than guess one format and break on the first real response, every field is read through a list
of candidate names and formats — `start`, `date` + `time`, ISO with a timezone, Unix seconds,
`dd.mm.yyyy`; patient as an id or a nested object; doctor as an object or a list. The raw JSON is
always stored too, so nothing is lost, and a built-in **API diagnostics** screen shows real responses
so the mapping can be tuned without a rebuild. The sync is tested against four differently shaped fake
servers.

**Writes that can't create duplicates.** Automatic sending to the clinic's live system is the riskiest
part, so it follows strict rules: an item counts as sent only on a 2xx answer; a write that timed out
is never retried automatically (status "check by hand"); before creating a visit the app looks for the
same visit in Dentist Plus; after creating it re-reads the day and compares time and doctor. Endpoint
paths and field names live in settings, so they can be corrected on site. Medical records, documents
and payments stay manual — payments need a fiscal receipt anyway.

**Local edits as an overlay, not a fork.** Offline changes never touch the synced tables. A moved
appointment is a local row that hides the synced one; the calendar is a `UNION` of both. When the next
sync brings the change back from Dentist Plus, the overlay disappears on its own and a temporary patient
card is merged into the real one. Sync can replace its data at any time without losing anything typed
by staff.

## Clinic network without a server (3.0)

A clinic where the power — and the router with it — goes off several times a day cannot depend on one computer
being the server. Since 3.0 every laptop keeps its own database and works on its own; computers of the same
clinic that see each other in the Wi-Fi find each other by a UDP broadcast and exchange changes directly, every
minute and within a second or two after any change. There is nothing to set up: the installer adds the firewall
rule (one UAC prompt), the first computer creates the clinic, and a new computer finds it and asks to join — the
director clicks «Принять» on any of his computers that is online, after checking a six-digit code shown on both
screens. Until then the new computer gets nothing: patient data never goes to a device just because it is in the
Wi-Fi.

* **Pairing.** The new computer sends a one-time X25519 public key; the code on both screens is made from it, so a
  substituted key shows a different code. On «Принять» the clinic key is sealed for exactly that key
  (X25519 + HKDF + AES-GCM). Every later request and answer is sealed with the clinic key (AES-256-GCM).
* **Versions, peer to peer.** A local change becomes a version with a version vector (`{computer: counter}`,
  the counter being a time in ms, so it keeps growing after a restore from a backup) and a link to the row it
  was made from. A computer gives each peer the versions with a local change number above what that peer already
  took from it, and passes on what it got from a third computer, so every change reaches everyone. A vector that
  covers another wins; two concurrent versions are merged field by field against their common ancestor, and the
  result gets a version made from its content — two computers merging the same pair end up with the same row
  instead of bouncing it. Files go the same way, encrypted, by checksum.
* **Cloud and LAN together.** The cloud carries the same versions; each computer remembers which version the
  cloud has, so a row that came over the Wi-Fi is not sent again and is never a false conflict.
* **Upgrading 2.x.** A computer that worked alone keeps its data and becomes a clinic of its own; the director
  joins the laptops together in Settings → «Сеть клиники» («Объединить с ним»), and their patients, bookings,
  payments and staff are merged. A former client computer gets its own database and asks to join.

### Accounts and permissions (2.0)


Version 2.0 turns the single-laptop app into a small clinic system without adding any infrastructure.
The same `.exe` asks on first start whether this computer is the **server** or should **connect to
one**. The server keeps the database and the Dentist Plus sync and serves the UI over HTTP; other
computers find it with a UDP broadcast and open it in their own window. If the router hands out a new
address, clients find the same server again by its id.

Every request carries a session token and is checked on the server against the employee's
permissions, so a hidden button is never the only protection. A new employee registers, the director
approves the request and picks a role; any role can be fine-tuned per person. Passwords are PBKDF2
hashes, only token hashes are stored, repeated wrong passwords are throttled, blocking an employee ends
their sessions at once, and the last director cannot be demoted. Bookings, payments, treatments,
permission edits and sign-ins land in an action journal with the employee's name.

The same server is ready to move to a hosted machine later: the UI already talks to it only over HTTP.

## Updates from GitHub (3.1)

Every laptop checks once a minute whether a new version is out and shows «Вышла новая версия X.Y.Z» bottom right
to whoever works on it; «Обновить» downloads the update, checks it, closes the program (which saves a backup)
and opens the new version. Laptops of a clinic work on their own, so any employee may update, not only the director.

* **Where.** A public GitHub repository holds nothing but releases. The program reads
  `https://github.com/<owner>/<repo>/releases/latest/download/latest.json`: a download link, not the REST API,
  so the check once a minute from several laptops behind one IP is not limited to 60 requests an hour; it sends
  `If-None-Match`, and an unchanged file comes back as a short 304. A repository without releases is just «no update».
* **Trust.** `latest.json` is signed with Ed25519 (the secret key stays with the developer, DPAPI); size and
  SHA-256 are checked after the download and again right before the installer starts.
* **Privacy.** The clinic's build carries its name, so the installer is stored encrypted (AES-256-CTR, neutral name
  `update-X.Y.Z.bin`) and so are the notes (AES-GCM), with a key that exists only in that build (`brand.json` →
  `update_key`, never in git). A build with another key or none explains that the update is not for it.
* **Publishing.** `tools\update_sign.py feed --github <repo>` once (address and key into brand.json, a DPAPI copy of
  the key), then after each build `.\publish-update.ps1`: signs, encrypts and uploads a draft release, adds
  `latest.json` last and only then marks the release latest.

## Add-on over Dentist Plus (3.2)

Dentist Plus is the clinic's official, certified system: the medical record and every document an inspector may ask
for live there. Since 3.2 the program says so out loud. The mode «Надстройка над Dentist Plus» is on by default, also
for installations updated from older versions, and only the director switches it (Settings → Dentist Plus → «Режим работы»).

* **Where the data comes from.** Patients, appointments, doctors and services carry a discreet «из Dentist Plus».
* **Drafts.** The medical record, visit templates, dictation, visit recording, the AI record check, prescriptions and
  referrals carry «Черновик для Dentist Plus — официальная запись в Dentist Plus».
* **Official documents.** The contract, consents, refusal, 043/у, the record extract, the visit note and the tax
  deduction certificate say «Не для контролирующих органов — официальный документ печатайте из Dentist Plus» on
  screen and at the bottom of the printed sheet, or are hidden altogether (a second switch). Internal papers — the
  health questionnaire, memo, plan presentation, receipt — stay as they are.
* **What is put away.** The cloud for many clinics with its subscription and moving a base in from IDENT are hidden
  in the UI and the settings search; a computer already in the cloud keeps its panel. Nothing is deleted and no method
  is blocked: switching the mode off brings everything back. The clinic network and updates work in both modes.

`app/addon.py` holds the lists and the setting, `app/ui/addon.js` the labels; the labels are always in the page and
CSS shows them only under `body.addon`, so the mode switches live (the 3-second status carries it) without a reload.

## No double entry (3.3)

The partner API of Dentist Plus does not accept medical records, so a record written here — by hand, from a visit
template, by dictation or with the AI — is pasted into Dentist Plus by the doctor. 3.3 makes that a few clicks and keeps
it from being forgotten.

* **«Скопировать для DP».** One click puts the whole record on the clipboard in the order of the Dentist Plus form —
  Жалобы, Анамнез, Объективно, Диагноз (МКБ-10), Лечение, Рекомендации; «по разделам» copies one field at a time.
  Diagnoses go with their ICD-10 code and tooth, prescriptions with dose and schedule. It works from the patient card,
  the record editor (unsaved text too) and the list. Sections, their order and names are a clinic setting
  (`dp_settings`, synced like the rest of the clinic data).
* **The mark «перенесено в Dentist Plus».** Who and when (`records.transferred_by` / `transferred_at`); the row travels
  to the other computers over the clinic network and the mark goes to the action journal. Saving a record again
  unchanged keeps the mark, a real change drops it. Optionally the copy marks the record by itself.
* **«Не перенесено».** «Перенос» → «Медкарта» lists unmarked records by day and doctor with a 30-day counter on the menu;
  at 20:00 (configurable) a doctor with records of today left gets a reminder; the day report (Telegram and e-mail)
  has a line per doctor.
* **«Сверка».** Records, invoices, payments and documents of a period against the marks, and finished Dentist Plus
  visits (from the synced schedule and its archive) that have no record here — matched by the visit, a visit changed
  here, or patient + day. Dentist Plus payments are not in its API, and the screen says «нет данных из Dentist Plus».
* **Rights.** The director and staff with «Отчёты» or «Перенос в Dentist Plus» see everyone; a doctor sees and marks only
  the records of the doctor his account is linked to. Everything works offline.

`app/dp_transfer.py` holds the rules, `app/ui/dp.js` the screens.

## Finance and staff (3.4)

The owner's management accounting and the staff's time, built on what the program already has — the financial model,
the payroll, the expenses of the day, cash shifts, work schedules and the day report.

* **Profit and loss by months («ОПиУ»).** The month of the financial model laid side by side for 3, 6 or 12 months:
  revenue, variable costs, margin, fixed costs by category, salaries, operating and net profit, totals and shares.
  Salaries are accrued pay, so payouts are never counted twice.
* **Cash flow («Деньги»).** Money that really moved, by days or months, with a running total and by «where the money is»:
  the drawer, the bank account and cards, employees' own money. Paying from the advance, by bonuses or a certificate moves
  no money; cash put into or collected from the drawer is a move inside the clinic. Expenses without a document are shown
  apart, and cash shifts are reconciled against the terminal and the bank. Dentist Plus payments are not in its API — the
  screen says «нет данных из Dentist Plus».
* **Administrators' motivation.** Rules for all administrators or per person: a sum per booking that came, per new patient,
  per CRM request brought to a visit, a percent of own sales (invoices the employee made, certificates sold), a percent of
  the clinic's revenue and a bonus when the clinic's plan is met. Everything is 0 until the director sets it; the bonus goes
  into the payroll and the profit. Bookings are logged when a visit is created here (`staff_bookings`) and matched to the
  visit later by id, by doctor and minute, or by patient and day — the local visit disappears once Dentist Plus has it.
* **Timesheet.** «Я пришёл» / «Я ушёл» under one's own account; «Графики» → «Табель» puts the marks against the schedule:
  late, early, absent, no leaving, outside the schedule, with a grace in minutes. Corrections are flagged and journaled.
  Accounts are stored by login, not by the local integer id, so every computer shows the same person; someone who never
  marks is not «absent».
* **The week and month report.** On Mondays and on the 1st the owner gets the last week / month through the channels of the
  day report (Telegram and/or e-mail, Excel attached); without a configured channel nothing is sent. Missed reports are
  retried for three days, and `period_reports` syncs so a second computer does not send the same report.

`app/finreport.py` holds the profit and loss, the cash flow and the reports, `app/motivation.py` the rules and the bonus,
`app/timesheet.py` the marks; `app/ui/finstaff.js` the screens. New tables travel over the clinic network like the rest.

## Stock automation (3.5)

The stock follows the visits that really happened in Dentist Plus, knows which cabinet holds what, and tells the owner what a
service costs.

* **Write-off by Dentist Plus visits («По приёмам»).** A finished visit (status «завершён» / «пришёл») with its services
  becomes a write-off of the materials of the services' norms — the same «техкарта» that already writes off an invoice made
  here. The services come from the visit as Dentist Plus gave it (`services`, `items`, `works`, nested `service`, an embedded
  invoice — the partner API does not document them, so the usual shapes are tried), then from the visit's title when it is
  exactly a service's name; otherwise the screen says «нет данных из Dentist Plus» and the services are entered by hand.
* **Safe by default.** Visits are drafts until someone with the stock right confirms them. The automatic mode writes them
  off by itself every five minutes, but only visits from the day it was switched on, and a visit still «in the chair» waits
  for the next day. A reverted visit is never taken again automatically.
* **Never twice.** One row per visit (`stock_visit_use`, keyed by the Dentist Plus visit id); a visit with an invoice here
  (by the visit, a visit edited here, or patient + day) is left to the invoice. The document is `V-<visit>` and its moves get
  stable `uid`s, so two laptops that wrote off the same visit offline converge to one write-off instead of two.
* **Places («Места хранения»).** The main stock, cabinets (with the Dentist Plus chair) and branches. Every move carries its
  place (`stock_moves.location_id`), a transfer is one numbered document with − there and + here, so the clinic's balance and
  the FEFO lots stay as they were. Receipts, write-offs and stock counts can name a place and cannot take more than it holds.
  A visit is written off in the cabinet of its chair, then the place of its branch, then the default place.
* **Cost of services («Себестоимость»).** Materials by norm × last purchase price + laboratory + other costs + the doctor's
  percent (the service's own, the clinic's setting, or the average of the doctors' pay schemes). The month view counts the
  services made — invoices here and visits written off — against that cost. The P&L can take materials from the stock
  (what left it in the month) instead of the purchases; never both.

`app/stock_auto.py` holds the visit write-off and the cost, `app/stock.py` the places and transfers, `app/ui/stock-auto.js`
the screens. The four new tables sync over the clinic network; staff are stored by login.

## Treatment plan statuses (3.6)

A treatment plan is a sale: it is proposed, sold, worked on and finished — or it is quietly abandoned. The program now tells
these apart, finds the abandoned ones and gives the front desk a call list for them.

* **Statuses.** «Предложен» (Предварительный), «Продан» (Подтверждён), «В работе» (Активен), «Завершён» (Лечение завершено),
  the new «Брошен» and «Отказ». The stored names stay those of 2.9, so every report, segment and call list keeps working.
* **Automatic, where the data allows** (on by default, the rules are a setting of «Отчёты»): a bill by the plan or a finished
  Dentist Plus visit with a service of the plan → «В работе»; every billable item billed → «Завершён»; sold or in work with no
  visit, bill or booking for 60 days → «Брошен» (a proposed plan only when the director sets its own number of days); a bill,
  a visit or a booking brings an abandoned plan back. A status set by hand wins — the rules only look at what happened after it.
* **History.** Every change is a row of `plan_status_log` with who (by login), when and why; the plan shows it, the
  automatic pass writes one line to the action journal. An automatic row's id is made of the plan, the change and the row
  before it, so two laptops that abandon the same plan offline keep one row after the sync.
* **Call list («CRM» → «Обзвон» → «Брошенные планы»).** Who to call, the plan, the money left, the last visit and why the plan
  is in the list; «к звонку» or all, by doctor and by how long ago. Results: reached, not reached (again tomorrow), call back
  on a date (a CRM task due that day — the menu badge reminds), refused with a reason (the plan becomes «Отказ»), booked (back
  to work as soon as the visit is in the schedule). Calls are rows of the existing call journal with the plan and the caller's
  login; the plan's CRM tasks are closed by the call, and closing the «перезвонить» task on the tasks screen works the same.
* **Report («Отчёты» → «Планы лечения»).** Plans made in the period by status and by doctor, the funnel «предложен → продан →
  в работе → завершён», the money left in abandoned plans now, plans brought back by calls and by whom; a doctor without
  «Отчёты» gets only own plans. A new motivation rule pays for an abandoned plan brought back after the employee's call.

`app/plan_status.py` holds the statuses, the rules, the call list and the report; `app/ui/plan-status.js` the screens. Both
new tables sync over the clinic network.

## Architecture

```
Dentist Plus partner API
        │  every 5 min while online (7-day chunks, paged, retries with Retry-After)
        ▼
  sync.py ── api_client.py ── normalize.py (tolerant field reader)
        │                         pusher.py (optional automatic sending)
        ▼
  SQLite (WAL, one transaction per chunk — safe on power loss)
        ▲
  server.py  HTTP API + UI files · auth.py (accounts, roles, sessions, journal) · UDP discovery
        ▲  clinic LAN
  main.py on every computer (pywebview window, server or client)
        ▲
  ui/  plain HTML/CSS/JS, no framework, works fully offline (fonts bundled)

  replica.py  triggers → sync_dirty · three-way merge · conflict journal
        │  cloud.py: AES-GCM rows under HMAC names, pull → merge → push (optimistic versions)
        ▼  https
  cloud/cloud_server.py  many clinics, one SQLite file each, tenant taken from the device token only
```

| File | Role |
|---|---|
| `app/main.py` | Window, server/client start, data API, autostart |
| `app/ui/platform.js` | Settings for the cloud, updates and import; PIN sign-in |
| `app/installer.py` | Install and update the program folder for the current user: close the running copy, swap folders safely, shortcuts |
| `app/setup_main.py` | The shipped `.exe`: a small installer carrying the program folder as a zip |
| `app/server.py` | Each computer's own server: HTTP API, permission checks, UI files, network discovery |
| `app/p2p.py` | 3.0 clinic network: discovery, pairing with the director's approval, sealed peer-to-peer exchange of versions and files |
| `app/auth.py` | Staff accounts, password hashing, sessions, roles and permissions, action journal |
| `app/speech.py` | Offline speech recognition: model download, transcription |
| `app/dictation.py` | Dictated protocol → record fields, ICD-10, tooth states |
| `app/ai.py` | Optional language-model layer (OpenAI-compatible), anonymization, validation, common rules and answer cleaning |
| `app/assistant.py` | AI assistant 2.13: dates, times and surnames in any case by rules, tools with the asker's rights, proposals (booking, task, note), the model as a tool picker, voice notes |
| `app/ai_docs.py` | Drafts from the record (memo, explanation, extract, insurer letter), plan option text, line-by-line translation; rules without the AI |
| `app/medcheck.py` | Record and card check: what is missing for an inspection or an insurer |
| `app/consents.py` | The patient's consent to a visit recording |
| `app/daily.py` | 2.14: expenses of the day (own and today only, the cash drawer), the day report: text, Excel, SMTP sending, retry and the moment to send |
| `app/ui/daily.js` | Expenses of the day in «Cash», the report preview and «send now», mail settings |
| `app/ui/staff.js` | Staff: requests, positions and their rights by groups, per-person rights, action journal |
| `app/llm_local.py` | AI on this computer: Ollama and models downloaded by the program, the clinic's own «dental-desk» model, the background quality check |
| `app/ai_eval.py` | The program's test questions for a model: accuracy, Russian, speed (also `tools/ai_eval.py` to compare models) |
| `app/ui/ai.js` | The assistant panel, drafts and translation, record check, voice chart and notes, consent dialog, weekly card, local model settings |
| `app/conflicts.py` | Double-booking detection |
| `app/fiscal.py` | Fiscal receipts: receipt rules, test mode, ATOL web server and Shtrih-M drivers, shifts, returns |
| `app/stock.py` | Materials as a ledger of moves, receipts, write-offs, stock counts, service norms, lots and expiry (FEFO), purchase list, barcode parsing (GS1), equipment register |
| `app/ui/stock-lots.js` | Lots in the material card, expired write-off, purchase list window and supplier requests |
| `app/stock_auto.py` | 3.5: write-off by Dentist Plus visits (drafts or automatic, never twice, reversible), the place of a visit, the cost of services, materials for the P&L |
| `app/ui/stock-auto.js` | «По приёмам», «Места хранения» and transfers, «Себестоимость» |
| `app/plan_status.py` | 3.6: treatment plan statuses for sales — automatic rules, history, the call list for abandoned plans, the report |
| `app/ui/plan-status.js` | Status and history in the plan, «Брошенные планы» in «Обзвон», «Планы лечения» in «Отчёты», the rules |
| `app/backup.py` | Automatic backups: online copy, integrity check, rotation, second folder, restore with a safety copy |
| `app/security.py` | Disk encryption state (BitLocker / Device Encryption) without admin rights |
| `app/waitlist.py` | Waiting list: entries, filters by doctor and day, booked / removed |
| `app/files.py` | Patient files: storage, previews (Pillow, pydicom), visiograph folder import, mirror for backups |
| `app/perio.py` | Periodontal chart: validation, statistics, voice commands |
| `app/allergy.py` | Allergy rules: substances, groups, allergies from the card and anamnesis |
| `app/sterilization.py` | Sterilization journal |
| `app/forms.py` | Signatures and the health questionnaire |
| `app/tablet.py` | Patient tablet: pairing codes, device keys, tasks, throttling |
| `app/taxcert.py` | Tax deduction certificates and their register |
| `app/xlsx.py` | Minimal .xlsx writer |
| `app/lab.py` | Dental lab orders, labs, paying labs |
| `app/loyalty.py` | Gift certificates, bonus points, families |
| `app/plans.py` | Treatment plan options: cleaning, sums per option, billable items, the patient's choice, signing on the tablet, PDF through headless Edge |
| `app/finance.py` | Money 2.12: advance and its use, refunds, payment schedules and overdue list, memberships, cash shifts, insurers, policies and registries |
| `app/ui/finance.js` | Advance, refund, schedule, membership, cash shift and ДМС dialogs, the debts-report reminders |
| `app/crm.py` | CRM: tasks and the rules that make them, requests and the funnel, segments, visit scores (NPS) and review QR codes, advertising spend by source |
| `app/ui/crm.js` | Tasks, the requests board and funnel, segments and the WhatsApp mailing, scores, CRM settings, the CRM tab of the patient card |
| `app/director.py` | Director's analytics: visit history (schedule + archive of Dentist Plus visits), main screen and hints, patients and retention, load, conversion, materials share, plan vs fact |
| `app/finreport.py` | 3.4: profit and loss by months, the cash flow by days / months and accounts, the week and month report and its sending |
| `app/motivation.py` | 3.4: the administrators' motivation rules, bookings made by staff, the monthly bonus for the payroll |
| `app/timesheet.py` | 3.4: arrival and leaving marks, the timesheet against the work schedule, stable person keys |
| `app/ui/finstaff.js` | 3.4: «ОПиУ», «Деньги», «Мотивация», the owner's report window, «Табель» and «Я пришёл» |
| `app/replica.py` | Replication: change capture by triggers, integer ids made stable (uid / login), three-way merge, conflict journal |
| `app/cloud.py` | Cloud client: connection codes, clinic key, AES-GCM encryption, pull / merge / push loop, encrypted file transfer |
| `cloud/cloud_server.py` | Multi-clinic sync server (standard library only): devices, plans and trials, versioned rows, files; admin commands |
| `app/updates.py` | Update check once a minute (GitHub release feed, ETag): signed latest.json, encrypted installer, download with size and SHA-256 check, starting the installer |
| `app/importer.py` | Patient import from .xlsx / CSV: column recognition, phone and date clean-up, duplicates |
| `tools/update_sign.py` | Developer side: signing key (DPAPI, outside the repository), the build's encryption key and feed address, signing a release |
| `tools/publish_update.py` | Uploading an update as a GitHub release (gh CLI), to Yandex Object Storage (S3, SigV4) or a folder; `publish-update.ps1` signs and publishes the version just built |
| `app/config.py` | Paths, settings, DPAPI password protection, clinic branding |
| `app/sync.py` | Background worker: online check, pull, purge, push, offline mode |
| `app/api_client.py` | Partner API client: auth, paging in any shape, retries, writes |
| `app/normalize.py` | Field extraction across naming and date formats |
| `app/db.py` | Schema, migrations, combined synced + local views |
| `app/local.py` | Everything created in the app: visits, records, documents, invoices, payments, transfer journal |
| `app/pusher.py` | Automatic sending to Dentist Plus with dedupe and verification |
| `app/catalog.py` | ICD-10 dental codes, phrase and document templates |
| `app/demo.py` | Invented demo clinic for showing the app without an account |

## Details that were harder than they looked

- **Power cuts mid-sync.** Visits are replaced one 7-day chunk per transaction with SQLite in WAL and
  `synchronous=FULL`; a cut leaves the previous data intact.
- **Endpoints that ignore filters.** If the server returns visits outside the requested dates, or
  ignores `?page`, the client notices and stops instead of looping.
- **One bad record.** A 500 on a single patient card used to stall the sync for over a minute; now two
  short retries and the sync moves on, counting the error.
- **Shipping to a non-technical client.** The `.exe` installs itself to the user profile on first run,
  creates desktop and Start menu shortcuts, and running a newer `.exe` updates it in place.
- **Start time.** A single-file PyInstaller build unpacked ~300 MB (speech recognition, ONNX, WebView2 bridge)
  into a temp folder on every start, and the antivirus re-scanned it each time. The shipped `.exe` is now a small
  installer that puts a folder build in place once; the program then starts with nothing to unpack (3.2 s → 1.1 s
  to a ready server on the test laptop; more on slower disks). The start-up backup and the first sync wait until the window is up.
- **Secrets.** The API password is encrypted with Windows DPAPI and only decrypts under the same
  Windows account.
- **Two laptops, no network, same patient.** Integer primary keys (notes, stock moves, staff) differ between
  laptops, so replicated rows travel under a stable key (a random uid, or the login) and references between
  tables are translated on the way. A row changed on both sides is merged against the last synced copy, so
  only a real clash of one field needs a decision — and the losing value is kept, not dropped.
- **Sending to Dentist Plus twice.** With the cloud, a new patient created on laptop A reaches laptop B too;
  only the laptop where a row was created sends it to Dentist Plus.

## Stack

Python 3.11 · pywebview (Edge WebView2) · SQLite · requests · faster-whisper · vanilla HTML/CSS/JS ·
PyInstaller (single-file exe) · Playwright for screenshots

No web framework: the clinic server is the standard-library HTTP server on a clinic computer, and the
cloud server is a single standard-library Python file. Encryption and signatures: `cryptography`; QR codes: `segno`.

## Running it

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python app\main.py          # desktop window, demo data
.venv\Scripts\python app\devserver.py     # same UI in a browser at http://127.0.0.1:8775
powershell -File build.ps1                # release\DentalDesk-<version>.exe, older builds move to release\old\
python cloud\cloud_server.py serve --port 8780          # test cloud (see cloud/README.md for a VPS)
python cloud\cloud_server.py create-tenant "Clinic"     # prints the connection code
```

Set `DD_SIGN_THUMBPRINT` to a code-signing certificate's thumbprint and `build.ps1` signs both exe files.

The app starts in demo mode with an invented clinic.

**Branding.** The public build is called *Dental Desk*. A clinic build puts its own name, mark,
icon and data folder into `app/brand.json` (kept out of the repository):

```json
{"name": "My Clinic", "short": "MC", "sub": "clinic", "exe": "MyClinic", "folder": "MyClinic"}
```

To connect a real account: Settings → untick demo mode → partner API login and password →
*Check connection* → *Save and sync*.

## Tests

```powershell
.venv\Scripts\python tests\test_api_all_functions.py     # 112 checks over every app function
.venv\Scripts\python tests\test_push_to_dentist_plus.py  # automatic sending against a fake API
.venv\Scripts\python tests\test_sync_api_formats.py      # sync against 4 differently shaped APIs
.venv\Scripts\python tests\test_server_auth.py           # 45 checks: accounts, approval, permissions over HTTP
.venv\Scripts\python tests\test_stock.py                 # 54 checks: stock, automatic write-off, equipment, rights
.venv\Scripts\python tests\test_fiscal.py                # 48 checks: receipt rules, test mode, fake ATOL server, fake Shtrih-M driver
.venv\Scripts\python tests\test_offline_copy.py          # 21 checks: encrypted read-only copy for laptops
.venv\Scripts\python tests\test_double_booking.py        # 18 checks: overlap rules, calendar flags, blocked sending
.venv\Scripts\python tests\test_dictation.py             # 25 checks: parsing rules, AI layer vs a fake server, real recognition if a model is present
.venv\Scripts\python tests\test_backup.py               # 56 checks: copy and check, rotation, missing flash drive, restore round-trip
.venv\Scripts\python tests\test_schedule_tools.py       # 64 checks: drag-move, recurring visits, waiting list, reminders, disk encryption
.venv\Scripts\python tests\test_medcard_tools.py        # 105 checks: allergy rules, sterilization, periodontal chart and voice, files, DICOM, visiograph folder
.venv\Scripts\python tests\test_documents_tools.py      # 92 checks: signatures, questionnaire, tablet over HTTP, tax certificate, Excel
.venv\Scripts\python tests\test_money_tools.py          # 107 checks: lab orders and payroll, certificates, bonuses, families, SBP, fiscal rules
.venv\Scripts\python tests\test_stock_lots.py           # 55 checks: FEFO lots, expiry, expired write-off, purchase list, cheapest supplier, barcode scanner, rights
.venv\Scripts\python tests\test_installer.py            # 15 checks: folder install, in-place update, broken installer, leftovers, data folder untouched
.venv\Scripts\python tests\test_exams.py                # 40 checks: visit templates and medicines, hiding and restoring built-ins, prescriptions in the record, allergy check, documents
.venv\Scripts\python tests\test_plans.py                # 78 checks: plan options and sums, choice and billing, tablet choice and signature, surfaces of the tooth chart, migration, PDF, rights
.venv\Scripts\python tests\test_director.py             # 72 checks: visit history after the mirror is purged, new/repeat and retention, load by chairs and schedules, conversion, materials, plan vs fact, rights, change capture under UPSERT
.venv\Scripts\python tests\test_crm.py                  # 109 checks: rule tasks and their ids, plan and score tasks, requests and funnel, segments, NPS and the tablet, ad payback, sync capture, rights
.venv\Scripts\python tests\test_finance.py              # 115 checks: advance and its use, refunds and receipts, schedules and reminder tasks, memberships, cash shift, ДМС registries, sync capture, rights
.venv\Scripts\python tests\test_ai_213.py               # 144 checks: dates and surnames in any case, short texts (token limit, cut at sentences, no greeting), assistant answers and proposals with rights over HTTP, drafts by rules and by a fake model with anonymous data, translation, record check, weekly summary, voice chart, consent, quality check
.venv\Scripts\python tests\test_staff_214.py            # 92 checks: positions and their rights (built-in and own, later rights, voice labels), rights over HTTP at once, expenses of the day and the drawer, the day report with a fake SMTP server and a fake Telegram Bot API, retry of one channel and the moment to send
.venv\Scripts\python tests\test_stock_grey.py           # 43 checks: stock without documents — receipts, write-offs and counts, balance by documents and who sees it over HTTP, act numbers, receipt as an expense of the day, the stock block of the day report
.venv\Scripts\python tests\test_p2p.py                  # 48 checks: three computers (processes) find each other, pairing with the director's approval, both-way sync, staff approval, files, conflicts converge, LAN + cloud without duplicates
.venv\Scripts\python tests\test_updates.py              # 58 checks: encrypted installer and notes, signing a release, a fake GitHub (302, ETag/304, 404), download and install, another build's key, worker once a minute, rights, publishing order
.venv\Scripts\python tests\test_addon_mode.py           # 107 checks: the add-on mode — default for old installs, the director's switch, official / draft / internal documents, hiding, SaaS kept callable, UI wiring, addon.js in node
.venv\Scripts\python tests\test_dp_transfer.py          # 129 checks: no double entry — sections and their settings, the text for Dentist Plus, the mark (kept / dropped), auto mark, «Не перенесено», the reminder, the day report line, reconciliation, sync of marks, rights over HTTP, UI wiring
.venv\Scripts\python tests\test_finance_staff.py        # 150 checks: profit and loss by months, the cash flow by accounts, the administrators' motivation into the payroll and the profit, the timesheet against the schedule, the week and month report (fake SMTP and Telegram, when it is due), sync between computers, rights over HTTP, UI wiring
.venv\Scripts\python tests\test_stock_auto.py           # 129 checks: services of a Dentist Plus visit in its shapes, drafts, the place by chair / branch, never twice (an invoice here, two computers offline), revert and skip, services by hand, the automatic mode from its day, places and transfers, the cost of services, materials in the P&L, sync, rights over HTTP, UI wiring
.venv\Scripts\python tests\test_plan_status.py          # 116 checks: plan status history, the automatic rules (bill or Dentist Plus visit → in work, all billed → finished, 60 idle days → abandoned, back on a visit / bill / booking), a manual status wins, the call list and its results with CRM tasks, the report by status and doctor, the motivation, two computers offline, rights over HTTP, UI wiring
.venv\Scripts\python tests\test_staff_refs.py           # 85 checks: staff in schedules, pay schemes and payouts by login — two laptops with different account ids sync both ways, the migration on start (own rows only, idempotent), gone accounts and rows from an older version as «неизвестный сотрудник», payroll and timesheet unchanged
.venv\Scripts\python tests\test_platform.py             # 110 checks: two laptops offline converge, conflicts, isolation of clinics, encryption, plans, signed updates, PIN, import
```

Cover booking, moving and cancelling, medical records, documents, invoices and partial payments,
treatment plans, CSV price import (including Windows-1251 files from Excel), the transfer journal,
settings, dedupe and validation errors on write, paging variants, timezones and partial server failures.

## Status and privacy

Version 2.14.1: the day report in Telegram; 2.14: positions with rights the director changes, the administrators' expenses of the day and the day report by e-mail; 2.13: AI — the assistant with the employee's rights, texts and translation in seconds, the record check, the director's weekly summary, the tooth chart and notes by voice, consent to record a visit, the clinic's own local model with a quality check; 2.12: money — advance, refunds, installments, memberships, cash shifts with reconciliation, ДМС registries, debt reminders; 2.11: CRM — tasks by hand and by rules, requests and funnel, segments with a WhatsApp mailing, visit scores with review QR codes, advertising payback; 2.10: visit templates by speciality, prescriptions, prescription form, referral and patient memo; 2.9: treatment plan options, the plan presentation (print, PDF, patient tablet), the tooth chart by surfaces. All screenshots use an invented demo clinic — no real patient
appears anywhere in this repository. The app stores medical data locally only; the clinic is advised
to use Windows login and BitLocker.

Document templates are generic drafts written for this project and are meant to be reviewed by the
clinic's lawyer.

## License

Code — MIT. Bundled font Playfair Display SC — SIL Open Font License 1.1 (`app/ui/fonts/OFL.txt`).
