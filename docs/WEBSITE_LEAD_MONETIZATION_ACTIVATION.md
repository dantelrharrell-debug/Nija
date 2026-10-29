# NIJA website monetization activation checklist

This feature records measurement logic only; it does not install ads, transmit contacts, or claim revenue.

1. On the IONOS website, maintain one canonical lead-intake path and use explicit unchecked marketing and **separate** partner-sharing checkboxes. Partner sharing must name the recipient and purpose, and consent evidence must be retained before transfer. Never send API keys or broker credentials.
2. Correct public FAQ language to match checkout availability and current founding offer. Verify the live Stripe and ClickBank checkout and trial terms before publishing.
3. Obtain advertising-network approval before inserting ad tags. Keep advertising off checkout/account/security pages. Add visible 'Advertisement' labels and update cookie consent/privacy notices as necessary.
4. Publish the free education lead magnet only when the promised asset is actually accessible. Never require brokerage onboarding to get the educational guide.
5. Add affiliate destinations only after approval, using actual partner-issued URLs and clear disclosures: 'NIJA may earn a commission if you sign up through certain links, at no extra cost to you.' Explain material incentives near the link.
6. Emit pseudonymous unique visitor IDs and stable lead submission IDs from first-party analytics. Do not use raw email as a public tracking identifier. Respect regional privacy settings and avoid exporting contact details to analytics providers.
7. Reconcile Stripe, ClickBank, affiliate-network settlement, sponsor invoices and ad-network reports into trusted, *verified* revenue events. Deduplicate by provider event ID. Apply refunds/chargebacks as negative revenue. Do not count click events as revenue.
8. Run `python -m unittest tests.test_website_revenue_attribution`. Use `website_revenue_attribution.summarize` to compute two separate KPIs on the same earned revenue denominator, without adding the KPIs together.
9. Before launch: confirm IONOS editor permissions, live privacy/consent changes, working intake integration, payment provider permissions, partner approvals, and ad-network approval. Otherwise keep features in draft.

The $1 per visitor and $1 per lead values are **targets**, not promises. A visitor who becomes a lead is one person; counting the payment in both per-person ratios is acceptable for *separate analytic ratios*, but never sum the two revenue values into total earnings.
