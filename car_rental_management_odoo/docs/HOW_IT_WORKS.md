# How It Works: Car Rental

## Start Here

### Collect rental payment and security deposit together

Open **Payment & Security Deposit** from the rental or the journey's Payment step. The form shows the rental balance, deposit remaining and combined total. Enter the amount received, payment method, date and optional bank/receipt reference once. Check the allocation preview, then click **Record Payment & Deposit**.

Partial payments fund the security deposit first, then rent. The first deposit collection must cover at least 50% of the agreed daily rate; the full required deposit is still needed before handover. Subsequent collections default to the remaining amount only. Recording creates/posts the rental invoice if needed and posts both entries together. A failure rolls back the whole collection. Repeated clicks do not create duplicate receipts. The receiving journal shown is the company's configured receipt bank/cash journal.

Rental income and refundable deposits remain separately traceable in accounting, but staff use one collection form. Deposit deductions and refunds remain part of return settlement.

### City Delights digital agreement

1. In Settings → Digital Rental Agreement, load the supplied City Delights contract (or upload the approved PDF) and give it a version. This setting applies only to the active company.
2. Confirm the booking and create its rental. Open **Digital Agreement** from the rental, or **Customer Digital Agreement** in the journey's agreement step.
3. Enter the delivery place, payment advance deadline from clause 6, company notices email, company representative and the four witness names. Click **Prepare Signing Links**.
4. Share the **Renter** link with the customer first. The customer reads the original contract, checks the prefilled booking schedule, completes their identity/contact/address and next-of-kin particulars, and draws their signature. Prices and security deposit are read-only.
5. Customer submission locks those particulars. Share each remaining link only with its named company representative or witness. They review and sign the same locked document. These are private bearer links: anyone with one can access that person's signing request. They expire after 30 days. No email is sent automatically.
6. Once all six people have signed, Odoo marks the rental agreement acknowledged and saves a combined PDF containing the unchanged original contract plus the completed particulars and signatures. **Print Agreement** opens that signed document. Original contract wording and banking details are retained as supplied.
7. Complete the pickup inspection and delivery acknowledgement at the actual handover. The contract's Third Schedule is not a declaration that the car was received when the customer booked it.

For corrections before all signatures are complete, a manager revokes the packet and prepares a replacement; old signatures remain in the audit trail and old links stop working. Issued documents retain their PDF version, booking particulars and content hash even if settings change later. Customer-entered details are retained on the agreement; they do not silently overwrite the customer profile.

Local links starting with `127.0.0.1` work on this computer only. After deployment, use the Odoo.sh site's public HTTPS address for customer links. The application uses Odoo's configured `web.base.url`.

### Guided booking

Open **Bookings → Booking Journeys → New**. Use **Continue** to move through Customer, Booking, Quote, Confirm, Payment, Agreement & Inspection, Handover, Return, Settlement and Closed.

Use **Save & Exit** at any stage and reopen the journey later. Existing reservations and rentals have a **Booking Journey** button that resumes from their actual records. Back / Review Booking opens the reservation after a quote exists; confirmed booking details remain protected.

The quote shows the hire total, refundable security deposit and separate one-time dirty return fee. Payment actions belong to the accountant. Agreement acknowledgement and completed pickup inspection precede handover. On return, complete the return inspection before Continue. At settlement, post and settle all applicable charges, apply approved deposit deductions and refund the remainder. **Close Rental** is available to the accountant and validates that nothing remains outstanding.

Closing the customer rental does not release the car. Use **Vehicle / Fleet Follow-up** for cleaning, repairs and fleet release.

### Who does what?

- Rental Staff: register customers, prepare bookings, obtain signatures, complete inspections and record handovers and returns.
- Rental Manager: approve destination pricing and exceptional price overrides.
- Rental Accountant: create and post invoices, post rental receipts, collect deposits, apply deposits to damage invoices and record refunds.
- Fleet Manager: prepare vehicles, manage compliance and repairs, complete cleaning and release vehicles for hire.
- Car Rental Admin: has the combined rental roles. An administrator configures company settings.

### Where to work

Customers holds customer identity and licence details. Bookings contains reservations and rentals. Fleet contains vehicle previews, inspections, damage and maintenance. Payments contains receipts, invoices, deposits/refunds and outstanding invoices. Configuration contains categories, destinations, pricing rules and settings.

### What counts as a completed cycle?

- The rental has completed return and is marked Closed by the accountant.
- Rental, late-return, cleaning and damage invoices are posted and settled.
- The deposit has been refunded or applied to approved damage charges; the amount held is zero.
- Damage and repairs are resolved, cleaning is complete and the vehicle has been released.

Returned describes the physical return. Closed records completion of customer financial settlement. Fleet readiness is tracked separately and must be completed before the next handover.

## Before Your First Booking

### Prepare the business once

1. In Configuration → Vehicle Categories and Destinations, create the categories and destinations you actually serve.
2. In Configuration → Pricing Rules, enter daily rates, duration bands, validity dates and the deposit ratio and dirty-return cleaning fee. A manager must click Approve Rate. Draft example rates cannot confirm bookings.
3. In Fleet → Vehicles, add the registration, category, photo, odometer and compliance documents/expiry dates. Use the number plate as Fleet ID; registration fills automatically. Activate the completed vehicle. Only real registered vehicles appear in dashboard totals.
4. In Configuration → Settings, configure rental/damage income accounts, the deposit liability account, maintenance expense account, sales journal, bank/cash journal and rental service product. Configure sales tax if applicable and check the company's accounting currency and customer receivable account.
5. Add approved agreement terms. Decide whether full rental payment, valid compliance documents and a working tracker are required at pickup, and set the late-return grace period.
6. Assign users the appropriate rental roles. Buttons and financial menus depend on permissions.

Deposit calculation: agreed daily rate × deposit ratio. It is calculated from one daily rate, separately from the rental total. The pricing screen shows the Pula deposit amount, defaulting to the full daily rate, with a 50% minimum. For example, a daily rate of 500 and a ratio of 1 require a 500 deposit, even for a three-day rental. These numbers are illustrative.

## 1. Welcome and Book

### 1. Register or find the customer

Open Customers and search before creating a duplicate. Enter the name, Omang/passport number, date of birth, physical and postal addresses, licence number, issue date and expiry. Upload either Omang or passport in its document section, plus the driving licence. The customer must be at least 21 on pickup and the licence must cover the full hire.

### 2. Prepare the reservation and quote

Open Bookings → Reservations → New. Select the customer, destination, vehicle category, pickup and return date/time. Click Calculate Price. Each started 24-hour period is one rental day. Review the rental days, daily rate, tax, total, dirty-return fee and required deposit with the customer.

Select an available vehicle or click Allocate Vehicle. You can also start from a vehicle's preview using its booking button. Allocation checks for overlapping bookings; a car currently rented may be booked for a future free period, but cannot be handed over until it is returned and cleared.

For a special rate, use Price Override: enter the proposed rate and reason, request approval and have a manager approve it before confirmation. Do not change a sales quotation to bypass the agreed booking price.

### 3. Confirm, then create the rental

Click Confirm Reservation once the customer accepts the quote. Confirmation locks the booking details. Click Create Rental to open the linked draft rental. Keep using this rental for payments, signatures, inspections and return; do not create another booking for the same handover.

If an unused reservation needs cancelling, use Cancel. A confirmed booking that needs different dates or pricing should be cancelled while unused and replaced. Linked rentals and posted financial records require follow-up rather than deleting the history.

## 2. Payment and Pickup

### 4. Invoice and collect rental payment

Finance opens the draft rental and clicks Create / Open Invoice. Review the invoice and click Confirm to post it. Then open the rental's Payments tab, click Record Payment, enter the amount/date/payment method, save and click Post Receipt. A draft receipt does not count as money received. Posted receipts settle the linked rental invoice and update the rental balance.

If your business uses Sales, a manager can create the linked Sales Quotation first; finance can invoice that quotation. Use the linked invoice rather than producing a second invoice for the same hire.

### 5. Collect the security deposit

In the rental's Payments tab, click Collect Deposit, check the amount and click Post Deposit Transaction. The deposit is held separately from rental revenue. A rental receipt does not satisfy the deposit requirement.

### 6. Sign and inspect before giving out the keys

In Agreement, review the terms, verify the automatically filled customer name, capture the signature and click Acknowledge Agreement. Use Print Agreement for the agreement document.

Click Pickup Inspection. Record the actual inspection time, inspector, odometer, fuel, exterior/interior/tyres/accessories and existing damage. Attach photos, verify the automatically filled customer name and capture the signature. Save and click Complete Inspection.

### 7. Start the rental

Return to the rental and click Start Rental. Pickup requires a confirmed reservation, completed pickup inspection, acknowledged agreement, the required posted deposit, a ready vehicle and any compliance/tracker checks enabled in settings. If full payment is required, posted rental receipts must cover the rental total. The rental becomes Ongoing and the car becomes Rented.

## 3. Return and Finish

### 8. Inspect the returned car

Open the ongoing rental and click Return Inspection. Record the actual return time, odometer, fuel and condition; compare with the pickup inspection. Attach return photos and obtain the customer's acknowledgement and signature. Describe any new damage and complete the inspection.

Click Return Vehicle on the rental. Return mileage cannot be lower than pickup mileage. The rental becomes Returned; the vehicle moves into inspection or damage handling. Late charges are calculated using the actual return time and the configured grace period.

### 9. Assess and bill additional charges

For a late return, use Create / Open Late Return Invoice in the rental's Payments tab and post the invoice. New damage creates an assessment under Fleet → Damage Assessments. A manager reviews the evidence/cost and clicks Approve Charge. Finance creates and posts the Damage Invoice.

For an existing confirmed booking without a cleaning fee, a manager can configure/approve the linked rule and use Refresh Cleaning Fee before the agreement is signed or the car is handed over. A dirty return automatically creates a draft cleaning invoice using the fee captured from the booking pricing rule. Post it, then use Apply Deposit to Cleaning in Payments; any fee above the deposit remains payable. Finance can use Apply Deposit on the approved damage case to settle its posted invoice, up to the deposit held and the invoice's outstanding balance. If damage exceeds the deposit, collect the remaining amount against that damage invoice using its standard accounting payment workflow. Settle late invoices through their standard invoice payment workflow too. Record Payment on the rental is for the base rental invoice.

### 10. Refund and reconcile

After inspecting the return and settling assessed damage and cleaning invoices, use Refund Remaining Deposit in the rental's Payments tab and post the transaction. If there is no damage, refund the full deposit held. Check Payments → Outstanding Invoices for any remaining rental, damage or late charges.

Posting a receipt or refund records the accounting entry. Staff must also collect or return the money through the actual cash, bank or card process; this module does not send bank transfers automatically.

### 11. Repair, clean and release

Fleet staff request and complete any necessary repairs in Maintenance, record work and costs, and resolve the damage case. On the vehicle, click Send to Cleaning. After cleaning, click Release Vehicle. The car becomes available for its next hire. Review the completion checklist in Start Here and keep the documents attached to the rental.

## Balances and Help

### Understand the money

- Rental amount: the agreed hire charge including configured tax.
- Paid total / rental balance: posted base rental receipts and the remaining base rental charge.
- Total Customer Balance: outstanding posted rental-linked invoices, including damage and late charges; if no posted base rental invoice exists, the rental balance is also included. Check draft invoices separately before closing the cycle. Cleaning invoices also contribute to the outstanding balance once posted.
- Deposit held: posted collections less posted refunds and damage applications. It is customer money held as a liability, not rental income.

Example: three days at 500, no tax, and a deposit ratio of 1 means a rental invoice of 1,500 plus a separately collected deposit of 500. With no damage, refund 500 after inspection. With approved damage of 200, post its invoice, apply 200 of the deposit and refund the remaining 300. Settle any late invoice separately.

### If an action is blocked

- No approved rate: ask the manager to approve a rule matching destination, category, duration and rental date; recalculate the draft reservation.
- No vehicle available: check category, dates, overlapping bookings and vehicle readiness.
- Pickup blocked: check agreement, completed signed/photo inspection, posted deposit, posted rental receipts and vehicle compliance.
- Receipt cannot post: post the base rental invoice first and check the configured bank/cash journal and remaining invoice balance.
- Refund blocked: complete the return inspection, assess new damage and settle the damage invoices before refunding the remaining amount.
- Vehicle cannot be released: complete the return inspection, resolve damage/repairs and send the vehicle to cleaning first.
- Button or menu missing: ask your administrator to check your rental role.
- Historical receipts: ask finance to reconcile opening balances before creating new invoices; do not charge the customer twice.

Completed inspections, acknowledged agreements and posted transactions are protected history. Finance uses accounting reversals for corrections to posted entries.
