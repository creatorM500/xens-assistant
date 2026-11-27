# AINSLUP Web — commercial launch readiness

**Status: NOT READY for paid/commercial launch.** This is an engineering checklist, not legal advice or a compliance certification. Do not activate live billing based on this document.

## What the current repository shows

- The current `/app` route loads a static HTML/JS client from `webapp/public/ainslup-ui/`.
- Chat history and preferences are stored in browser `localStorage`; the current UI does not provide cloud history or account deletion.
- Sign-in uses Supabase Auth. Chat requests go to the Supabase Edge Function and then to the selected/available model provider. Provider-side retention and contractual settings have not been verified here.
- The Edge Function contains PayPal checkout/webhook code, but the current main UI has no purchase flow. Whether PayPal credentials, live plans, webhook settings, and database migrations are configured cannot be confirmed from this repository.
- The public Terms and Privacy pages are provisional notices, not final commercial terms or a completed privacy policy.
- The repository has no root `LICENSE` file. This does not establish permission for others to reuse the code or prove that every included asset is cleared for commercial use.
- The web production build succeeds. An authenticated end-to-end check against the deployed Supabase project, model providers, and PayPal has not been performed.

## Required before charging customers

### Adult/business and legal review

- A responsible adult/business owner must decide the operator identity, supported locations, target age, support contact, pricing, tax handling, cancellation/refund policy, and dispute process.
- Have a qualified adult review the final Terms and Privacy notice for the operator's jurisdiction and intended audience. If minors may use the service, review age/consent and data-protection requirements before launch.
- Confirm ownership or commercial permission for the AINSLUP name/brand, UI, source code, fonts, icons, and other assets. Review third-party dependency licenses. Add a root project license only after the rights holder chooses the intended grant.
- Obtain and review current commercial/data-processing terms for Supabase, each model/search provider, and PayPal; document what data each receives and how deletion/retention works.

### Product and privacy controls

- Implement and test account deletion, including an understandable request path and cleanup of account/billing records where legally permitted. Distinguish this from clearing browser history or signing out.
- Set and document retention periods; confirm provider logging/training/retention settings and disclose them accurately.
- Decide whether chat data stays local or is stored in the cloud, then make the UI and privacy notice agree.
- Add a support/privacy contact and a way to report security issues.
- Test signup, email verification/reset, logout, data export, history clearing, and deletion on desktop/mobile and in private browsing.

### Billing and operations

- Decide whether paid subscriptions are part of this launch. If yes, configure PayPal live products/plans only after adult/business review; keep sandbox mode until all tests pass.
- Test checkout, approval/cancel/return, webhook signature verification, subscription activation/renewal/cancellation/past-due/refund, credit grants/revocations, duplicate/replayed webhook events, and failed payments.
- Verify production Supabase secrets and database migrations without printing secret values. Deploy the Edge Function and migrations deliberately; verify provider fallback and rate/credit limits with controlled tests.
- Confirm Render is deploying the intended `main` commit, then run a production smoke test for `/`, `/app`, `/terms`, `/privacy`, authentication, chat, and error handling.
- Set up monitoring, incident response, backups/recovery, abuse/rate controls, and a contact path before accepting paying users.

## Safe release state until blockers are closed

- Keep AINSLUP marked as a preview; do not advertise paid plans or enable live PayPal.
- Do not put real provider secrets in browser code, git, or support messages.
- Do not use real customer or sensitive personal data for smoke tests.
- Ask a parent/guardian or another responsible adult to lead business, legal, account, and payment decisions. No credentials or personal information need to be shared in this repository or chat.

## Local verification

From `webapp/`:

```text
npm run check
npm run build
```

These checks do not prove production configuration, legal readiness, provider availability, or payment correctness.
