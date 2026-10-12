# Proposal implementation and operating guide

Source: **Car Rental Management Proposal.pdf**, 26 pages, supplied on 8 October 2026. Commercial acceptance, warranties and project timelines in the proposal are context, not automation instructions.

## Implemented requirements

| Proposal sections | Implementation |
| --- | --- |
| 4, 9: fleet and allocation | Individual fleet IDs, registration/VIN, categories, photos, compliance dates, service schedules, native Fleet links, date-overlap checks and allocation. Ten DEMIO-001 through DEMIO-010 setup records are provided. |
| 5–6, 17: pricing | Approved company/category/destination/duration/effective-date rules; explicit priorities; ambiguous overlap protection; agreed-rate snapshots; reasoned, audited manager price overrides. |
| 7, 12, 15: deposits/accounting | Native posted invoices, bank/cash receipt journal entries, receivable reconciliation, deposit liability entries, refunds, damage invoices and deposit applications. Deposits never credit rental revenue. |
| 8: booking | Customer → destination → category/dates → price/deposit → allocation → confirmation → linked rental → agreement/payment → pickup. |
| 10–11: inspections | Fuel, mileage, exterior/interior/tyres/accessories, existing/new damage, photos, inspector, time and customer acknowledgement; pickup/return comparison; immutable completed records. |
| 12: damage | Return inspection creates an assessment; manager approves the charge; repair request, customer damage invoice, deposit application/refund, outstanding balance and resolution. |
| 13–14: maintenance | Native Maintenance requests with vehicle, supplier, mileage, work, parts, labour, cost, warranty, next service and supplier bill links. Daily service reminders can create preventive requests. |
| 16: agreements | Printable QWeb rental agreement with agreed terms, customer/vehicle/pricing/deposit/inspection details and captured signature acknowledgement. Attachments hold ID, vehicle and rental documents. |
| 18: reminders | Daily, deduplicated activities for upcoming compliance expiry, service thresholds, overdue returns, outstanding rental receipts, pending return inspections and damage assessments. |
| 19: management | Operational fleet counts, receipts versus invoiced rental income, deposits held, damage recovery, maintenance costs, customer balances, revenue per vehicle and period utilisation. |
| 20: roles | Rental Staff, Rental Manager, Fleet Manager, Accountant, Administrator; restricted approvals/postings, immutable financial records and company record rules. |

## Business configuration still required

The owner has not yet supplied approved rates, registrations/VINs or agreement terms. Consequently:

- Example pricing rules are **drafts** and cannot confirm bookings. Replace the illustrative amounts/duration bands with approved values, then explicitly approve each rule.
- Create actual vehicles with their number plates/Fleet IDs, category, insurance and road licence dates, service schedule and photos. No sample fleet is installed; incomplete setup vehicles are excluded from dashboard totals and allocation.
- **Car Rental → Configuration → Settings** requires the actual company accounts, receipt journal, sales journal, service product, applicable sales tax and approved rental terms. Company currency is taken from Odoo; choose the company's approved currency before transacting. No account numbers or tax treatment are fabricated.
- The default policy blocks pickup without valid compliance, signed terms, completed pickup inspection, collected deposit and full posted rental receipts. Management can change the payment/compliance/tracker policy. Missing terms still block agreement acknowledgement.
- A late return beyond the configurable grace period is charged per commenced additional 24-hour period at the agreed daily rate. Confirm this policy with the business before production use.

The proposal's 4–6-week estimate, training completion, user acceptance and production go-live cannot be certified by code changes. Obtain actual business sign-off using the checklist below.

## Installation and historical data

Version `19.0.3.0.0` upgrades `car_rental_management_odoo`; it does not reinstall the separate City Delights addon. Standard Contacts, Fleet, Sales, Accounting, Maintenance and Inventory capabilities are dependencies.

The pre-upgrade migration snapshots existing reservation rates from their stored amount/duration and labels existing receipts **Historical / Unposted**. It does not generate journal entries from historical records. Rentals with historical receipts are blocked from automatic invoicing until the accountant resolves their opening balances, preventing duplicate billing. Existing receipts remain in operational balances but are not asserted to be posted accounting receipts.

A database backup was saved locally under `backups/` before the upgrade. Backups, runtime data and credentials are excluded from Git.

## Operating procedure

1. Configure company accounting, taxes, approved terms and policies. Set up real vehicle compliance and approve pricing rules.
2. Add the customer, ID/licence details and attachments. Select destination/category and rental dates; calculate the quote and allocate an available vehicle.
3. For discounts, enter proposed daily rate and reason, request approval, and have a Rental Manager approve before confirmation.
4. Confirm the reservation and create its linked rental. Create and post the rental invoice in Accounting. Record and **Post Receipt** for each instalment; only posted receipts reduce the new rental's operational balance.
5. Collect/post the deposit. Acknowledge the agreement with the customer signature. Complete the photographed pickup inspection and start the rental.
6. On return, complete the photographed return inspection and use **Return Vehicle**. The vehicle goes into inspection/damage handling rather than immediately becoming available.
7. For damage, approve the assessment, generate/post its invoice, apply the deposit to that invoice, invoice/collect the residual using native Accounting, and arrange/complete repairs. Refund the remaining deposit only after damage charges are settled against available deposits. Post any late-return invoice separately.
8. Resolve damage, send the vehicle to cleaning and release it after cleaning. Complete maintenance work and update the next service schedule as required.

Bank/cash posting represents a receipt or refund confirmed by the operator; it does not transfer money. Additional damage/late invoices can be paid with Odoo's native invoice payment tools. Draft invoices remain drafts until the Accountant reviews/posts them. Linked Sales quotations and the rental form share the same invoice relationship; the rental recognizes invoices generated through Sales, and module-generated invoices link to the quotation lines. Quotation totals and currency must match the agreed rental. New quotations are blocked when the rental is already invoiced.

## Dashboard definitions

- Rental income/damage recovery use posted invoice untaxed amounts; receipts are separately recorded bank/cash receipts, with historical/unposted receipts identified on their records.
- Deposits held = posted collections − posted refunds − posted damage applications.
- Outstanding customer balance uses posted invoice residuals, with an operational rental balance only when a base rental invoice is not posted.
- Utilisation counts unique actual rental days per eligible vehicle within an inclusive reporting date range. Setup/decommissioned vehicles are excluded. This is calendar-day utilisation, not a claim of minute-level capacity or a full historical fleet acquisition/decommissioning ledger.
- Maintenance costs are the recorded service costs; review linked supplier bills before financial reporting.

## Edition differences and external integrations

This environment does not contain Odoo **Sign**, **Documents**, **Studio** or the Enterprise **Rental** app. The module provides native custom rental records, local signature acknowledgement, QWeb agreements and attachments instead. This is not an Odoo Sign integration or a certified remote/electronic-signature service. Installing/licensing those Enterprise apps and integrating formal signature requests is separate work.

No SMS, WhatsApp, payment gateway, GPS or production hosting integration is installed; these are exclusions/future expansion in the proposal. Inventory is the standard Odoo dependency; the maintenance form records parts used, while actual stock consumption remains a standard Inventory transaction.

## Acceptance checklist

- Configure your actual vehicles and grant a separate test user each role.
- Test a five-day Maun booking with an approved 500/day rule: rental subtotal 2,500; deposit 500. Review taxes independently under approved company configuration.
- Reject overlapping bookings and allow a new rental starting on the previous rental's scheduled end date. The date intervals are half-open; inspect same-day turnaround policies before production.
- Reject missing rules, expired compliance, unsigned agreements, incomplete inspections and unapproved overrides.
- Post two instalment receipts and verify both the operational balance and native invoice residual; attempt a combined overpayment.
- Return an undamaged car; refund the deposit; complete inspection/cleaning before release.
- For a 500 deposit and 300 damage invoice: retain 300, refund 200. For 2,000 damage: retain 500 and leave a 1,500 invoice balance (before any configured tax).
- Confirm repair/service completion, next service reminders, compliance reminders and overdue return/payment activities.
- Print/review the agreement and photographs with staff. Confirm the business's legal terms, rates, deposit/refund and late-return policies.
- Review dashboard totals against Accounting, complete staff training and record user acceptance before production go-live.

## Navigation

The Car Rental menu groups Reservations and Rentals under **Bookings**; Vehicles, Inspections, Damage Assessments and Maintenance under **Fleet**; and Receipts, Invoices, Deposits & Refunds and Outstanding Invoices under **Payments**. Financial screens retain their accountant permissions. Invoice lists show only rental-linked invoices.

Each rental has one **Payments** tab containing receipts, security deposit collection/refunds and late return charges. Pickup/return, agreement, inspections/damage and documents remain separate operational sections.

## Operational upgrade (19.0.4.0.0)

No demo fleet or example pricing is installed. The migration removes only unused, unregistered original Demio setup records and unused draft example rates; real vehicles, bookings and attachments are preserved. Dashboard values use the active company and actual registered vehicles.

Fleet ID is the registration number and synchronises both ways. Fitness fields are hidden and no longer block booking/compliance checks. Customer profiles require physical/postal addresses, DOB and licence issue/expiry; confirmation requires age 21 on pickup, full-period licence validity and either Omang or passport plus a licence attachment. Historical unsorted attachments remain visible for manual classification.

Booking timestamps are authoritative. Duration is rounded up by elapsed 24-hour periods; adjacent time slots can share a date. Late-return grace remains configurable; each commenced overdue 24-hour period after grace incurs one agreed daily rate. New references use RES/REN plus pickup month and a three-digit counter; counters are separate by company, month and year. Existing references remain intact.

Pricing-rule deposits remain 50?100% of the agreed daily rate and are protected across reservation/rental creation and updates. Initial deposit collection below 50% is rejected, and handover still requires the full required deposit. Cleaning fees are configurable per rule and captured at booking. A dirty return creates a draft cleaning invoice; finance posts it and can reconcile it using the held deposit. Unpaid cleaning invoices block deposit refunds. No money is transferred automatically.
