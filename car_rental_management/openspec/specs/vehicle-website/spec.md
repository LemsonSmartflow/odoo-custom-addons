# Specification: Vehicle Website

## Purpose
Enable public-facing vehicle catalog and booking functionality for City Delights car rental customers.

## Requirements

### Requirement: Vehicle Catalog Display
The system SHALL display all published vehicles in a filterable grid layout on the `/vehicles` page.

#### Scenario: Public catalog access
- GIVEN a visitor accesses `/vehicles`
- WHEN the page loads
- THEN display all vehicles with `website_published = True`
- AND show primary photo, name, category, starting price
- AND provide filter options for category, destination, price range

#### Scenario: Mobile responsive layout
- GIVEN a visitor accesses `/vehicles` on a mobile device
- WHEN the page renders
- THEN display vehicles in a single-column layout
- AND ensure all images are properly scaled

### Requirement: Vehicle Detail Page
The system SHALL display a detailed view for each published vehicle including photo gallery and pricing.

#### Scenario: Vehicle detail access
- GIVEN a visitor accesses `/vehicles/<model>-<id>`
- WHEN the page loads
- THEN display vehicle photos in a gallery format
- AND show vehicle specifications (model, year, seats, fuel type)
- AND display pricing matrix by destination and duration
- AND show current availability status
- AND provide a "Book Now" button

#### Scenario: SEO-friendly URLs
- GIVEN a vehicle with name "Mazda Demio" and ID 5
- WHEN the URL is generated
- THEN the URL SHALL be `/vehicles/mazda-demio-5`

### Requirement: Online Booking Request
The system SHALL allow visitors to submit booking requests through a form.

#### Scenario: Booking form submission
- GIVEN a visitor clicks "Book Now" on a vehicle detail page
- WHEN they fill in pickup/return dates and destination
- AND accept terms and conditions
- WHEN they submit the form
- THEN create a `sale.order` with `rental_state = 'draft'`
- AND link the order to the selected vehicle
- AND send confirmation email to the customer

#### Scenario: Price calculation
- GIVEN a visitor selects dates and destination
- WHEN the form updates
- THEN calculate and display the total rental price
- AND apply the matching pricing rule

### Requirement: Customer Portal
The system SHALL provide authenticated customers access to their rental history.

#### Scenario: Portal rental listing
- GIVEN a logged-in customer accesses `/my/rentals`
- WHEN the page loads
- THEN display only their rental orders
- AND show order status, dates, total amount

#### Scenario: Portal rental detail
- GIVEN a customer clicks on a rental order
- WHEN the detail page loads
- THEN display full order details
- AND show inspection reports if available
- AND show invoices and payment status

### Requirement: Social Media Sharing
The system SHALL support sharing vehicle listings on social media platforms.

#### Scenario: Link preview generation
- GIVEN a vehicle detail page is shared on social media
- WHEN the link is previewed
- THEN display the vehicle name as title
- AND display the vehicle description
- AND display the primary vehicle photo
- AND display the canonical URL

#### Scenario: Share buttons
- GIVEN a visitor views a vehicle detail page
- WHEN they click a share button
- THEN open the platform's share dialog with the vehicle URL
- AND pre-fill the share text with vehicle name and price
