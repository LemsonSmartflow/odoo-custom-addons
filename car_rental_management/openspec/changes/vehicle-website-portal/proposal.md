# Proposal: Vehicle Website Portal & Booking System

**Change ID:** vehicle-website-portal
**Date:** 2026-09-17
**Status:** Draft

## Problem

City Delights' clients currently have no way to:
- Browse available vehicles online with photos
- See pricing per destination and duration
- Request bookings through a self-service portal
- Share vehicle listings on social media

All operations are backend-only, requiring phone calls or in-person visits.

## Solution

Build a public-facing website portal within Odoo that:
1. Displays a vehicle catalog with photos, pricing, and availability
2. Allows customers to request bookings online
3. Provides a customer portal for tracking rentals
4. Supports social media sharing with proper meta tags

## Scope

### In Scope
- Vehicle catalog page (public)
- Vehicle detail page with photo gallery and pricing
- Online booking request form
- Customer portal (login → my rentals, invoices)
- Social media sharing (Open Graph meta tags)
- Responsive design (mobile-friendly)

### Out of Scope
- Online payment processing (future phase)
- Multi-language support (future phase)
- Mobile app (future phase)

## Success Criteria
- Customer can browse vehicles without login
- Customer can submit a booking request
- Customer can log in and see their rental history
- Vehicle pages generate proper link previews on Facebook/WhatsApp
