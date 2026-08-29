# NIJA Official Pricing Policy

**Effective:** August 29, 2026  
**Currency:** USD  
**Status:** Canonical public pricing policy

This document is the authoritative public pricing policy for NIJA. Older Basic/Pro/Enterprise price tables are retired and must not be used in customer-facing sales, website copy, call-center scripts, checkout copy, or new billing integrations.

## 1. NIJA Lessons

**Price: $99 one-time**

- NIJA Lessons are an educational product.
- This is a one-time purchase, not a recurring subscription.
- The lesson purchase is separate from NIJA platform access.
- Educational content does not guarantee profits, income, or investment performance.

## 2. NIJA Beta - First 100 Users

**14 days free, then $50/month**

- The founding beta offer is limited to the first 100 eligible beta users.
- Each eligible founding beta user receives a 14-day free trial.
- After the trial, the recurring price is $50/month.
- A founding beta user's $50/month offer is price-locked to that cohort unless NIJA later changes that user's agreement through an appropriate customer-facing process.
- Filling the first 100 spots must not automatically reprice existing founding beta users.

## 3. NIJA Beta - After the First 100 Users

**$75/month**

- Once 100 eligible founding beta spots have been claimed, the public beta offer for new users becomes $75/month.
- Existing founding beta users remain associated with their $50/month offer.
- The $75 price applies to new beta subscriptions after the founding cohort is filled.

## 4. Full Apple App Store / Google Play Paid Release

**Planned standard paid price: $99/month**

- This is the intended standard paid subscription price for the full mobile-app release.
- It must not be represented as the current beta price.
- Store-specific billing, taxes, fees, regional pricing, and platform requirements may require implementation details to be finalized before launch.

## 5. Internal Access Tiers Are Not Public Prices

Legacy/internal labels such as `basic`, `pro`, `enterprise`, and `alpha` may still exist in code for feature permissions, testing, migration, or backwards compatibility. They are **not customer-facing price names** and must not be used to advertise conflicting subscription prices.

Commercial pricing must be derived from the NIJA offer/cohort policy:

| Offer | Price | Billing |
|---|---:|---|
| NIJA Lessons | $99 | One-time |
| Founding Beta - first 100 | $50/month after 14-day trial | Recurring |
| Standard Beta - after first 100 | $75/month | Recurring |
| Full mobile paid release | $99/month | Recurring |

## 6. Sales and Marketing Rules

NIJA representatives and marketing pages must not claim or imply:

- guaranteed profits;
- guaranteed income;
- guaranteed investment returns;
- risk-free trading;
- certain financial results.

Trading and investing involve risk, including possible loss of capital.

## 7. Implementation Requirements

Every customer-facing implementation should use the same policy values:

- `BETA_TRIAL_DAYS = 14`
- `FOUNDING_BETA_LIMIT = 100`
- `FOUNDING_BETA_MONTHLY_USD = 50`
- `STANDARD_BETA_MONTHLY_USD = 75`
- `FULL_RELEASE_MONTHLY_USD = 99`
- `LESSONS_ONE_TIME_USD = 99`

Website, CRM, billing, analytics, and call-center systems must preserve the user's offer/cohort at signup so future public-price changes do not silently reprice existing users.
