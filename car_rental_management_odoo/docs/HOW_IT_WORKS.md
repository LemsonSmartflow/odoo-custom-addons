# How It Works: Car Rental

## Start Here

### Shared Contacts, Fleet and Accounting

**Car Rental → Customers uses Odoo Contacts.** Enter the name, phone, email and physical street address once on the standard Contact form. Open **Rental Details**, enable rentals for the current company, and enter the postal address, ID, date of birth, licence and next-of-kin name, relationship and phone. Upload Omang or passport plus the licence. Save, then choose **Create a Booking**. Existing rental customers already have these details in the tab; there is no separate customer form to maintain. Booking customer selectors use Contacts directly. Rental identity documents remain scoped to the current company.

**Car Rental → Fleet → Vehicles uses Odoo Fleet.** Enter the model, registration plate and category in Fleet. The native Fleet category is used for rental pricing, so you only set it once. On **Rental Details**, click **Enable Rentals** and use **Activate for Rental**. Vehicle road-licence contracts can be recorded here; requiring one before pickup is an optional company setting and is off by default. This is separate from the customer's driving licence. Insurance can also be recorded but is optional. After a return, use **Start Cleaning** and **Release after Cleaning**. Existing rental vehicles are already enabled. Fleet manages registration, model, VIN, colour, seats, transmission, fuel, category and odometer; the rental tab contains rental-specific setup, availability, preview, documents and actions. Pickup/return inspections synchronize odometer readings to Fleet, and the rental calculates the distance driven. Service intervals populate the next-service mileage and trigger a reminder as the vehicle approaches it.

Existing customer and vehicle profile IDs are retained during upgrade, so reservations, rentals and accounting links remain intact. Existing Contact/Fleet links are preserved. Do not replace these links to change the customer or car behind historical bookings. Signed agreements retain their recorded particulars and PDFs when shared records change later.

**Customer deposit credit:** At booking, the available prior-deposit balance is shown on the quote. In the Payment step, settled and unrefunded deposits from that customer's returned rentals with completed inspections are applied to the new invoice by default. The accountant can adjust the credit amount; any remaining invoice balance is paid normally. Credits transfer the liability between rentals without recording another cash receipt. Deposits tied to unresolved damage or cleaning charges are not available.

**Sort and group records:** Lists open with the newest relevant date first (vehicle and contact lists use Created On; reservations and rentals use their booking dates; maintenance requests use Request Date). The rental maintenance list also supports grouping by vehicle and request/creation month. Click any visible date or type/status column heading to sort ascending or descending. Use the search bar's Group By menu for booking/rental type, vehicle category, transaction type, or date/month. Choose Created On / Created Month when you need audit chronology rather than booking chronology.

Sales orders, invoices, journal entries and reconciliation use the existing Odoo apps. Configure the rental service product, untaxed security-deposit product, delivery product, off-site collection product, cleaning product and late-return product under Car Rental Settings, along with the customer deposit liability account and distinct unpaid-deposit clearing liability account. Posting the booking invoice first defers its unpaid deposit line to the clearing liability; as payments or prior-deposit credits settle the invoice, the corresponding amount is reclassified to the deposit liability. This keeps the deposit liability balance aligned with the actually held deposit. The delivery, off-site collection, cleaning and late-return product list prices are suggested amounts; staff may edit applicable charges in the booking or return popup. The agreement uses the module's private signing workflow, not Odoo Sign. Only the renter is required when no additional signers are named; each named representative or witness must sign.

### Collect rental payment and security deposit together

For new guided bookings, use **Record Payment** in the Payment step. Hire and refundable deposit are already on one posted invoice. The accountant can apply prior deposit credit and register one payment against that invoice; the deposit portion is treated as paid first. Payments registered from the standard invoice screen are also reflected in the journey automatically.

Pickup is blocked until the required deposit is held; when the company policy requires full payment, the hire balance must also be zero. Legacy rentals retain the previous split collection form and separate deposit transactions so their history remains usable.

At return, one settlement invoice contains late, cleaning and approved damage charges. The accountant applies deposit up to the invoice balance; any shortfall is paid against that invoice and any remaining held deposit is refunded.

### City Delights digital agreement

1. In Settings → Digital Rental Agreement, load the supplied City Delights contract (or upload the approved PDF) and give it a version. This setting applies only to the active company.
2. In **Bookings → Create a Booking**, complete Booking and Quote, then continue to Agreement. Use **Review Customer Contact** to check or correct the customer's profile before issuing the agreement.
3. Confirm the delivery place, payment advance deadline from clause 6 and company notices email. Add a company representative or witness only if your company requires that person to sign; all additional signer names are optional.
4. Click **Send Signing Link to Customer**, then choose email, WhatsApp or Telegram in the popup. WhatsApp and Telegram open a prefilled message for staff to send; they do not send directly from Odoo. The renter reviews the original contract and the snapshotted Contact and booking details, enters only the place of signing, then signs. Prices and security deposit are read-only. You can also copy the clickable link from the Agreement step.
5. Each additional named signer receives a separate private link and can sign after the renter. These are private bearer links: anyone with one can access that person's signing request. Links expire after 30 days; a rental manager can renew an expired unsigned agreement. A replacement keeps the old agreement and any existing signatures in the audit trail while disabling its links.
6. Once the renter and every additional named signer have signed, Odoo marks the rental agreement acknowledged and saves a combined PDF containing the unchanged original contract plus the snapshotted particulars and signatures. **Print Agreement** opens that signed document. Original contract wording and banking details are retained as supplied.
7. Complete the pickup inspection and delivery acknowledgement at the actual handover. The contract's Third Schedule is not a declaration that the car was received when the customer booked it. After **Hand Over Vehicle**, the booking pauses at **On Hire** with a success summary; use **Save & Exit** while the customer has the car. When the car is physically returned, reopen the booking and click **Begin Return Process** to start the return inspection.

For corrections before all signatures are complete, a manager revokes the packet and prepares a replacement; old signatures remain in the audit trail and old links stop working. Issued documents retain their PDF version, booking particulars and content hash even if settings change later. Customer-entered details are retained on the agreement; they do not silently overwrite the customer profile.

Signing links use Odoo's configured `web.base.url`. It must be your publicly reachable HTTPS address: `localhost`, private-network addresses and HTTP links will not work for customers and are blocked before email or social sharing. Configure `web.base.url` after deployment (for example, the Odoo.sh site's public HTTPS address), and verify customers can open it outside your office network.

The WhatsApp option opens WhatsApp with a prefilled message and link; the link appears on its own line so WhatsApp can recognize it. It still requires a public URL and staff must choose the recipient and send the message. Direct sending and receiving from Odoo requires the Odoo WhatsApp app connected to a Meta WhatsApp Business Account through the WhatsApp Business API; this is separate from the current click-to-chat option and needs Meta setup and approved templates. Social Marketing manages publishing to connected social accounts; it does not make a local Odoo URL public or replace WhatsApp Business messaging. Those integrations are not installed in the current local Odoo environment.

### Guided booking

Open **Bookings → Create a Booking → New**. Use **Continue** to move through Booking, Quote, Agreement, Payment, Pickup, Return and Settlement. Booking captures the customer, destination, category and dates, then creates a draft reservation. Use **Choose Vehicle & Preview** to open the vehicle picker: it lists every vehicle available for the selected category and booking period in a scrollable list. Click **Select** on a car to preview its photo, then **Use This Vehicle** to apply the choice; **Preview Full Picture** opens the full-size image.

Use **Save & Exit** at any stage and reopen the booking later. Existing reservations and rentals can resume the guided journey from their actual records. Back returns to the preceding journey step; it does not open the reservation. Sales validates the linked quotation before sending or confirming it. Cancelling an unconfirmed quotation from Sales also cancels its linked booking and releases its vehicle; bookings with financial records must be cancelled from Booking so Finance can reverse them safely.

In Booking, select customer delivery if requested. Continue opens a popup for the delivery address and editable product price; saving proceeds to Quote. The quote lists delivery alongside hire, refundable deposit and prior deposit credit. Continuing confirms the quote and creates the sale order with matching product lines. Signing posts one invoice containing hire, deposit and delivery. An accountant records payment and applies eligible prior deposit credit against this invoice. The pickup inspection records whether the vehicle is clean using a checkbox. At Return, staff can select **Collect the vehicle from another location** and enter its address and editable product price in the return-charge popup. If the vehicle was clean at pickup and is returned dirty, or if it is late beyond the grace period, the same popup asks staff to confirm or edit those product charges. One final invoice contains late, cleaning, vehicle-collection and approved damage charges. The accountant settles it and refunds any remaining deposit. **Close Rental** validates that no charges, payments or deposits remain outstanding.

Closing the customer rental does not release the car. Use **Vehicle / Fleet Follow-up** for cleaning, repairs and fleet release. The daily operations reminder creates an internal activity for the rental's responsible user on the calendar day before the scheduled return, then an overdue activity if the rental remains ongoing after its due time. It does not message the customer.

### Who does what?

- Rental Staff: prepare bookings, obtain signatures, complete inspections and record handovers and returns.
- Rental Manager: approve destination pricing and exceptional price overrides.
- Rental Accountant: record payments, apply prior deposit credit, post settlement invoices, retain or refund deposits, and close rentals.
- Fleet Manager: prepare vehicles, manage compliance and repairs, complete cleaning and release vehicles for hire.
- Car Rental Admin: has the combined rental roles. An administrator configures company settings.

### Where to work

Customers holds customer identity and licence details. Bookings contains reservations and rentals. Fleet contains vehicle previews, inspections, damage and maintenance. Payments contains receipts, invoices, deposits/refunds and outstanding invoices. Configuration contains categories, destinations, pricing rules and settings.

### What counts as a completed cycle?

- The rental has completed return and is marked Closed by the accountant.
- The hire invoice and, when there are return charges, one final settlement invoice are posted and settled. Legacy rentals may retain separate charge invoices.
- The deposit has been refunded or applied to approved damage charges; the amount held is zero.
- Damage and repairs are resolved, cleaning is complete and the vehicle has been released.

Returned describes the physical return. Closed records completion of customer financial settlement. Fleet readiness is tracked separately and must be completed before the next handover.

## Before Your First Booking

### Prepare the business once

1. In Configuration → Vehicle Categories and Destinations, create the categories and destinations you actually serve.
2. In Configuration → Pricing Rules, enter daily rates, duration bands, validity dates and the deposit ratio. A manager must click Approve Rate. Draft example rates cannot confirm bookings.
3. In Fleet → Vehicles, add the registration, category, photo, odometer and compliance documents/expiry dates. Use the number plate as Fleet ID; registration fills automatically. Activate the completed vehicle. Only real registered vehicles appear in dashboard totals.
4. In Configuration → Settings, configure rental/damage income accounts, the deposit liability and unpaid-deposit clearing liability accounts, maintenance expense account, sales journal, bank/cash journal, and rental, security-deposit, delivery, off-site collection, cleaning and late-return products. The deposit product must be untaxed; give the charge products their appropriate sales taxes if required. Configure sales tax if applicable and check the company's accounting currency and customer receivable account.
5. Add approved agreement terms. Decide whether full rental payment, valid compliance documents and a working tracker are required at pickup, and set the late-return grace period.
6. Assign users the appropriate rental roles. Buttons and financial menus depend on permissions.

Deposit calculation: agreed daily rate × deposit ratio. It is calculated from one daily rate, separately from the rental total. The pricing screen shows the Pula deposit amount, defaulting to the full daily rate, with a 50% minimum. For example, a daily rate of 500 and a ratio of 1 require a 500 deposit, even for a three-day rental. These numbers are illustrative.

The following sections describe the manual reservation and rental forms, which remain available for existing and legacy records. For new bookings, use the **Guided booking** workflow above.

## Legacy workflow: Welcome and Book

### 1. Register or find the customer

Open Customers and search before creating a duplicate. Select Omang or Passport and enter that document's number, date of birth, physical and postal addresses, licence number, issue date and expiry. Omang numbers must be exactly 9 digits; passport and driving licence numbers accept 6 to 20 letters or digits. A customer must already be at least 21 and have an unexpired licence to enable rentals. Upload the selected identity document and driving licence before saving. Under-21 customers are flagged as soon as their date of birth is entered. Dates are also shown in full (day, month and year). At booking, the licence must remain valid through the full hire.

### 2. Prepare the reservation and quote

Open Bookings → Reservations → New. Select the customer, destination and vehicle category, then enter the pickup date/time and number of 24-hour rental days. The expected return date/time is calculated from the pickup time; review it along with the daily rate, tax, total, dirty-return fee and required deposit. Older reservations with an explicit return timestamp remain supported and are billed by each started 24-hour period.

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

Click Pickup Inspection. Record the actual inspection time, inspector, odometer and fuel. Tick the accessories present in the vehicle, then confirm that you checked the list. Record any existing damage. Attach photos, verify the automatically filled customer name and capture the signature. Save and click Complete Inspection.

### 7. Start the rental

Return to the rental and click Start Rental. Pickup requires a confirmed reservation, completed pickup inspection, acknowledged agreement, the required posted deposit, a ready vehicle and any enabled Road Licence/tracker checks. Insurance is tracked but does not block pickup. If full payment is required, posted rental receipts must cover the rental total. The rental becomes Ongoing and the car becomes Rented.

## 3. Return and Finish

### 8. Inspect the returned car

Open the ongoing rental and click Return Inspection. Confirm the odometer reading (pre-filled from Fleet), actual return time and fuel. Compare the accessory checklist with pickup; missing items are automatically recorded as a damage assessment. Tick the accessories present at return, confirm that you checked the list, and record any other new damage. Attach return photos and obtain the customer's acknowledgement and signature, then complete the inspection. The rental automatically calculates distance travelled from pickup and return mileage.

Click Return Vehicle on the rental. Return mileage cannot be lower than pickup mileage. The rental becomes Returned; the vehicle moves into inspection or damage handling. Late charges are calculated using the actual return time and the configured grace period.

### 9. Assess and bill additional charges

For a late return, use Create / Open Late Return Invoice in the rental's Payments tab and post the invoice. New damage creates an assessment under Fleet → Damage Assessments. A manager reviews the evidence/cost and clicks Approve Charge. Finance creates and posts the Damage Invoice.

Legacy rentals retain their existing separate cleaning, late-return and damage invoices and deposit-application actions. New guided rentals capture cleaning and late-return charges in the return popup and include them with approved damage in one settlement invoice. Finance can use Apply Deposit on legacy approved damage cases to settle their posted invoice, up to the deposit held and the invoice's outstanding balance. Collect any remaining legacy charge through its standard accounting payment workflow.

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
