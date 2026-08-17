# Loan Management (overdraft_interest_calculator)

**Module name:** `overdraft_interest_calculator`
**Display name:** Loan Management
**Version:** `18.0.4.1.0`
**Category:** Accounting
**Author:** Eyosias Yitay
**License:** LGPL-3
**Odoo Compatibility:** Odoo 18
**Application:** Yes (installable, `auto_install=False`)

---

## 1. Overview

**Loan Management** is a comprehensive Odoo 18 module that lets a company manage
**four different types of bank lending facilities** end-to-end — from initial
request and bank approval, through interest accrual and repayment, to closure and
management reporting.

The four loan facilities handled are:

| Loan Type        | Model                 | Prefix | Purpose                                                            |
|------------------|-----------------------|--------|---------------------------------------------------------------------|
| **Overdraft**    | `overdraft.interest`  | `OD/`  | Revolving credit line with daily-balance interest and penalties    |
| **Term Loan**    | `term.loan`           | `TL/`  | Fixed-amount loan with a full amortization schedule                |
| **Merchandise**  | `merchandise.loan`    | `MRL/` | Bank-financed purchase of goods held as collateral                 |
| **Pre-Shipment** | `preshipment.loan`    | `PSL/` | Export financing with foreign-currency delivery commitment         |

Each facility has a **header record** and a set of **line records** (daily / release /
payment entries), follows an **approval workflow**, and is wired into Odoo's
**Accounting** (journal entries and vendor bills), **Inventory/Warehouse**
(merchandise storage), and **Sales** (pre-shipment export orders) modules.

Alongside the core models the module provides:

- A **tabbed KPI Dashboard** (OWL component) for all four loan types.
- A **Reporting section** with five different management reports, exportable to
  PDF / XLSX / CSV.
- A **weekly scheduled action (cron)** that alerts users about upcoming and
  overdue payments.
- **Multi-company** security rules and a role-based permission model
  (Viewer / Editor).

---

## 2. Feature Highlights

### 2.1 Overdraft (`overdraft.interest`)
- Links to a **bank journal**, bank, currency, overdraft limit, and OD account number.
- Tracks the facility **purpose** and requires at least one **collateral document**.
- Records **daily lines** (`overdraft.line`): debit (money withdrawn), payment
  (money repaid), interest payment, principal payment, and penalty payment.
- **Daily balance tracking**: `balance = balance - debit + principal_payment`.
- **Automatic daily interest**: `daily_interest = |negative balance| × annual_rate/100/365`.
- **90-day penalty**: when no interest payment has been made for 90 consecutive
  days, a flat penalty (`three_month_penalty_rate`) is applied to the cumulative
  interest.
- Enforces the **overdraft limit** — a debit that pushes the balance beyond the
  limit raises a `UserError`.
- **Approval workflow**: Draft → Submitted → Approved / Rejected → Closed.
- On approval, creates a **journal entry** for accrued interest + penalty.
- Can generate a **vendor bill** for outstanding interest/penalty.
- A **payment wizard** records normal and penalty payments on the correct daily line.

### 2.2 Term Loan (`term.loan`)
- Fixed loan amount, annual interest rate, loan period (years), and payment
  frequency (monthly / quarterly / semi-annual / annual).
- Computes a fixed **scheduled payment** (principal + interest) via standard
  annuity / amortization math.
- Full **amortization schedule** of `term.loan.line` records: payment number,
  dates, beginning/ending balance, interest, principal, cumulative interest.
- Optional **grace period** handling:
  - Unchecked (default): interest accrues from `start_date` and is captured as a
    standalone interest-only line (Pmt #0) at the grace period end.
  - Checked (`interest_accrue_from_grace`): interest only starts after the grace
    period, so amortization simply begins there.
- **Extra payments**: record extra lump-sum payments that shorten the life of
  the loan and reduce total interest (`action_recalculate_schedule`).
- **Delinquency / risk tracking**: days past due, overdue principal & interest,
  due-within-30/90-day buckets, and a color-coded **alert level**
  (green / yellow / red / purple).
- **Tiered penalties** on overdue installments (Days 1–30 / 31–60 / 60+).
- Loan **disbursement journal entry** and **vendor bill** generation for the next
  unpaid installment.
### 2.3 Merchandise Loan (`merchandise.loan`)
- Finances the **purchase of physical goods** that are stored in a warehouse as
  collateral for the bank.
- The company deposits a percentage (`company_coverage_percent`, default 30%);
  the **bank covers the remainder** (`bank_coverage_percent`) — the bank's share
  is the loan to be repaid (`bank_amount`).
- Records the **product / merchandise, quantity, unit price, selling price,
  product category, import document, goods location, and sales status**.
- **Goods release entries** (`merchandise.loan.line`): the user enters the
  quantity of goods to release from the warehouse; the module computes the goods
  value (qty × unit price), daily interest accrued since the last entry
  (or activation date), and the total payment (principal + interest + penalty).
- Enforces that the company **cannot release more goods than the bank controls**
  and cannot release goods after the loan is fully paid.
- **Dead-stock risk** detection: goods left unsold / slow-moving beyond
  90 days while the loan is active are flagged as a risk.
- Shows interest per unit, actual unit cost (unit price + interest), and
  margin per unit (selling price − actual cost).
- **Tiered penalties** applied on the outstanding bank amount after the loan end date.
- Disbursement journal entry and vendor bill generation (principal + interest + penalty).

### 2.4 Pre-Shipment Loan (`preshipment.loan`)
- **Export financing**: the bank lends local currency to fund export production;
  the company commits to deposit **foreign currency** to the bank by an expected
  export date.
- Records the **foreign currency** to deliver (`total_currency_to_store`), a
  **conversion rate**, and tracks **currency fulfillment %**
  (deposited / committed).
- Two kinds of line entries (`preshipment.loan.line`):
  - **Utilization entry** — drawn local-currency amount; interest is computed as
    `amount_used × annual_rate/100/365 × days since start_date`.
  - **Foreign currency entry** — foreign currency deposited, converted to local
    equivalent via the conversion rate.
- Tracks **export proceeds** (foreign and local), the **loan settled amount**,
  the company's remaining amount, and the **outstanding balance**.
- **Tiered penalties** if the foreign currency is not fully delivered by the
  expected export date (Days 1–30 / 31–60 / 60+).
- Linked to **sales orders** for the export contracts and shows
  **export contract status**.
- Disbursement journal entry and vendor bill generation (loan usage + interest + penalty).

### 2.5 Shared behaviours
- All four facilities inherit `mail.thread` and `mail.activity.mixin` → full
  **chatter / messaging** and activity tracking.
- Every record has an **approval workflow** with guarded state transitions.
- Every record can link to **journal entries** and **vendor bills**, with smart
  buttons to view them.
- Automatic **reference sequences** (`OD/`, `TL/`, `MRL/`, `PSL/`).
- Rich **chatter logging** on line edits and payments (who changed what).

---

## 3. Module Structure

```
overdraft_interest_calculator/
├── __init__.py
├── __manifest__.py
├── data/
│   ├── ir_cron_data.xml          # Weekly loan payment alert cron
│   └── ir_sequence_data.xml      # OD/, TL/, MRL/, PSL/ sequences
├── demo/
│   └── load_demo_data.py         # Optional dev/demo record loader
├── models/
│   ├── __init__.py
│   ├── overdraft_interest.py     # Overdraft facility header + amortization
│   ├── overdraft_line.py         # Overdraft daily line
│   ├── term_loan.py              # Term loan header + schedule generation
│   ├── term_loan_line.py         # Amortization / payment line
│   ├── merchandise_loan.py       # Merchandise loan header
│   ├── merchandise_loan_line.py  # Goods release entry
│   ├── preshipment_loan.py       # Pre-shipment loan header
│   ├── preshipment_loan_line.py  # Utilization / currency entry
│   ├── account_move.py           # account.move extension (reverse links)
│   ├── loan_alert_cron.py        # Abstract model: weekly alert cron logic
│   ├── loan_management_report.py # Weekly report model + export logic
│   └── loan_report_wizard.py     # 5-type management report wizard
├── security/
│   ├── overdraft_groups.xml      # Viewer / Editor groups + category
│   ├── ir.model.access.csv       # Per-group access rights
│   └── ir_rule_data.xml          # Multi-company record rules
├── static/
│   ├── description/icon.png
│   └── src/
│       ├── components/loan_dashboard.js / .xml   # OWL dashboard component
│       └── css/loan_dashboard.css                # Dashboard styles
├── views/
│   ├── overdraft_interest_views.xml
│   ├── overdraft_line_views.xml
│   ├── term_loan_views.xml
│   ├── term_loan_line_views.xml
│   ├── merchandise_loan_views.xml
│   ├── preshipment_loan_views.xml
│   ├── dashboard_views.xml
│   ├── loan_management_report_views.xml
│   ├── loan_report_wizard_views.xml
│   └── menu_items.xml            # Menus + window actions (always last)
└── wizard/
    ├── __init__.py
    ├── overdraft_close_wizard.py   # Double-confirmation close wizard
    ├── overdraft_payment_wizard.py # Record OD payment
    ├── term_loan_payment_wizard.py # Record term-loan extra payment
    └── payment_wizard_views.xml
```


---

## 4. Technical Stack & Dependencies

The module depends on the following core Odoo apps:

| Dependency | Why it is used                                                    |
|------------|-------------------------------------------------------------------|
| `base`     | Core framework                                                     |
| `mail`     | Chatter / messaging, activities                                   |
| `account`  | Journals, chart of accounts, journal entries, vendor bills        |
| `stock`    | Merchandise warehouse management                                   |
| `web`      | OWL backend component assets (dashboard)                          |
| `analytic` | `analytic.mixin` for business unit / department on merchandise    |
| `sale`     | Sales orders for pre-shipment export contracts                    |

**Python / JS libraries used at runtime:**
- Standard library: `datetime`, `dateutil.relativedelta`, `io`, `base64`, `csv`.
- `xlsxwriter` — XLSX export (should be installed in the Odoo environment).
- `beautifulsoup4` (bs4) — parses report HTML into tables for exports.
- `markupsafe.Markup` — safe HTML logging into chatter.
- **Chart.js** — charts rendered in the OWL dashboard.

---

## 5. Installation & Configuration

### 5.1 Install the module
1. Place the `overdraft_interest_calculator` folder in your Odoo **addons path**.
2. Update the app list (`Apps` → `Update Apps List`), then search for
   **Loan Management** and install it.
3. Install the Python extras (`xlsxwriter`, `beautifulsoup4`) if you want to
   export reports to Excel / CSV:
   ```bash
   pip install xlsxwriter beautifulsoup4
   ```

### 5.2 Prerequisite configuration in Odoo
For the module to function fully you should configure:

- **Bank journals** (`Accounting → Configuration → Journals`, type `bank`) —
  one per lender; the bank linked to the journal is used across all facilities.
- **Purchase journals** (type `purchase`) — used to create vendor bills for
  interest / penalties.
- **Chart of accounts** accounts for each facility:
  - Receivable (`asset_receivable`)
  - Payable (`liability_payable`)
  - Income (`income`)
  - Expense (`expense`)
- **Currencies** — including the **foreign currency** (e.g. USD) for
  pre-shipment loans.
- **Warehouse** (`Inventory`) for merchandise storage.
- **Products** for financed merchandise and for sales order linking.

### 5.3 Third-party libraries on the client
- The dashboard renders charts (e.g. maturity schedule, utilization, contract
  status) and may load **Chart.js** as a client asset.

---

## 6. User Roles & Security

The module defines a security category **Loan Management** with two roles:

| Role  | Group XML id                        | Rights                                                         |
|-------|-------------------------------------|----------------------------------------------------------------|
| **Viewer** | `group_overdraft_viewer` | Read-only access to all four loan models, lines, reports and wizards (create allowed on the report wizard). |
| **Editor** | `group_overdraft_editor`   | Implies Viewer; full create / read / write / delete on all models and wizards. |

- Editors can modify the **computed fields**; a guard in
  `overdraft.line.write` restricts non-editors to only `debit`, `payment`,
  `penalty_payment`, and `notes`.
- **Multi-company** record rules restrict each record to the companies the user
  belongs to (`company_ids`).
- The root `Loan Management` menu and all its submenus are gated behind the
  Viewer group, so non-members never see the module.

Access rights are defined in `security/ir.model.access.csv`. Additional Python
model constraints exist (e.g. interest rates cannot be negative; dates and
overdraft limits are validated).


---

## 7. Workflow Reference

All four facilities share the same high-level approval pattern:

```
Draft ──submit──▶ Submitted ──approve──▶ Approved ──activate▶ Active
   ▲                  │                      │
   └────reset◀─ Rejected ◀──reject───────────┘
                                               │
                                          (payments)
                                               ▼
                                           Closed
```

| Loan Type      | Transitions                                                       |
|----------------|-------------------------------------------------------------------|
| **Overdraft**  | Draft → Submitted → Approved / Rejected → Closed; closing requires zero outstanding interest & penalty (via double-confirmation wizard). |
| **Term Loan**  | Draft → Submitted → Approved / Rejected → **Generate Schedule** → Active → Closed. |
| **Merchandise**| Draft → Submitted → Approved → **Activate** (starts interest accrual) → Active → Closed. |
| **Pre-Shipment**| Draft → Submitted → Approved → **Activate** → Active → Closed. |

Overdraft has an extra `reopen` action and a dedicated **double-warning close
wizard** (`overdraft.close.wizard`) that refuses to close a facility with
outstanding interest or penalties.

---

## 8. Calculation Formulas (reference)

### 8.1 Overdraft
- **Daily rate:** `annual_interest_rate / 365 / 100`
- **Balance:** `balance = previous_balance - debit + principal_payment`
  (negative ⇒ overdrawn).
- **Daily interest:** `max(-balance, 0) × daily_rate`
- **Interest payment allocation:** payments first cover cumulative interest,
  then reduce principal.
- **90-day penalty:** after 90 consecutive days with no interest payment,
  `penalty = cumulative_interest × three_month_penalty_rate / 100`.
- **Current utilization:** `abs(min(current_balance, 0))`
- **Available balance:** `max(overdraft_limit - current_utilization, 0)`

### 8.2 Term Loan
- **Rate per period:** `annual_interest_rate / payments_per_year`
- **Scheduled payment:** standard amortization of `loan_amount` over
  `years × payments_per_year` periods.
- **Grace period (default):** an interest-only line (Pmt #0) is created for
  `balance × (annual_rate/365) × grace_days`.
- **Recalculation:** each regular line uses `interest = balance × rate_per_period`,
  applies any `extra_payment`, and the final installment is forced to fully clear
  the remaining balance.
- **Tiered penalty (per line):** applied on the overdue installment's `total_payment`
  using tiered annual rates split into Days 1–30 / 31–60 / 60+.

### 8.3 Merchandise
- **Goods value (per entry):** `goods_released_quantity × goods_unit_price`
- **Bank loan amount:** `total_goods_value × bank_coverage_percent/100`
- **Company deposit:** `total_goods_value × company_coverage_percent/100`
- **Interest per entry:** `outstanding × annual_rate/100/365 × days_elapsed`
  (since the previous entry or the activation date).
- **Payment per entry:** `goods_value + interest + penalty`
- **Interest per unit / actual unit cost / margin per unit:** derived from total
  interest and selling price.
- **Dead-stock risk:** flagged when `sales_status in ('unsold','slow_moving')`,
  the loan is active, and `days_held > 90` (or manually marked dead stock).

### 8.4 Pre-Shipment
- **Utilization interest:** `amount_used × annual_rate/100/365 × days_since_start`
- **Local equivalent deposited:** `currency_deposited × conversion_rate`
- **Currency fulfillment %:** `currency_stored / total_currency_to_store × 100`
- **Loan settled amount:** capped at export proceeds (local), up to total due.
- **Outstanding balance:** `loan_used + total_interest + penalty_amount - loan_settled_amount`
  (floor 0).
- **Tiered penalty:** applied on `loan_used` when `currency_remaining > 0` and the
  expected export date has passed (Days 1–30 / 31–60 / 60+).

---

## 9. Dashboard

The **Dashboard** is an OWL (Odoo Web Library) component
(`static/src/components/loan_dashboard.js` / `.xml`) opened from the
`Loan Management → Dashboard` menu.

Features:
- **Four tabs**: Overdraft 💳, Term Loan 🏦, Merchandise Loan 📦, Pre-Shipment Loan 🚢.
- **Filters**: bank dropdown + **From / To** date range.
- **KPI cards** per tab, for example:
  - Overdraft: total limit, current utilization, available balance.
  - Term Loan: portfolio totals, outstanding, near-term due amounts.
  - Merchandise: bank loan outstanding, goods held by bank vs. owned by company,
    dead-stock risk.
  - Pre-Shipment: loan usage, currency commitment fulfillment %, export proceeds,
    loans maturing in 30/60/90 days, export contract status.
- Charts (via Chart.js) for maturity schedules, utilization progress,
  currency commitment progress, and export proceeds / contract status.

The dashboard calls the backend via RPC to aggregate records across the four
loan models and render the KPIs.


---

## 10. Reporting

Two reporting mechanisms are provided.

### 10.1 Weekly Loan Management Report (`loan.management.report`)
- Generated automatically by the **cron** (`ir_cron_weekly_loan_payment_alert`).
- Contains HTML sections/tables for overdue and due-this-week payments across
  term, pre-shipment, and merchandise loans.
- Users can **print a PDF** (`action_print_report`), **export XLSX**
  (`action_export_xlsx`, requires `xlsxwriter`) and **export CSV**
  (`action_export_csv`) — the exports parse the HTML body with `beautifulsoup4`.

### 10.2 Loan Report Wizard (`loan.report.wizard`)
A single wizard (`Loan Management → Reporting`) offers **five report types**:

| Report Type              | Menu id / name                | What it shows                                          |
|--------------------------|-------------------------------|--------------------------------------------------------|
| **Loan Portfolio**       | `menu_report_portfolio`       | Summary of all loans grouped by type and state.        |
| **Repayment Schedule**   | `menu_report_repayment`       | Upcoming/actual repayment schedules.                   |
| **Loan Utilization**     | `menu_report_utilization`     | Drawn vs. available amounts per facility.              |
| **Loan Maturity**        | `menu_report_maturity`        | Loans maturing in the selected period / maturity risk. |
| **Loan Exposure**        | `menu_report_exposure`        | Total exposure by bank / currency / facility type.     |

Each report is:
- Filtered by **date range**, **bank**, and **loan state**.
- Rendered to **HTML** with styled, color-coded tables and state badges.
- Exportable to **XLSX** (`action_export_xlsx`), **CSV** (`action_export_csv`),
  and **PDF** (`action_export_pdf` via a QWeb report).

*Note:* XLSX / CSV exports rely on the `xlsxwriter` and `beautifulsoup4` Python
packages being installed.

---

## 11. Scheduled Actions / Automation

A single cron is defined in `data/ir_cron_data.xml`:

| Cron | Interval | What it does |
|------|----------|--------------|
| **Weekly Loan Payment Alert Summary** (`_cron_send_weekly_payment_alert`) | Every 1 week (Monday 08:00) | Scans active term, pre-shipment, and merchandise loans, builds an HTML summary of **overdue** and **due-this-week** payments, creates a `loan.management.report` record, sends a `discuss.channel` message to users in the Viewer group (via OdooBot), and creates a `mail.activity` for each user. |

The cron uses `sudo()` so it can message users regardless of their record
permissions, and degrades gracefully to `base.group_system` if the viewer group
is unavailable.

---

## 12. Accounting Integration

Each loan type writes into Odoo's `account.move` model (extended in
`models/account_move.py` with reverse Many2one links: `overdraft_id`,
`term_loan_id`, `merchandise_loan_id`, `preshipment_loan_id`).

- **Disbursement journal entry** (`_create_disbursement_journal_entry`):
  debits the bank account and credits the payable account for the loan amount.
- **Interest/penalty journal entry** (overdraft, on approval): posts accrued
  interest + penalty.
- **Vendor bills** (`action_create_bill`): create `in_invoice` moves in the
  **purchase journal** charging the expense/payable accounts for principal,
  interest and/or penalty (the bank is used as partner).
- **Smart buttons** on each form open the related journal entries and bills.

Make sure the required accounts are configured on each loan record before
generating schedules / bills, or a friendly `UserError` is raised.


---

## 13. Demo / Development Data

A fix-up demo loader exists at `demo/load_demo_data.py`. It is **not** loaded by
the manifest (there is no `demo` entry), so it is intended for manual development
use (e.g. via a shell script) to quickly create term, merchandise, and
pre-shipment records using existing bank journals, currencies, products,
warehouses, and chart-of-account accounts. Review and adapt the account types /
journals if your database differs.

---

## 14. Getting Started (Quick Walkthrough)

1. **Install** the module and configure bank/purchase journals, accounts,
   currencies, warehouse and products (see §5).
2. **Grant roles**: add users to `Loan Management → Viewer` or `Editor`.
3. **Create a facility** of your chosen type and fill in bank, amounts, rates,
   dates and (where required) collateral documents.
4. **Submit → Approve** (and **Activate** / **Generate Schedule** for
   non-overdraft facilities).
5. **Record daily activity**:
   - Overdraft: add debits/payments on the **Daily Lines**, then run
     **Calculate Amortization**.
   - Term Loan: run **Generate Schedule**, then use **Record Payment** for
     extra payments.
   - Merchandise: add **Goods Release Entries**.
   - Pre-Shipment: add **Utilization** and **Foreign Currency** entries.
6. **Monitor** via the **Dashboard** and the **Reporting** section; rely on the
   **weekly cron** alerts for upcoming/overdue payments.
7. **Close** the facility once fully repaid (overdraft via the guarded close
   wizard).

---

*This README was generated from a review of the module source in
`odoo-custom-addons18/overdraft_interest_calculator`.*

